"""Unit tests for scripts/s3-reorganize-legacy-logs.py."""
import importlib.util
import unittest
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List

from botocore.exceptions import ClientError

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "s3-reorganize-legacy-logs.py"
SPEC = importlib.util.spec_from_file_location("s3_reorganize_legacy_logs", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
rl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rl)

BUCKET = "test-bucket"


def obj(key: str, size: int = 10, etag: str = "abc") -> Any:
    """A listed source object."""
    return rl.SourceObject(key, size, etag)


class FakeS3:
    """The head, copy and delete calls of an S3 client, over a dict of key -> (size, etag)."""

    def __init__(self, objects: Dict[str, Any], corrupt_copies: bool = False) -> None:
        self.objects = dict(objects)
        self.corrupt_copies = corrupt_copies
        self.deleted: List[str] = []

    def head_object(self, Bucket: str, Key: str) -> Dict[str, Any]:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        size, etag = self.objects[Key]
        return {"ContentLength": size, "ETag": f'"{etag}"'}

    def copy_object(self, CopySource: Dict[str, str], Bucket: str, Key: str) -> None:
        size, etag = self.objects[CopySource["Key"]]
        self.objects[Key] = (size + 1, etag) if self.corrupt_copies else (size, etag)

    def delete_object(self, Bucket: str, Key: str) -> None:
        self.deleted.append(Key)
        del self.objects[Key]


class ParseLogMonthTest(unittest.TestCase):
    def test_iis_names(self) -> None:
        self.assertEqual(rl.parse_log_month("u_ex210101.log.gz"), (2021, 1))
        self.assertEqual(rl.parse_log_month("u_ex240131web4pp.log.gz"), (2024, 1))

    def test_two_digit_year_log_names(self) -> None:
        self.assertEqual(rl.parse_log_month("xferlog.190915.gz"), (2019, 9))
        self.assertEqual(rl.parse_log_month("access_log.221231"), (2022, 12))

    def test_four_digit_year_names(self) -> None:
        self.assertEqual(rl.parse_log_month("access-2023-07-04.log"), (2023, 7))
        self.assertEqual(rl.parse_log_month("access-2023-07.log"), (2023, 7))
        self.assertEqual(rl.parse_log_month("access.20230704.log"), (2023, 7))

    def test_no_date(self) -> None:
        self.assertIsNone(rl.parse_log_month("README.txt"))
        self.assertIsNone(rl.parse_log_month("u_ex.log.gz"))

    def test_invalid_month_is_not_a_date(self) -> None:
        self.assertIsNone(rl.parse_log_month("u_ex211301.log.gz"))
        self.assertIsNone(rl.parse_log_month("u_ex210001.log.gz"))


class PlanSourceTest(unittest.TestCase):
    def test_destination_layout(self) -> None:
        plan = rl.plan_source([obj("geo/geo-an/u_ex210105.log.gz")], "geo", "geo-an", "legacy")
        self.assertEqual([m.dest_key for m in plan.moves], ["geo/legacy/geo-an/2021/01/u_ex210105.log.gz"])
        self.assertEqual(plan.skipped, [])

    def test_unmovable_objects_are_reported(self) -> None:
        objects = [
            obj("geo/geo-an/"),
            obj("geo/geo-an/notes.txt"),
            obj("geo/geo-an/old/u_ex210105.log.gz"),
            obj("geo/geo-an/u_ex210105.log.gz", size=rl.MAX_COPY_BYTES + 1),
        ]
        plan = rl.plan_source(objects, "geo", "geo-an", "legacy")
        self.assertEqual(plan.moves, [])
        self.assertEqual(
            [reason for _, reason in plan.skipped],
            ["folder marker", "no date in the file name", "in a subdirectory", "larger than 5 GiB"],
        )

    def test_year_filter(self) -> None:
        objects = [obj("geo/geo-an/u_ex201231.log.gz"), obj("geo/geo-an/u_ex210101.log.gz")]
        plan = rl.plan_source(objects, "geo", "geo-an", "legacy", year=2021)
        self.assertEqual([m.year for m in plan.moves], [2021])
        self.assertEqual(plan.skipped, [])


class ValidateNamesTest(unittest.TestCase):
    def args(self, source: List[str], legacy: str = "legacy", node: str = "geo") -> Any:
        return rl.parse_args(["--bucket", BUCKET, "--node", node, "--source", *source, "--legacy-name", legacy])

    def test_accepts_plain_names(self) -> None:
        self.assertIsNone(rl.validate_names(self.args(["geo-an", "geo-ftp"])))

    def test_rejects_weblogs_as_source_or_legacy_name(self) -> None:
        self.assertIsNotNone(rl.validate_names(self.args(["weblogs"])))
        self.assertIsNotNone(rl.validate_names(self.args(["geo-an"], legacy="weblogs")))

    def test_rejects_source_equal_to_legacy_name(self) -> None:
        self.assertIsNotNone(rl.validate_names(self.args(["legacy"])))

    def test_rejects_names_with_slashes(self) -> None:
        self.assertIsNotNone(rl.validate_names(self.args(["geo-an/2021"])))
        self.assertIsNotNone(rl.validate_names(self.args(["geo-an"], node="geo/weblogs")))


class MoveObjectTest(unittest.TestCase):
    SRC = "geo/geo-an/u_ex210105.log.gz"
    DEST = "geo/legacy/geo-an/2021/01/u_ex210105.log.gz"

    def move(self) -> Any:
        return rl.plan_source([obj(self.SRC, size=10, etag="abc")], "geo", "geo-an", "legacy").moves[0]

    def test_moves_and_deletes_source(self) -> None:
        client = FakeS3({self.SRC: (10, "abc")})
        self.assertEqual(rl.move_object(client, BUCKET, self.move(), keep_source=False), "moved")
        self.assertEqual(list(client.objects), [self.DEST])

    def test_keep_source_copies_only(self) -> None:
        client = FakeS3({self.SRC: (10, "abc")})
        self.assertEqual(rl.move_object(client, BUCKET, self.move(), keep_source=True), "copied")
        self.assertEqual(sorted(client.objects), sorted([self.DEST, self.SRC]))

    def test_identical_destination_is_not_copied_again(self) -> None:
        client = FakeS3({self.SRC: (10, "abc"), self.DEST: (10, "abc")})
        self.assertEqual(rl.move_object(client, BUCKET, self.move(), keep_source=False), "already present")
        self.assertEqual(client.deleted, [self.SRC])

    def test_different_destination_is_a_conflict_and_nothing_is_deleted(self) -> None:
        client = FakeS3({self.SRC: (10, "abc"), self.DEST: (99, "zzz")})
        with self.assertRaises(rl.DestinationConflictError):
            rl.move_object(client, BUCKET, self.move(), keep_source=False)
        self.assertEqual(client.deleted, [])
        self.assertEqual(client.objects[self.DEST], (99, "zzz"))

    def test_failed_verification_keeps_the_source(self) -> None:
        client = FakeS3({self.SRC: (10, "abc")}, corrupt_copies=True)
        with self.assertRaises(rl.CopyVerificationError):
            rl.move_object(client, BUCKET, self.move(), keep_source=False)
        self.assertEqual(client.deleted, [])
        self.assertIn(self.SRC, client.objects)


class ExecuteMovesTest(unittest.TestCase):
    def test_failures_do_not_stop_the_other_moves(self) -> None:
        good = "geo/geo-an/u_ex210105.log.gz"
        bad = "geo/geo-an/u_ex210106.log.gz"
        moves = rl.plan_source([obj(good), obj(bad)], "geo", "geo-an", "legacy").moves
        client = FakeS3(
            {good: (10, "abc"), bad: (10, "abc"), "geo/legacy/geo-an/2021/01/u_ex210106.log.gz": (5, "other")}
        )
        done, failed = rl.execute_moves(client, BUCKET, moves, keep_source=False, workers=2)
        self.assertEqual([move.source.key for move, _ in done], [good])
        self.assertEqual([move.source.key for move, _ in failed], [bad])


class ListObjectsTest(unittest.TestCase):
    def test_collects_every_page_and_strips_etag_quotes(self) -> None:
        pages = [
            {"Contents": [{"Key": "geo/geo-an/a", "Size": 1, "ETag": '"e1"'}]},
            {},
            {"Contents": [{"Key": "geo/geo-an/b", "Size": 2, "ETag": '"e2"'}]},
        ]

        class Paginator:
            def paginate(self, Bucket: str, Prefix: str) -> List[Dict[str, Any]]:
                self.args = (Bucket, Prefix)
                return pages

        class Client:
            def get_paginator(self, name: str) -> Paginator:
                assert name == "list_objects_v2"
                return Paginator()

        found = rl.list_objects(Client(), BUCKET, "geo/geo-an/")
        self.assertEqual(
            [(o.key, o.size, o.etag) for o in found], [("geo/geo-an/a", 1, "e1"), ("geo/geo-an/b", 2, "e2")]
        )


class HeadObjectTest(unittest.TestCase):
    def test_missing_object_is_none(self) -> None:
        self.assertIsNone(rl.head_object(FakeS3({}), BUCKET, "nope"))

    def test_other_errors_propagate(self) -> None:
        class Denied:
            def head_object(self, Bucket: str, Key: str) -> None:
                raise ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject")

        with self.assertRaises(ClientError):
            rl.head_object(Denied(), BUCKET, "key")


if __name__ == "__main__":
    unittest.main()
