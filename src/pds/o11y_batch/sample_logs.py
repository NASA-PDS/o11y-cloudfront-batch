"""Copy a small sample of S3 log objects, keeping their keys, between two sets of buckets.

The prefixes come from the ``s3`` inputs in the Logstash input configs, so the sample covers
exactly what the pipelines poll. For each prefix the source listing is filtered with the input's
own ``exclude_pattern``, a few keys are picked evenly across the whole listing (so every year
present is represented), and each is copied to the same key in the matching destination bucket.
It is a dry run unless ``--execute`` is given.
"""
import argparse
import glob
import logging
import os
import re
import sys
from typing import Any
from typing import Iterator
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Sequence

import boto3  # type: ignore
from botocore.exceptions import ClientError  # type: ignore

logger = logging.getLogger(__name__)

NODE_BUCKET_VAR = "S3_BUCKET_NAME"
CF_BUCKET_VAR = "S3_CF_BUCKET_NAME"
DEFAULT_INPUTS_DIR = os.path.join("config", "logstash", "config", "inputs")
DEFAULT_PER_PREFIX = 12

S3_BLOCK = re.compile(r"^  s3 \{\n(.*?)^  \}$", re.MULTILINE | re.DOTALL)


class SamplePrefix(NamedTuple):
    """One S3 input: where it reads and which keys it skips."""

    node: str
    bucket_var: str
    prefix: str
    exclude_pattern: Optional[str]


class SampleLogsError(RuntimeError):
    """Raised when the sample cannot be planned or copied."""


def _setting(body: str, name: str) -> Optional[str]:
    """Return the quoted value of ``name => "..."`` in an s3 block body, if present."""
    found = re.search(rf'^    {name} => "(.*)"$', body, re.MULTILINE)
    return found.group(1) if found else None


def parse_inputs(inputs_dir: str, nodes: Sequence[str] = ()) -> List[SamplePrefix]:
    """Read the s3 inputs from the ``pds-input-s3-<node>.conf`` files in ``inputs_dir``.

    Args:
        inputs_dir: Directory holding the per-node input configs.
        nodes: Node IDs to keep (case-insensitive); empty keeps every node.

    Returns:
        One entry per s3 block, in file order.

    Raises:
        SampleLogsError: If no input config matches or a node ID is unknown.
    """
    wanted = {n.lower() for n in nodes}
    paths = sorted(glob.glob(os.path.join(inputs_dir, "pds-input-s3-*.conf")))
    available = {os.path.basename(p)[len("pds-input-s3-") : -len(".conf")] for p in paths}
    if not paths:
        raise SampleLogsError(f"no pds-input-s3-*.conf files in {inputs_dir}")
    unknown = wanted - available
    if unknown:
        raise SampleLogsError(f"unknown node(s) {sorted(unknown)}; valid: {sorted(available)}")

    prefixes: List[SamplePrefix] = []
    for path in paths:
        node = os.path.basename(path)[len("pds-input-s3-") : -len(".conf")]
        if wanted and node not in wanted:
            continue
        with open(path) as f:
            for body in S3_BLOCK.findall(f.read()):
                bucket = _setting(body, "bucket") or ""
                bucket_var = re.sub(r"^\$\{(\w+)\}$", r"\1", bucket)
                prefix = _setting(body, "prefix")
                if prefix is None:
                    raise SampleLogsError(f"s3 block without a prefix in {path}")
                prefixes.append(SamplePrefix(node, bucket_var, prefix, _setting(body, "exclude_pattern")))
    return prefixes


def pick_evenly(keys: Sequence[str], count: int) -> List[str]:
    """Pick up to ``count`` keys spread evenly over ``keys``, always including the first and last.

    Args:
        keys: Keys in listing order.
        count: How many to pick.

    Returns:
        The picked keys in listing order, without duplicates.
    """
    if count <= 0 or not keys:
        return []
    if len(keys) <= count:
        return list(keys)
    if count == 1:
        return [keys[0]]
    last = len(keys) - 1
    indexes = sorted({round(i * last / (count - 1)) for i in range(count)})
    return [keys[i] for i in indexes]


def list_keys(client: Any, bucket: str, prefix: str) -> Iterator[str]:
    """Yield the non-empty object keys under ``prefix`` that are not folder markers."""
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Size"] > 0 and not obj["Key"].endswith("/"):
                yield obj["Key"]


def plan_sample(client: Any, bucket: str, entry: SamplePrefix, per_prefix: int) -> List[str]:
    """Return the keys to copy for one input: its listing minus excluded keys, sampled evenly."""
    exclude = re.compile(entry.exclude_pattern) if entry.exclude_pattern else None
    keys = [k for k in list_keys(client, bucket, entry.prefix) if not (exclude and exclude.search(k))]
    return pick_evenly(keys, per_prefix)


def copy_key(src_client: Any, src_bucket: str, dst_client: Any, dst_bucket: str, key: str) -> None:
    """Copy one object to the same key in the destination bucket."""
    body = src_client.get_object(Bucket=src_bucket, Key=key)["Body"].read()
    dst_client.put_object(Bucket=dst_bucket, Key=key, Body=body)


def run(args: argparse.Namespace) -> int:
    """Plan the sample for the selected inputs and copy it when ``--execute`` is set."""
    buckets = {
        NODE_BUCKET_VAR: (args.src_bucket, args.dst_bucket),
        CF_BUCKET_VAR: (args.src_cf_bucket, args.dst_cf_bucket),
    }
    for var, (src, dst) in buckets.items():
        if src and src == dst:
            raise SampleLogsError(f"source and destination are the same bucket for {var}")

    src_client = boto3.Session(profile_name=args.src_profile).client("s3")
    dst_client = boto3.Session(profile_name=args.dst_profile).client("s3")

    total = 0
    for entry in parse_inputs(args.inputs_dir, args.nodes):
        src_bucket, dst_bucket = buckets.get(entry.bucket_var, (None, None))
        if not src_bucket or not dst_bucket:
            logger.info("skip %s %s: no buckets given for %s", entry.node, entry.prefix, entry.bucket_var)
            continue
        keys = plan_sample(src_client, src_bucket, entry, args.per_prefix)
        logger.info("%s %s: %d key(s)", entry.node, entry.prefix, len(keys))
        for key in keys:
            if args.execute:
                copy_key(src_client, src_bucket, dst_client, dst_bucket, key)
            logger.info("  %s %s", "copied" if args.execute else "would copy", key)
        total += len(keys)
    logger.info("%s %d object(s)", "copied" if args.execute else "would copy", total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--src-profile", required=True, help="AWS profile that can read the source buckets")
    parser.add_argument("--dst-profile", required=True, help="AWS profile that can write the destination buckets")
    parser.add_argument("--src-bucket", required=True, help="source node logs bucket")
    parser.add_argument("--dst-bucket", required=True, help="destination node logs bucket")
    parser.add_argument("--src-cf-bucket", help="source CloudFront logs bucket (omit to skip EN CloudFront inputs)")
    parser.add_argument("--dst-cf-bucket", help="destination CloudFront logs bucket")
    parser.add_argument("--nodes", nargs="*", default=[], help="node IDs to sample (default: all)")
    parser.add_argument("--per-prefix", type=int, default=DEFAULT_PER_PREFIX, help="objects per input prefix")
    parser.add_argument("--inputs-dir", default=DEFAULT_INPUTS_DIR, help="directory of pds-input-s3-*.conf files")
    parser.add_argument("--execute", action="store_true", help="copy the objects (default: print the plan only)")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Entry point for the ``copy-sample-logs`` command."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)
    try:
        sys.exit(run(args))
    except (SampleLogsError, ClientError) as err:
        logger.error("copy-sample-logs failed: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
