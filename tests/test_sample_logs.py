"""Unit tests for the sample log copier."""
import os
import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from pds.o11y_batch import sample_logs
from pds.o11y_batch.sample_logs import SampleLogsError
from pds.o11y_batch.sample_logs import SamplePrefix

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUTS_DIR = os.path.join(REPO_ROOT, "config", "logstash", "config", "inputs")


def fake_s3(listing):
    """Build a stub S3 client whose paginator returns ``listing`` ({key: size}) in one page."""
    client = MagicMock()
    page = {"Contents": [{"Key": k, "Size": s} for k, s in listing.items()]}
    client.get_paginator.return_value.paginate.return_value = [page]
    return client


def make_args(**overrides):
    """Build parsed arguments the way the command line would."""
    argv = [
        "--src-profile",
        "src",
        "--dst-profile",
        "dst",
        "--src-bucket",
        "src-bucket",
        "--dst-bucket",
        "dst-bucket",
        "--inputs-dir",
        INPUTS_DIR,
    ]
    args = sample_logs.build_parser().parse_args(argv)
    for name, value in overrides.items():
        setattr(args, name, value)
    return args


class TestParseInputs(unittest.TestCase):
    """Reading prefixes out of the real input configs."""

    def test_every_node_is_read(self):
        """All nodes and their buckets and prefixes are found."""
        entries = sample_logs.parse_inputs(INPUTS_DIR)
        self.assertEqual({e.node for e in entries}, {"atm", "en", "geo", "img", "naif", "ppi", "rings", "sbn"})
        self.assertIn(SamplePrefix("en", "S3_BUCKET_NAME", "eng/en/", None), entries)
        cf_prefixes = {e.prefix for e in entries if e.bucket_var == "S3_CF_BUCKET_NAME"}
        self.assertIn("pdc-cds-infra/cloudfront/access/json/pds-main/", cf_prefixes)
        self.assertEqual(len(cf_prefixes), 3)

    def test_exclude_pattern_is_returned(self):
        """An input's own exclude_pattern comes back with its prefix."""
        img = sample_logs.parse_inputs(INPUTS_DIR, ["IMG"])
        self.assertEqual([e.prefix for e in img], ["img/"])
        self.assertIn("nohup", img[0].exclude_pattern)

    def test_nodes_filter_and_unknown_node(self):
        """Node IDs are case-insensitive and unknown ones are rejected."""
        self.assertEqual({e.node for e in sample_logs.parse_inputs(INPUTS_DIR, ["Geo", "ppi"])}, {"geo", "ppi"})
        with self.assertRaises(SampleLogsError):
            sample_logs.parse_inputs(INPUTS_DIR, ["bogus"])

    def test_missing_directory_is_rejected(self):
        """A directory without input configs is an error, not an empty plan."""
        with self.assertRaises(SampleLogsError):
            sample_logs.parse_inputs(os.path.join(INPUTS_DIR, "nope"))


class TestPickEvenly(unittest.TestCase):
    """Choosing keys across a listing."""

    def test_short_listing_is_returned_whole(self):
        """Fewer keys than requested are all kept."""
        self.assertEqual(sample_logs.pick_evenly(["a", "b"], 5), ["a", "b"])

    def test_first_and_last_are_always_included(self):
        """The ends of the listing are kept and the rest is spread between them."""
        keys = [f"k{i:03d}" for i in range(100)]
        picked = sample_logs.pick_evenly(keys, 5)
        self.assertEqual(len(picked), 5)
        self.assertEqual(picked[0], "k000")
        self.assertEqual(picked[-1], "k099")
        self.assertEqual(picked, sorted(picked))

    def test_degenerate_counts(self):
        """Zero, one and empty inputs are handled."""
        self.assertEqual(sample_logs.pick_evenly(["a", "b", "c"], 0), [])
        self.assertEqual(sample_logs.pick_evenly(["a", "b", "c"], 1), ["a"])
        self.assertEqual(sample_logs.pick_evenly([], 3), [])


class TestPlanSample(unittest.TestCase):
    """Listing, filtering and sampling one input."""

    def test_empty_objects_folder_markers_and_excluded_keys_are_dropped(self):
        """Only real, non-excluded objects are candidates."""
        client = fake_s3({"img/a/": 0, "img/a/empty.gz": 0, "img/a/nohup.out.gz": 5, "img/a/log.2023-01-01.gz": 5})
        entry = SamplePrefix("img", "S3_BUCKET_NAME", "img/", "nohup")
        self.assertEqual(sample_logs.plan_sample(client, "b", entry, 10), ["img/a/log.2023-01-01.gz"])


class TestRun(unittest.TestCase):
    """The copy driver."""

    def setUp(self):
        """Stub boto3 so no AWS call is made and capture the two clients."""
        self.src = fake_s3({"naif/weblogs/naif-apache/access_log.230102.gz": 5})
        self.src.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"data"))}
        self.dst = MagicMock()
        patcher = patch("pds.o11y_batch.sample_logs.boto3.Session")
        session = patcher.start()
        self.addCleanup(patcher.stop)
        session.side_effect = lambda profile_name: MagicMock(client=MagicMock(return_value=self._client(profile_name)))

    def _client(self, profile):
        return self.src if profile == "src" else self.dst

    def test_dry_run_copies_nothing(self):
        """Without --execute no object is read or written."""
        self.assertEqual(sample_logs.run(make_args(nodes=["naif"], execute=False)), 0)
        self.src.get_object.assert_not_called()
        self.dst.put_object.assert_not_called()

    def test_execute_copies_to_the_same_key(self):
        """With --execute each sampled object lands at its own key in the destination bucket."""
        self.assertEqual(sample_logs.run(make_args(nodes=["naif"], execute=True)), 0)
        self.dst.put_object.assert_any_call(
            Bucket="dst-bucket", Key="naif/weblogs/naif-apache/access_log.230102.gz", Body=b"data"
        )

    def test_cloudfront_inputs_are_skipped_without_cf_buckets(self):
        """EN's CloudFront prefixes need --src-cf-bucket and --dst-cf-bucket."""
        sample_logs.run(make_args(nodes=["en"], execute=True))
        copied = [c.kwargs["Bucket"] for c in self.dst.put_object.call_args_list]
        self.assertTrue(copied)
        self.assertEqual(set(copied), {"dst-bucket"})

    def test_same_source_and_destination_bucket_is_refused(self):
        """A copy onto the source bucket must never start."""
        with self.assertRaises(SampleLogsError):
            sample_logs.run(make_args(dst_bucket="src-bucket", execute=True))
        self.dst.put_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()
