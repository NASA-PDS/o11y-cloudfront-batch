"""Integration tests for LOG_YEARS: the generated inputs run in Logstash against a fake S3 server.

The real input configs are built by scripts/logstash_build_config.sh with LOG_YEARS set, pointed at a
local moto S3 server, and run in Logstash with a file output that records the key of every object the
s3 inputs ingest. The year patterns therefore run in the plugin's own regex engine, over the real
prefixes of every node and the CloudFront bucket. The shared filter is not part of these tests.
"""
import gzip
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import Iterable
from typing import List
from typing import Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "scripts" / "logstash_build_config.sh"
SOURCE_CONFIG_DIR = REPO_ROOT / "config" / "logstash" / "config"

NODE_BUCKET = "test-bucket"
CF_BUCKET = "test-cf-bucket"
LOG_LINE = b'203.0.113.5 - - [01/Jan/2023:00:00:00 +0000] "GET / HTTP/1.1" 200 1 "-" "test"\n'

# One object per input prefix and per date shape, with the year as {year} (YYYY) and {yy} (YY).
# Every base name is unique: the s3 input downloads each object under its base name in a directory
# shared by all inputs.
NODE_KEY_TEMPLATES = [
    "geo/geo-an/u_ex{yy}0101.log.gz",
    "geo/geo-ode-mapserver/u_ex{yy}0601mars2a.log.gz",
    "geo/weblogs/geo-iis/ode.rsl.wustl.edu/{year}/10/u_ex{yy}1001.log.gz",
    "geo/weblogs/geo-apache/geoweb.rsl.wustl.edu/{year}/10/access.log-{year}-10-22.gz",
    "atm/atm-apache-http/atm-atmos-apache.{year}-05-01.txt.gz",
    "atm/all/atm-atmos-ftp.{year}-07-01.gz",
    "eng/en/en-http-pdscloud-prod1/access_log-{year}0418.gz",
    "img/img-pdsimg1-http/access_log-{year}1023.gz",
    "naif/naif-httpdlogs/naif_access_log.{yy}0101.gz",
    "naif/naif-xferlogs/naif_xferlog.{yy}0312.gz",
    "naif/weblogs/naif-apache/access_log.{yy}0102.gz",
    "ppi/ppi-tomcat/pds-ppi_{year}-04.log.gz",
    "rings/rings-apache-metrics/server1-pds-rings-apache2.{year}-01-01.log.gz",
    "rings/rings-apache-metrics/tools2_access_log-{year}-01-01.gz",
    "rings/rings-apache-metrics/tools_access_log-{year}-08-02.gz",
    "sbn/sbn-apache-http/sbnumd{year}0101.log.gz",
    "sbn/sbn-psi-tomcat/sbn_archive_{year}0101.txt.gz",
    "sbn/sbn-psi-tools/sbnapps_{year}0101.txt.gz",
]
CF_KEY_TEMPLATES = [
    "pdc-cds-infra/cloudfront/access/json/pds-main/year={year}/month=07/day=17/EDISTRIBUTIONID.{year}-07-17-21.d7397384.gz",
    "pdc-cds-infra/cloudfront/access/w3c/pds-main/year={year}/month=08/day=14/EDISTRIBUTIONID.{year}-08-14-23.e4a0766e.gz",
    "pdc-cds-infra/cloudfront/access/w3c/portal-legacy/year={year}/month=08/day=21/EDISTRIBUTIONID.{year}-08-21-23.25565567.gz",
]
# Under a polled prefix but never ingested: IMG excludes undated rotations, temp files and nohup.out.
IMG_JUNK_KEYS = [
    "img/img-pdsimg1-http/access_log.3.gz",
    "img/img-pdsimg1-http/nohup.out.gz",
    "img/img-pdsimg2-http/.access_log-20241015.lxNDxM.gz",
]
# Ingested only when LOG_YEARS is unset: no date in the key and no input excludes it.
UNDATED_KEY = "sbn/sbn-psi-tools/robots.txt.tmp.gz"

OUTPUT_CONFIG = """
output {{
  file {{
    path => "{keys_file}"
    codec => line {{ format => "%{{[@metadata][s3][key]}}" }}
    flush_interval => 1
  }}
}}
"""


def keys_for_years(years: Iterable[int]) -> List[str]:
    """Return the sorted keys the templates produce for ``years``."""
    return sorted(
        template.format(year=year, yy=str(year)[2:])
        for year in years
        for template in NODE_KEY_TEMPLATES + CF_KEY_TEMPLATES
    )


def free_port() -> int:
    """Return a TCP port that is free on the loopback interface."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestLogYearsIntegration(unittest.TestCase):
    """Run the LOG_YEARS-expanded S3 inputs in Logstash and check which objects are ingested."""

    YEARS = (2022, 2023, 2024)
    INGEST_TIMEOUT = 240  # seconds to wait for the expected objects
    SETTLE_SECONDS = 10  # extra time to catch objects that should not have been ingested

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        """Start a fake S3 server and fill it with objects for several years."""
        try:
            result = subprocess.run(["logstash", "--version"], capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                raise FileNotFoundError("Logstash version check failed")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            raise unittest.SkipTest("Logstash not available on this system.")
        try:
            import boto3
            from moto.server import ThreadedMotoServer
        except ImportError as err:
            raise unittest.SkipTest(f"moto[server] is not installed: {err}")

        cls.work_dir = Path(tempfile.mkdtemp(prefix="log_years_"))
        cls.addClassCleanup(shutil.rmtree, cls.work_dir, ignore_errors=True)

        port = free_port()
        server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
        server.start()
        cls.addClassCleanup(server.stop)
        cls.endpoint = f"http://127.0.0.1:{port}"

        s3 = boto3.client(
            "s3",
            endpoint_url=cls.endpoint,
            region_name="us-west-2",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        for bucket in (NODE_BUCKET, CF_BUCKET):
            s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "us-west-2"})
        body = gzip.compress(LOG_LINE)
        for bucket, key in cls.all_objects():
            s3.put_object(Bucket=bucket, Key=key, Body=body)
        time.sleep(3)  # the s3 input defers objects modified in the last two seconds

    @classmethod
    def all_objects(cls) -> List[Tuple[str, str]]:
        """Return every (bucket, key) to upload."""
        node_keys = (
            [t.format(year=year, yy=str(year)[2:]) for year in cls.YEARS for t in NODE_KEY_TEMPLATES]
            + IMG_JUNK_KEYS
            + [UNDATED_KEY]
        )
        cf_keys = [t.format(year=year) for year in cls.YEARS for t in CF_KEY_TEMPLATES]
        return [(NODE_BUCKET, k) for k in node_keys] + [(CF_BUCKET, k) for k in cf_keys]

    def build_inputs(self, log_years: str) -> str:
        """Build every node pipeline with the real build script and return their input sections."""
        settings_dir = Path(tempfile.mkdtemp(dir=self.work_dir)) / "config"
        shutil.copytree(SOURCE_CONFIG_DIR, settings_dir)
        env = os.environ.copy()
        env["LS_SETTINGS_DIR"] = str(settings_dir)
        env["LOG_YEARS"] = log_years
        env.pop("ENABLED_NODES", None)
        result = subprocess.run(["bash", str(BUILD_SCRIPT)], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        pipelines = sorted((settings_dir / "pipelines").glob("pipeline-*.conf"))
        self.assertEqual(len(pipelines), 8)
        return "\n".join(p.read_text().split("\nfilter {", 1)[0] for p in pipelines)

    def point_at_fake_s3(self, inputs: str, sincedb_dir: Path) -> str:
        """Aim the inputs at the fake S3 server, poll every second and keep state in ``sincedb_dir``."""
        inputs = inputs.replace(
            'region => "us-west-2"',
            f'region => "us-west-2"\n    endpoint => "{self.endpoint}"\n'
            '    additional_settings => { "force_path_style" => "true" }',
        )
        inputs = re.sub(r"interval => \d+", "interval => 1", inputs)
        return inputs.replace("/var/lib/logstash/plugins/inputs/s3/", f"{sincedb_dir}/")

    def ingest(self, log_years: str, sincedb_dir: Path, expected: int) -> List[str]:
        """Run Logstash on the inputs for ``log_years`` and return the sorted keys it ingested."""
        sincedb_dir.mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(dir=self.work_dir))
        keys_file = run_dir / "keys.txt"
        pipeline = self.point_at_fake_s3(self.build_inputs(log_years), sincedb_dir)
        pipeline += OUTPUT_CONFIG.format(keys_file=keys_file)
        conf = run_dir / "pipeline.conf"
        conf.write_text(pipeline)

        env = os.environ.copy()
        env.update(
            {
                "S3_BUCKET_NAME": NODE_BUCKET,
                "S3_CF_BUCKET_NAME": CF_BUCKET,
                "AWS_ACCESS_KEY_ID": "testing",
                "AWS_SECRET_ACCESS_KEY": "testing",
                "AWS_EC2_METADATA_DISABLED": "true",
            }
        )
        log_path = run_dir / "logstash.log"
        with open(log_path, "w") as log:
            proc = subprocess.Popen(
                ["logstash", "-f", str(conf), "--path.data", str(run_dir / "data")],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                self.wait_for_keys(proc, keys_file, log_path, expected)
                time.sleep(self.SETTLE_SECONDS)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=90)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        return sorted(keys_file.read_text().split()) if keys_file.exists() else []

    def wait_for_keys(self, proc: "subprocess.Popen[bytes]", keys_file: Path, log_path: Path, expected: int) -> None:
        """Wait until ``expected`` keys are written, Logstash exits or the timeout passes."""
        deadline = time.monotonic() + self.INGEST_TIMEOUT
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                self.fail(f"Logstash exited early ({proc.returncode}):\n{log_path.read_text()[-4000:]}")
            if keys_file.exists() and len(keys_file.read_text().split()) >= expected:
                return
            time.sleep(1)

    def test_one_year_loads_only_that_year(self):
        """LOG_YEARS=2023 ingests every 2023 object across all nodes and CloudFront, and nothing else."""
        expected = keys_for_years([2023])
        got = self.ingest("2023", Path(tempfile.mkdtemp(dir=self.work_dir)), len(expected))
        self.assertEqual(got, expected)

    def test_adding_a_year_loads_only_the_new_year(self):
        """Redeploying with a longer list reads the new year and leaves the loaded year's position alone."""
        sincedb_dir = Path(tempfile.mkdtemp(dir=self.work_dir))
        first = keys_for_years([2023])
        self.assertEqual(self.ingest("2023", sincedb_dir, len(first)), first)

        added = keys_for_years([2024])
        self.assertEqual(self.ingest("2023 2024", sincedb_dir, len(added)), added)

    def test_unset_loads_every_year_and_skips_junk(self):
        """With LOG_YEARS unset every dated object is ingested, plus the undated one, minus IMG junk."""
        expected = sorted(keys_for_years(self.YEARS) + [UNDATED_KEY])
        got = self.ingest("", Path(tempfile.mkdtemp(dir=self.work_dir)), len(expected))
        self.assertEqual(got, expected)


if __name__ == "__main__":
    unittest.main()
