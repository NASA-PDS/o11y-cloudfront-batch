"""Unit tests for scripts/logstash_build_config.sh: ENABLED_NODES and LOG_YEARS support."""
import glob
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_SCRIPT = os.path.join(REPO_ROOT, "scripts", "logstash_build_config.sh")
SOURCE_CONFIG_DIR = os.path.join(REPO_ROOT, "config", "logstash", "config")
SOURCE_INPUT_DIR = os.path.join(SOURCE_CONFIG_DIR, "inputs")

ALL_NODES = ["atm", "en", "geo", "img", "naif", "ppi", "rings", "sbn"]

S3_BLOCK = re.compile(r"^  s3 \{\n(.*?)^  \}$", re.MULTILINE | re.DOTALL)

# Keys in the shapes found in the prod buckets, grouped by the year they belong to.
KEYS_2023 = [
    "geo/geo-an/u_ex230101.log.gz",
    "geo/geo-ftp/u_ex230101web4pp.log.gz",
    "geo/geo-ode-mapserver/u_ex230601mars2a.log.gz",
    "geo/weblogs/geo-iis/ode.rsl.wustl.edu/2023/10/u_ex231001.log.gz",
    "geo/weblogs/geo-apache/geoweb.rsl.wustl.edu/2023/10/access.log-2023-10-22.gz",
    "atm/atm-apache-http/atm-atmos-apache.2023-05-01.txt.gz",
    "atm/all/atm-atmos-ftp.2023-07-01.gz",
    "eng/en/en-http-pdscloud-prod1/access_log-20230418.gz",
    "eng/en/en-http-pdscloud-prod1/access_log.2023-04-14.txt.gz",
    "eng/en/en-tomcat-pds-prod1/localhost_access_log.2023-01-01.txt.gz",
    "img/img-pdsimage-http/ssl_access_2023-01-01.log.gz",
    "img/img-pdsimg1-http/access_log-20231023.gz",
    "naif/naif-httpdlogs/naif_access_log.230101.gz",
    "naif/naif-xferlogs/naif_xferlog.230312.gz",
    "naif/weblogs/naif-apache/access_log.230102.gz",
    "ppi/ppi-tomcat/pds-ppi_2023-04.log.gz",
    "rings/rings-apache-metrics/server1-pds-rings-apache2.2023-01-01.log.gz",
    "rings/rings-apache-metrics/tools2_access_log-2023-01-01.gz",
    "rings/rings-apache-metrics/tools_access_log-2023-08-02.gz",
    "sbn/sbn-apache-http/sbnumd20230101.log.gz",
    "sbn/sbn-psi-tomcat/sbn_archive_20230101.txt.gz",
    "sbn/sbn-psi-tools/sbnapps_20230101.txt.gz",
    "pdc-cds-infra/cloudfront/access/w3c/pds-main/year=2023/month=08/day=14/EDISTRIBUTIONID.2023-08-14-23.e4a0766e.gz",
    "pdc-cds-infra/cloudfront/access/json/pds-main/year=2023/month=07/day=17/EDISTRIBUTIONID.2023-07-17-21.d7397384.gz",
]
KEYS_OTHER_YEARS = [
    "geo/geo-an/u_ex220101.log.gz",
    "geo/geo-an/u_ex240523.log.gz",
    "geo/geo-ode-mapserver/u_ex24122bm1ms.log.gz",
    "geo/weblogs/geo-iis/ode.rsl.wustl.edu/2025/10/u_ex251001.log.gz",
    "geo/weblogs/geo-apache/geoweb.rsl.wustl.edu/2026/10/access.log-2026-10-13.gz",
    "atm/atm-apache-http/atm-atmos-apache.2022-05-01.txt.gz",
    "atm/atm-apache-http/atm-atmos-apache.txt-20150601.gz",
    "eng/en/en-http-pdscloud-prod1/access_log-20220418.gz",
    "eng/en/en-http-pdscloud-prod1/access_log.2025-09-07.txt.gz",
    "img/img-pdsimg1-http/access_log.3.gz",
    "naif/naif-httpdlogs/naif_access_log.221023.gz",
    "naif/naif-httpdlogs/access_log.240401.gz",
    "naif/weblogs/naif-apache/access_log.260902.gz",
    "ppi/ppi-tomcat/pds-ppi_2021-01.log.gz",
    "rings/rings-apache-metrics/server2-pds-rings-apache2.2025-08-31.log.gz",
    "sbn/sbn-apache-http/sbnumd20210101.log.gz",
    "sbn/sbn-psi-tools/robots.txt.tmp.gz",
    "pdc-cds-infra/cloudfront/access/w3c/pds-main/year=2024/month=08/day=14/EDISTRIBUTIONID.2024-08-14-23.e4a0766e.gz",
    "pdc-cds-infra/cloudfront/access/json/pds-main/year=2026/month=07/day=17/EDISTRIBUTIONID.2026-07-17-21.d7397384.gz",
]


def parse_s3_blocks(conf_text):
    """Return one dict of `key => "value"` settings per top-level s3 block in an input config."""
    blocks = []
    for body in S3_BLOCK.findall(conf_text):
        settings = {}
        for key in ("prefix", "exclude_pattern", "sincedb_path", "id"):
            found = re.findall(rf'^    {key} => "(.*)"$', body, re.MULTILINE)
            settings[key] = found
        blocks.append(settings)
    return blocks


def input_section(pipeline_conf_text):
    """Return the `input { ... }` section of a generated pipeline config."""
    return pipeline_conf_text.split("\nfilter {", 1)[0]


class TestLogstashBuildConfig(unittest.TestCase):
    """Test cases for scripts/logstash_build_config.sh node filtering."""

    def setUp(self):
        """Copy the real Logstash config templates into a scratch directory."""
        self.settings_dir = tempfile.mkdtemp()
        shutil.rmtree(self.settings_dir)
        shutil.copytree(SOURCE_CONFIG_DIR, self.settings_dir)

    def tearDown(self):
        """Clean up the scratch directory."""
        shutil.rmtree(self.settings_dir, ignore_errors=True)

    def run_build(self, enabled_nodes=None, log_years=None):
        """Run the real build script against the scratch settings directory."""
        env = os.environ.copy()
        env["LS_SETTINGS_DIR"] = self.settings_dir
        env["ENABLED_NODES"] = enabled_nodes or ""
        env["LOG_YEARS"] = log_years or ""
        return subprocess.run(
            ["bash", BUILD_SCRIPT],
            env=env,
            capture_output=True,
            text=True,
        )

    def pipeline_ids(self):
        """Return the sorted list of `pipeline.id` values in the generated pipelines.yml."""
        with open(os.path.join(self.settings_dir, "pipelines.yml")) as f:
            content = f.read()
        return sorted(re.findall(r"^- pipeline\.id:\s*(\S+)", content, re.MULTILINE))

    def pipeline_conf_files(self):
        """Return the sorted list of generated pipeline-*.conf basenames."""
        pipeline_dir = os.path.join(self.settings_dir, "pipelines")
        return sorted(os.listdir(pipeline_dir))

    def test_default_enables_all_nodes(self):
        """Unset ENABLED_NODES must enable every node (unchanged default behavior)."""
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.pipeline_ids(), sorted(ALL_NODES))
        self.assertEqual(
            self.pipeline_conf_files(),
            sorted(f"pipeline-pds-input-s3-{n}.conf" for n in ALL_NODES),
        )

    def test_single_node_enabled(self):
        """ENABLED_NODES=en restricts both pipelines.yml and pipelines/ to EN only."""
        result = self.run_build("en")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.pipeline_ids(), ["en"])
        self.assertEqual(self.pipeline_conf_files(), ["pipeline-pds-input-s3-en.conf"])

    def test_multiple_nodes_case_insensitive_and_comma_separated(self):
        """ENABLED_NODES accepts a comma-separated, case-insensitive list."""
        result = self.run_build("EN, Geo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.pipeline_ids(), ["en", "geo"])
        self.assertEqual(
            self.pipeline_conf_files(),
            ["pipeline-pds-input-s3-en.conf", "pipeline-pds-input-s3-geo.conf"],
        )

    def test_unknown_node_fails_with_valid_ids_listed(self):
        """An unrecognized node ID fails the build and lists the valid IDs."""
        result = self.run_build("bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bogus", result.stderr)
        for node in ALL_NODES:
            self.assertIn(node, result.stderr)

    def test_switching_to_a_subset_removes_stale_pipeline_files(self):
        """Rebuilding with fewer nodes removes pipeline files left over from a full build."""
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.pipeline_conf_files()), len(ALL_NODES))

        result = self.run_build("en")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.pipeline_conf_files(), ["pipeline-pds-input-s3-en.conf"])

    def pipeline_input_blocks(self, node):
        """Return the parsed s3 blocks of a generated node pipeline."""
        path = os.path.join(self.settings_dir, "pipelines", f"pipeline-pds-input-s3-{node}.conf")
        with open(path) as f:
            return parse_s3_blocks(input_section(f.read()))

    def year_pattern(self, year):
        """Build with one year and return the exclude_pattern the NAIF xferlogs input gets for it."""
        result = self.run_build("naif", str(year))
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.pipeline_input_blocks("naif")[1]["exclude_pattern"][0]

    def test_source_inputs_have_unique_ids_and_sincedb_paths(self):
        """Every s3 input in the source configs has its own id and sincedb file."""
        ids, sincedbs = [], []
        for path in glob.glob(os.path.join(SOURCE_INPUT_DIR, "pds-input-s3-*.conf")):
            with open(path) as f:
                for block in parse_s3_blocks(f.read()):
                    self.assertEqual(len(block["prefix"]), 1, path)
                    ids += block["id"]
                    sincedbs += block["sincedb_path"]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(sincedbs), len(set(sincedbs)))
        self.assertGreater(len(ids), 40)

    def test_no_log_years_leaves_inputs_unchanged(self):
        """With LOG_YEARS unset the generated input section is the source input file verbatim."""
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Log years: all", result.stdout)
        for node in ALL_NODES:
            with open(os.path.join(SOURCE_INPUT_DIR, f"pds-input-s3-{node}.conf")) as f:
                source = f.read()
            path = os.path.join(self.settings_dir, "pipelines", f"pipeline-pds-input-s3-{node}.conf")
            with open(path) as f:
                self.assertTrue(f.read().startswith(source), node)

    def test_log_years_emit_one_block_per_year_with_own_state(self):
        """Each year gets its own copy of every s3 block with a year-suffixed sincedb and id."""
        result = self.run_build(log_years="2022, 2023")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Log years: 2022 2023", result.stdout)
        for node in ALL_NODES:
            with open(os.path.join(SOURCE_INPUT_DIR, f"pds-input-s3-{node}.conf")) as f:
                source_blocks = parse_s3_blocks(f.read())
            blocks = self.pipeline_input_blocks(node)
            self.assertEqual(len(blocks), 2 * len(source_blocks), node)
            for block in blocks:
                self.assertEqual(len(block["exclude_pattern"]), 1, node)
            ids = [b["id"][0] for b in blocks]
            sincedbs = [b["sincedb_path"][0] for b in blocks]
            self.assertEqual(len(ids), len(set(ids)), node)
            self.assertEqual(len(sincedbs), len(set(sincedbs)), node)
            for year in ("2022", "2023"):
                self.assertEqual(sum(i.endswith(f"_{year}") for i in ids), len(source_blocks), node)
                self.assertEqual(sum(s.endswith(f"_{year}") for s in sincedbs), len(source_blocks), node)

    def test_log_years_ranges_are_expanded_and_deduplicated(self):
        """A YYYY-YYYY range expands to every year in it and repeated years collapse."""
        result = self.run_build("ppi", "2022 2021-2023")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Log years: 2022 2021 2023", result.stdout)
        ids = sorted(b["id"][0] for b in self.pipeline_input_blocks("ppi"))
        self.assertEqual(ids, [f"file_input_ppi1_{y}" for y in (2021, 2022, 2023)])

    def test_invalid_log_years_fail_the_build(self):
        """Malformed years and backwards ranges are rejected before any config is written."""
        for bad in ("23", "abcd", "2023-21", "2024-2021", "2023;2024"):
            result = self.run_build(log_years=bad)
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("LOG_YEARS", result.stderr, bad)

    def test_year_pattern_excludes_other_years_and_keeps_the_requested_one(self):
        """The generated exclude_pattern (a key matching it is skipped) selects exactly the year."""
        pattern = re.compile(self.year_pattern(2023))
        for key in KEYS_2023:
            self.assertIsNone(pattern.search(key), f"2023 key was excluded: {key}")
        for key in KEYS_OTHER_YEARS:
            self.assertIsNotNone(pattern.search(key), f"non-2023 key was kept: {key}")

    def test_year_pattern_selects_each_year_from_the_two_digit_names(self):
        """Two-digit YYMMDD names map to the right year, including the 2020s decade boundary."""
        pattern_2021 = re.compile(self.year_pattern(2021))
        pattern_2025 = re.compile(self.year_pattern(2025))
        self.assertIsNone(pattern_2021.search("geo/geo-an/u_ex210101.log.gz"))
        self.assertIsNotNone(pattern_2021.search("geo/geo-an/u_ex250101.log.gz"))
        self.assertIsNone(pattern_2025.search("geo/geo-an/u_ex250930.log.gz"))
        self.assertIsNotNone(pattern_2025.search("geo/geo-an/u_ex210101.log.gz"))

    def test_img_junk_is_excluded_without_log_years_and_combined_with_them(self):
        """IMG skips undated and temp files on its own, and the year filter is OR-ed on top."""
        with open(os.path.join(SOURCE_INPUT_DIR, "pds-input-s3-img.conf")) as f:
            base = re.compile(parse_s3_blocks(f.read())[0]["exclude_pattern"][0])
        junk = [
            "img/img-pdsimg1-http/nohup.out.gz",
            "img/img-pdsimg1-http/img-non-test-files.txt.gz",
            "img/img-pdsimg2-http/.access_log-20241015.lxNDxM.gz",
            "img/img-pdsimg2-http/access_log.8.gz",
        ]
        for key in junk:
            self.assertIsNotNone(base.search(key), key)
        for key in ("img/img-pdsimg1-http/access_log-20231023.gz", "img/img-pdsimg3-http/access_log.2021-01-01.txt.gz"):
            self.assertIsNone(base.search(key), key)

        result = self.run_build("img", "2023")
        self.assertEqual(result.returncode, 0, result.stderr)
        combined = re.compile(self.pipeline_input_blocks("img")[0]["exclude_pattern"][0])
        for key in junk:
            self.assertIsNotNone(combined.search(key), key)
        self.assertIsNone(combined.search("img/img-pdsimg1-http/access_log-20231023.gz"))
        self.assertIsNotNone(combined.search("img/img-pdsimg3-http/access_log.2021-01-01.txt.gz"))


if __name__ == "__main__":
    unittest.main()
