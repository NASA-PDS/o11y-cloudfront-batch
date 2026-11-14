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
each object is copied server-side, the copy is verified (size and ETag), and the
source is then deleted. The bucket is versioned, so a deleted source stays
recoverable until the noncurrent-version lifecycle rule expires it. Use
--keep-source to copy without deleting. Objects that already exist at the
destination with the same size and ETag are not copied again, so an interrupted
run can be repeated. A destination that differs from its source is reported and
left alone.

Files with no recognisable date, or in a subdirectory of the source, are
reported and left where they are.

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
MAX_COPY_BYTES = 5 * 1024**3  # largest object a single copy_object call can copy
NOT_FOUND_CODES = ("404", "NoSuchKey", "NotFound")
EXAMPLES_PER_REASON = 5

# (pattern, year is two digits). Group 1 is the year and group 2 the month.
DATE_PATTERNS: Tuple[Tuple["re.Pattern[str]", bool], ...] = (
    (re.compile(r"(?:u_ex|log\.|xferlog\.)(\d{2})(\d{2})\d{2}"), True),
    (re.compile(r"(?<!\d)(20\d{2})-(\d{2})(?:-\d{2})?(?!\d)"), False),
    (re.compile(r"(?<!\d)(20\d{2})(\d{2})\d{2}(?!\d)"), False),
)


class ReorganizeError(RuntimeError):
    """Base class for failures moving a single object."""


class DestinationConflictError(ReorganizeError):
    """The destination key exists and differs from the source object."""


class CopyVerificationError(ReorganizeError):
    """The copy does not match the source object."""


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


def plan_source(
    objects: Iterable[SourceObject], node: str, source: str, legacy: str, year: Optional[int] = None
) -> Plan:
    """Decide where each object under NODE/SOURCE/ moves.

    Args:
        objects: Every object listed under the source prefix.
        node: Node prefix, for example geo.
        source: Directory under the node prefix, for example geo-an.
        legacy: Name of the directory the moved logs go under.
        year: When set, only objects dated in this year are planned.
    """
    prefix = f"{node}/{source}/"
    moves: List[Move] = []
    skipped: List[Tuple[str, str]] = []
    for obj in objects:
        name = obj.key[len(prefix) :]
        if not name:
            skipped.append((obj.key, "folder marker"))
        elif "/" in name:
            skipped.append((obj.key, "in a subdirectory"))
        elif obj.size > MAX_COPY_BYTES:
            skipped.append((obj.key, "larger than 5 GiB"))
        else:
            parsed = parse_log_month(name)
            if parsed is None:
                skipped.append((obj.key, "no date in the file name"))
            elif year is None or parsed[0] == year:
                moves.append(Move(obj, destination_key(node, legacy, source, parsed[0], parsed[1], name), *parsed))
    return Plan(moves, skipped)


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


def matches_source(meta: Dict[str, Any], source: SourceObject) -> bool:
    """Whether an object's metadata has the size and ETag of the source object."""
    return meta["ContentLength"] == source.size and meta["ETag"].strip('"') == source.etag


def move_object(client: Any, bucket: str, move: Move, keep_source: bool) -> str:
    """Copy one object to its destination, verify the copy, and delete the source.

    Returns:
        "moved", "copied" when the source is kept, or "already present" when the destination
        already held an identical object (the source is still deleted unless keep_source).

    Raises:
        DestinationConflictError: The destination exists and differs from the source.
        CopyVerificationError: The new object does not match the source.
    """
    existing = head_object(client, bucket, move.dest_key)
    if existing is None:
        client.copy_object(CopySource={"Bucket": bucket, "Key": move.source.key}, Bucket=bucket, Key=move.dest_key)
        copied = head_object(client, bucket, move.dest_key)
        if copied is None or not matches_source(copied, move.source):
            raise CopyVerificationError(f"{move.dest_key} does not match {move.source.key}; source left in place")
        outcome = "copied" if keep_source else "moved"
    elif matches_source(existing, move.source):
        outcome = "already present"
    else:
        raise DestinationConflictError(f"{move.dest_key} exists and differs from {move.source.key}; left alone")
    if not keep_source:
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


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description="Move flat legacy logs into <legacy>/<source>/<YYYY>/<MM>/.")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--node", required=True, help="node prefix in the bucket, for example geo")
    parser.add_argument(
        "--source", required=True, nargs="+", help="directories under the node prefix, for example geo-an"
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
    names = [args.node, args.legacy_name, *args.source]
    for name in names:
        if not name or "/" in name:
            return f"'{name}' must be a single directory name without '/'"
    for name in [args.legacy_name, *args.source]:
        if name in RESERVED_NAMES:
            return f"'{name}' cannot be a source or legacy name"
    if args.legacy_name in args.source:
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
            plan = plan_source(objects, args.node, source, args.legacy_name, args.year)
            print_plan(source, plan)
            planned.extend(plan.moves)
    except (ClientError, BotoCoreError) as exc:
        print(f"Error listing s3://{args.bucket}: {exc}", file=sys.stderr)
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
