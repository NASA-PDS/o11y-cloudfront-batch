#!/usr/bin/env python3
r"""Move flat legacy web logs into a <YYYY>/<MM> layout under a separate prefix.

For each --source (a top-level directory under the node prefix, such as geo-an)
the objects in s3://BUCKET/NODE/SOURCE/ are moved to

    s3://BUCKET/NODE/LEGACY/SOURCE/YYYY/MM/FILENAME

where YYYY and MM come from the date in the file name (the same shapes the
LOG_YEARS filter in logstash_build_config.sh recognises: u_exYYMMDD, log.YYMMDD,
xferlog.YYMMDD, YYYY-MM[-DD] and YYYYMMDD). The Data Upload Manager layout under
NODE/weblogs/ is never read or written.

The default is a dry run that lists the plan and writes nothing. With --execute
each object is copied server-side, the copy is verified (size and ETag, or size and
the uploader-recorded md5chksum for objects uploaded in parts), and the
source is then deleted. The bucket is versioned, so a deleted source stays
recoverable until the noncurrent-version lifecycle rule expires it. Use
--keep-source to copy without deleting. Objects that already exist at the
destination with the same size and ETag are not copied again, so an interrupted
run can be repeated. A destination that differs from its source is reported and
left alone.

The copy is conditional (If-None-Match and x-amz-copy-source-if-match), so it never
overwrites a destination written after the check and only copies the source object
that was listed. The source is checked against the listing again just before it is
deleted, so a source replaced during the run is kept. Do not run two migrations over
the same prefixes at once.

Files with no recognisable date, hidden files, or files in a subdirectory of the
source, are reported and left where they are.

A directory that holds the logs of several sources is split with --route
REGEX=DEST: a file whose name matches REGEX goes under DEST instead of the
source directory, and a file that matches no route is left alone. If two objects
would land on the same key, the run stops before copying anything; move the
sources in separate runs so a differing destination is reported, not overwritten.

Copies get a new LastModified. A Logstash s3 input reads objects newer than its
sincedb timestamp, so point the inputs at the new prefix and set their sincedb
to a time after this run, or the moved logs are read again.

Usage:
    python3 scripts/s3-reorganize-legacy-logs.py --bucket BUCKET --node geo \
        --source geo-ode-cart --profile PROFILE
    python3 scripts/s3-reorganize-legacy-logs.py --bucket BUCKET --node geo \
        --source geo-ode-cart --year 2021 --profile PROFILE --execute
"""
import argparse
import base64
import csv
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple

import boto3
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError

DEFAULT_LEGACY_NAME = "legacy"
DEFAULT_REGION = "us-west-2"
DEFAULT_WORKERS = 8
RESERVED_NAMES = ("weblogs",)  # prefixes owned by the Data Upload Manager layout
MAX_COPY_BYTES = 5_000_000_000  # largest object a single copy_object call can copy (5 GB, not 5 GiB)
NOT_FOUND_CODES = ("404", "NoSuchKey", "NotFound")
# A conditional copy whose precondition did not hold (412), or that raced another conditional write (409)
PRECONDITION_CODES = ("412", "PreconditionFailed", "409", "ConditionalRequestConflict")
MD5_METADATA_KEY = "md5chksum"  # base64 MD5 of the file, recorded by the uploader in the object's user metadata
EXAMPLES_PER_REASON = 5

# (pattern, year is two digits). Group 1 is the year and group 2 the month.
DATE_PATTERNS: Tuple[Tuple["re.Pattern[str]", bool], ...] = (
    (re.compile(r"(?:u_ex|log\.|xferlog\.)(\d{2})(\d{2})\d{2}(?!\d)"), True),
    (re.compile(r"(?<!\d)(20\d{2})-(\d{2})(?:-\d{2})?(?!\d)"), False),
    (re.compile(r"(?<!\d)(20\d{2})(\d{2})\d{2}(?!\d)"), False),
)


class ReorganizeError(RuntimeError):
    """Base class for failures moving a single object."""


class DestinationConflictError(ReorganizeError):
    """The destination key exists and differs from the source object."""


class CopyVerificationError(ReorganizeError):
    """The copy does not match the source object."""


class SourceChangedError(ReorganizeError):
    """The source object was replaced or removed after it was listed."""


Route = Tuple["re.Pattern[str]", str]  # (file-name pattern, destination source directory)


@dataclass(frozen=True)
class SourceObject:
    """An object found under a source prefix."""

    key: str
    size: int
    etag: str


@dataclass(frozen=True)
class Move:
    """One object and the key it moves to."""

    source: SourceObject
    dest_key: str
    year: int
    month: int


@dataclass(frozen=True)
class Plan:
    """The moves for one source and the objects that were left alone, with the reason."""

    moves: List[Move]
    skipped: List[Tuple[str, str]]


def parse_log_month(name: str) -> Optional[Tuple[int, int]]:
    """Return (year, month) for the date in a log file name, or None when it has no valid date.

    Args:
        name: File name without the directory part.
    """
    for pattern, short_year in DATE_PATTERNS:
        match = pattern.search(name)
        if match is None:
            continue
        year = int(match.group(1)) + (2000 if short_year else 0)
        month = int(match.group(2))
        if 1 <= month <= 12:
            return year, month
    return None


def destination_key(node: str, legacy: str, source: str, year: int, month: int, name: str) -> str:
    """Return the key an object moves to."""
    return f"{node}/{legacy}/{source}/{year:04d}/{month:02d}/{name}"


def route_for(name: str, source: str, routes: Sequence[Route]) -> Optional[str]:
    """Return the destination source directory for a file name: the first matching route, or the source itself.

    Without routes every file keeps its source directory. With routes a file that matches none has no destination.
    """
    if not routes:
        return source
    for pattern, dest_source in routes:
        if pattern.search(name):
            return dest_source
    return None


def plan_source(
    objects: Iterable[SourceObject],
    node: str,
    source: str,
    legacy: str,
    year: Optional[int] = None,
    routes: Sequence[Route] = (),
) -> Plan:
    """Decide where each object under NODE/SOURCE/ moves.

    Args:
        objects: Every object listed under the source prefix.
        node: Node prefix, for example geo.
        source: Directory under the node prefix, for example geo-an.
        legacy: Name of the directory the moved logs go under.
        year: When set, only objects dated in this year are planned.
        routes: (pattern, destination source) pairs that send files of a mixed directory to the source
            directory named by the first pattern that matches the file name.
    """
    prefix = f"{node}/{source}/"
    moves: List[Move] = []
    skipped: List[Tuple[str, str]] = []
    for obj in objects:
        name = obj.key[len(prefix) :]
        dest_source = route_for(name, source, routes)
        if not name:
            skipped.append((obj.key, "folder marker"))
        elif "/" in name:
            skipped.append((obj.key, "in a subdirectory"))
        elif name.startswith("."):
            skipped.append((obj.key, "hidden file"))
        elif obj.size > MAX_COPY_BYTES:
            skipped.append((obj.key, "larger than 5 GB"))
        elif dest_source is None:
            skipped.append((obj.key, "matches no --route"))
        else:
            parsed = parse_log_month(name)
            if parsed is None:
                skipped.append((obj.key, "no date in the file name"))
            elif year is None or parsed[0] == year:
                moves.append(Move(obj, destination_key(node, legacy, dest_source, parsed[0], parsed[1], name), *parsed))
    return Plan(moves, skipped)


def duplicate_destinations(moves: Iterable[Move]) -> List[str]:
    """Return the destination keys that more than one planned move targets."""
    counts = Counter(move.dest_key for move in moves)
    return sorted(key for key, count in counts.items() if count > 1)


def list_objects(client: Any, bucket: str, prefix: str) -> List[SourceObject]:
    """List every object under a prefix."""
    objects: List[SourceObject] = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            objects.append(SourceObject(item["Key"], item["Size"], item["ETag"].strip('"')))
    return objects


def head_object(client: Any, bucket: str, key: str) -> Optional[Dict[str, Any]]:
    """Return the object's metadata, or None when it does not exist."""
    try:
        return client.head_object(Bucket=bucket, Key=key)  # type: ignore[no-any-return]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in NOT_FOUND_CODES:
            return None
        raise


def is_multipart(source: SourceObject) -> bool:
    """Whether the object was uploaded in parts; a copy of it cannot have the same ETag."""
    return "-" in source.etag


def recorded_md5(client: Any, bucket: str, key: str) -> Optional[str]:
    """Return the MD5 (hex) the uploader recorded in the object's md5chksum metadata, or None."""
    value = (client.head_object(Bucket=bucket, Key=key).get("Metadata") or {}).get(MD5_METADATA_KEY)
    try:
        return base64.b64decode(value, validate=True).hex() if value else None
    except ValueError:
        return None


def matches_source(client: Any, bucket: str, meta: Dict[str, Any], move: Move) -> bool:
    """Whether the destination's metadata matches the source object.

    A single-part source must have the same size and ETag. A copy of a multipart source is a single part, so its
    ETag is the MD5 that S3 computed over the copied bytes: it must have the same size and an ETag equal to the MD5
    the uploader recorded in the source's md5chksum metadata. A multipart source without that metadata never matches.
    """
    source = move.source
    if meta["ContentLength"] != source.size:
        return False
    etag = meta["ETag"].strip('"')
    if not is_multipart(source):
        return etag == source.etag
    expected = recorded_md5(client, bucket, source.key)
    return expected is not None and "-" not in etag and etag == expected


def error_code(exc: ClientError) -> str:
    """Return the S3 error code of a client error."""
    return str(exc.response.get("Error", {}).get("Code", ""))


def copy_if_absent(client: Any, bucket: str, move: Move) -> bool:
    """Copy the listed source to the destination only if the destination does not exist and the source is unchanged.

    Both conditions are checked by S3 as part of the copy (If-None-Match and x-amz-copy-source-if-match), so a
    destination written, or a source replaced, after the listing is never overwritten or copied.

    Returns:
        True when the copy was made, False when a precondition did not hold.
    """
    try:
        client.copy_object(
            CopySource={"Bucket": bucket, "Key": move.source.key},
            Bucket=bucket,
            Key=move.dest_key,
            CopySourceIfMatch=f'"{move.source.etag}"',
            IfNoneMatch="*",
        )
    except ClientError as exc:
        if error_code(exc) in PRECONDITION_CODES:
            return False
        raise
    return True


def require_unchanged_source(client: Any, bucket: str, move: Move) -> None:
    """Raise SourceChangedError unless the source key still holds the object that was listed."""
    current = head_object(client, bucket, move.source.key)
    if current is None:
        raise SourceChangedError(f"{move.source.key} is gone; nothing deleted")
    if current["ContentLength"] != move.source.size or current["ETag"].strip('"') != move.source.etag:
        raise SourceChangedError(f"{move.source.key} changed after it was listed; source left in place")


def move_object(client: Any, bucket: str, move: Move, keep_source: bool) -> str:
    """Copy one object to its destination, verify the copy, and delete the source.

    The copy is conditional: it fails rather than overwrite a destination that appeared after the check, and it
    copies only the source object that was listed. Before the source is deleted it is checked again against the
    listing, so a source replaced in the meantime is kept. Runs must still not overlap on the same prefixes: the
    check and the delete are separate calls, and the bucket's versioning is what covers that gap.

    Returns:
        "moved", "copied" when the source is kept, or "already present" when the destination
        already held an identical object (the source is still deleted unless keep_source).

    Raises:
        DestinationConflictError: The destination exists and differs from the source.
        CopyVerificationError: The new object does not match the source.
        SourceChangedError: The source was replaced or removed after it was listed.
    """
    existing = head_object(client, bucket, move.dest_key)
    if existing is None:
        if copy_if_absent(client, bucket, move):
            copied = head_object(client, bucket, move.dest_key)
            if copied is None or not matches_source(client, bucket, copied, move):
                raise CopyVerificationError(f"{move.dest_key} does not match {move.source.key}; source left in place")
            outcome = "copied" if keep_source else "moved"
        else:
            # Either the destination appeared since the check, or the source is no longer the listed object.
            existing = head_object(client, bucket, move.dest_key)
            if existing is None:
                raise SourceChangedError(f"{move.source.key} changed after it was listed; nothing copied")
    if existing is not None:
        if not matches_source(client, bucket, existing, move):
            raise DestinationConflictError(f"{move.dest_key} exists and differs from {move.source.key}; left alone")
        outcome = "already present"
    if not keep_source:
        require_unchanged_source(client, bucket, move)
        client.delete_object(Bucket=bucket, Key=move.source.key)
    return outcome


def execute_moves(
    client: Any, bucket: str, moves: Sequence[Move], keep_source: bool, workers: int
) -> Tuple[List[Tuple[Move, str]], List[Tuple[Move, str]]]:
    """Run the moves in parallel.

    Returns:
        The (move, outcome) pairs that succeeded and the (move, error message) pairs that failed.
    """

    def run(move: Move) -> Tuple[Move, str, bool]:
        try:
            return move, move_object(client, bucket, move, keep_source), True
        except (ReorganizeError, ClientError, BotoCoreError) as exc:
            return move, str(exc), False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run, moves))
    done = [(move, text) for move, text, ok in results if ok]
    failed = [(move, text) for move, text, ok in results if not ok]
    return done, failed


def print_plan(source: str, plan: Plan) -> None:
    """Print the files and bytes per year for a source, and the objects left alone."""
    by_year: Dict[int, List[int]] = {}
    for move in plan.moves:
        by_year.setdefault(move.year, []).append(move.source.size)
    print(f"\n{source}: {len(plan.moves)} to move, {len(plan.skipped)} left alone")
    for year in sorted(by_year):
        sizes = by_year[year]
        print(f"  {year}: {len(sizes):6d} files  {sum(sizes) / 1024**2:10.1f} MiB")
    reasons = Counter(reason for _, reason in plan.skipped)
    for reason, count in sorted(reasons.items()):
        print(f"  left alone ({reason}): {count}")
        shown = [key for key, why in plan.skipped if why == reason][:EXAMPLES_PER_REASON]
        for key in shown:
            print(f"    {key}")


def write_manifest(path: str, rows: Iterable[Tuple[Move, str]]) -> None:
    """Write source key, destination key, size and outcome for every move."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["source_key", "dest_key", "size", "outcome"])
        for move, outcome in rows:
            writer.writerow([move.source.key, move.dest_key, move.source.size, outcome])


def route_type(text: str) -> Route:
    """Parse a REGEX=DEST command-line value into a route."""
    pattern_text, separator, dest = text.rpartition("=")
    if not separator or not pattern_text or not dest:
        raise argparse.ArgumentTypeError(f"'{text}' must look like REGEX=DEST")
    try:
        return re.compile(pattern_text), dest
    except re.error as exc:
        raise argparse.ArgumentTypeError(f"'{pattern_text}' is not a valid regular expression: {exc}") from exc


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description="Move flat legacy logs into <legacy>/<source>/<YYYY>/<MM>/.")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--node", required=True, help="node prefix in the bucket, for example geo")
    parser.add_argument(
        "--source", required=True, nargs="+", help="directories under the node prefix, for example geo-an"
    )
    parser.add_argument(
        "--route",
        action="append",
        default=[],
        type=route_type,
        metavar="REGEX=DEST",
        help="send files whose name matches REGEX to the source directory DEST (for a directory holding the logs "
        "of several sources); files matching no route are left alone. Repeat for each destination.",
    )
    parser.add_argument("--legacy-name", default=DEFAULT_LEGACY_NAME, help="directory the moved logs go under")
    parser.add_argument("--year", type=int, help="only move files dated in this year")
    parser.add_argument("--profile", help="AWS profile (default: the usual boto3 lookup)")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="parallel copies")
    parser.add_argument("--manifest", help="write a TSV of source key, destination key, size and outcome")
    parser.add_argument("--keep-source", action="store_true", help="copy without deleting the source objects")
    parser.add_argument("--execute", action="store_true", help="make the changes; the default is a dry run")
    return parser.parse_args(argv)


def validate_names(args: argparse.Namespace) -> Optional[str]:
    """Return a message when a name could reach the weblogs layout or leave the node prefix."""
    route_dests = [dest for _, dest in args.route]
    names = [args.node, args.legacy_name, *args.source, *route_dests]
    for name in names:
        if not name or "/" in name:
            return f"'{name}' must be a single directory name without '/'"
        if name in RESERVED_NAMES:
            return f"'{name}' is reserved for the Data Upload Manager"
    for name in [args.node, args.legacy_name, *args.source, *route_dests]:
    if args.legacy_name in args.source or args.legacy_name in route_dests:
        return f"'{args.legacy_name}' cannot be both a source and the legacy name"
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Plan the moves, and with --execute carry them out."""
    args = parse_args(argv)
    problem = validate_names(args)
    if problem:
        print(f"Error: {problem}", file=sys.stderr)
        return 2
    client = boto3.Session(profile_name=args.profile, region_name=args.region).client("s3")

    planned: List[Move] = []
    try:
        for source in args.source:
            objects = list_objects(client, args.bucket, f"{args.node}/{source}/")
            plan = plan_source(objects, args.node, source, args.legacy_name, args.year, args.route)
            print_plan(source, plan)
            planned.extend(plan.moves)
    except (ClientError, BotoCoreError) as exc:
        print(f"Error listing s3://{args.bucket}: {exc}", file=sys.stderr)
        return 2

    clashes = duplicate_destinations(planned)
    if clashes:
        print(
            f"Error: {len(clashes)} destination keys are targeted by more than one object, for example:",
            file=sys.stderr,
        )
        for key in clashes[:EXAMPLES_PER_REASON]:
            print(f"  {key}", file=sys.stderr)
        print(
            "Move the sources in separate runs so a differing destination is reported, not overwritten.",
            file=sys.stderr,
        )
        return 2

    if not args.execute:
        if args.manifest:
            write_manifest(args.manifest, ((move, "planned") for move in planned))
        print(f"\nDry run: {len(planned)} objects would move. Re-run with --execute to apply.")
        return 0

    done, failed = execute_moves(client, args.bucket, planned, args.keep_source, args.workers)
    if args.manifest:
        write_manifest(args.manifest, done + [(move, f"FAILED: {text}") for move, text in failed])
    print(f"\n{len(done)} of {len(planned)} objects done, {len(failed)} failed")
    for move, text in failed[: EXAMPLES_PER_REASON * 4]:
        print(f"  {move.source.key}: {text}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
