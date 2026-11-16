"""Unit tests for scripts/s3-reorganize-legacy-logs.py."""
import argparse
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
    """The head, copy and delete calls of an S3 client, over a dict of key -> (size, etag[, checksum]).

    As in S3, a copy of a multipart object gets a plain ETag and only has a checksum when one was requested.
    """

    def __init__(self, objects: Dict[str, Any], corrupt_copies: bool = False) -> None:
        self.objects = dict(objects)
        self.corrupt_copies = corrupt_copies
        self.deleted: List[str] = []
        self.copy_checksum_requests: List[Any] = []

    def head_object(self, Bucket: str, Key: str, ChecksumMode: Any = None) -> Dict[str, Any]:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        size, etag, *rest = self.objects[Key]
        meta: Dict[str, Any] = {"ContentLength": size, "ETag": f'"{etag}"'}
        if rest and rest[0] and ChecksumMode == "ENABLED":
            meta.update({"ChecksumType": "FULL_OBJECT", "ChecksumCRC64NVME": rest[0]})
        return meta

    def copy_object(self, CopySource: Dict[str, str], Bucket: str, Key: str, ChecksumAlgorithm: Any = None) -> None:
        size, etag, *rest = self.objects[CopySource["Key"]]
        self.copy_checksum_requests.append(ChecksumAlgorithm)
        checksum = rest[0] if rest and ChecksumAlgorithm else None
        new_etag = "plain-md5" if "-" in etag else etag
        self.objects[Key] = (size + 1 if self.corrupt_copies else size, new_etag, checksum)

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

    def test_hidden_files_are_reported_not_moved(self) -> None:
        plan = rl.plan_source(
            [obj("img/img-pdsimg2-http/.access_log-20241015.lxNDxM.gz")], "img", "img-pdsimg2-http", "legacy"
        )
        self.assertEqual(plan.moves, [])
        self.assertEqual([reason for _, reason in plan.skipped], ["hidden file"])

    def test_year_filter(self) -> None:
        objects = [obj("geo/geo-an/u_ex201231.log.gz"), obj("geo/geo-an/u_ex210101.log.gz")]
        plan = rl.plan_source(objects, "geo", "geo-an", "legacy", year=2021)
        self.assertEqual([m.year for m in plan.moves], [2021])
        self.assertEqual(plan.skipped, [])


class RouteTest(unittest.TestCase):
    ROUTES = [rl.route_type("atm-atmos-apache=atm-apache-http"), rl.route_type("atm-atmos-ftp=atm-atmos-ftp")]

    def test_files_of_a_mixed_directory_go_to_their_own_source(self) -> None:
        objects = [obj("atm/all/atm-atmos-apache.2025-06-01.txt.gz"), obj("atm/all/atm-atmos-ftp.2025-07-01.gz")]
        plan = rl.plan_source(objects, "atm", "all", "legacy", routes=self.ROUTES)
        self.assertEqual(
            [m.dest_key for m in plan.moves],
            [
                "atm/legacy/atm-apache-http/2025/06/atm-atmos-apache.2025-06-01.txt.gz",
                "atm/legacy/atm-atmos-ftp/2025/07/atm-atmos-ftp.2025-07-01.gz",
            ],
        )

    def test_a_file_matching_no_route_is_left_alone(self) -> None:
        plan = rl.plan_source([obj("atm/all/other-2025-06-01.gz")], "atm", "all", "legacy", routes=self.ROUTES)
        self.assertEqual(plan.moves, [])
        self.assertEqual([reason for _, reason in plan.skipped], ["matches no --route"])

    def test_without_routes_files_keep_their_source_directory(self) -> None:
        plan = rl.plan_source(
            [obj("atm/atm-apache-http/atm-atmos-apache.2025-06-01.txt.gz")], "atm", "atm-apache-http", "legacy"
        )
        self.assertEqual(
            plan.moves[0].dest_key, "atm/legacy/atm-apache-http/2025/06/atm-atmos-apache.2025-06-01.txt.gz"
        )

    def test_route_text_must_have_a_pattern_and_a_destination(self) -> None:
        for bad in ("nodest", "=dest", "pattern=", "([unclosed=dest"):
            with self.assertRaises(argparse.ArgumentTypeError, msg=bad):
                rl.route_type(bad)

    def test_a_route_cannot_point_at_weblogs_or_leave_the_node(self) -> None:
        base = ["--bucket", BUCKET, "--node", "atm", "--source", "all"]
        self.assertIsNotNone(rl.validate_names(rl.parse_args([*base, "--route", "x=weblogs"])))
        self.assertIsNotNone(rl.validate_names(rl.parse_args([*base, "--route", "x=a/b"])))
        self.assertIsNone(rl.validate_names(rl.parse_args([*base, "--route", "x=atm-apache-http"])))

    def test_two_objects_with_one_destination_are_reported(self) -> None:
        first = rl.plan_source(
            [obj("atm/all/atm-atmos-apache.2025-06-01.txt.gz")], "atm", "all", "legacy", routes=self.ROUTES
        )
        second = rl.plan_source(
            [obj("atm/atm-apache-http/atm-atmos-apache.2025-06-01.txt.gz")], "atm", "atm-apache-http", "legacy"
        )
        clashes = rl.duplicate_destinations(first.moves + second.moves)
        self.assertEqual(clashes, ["atm/legacy/atm-apache-http/2025/06/atm-atmos-apache.2025-06-01.txt.gz"])
        self.assertEqual(rl.duplicate_destinations(first.moves), [])


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


class MultipartMoveTest(unittest.TestCase):
    SRC = "ppi/ppi-tomcat/pds-ppi_2021-01.log.gz"
    DEST = "ppi/legacy/ppi-tomcat/2021/01/pds-ppi_2021-01.log.gz"

    def move(self) -> Any:
        return rl.plan_source([obj(self.SRC, size=10, etag="abc-15")], "ppi", "ppi-tomcat", "legacy").moves[0]

    def test_multipart_object_is_verified_by_checksum(self) -> None:
        client = FakeS3({self.SRC: (10, "abc-15", "crc")})
        self.assertEqual(rl.move_object(client, BUCKET, self.move(), keep_source=False), "moved")
        self.assertEqual(client.copy_checksum_requests, ["CRC64NVME"])
        self.assertEqual(list(client.objects), [self.DEST])

    def test_single_part_object_does_not_request_a_checksum(self) -> None:
        client = FakeS3({"geo/geo-an/u_ex210105.log.gz": (10, "abc", "crc")})
        move = rl.plan_source([obj("geo/geo-an/u_ex210105.log.gz")], "geo", "geo-an", "legacy").moves[0]
        rl.move_object(client, BUCKET, move, keep_source=True)
        self.assertEqual(client.copy_checksum_requests, [None])

    def test_multipart_object_without_a_checksum_is_not_deleted(self) -> None:
        client = FakeS3({self.SRC: (10, "abc-15")})
        with self.assertRaises(rl.CopyVerificationError):
            rl.move_object(client, BUCKET, self.move(), keep_source=False)
        self.assertEqual(client.deleted, [])
        self.assertIn(self.SRC, client.objects)

    def test_identical_multipart_destination_is_not_copied_again(self) -> None:
        client = FakeS3({self.SRC: (10, "abc-15", "crc"), self.DEST: (10, "plain-md5", "crc")})
        self.assertEqual(rl.move_object(client, BUCKET, self.move(), keep_source=False), "already present")
        self.assertEqual(client.copy_checksum_requests, [])

    def test_multipart_destination_with_a_different_checksum_is_a_conflict(self) -> None:
        client = FakeS3({self.SRC: (10, "abc-15", "crc"), self.DEST: (10, "plain-md5", "other")})
        with self.assertRaises(rl.DestinationConflictError):
            rl.move_object(client, BUCKET, self.move(), keep_source=False)
        self.assertEqual(client.deleted, [])


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
