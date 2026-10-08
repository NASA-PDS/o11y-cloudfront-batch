"""Unit tests for scripts/logstash_build_config.sh and its ENABLED_NODES support."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_SCRIPT = os.path.join(REPO_ROOT, "scripts", "logstash_build_config.sh")
SOURCE_CONFIG_DIR = os.path.join(REPO_ROOT, "config", "logstash", "config")

ALL_NODES = ["atm", "en", "geo", "img", "naif", "ppi", "rings", "sbn"]


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

    def run_build(self, enabled_nodes=None):
        """Run the real build script against the scratch settings directory."""
        env = os.environ.copy()
        env["LS_SETTINGS_DIR"] = self.settings_dir
        env["ENABLED_NODES"] = enabled_nodes or ""
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


if __name__ == "__main__":
    unittest.main()
