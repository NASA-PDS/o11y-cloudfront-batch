"""
Integration tests for Logstash pipeline processing.

This module replaces the functionality of run_tests.sh with a Python-based
testing approach that provides better error handling, cross-platform compatibility,
and integration with unittest.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from typing import Dict
from typing import List
from typing import Tuple


class TestLogstashIntegration(unittest.TestCase):
    """Integration tests for Logstash pipeline processing."""

    # ============================================================================
    # CONFIGURATION: Set which configurations to test here
    # ============================================================================
    ENABLED_CONFIGS = [
        "https",
        "ftp",
        "cloudfront",
        "cloudfront-json",
    ]  # Options: "https", "ftp", "cloudfront", "cloudfront-json"

    # Configuration-specific test expectations
    EXPECTED_COUNTS = {
        "https": {
            "parse_failures": 0,
            "bad_logs": 0,
            "invalid_methods": 0,  # filter drops _invalid_http_method events before output
            "template_errors": 0,
            "empty_user_agents": 1,
            "duplicate_sources": 0,
            "processed_logs": 30,  # +2 url-field-parsing lines (10.99.1.1, 10.99.1.2), +1 cache-buster (91.107.144.23), +2 GEO IIS lines with time-taken "-"
            "corrupt_logs": 3,
        },
        "ftp": {
            "parse_failures": 0,
            "bad_logs": 0,
            "invalid_methods": 0,
            "template_errors": 0,
            "empty_user_agents": 0,
            "duplicate_sources": 0,
            "processed_logs": 20,
            # 5 deliberately invalid lines + the truncated IIS FTP fragment ("elClosed"); the IIS data-channel
            # lines (sc-status "-") parse and are dropped as non-RETR commands
            "corrupt_logs": 6,
        },
        "cloudfront": {
            "parse_failures": 0,
            "bad_logs": 0,
            "invalid_methods": 0,
            "template_errors": 0,
            "empty_user_agents": 1,  # line with "-" user-agent
            "duplicate_sources": 0,
            "processed_logs": 2,  # 200 OK + 404 (failure outcome, no special tag)
            "corrupt_logs": 0,
        },
        "cloudfront-json": {
            "parse_failures": 0,
            "bad_logs": 0,
            "invalid_methods": 0,
            "template_errors": 0,
            "empty_user_agents": 1,  # 403 record with cs(User-Agent) = "-"
            "duplicate_sources": 0,
            "processed_logs": 2,  # 200 GET /portal/ + 302 GET with query string
            "corrupt_logs": 0,
        },
    }

    # Logstash configuration components
    INPUT_CONFIGS = {
        "https": "test-input-https.conf",
        "ftp": "test-input-ftp.conf",
        "cloudfront": "test-input-cloudfront.conf",
        "cloudfront-json": "test-input-cloudfront-json.conf",
    }

    FILTER_CONFIGS = ["shared/pds-filter.conf"]

    OUTPUT_CONFIGS = ["test-output.conf"]

    @classmethod
    def setUpClass(cls):
        """Set up class-level configuration validation."""
        # Check if Logstash is available
        try:
            result = subprocess.run(["logstash", "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise FileNotFoundError("Logstash version check failed")
            print(f"[CONFIG] Logstash version: {result.stdout.strip()}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # Skip all tests if Logstash is not available
            raise unittest.SkipTest("Logstash not available on this system. Install Logstash to run integration tests.")

        # Validate that all enabled configs exist
        invalid_configs = [config for config in cls.ENABLED_CONFIGS if config not in cls.INPUT_CONFIGS]
        if invalid_configs:
            raise ValueError(f"Invalid enabled configs: {invalid_configs}. Available: {list(cls.INPUT_CONFIGS.keys())}")

        # Filter INPUT_CONFIGS to only include enabled ones
        cls.ACTIVE_INPUT_CONFIGS = {k: v for k, v in cls.INPUT_CONFIGS.items() if k in cls.ENABLED_CONFIGS}

        print(f"[CONFIG] Testing configurations: {cls.ENABLED_CONFIGS}")
        print(f"[CONFIG] Active input configs: {list(cls.ACTIVE_INPUT_CONFIGS.keys())}")

    def setUp(self):
        """Set up test environment before each test."""
        # Find the repository root (workspace directory) robustly
        current_file = Path(__file__).resolve()
        self.test_dir = current_file.parent
        self.workspace_dir = self.test_dir.parent
        self.ls_settings_dir = self.workspace_dir / "config" / "logstash" / "config"
        self.output_dir = self.workspace_dir / "output"
        self.test_config_dir = self.test_dir / "config"

        # Debug output for troubleshooting path issues
        print(f"[DEBUG] workspace_dir: {self.workspace_dir}")
        print(f"[DEBUG] ls_settings_dir: {self.ls_settings_dir}")
        print(f"[DEBUG] test_config_dir: {self.test_config_dir}")

        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Clean up old test directories (but be more careful about race conditions)
        if self.output_dir.exists():
            try:
                for item in self.output_dir.iterdir():
                    if item.is_dir() and (
                        item.name.startswith("data_")
                        or item.name.startswith("lsdata_")
                        or item.name.startswith("test_run_")
                    ):
                        # Only clean up directories that are clearly from previous test runs
                        try:
                            shutil.rmtree(item, ignore_errors=True)
                        except OSError:
                            # Ignore errors - another test might be using it
                            pass
            except OSError:
                # Ignore errors - directory might be in use
                pass

    # def tearDown(self):
    #     """Clean up after each test."""
    #     # Cleanup after tests - handle case where directory might not exist
    #     if self.output_dir.exists():
    #         try:
    #             # Clean up all test run directories
    #             for item in self.output_dir.iterdir():
    #                 if item.is_dir() and item.name.startswith("test_run_"):
    #                     shutil.rmtree(item, ignore_errors=True)
    #                 elif item.is_file():
    #                     item.unlink()
    #         except (FileNotFoundError, OSError):
    #             # Directory might have already been removed or is in use
    #             pass

    def get_input_config_path(self, config_name: str) -> Path:
        """Get the full path to an input configuration file."""
        if config_name not in self.ACTIVE_INPUT_CONFIGS:
            raise ValueError(f"Unknown or disabled input config: {config_name}")
        return self.test_config_dir / self.ACTIVE_INPUT_CONFIGS[config_name]

    def get_filter_config_paths(self) -> List[Path]:
        """Get the full paths to all filter configuration files."""
        return [self.ls_settings_dir / filter_config for filter_config in self.FILTER_CONFIGS]

    def get_output_config_paths(self) -> List[Path]:
        """Get the full paths to all output configuration files."""
        return [self.test_config_dir / output_config for output_config in self.OUTPUT_CONFIGS]

    def get_enabled_configs(self) -> List[Tuple[str, str]]:
        """Get list of (config_name, description) tuples for enabled configurations."""
        descriptions = {
            "https": "HTTPS Log Processing",
            "ftp": "FTP Log Processing",
            "cloudfront": "CloudFront Legacy W3C Log Processing",
            "cloudfront-json": "CloudFront JSON Standard Logging v2 Processing",
        }
        return [(config, descriptions.get(config, f"{config} Processing")) for config in self.ENABLED_CONFIGS]

    def build_pipeline_config(self, input_config_name: str) -> str:
        """
        Build a complete Logstash pipeline configuration.

        Args:
            input_config_name: Name of the input configuration to use

        Returns:
            Complete pipeline configuration as a string
        """
        config_parts = []

        # Add input configuration
        input_config_path = self.get_input_config_path(input_config_name)
        if not input_config_path.exists():
            raise FileNotFoundError(f"Input config not found: {input_config_path}")

        input_content = input_config_path.read_text()

        config_parts.append(input_content)

        # Add filter configurations
        for filter_path in self.get_filter_config_paths():
            if not filter_path.exists():
                raise FileNotFoundError(f"Filter config not found: {filter_path}")
            config_parts.append(filter_path.read_text())

        # Add output configurations
        for output_path in self.get_output_config_paths():
            if not output_path.exists():
                raise FileNotFoundError(f"Output config not found: {output_path}")
            config_parts.append(output_path.read_text())

        return "\n".join(config_parts)

    def kill_existing_logstash_processes(self):
        """Kill any existing Logstash processes to ensure clean state."""
        try:
            # Find and kill any running Logstash processes
            result = subprocess.run(["pkill", "-f", "logstash"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print("Killed existing Logstash processes")
            else:
                print("No existing Logstash processes found")

            time.sleep(3)
        except (subprocess.TimeoutExpired, OSError):
            # pkill might not be available on all systems, ignore errors
            pass

    def run_logstash_pipeline(self, input_config_name: str, description: str) -> Tuple[bool, Path]:
        """
        Run Logstash with a specific input configuration.

        Args:
            input_config_name: Name of the input configuration to use
            description: Description of the test being run

        Returns:
            Tuple of (success, output_directory_path)
        """
        print(f"\nRunning Logstash pipeline: {description}")

        # Kill any existing Logstash processes first
        self.kill_existing_logstash_processes()

        # Build the complete pipeline configuration
        try:
            pipeline_config = self.build_pipeline_config(input_config_name)
        except FileNotFoundError as e:
            self.fail(f"Configuration file not found: {e}")

        # Create temporary configuration file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as tmp_conf:
            tmp_conf_path = tmp_conf.name
            tmp_conf.write(pipeline_config)

        # Create unique output directory for this test run
        unique_output_dir = self.output_dir / f"data_{uuid.uuid4().hex}"
        unique_output_dir.mkdir(parents=True, exist_ok=True)

        # Create unique data directory for Logstash internal state (separate prefix)
        unique_data_dir = self.output_dir / f"lsdata_{uuid.uuid4().hex}"
        unique_data_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Set up environment variables for Logstash
            env = os.environ.copy()
            env["LS_SETTINGS_DIR"] = str(self.ls_settings_dir)
            env["OUTPUT_DIR"] = str(unique_output_dir)
            env.setdefault("S3_BUCKET_NAME", "test-bucket")
            env.setdefault("OPENSEARCH_URL", "https://localhost:9200")
            env.setdefault("INDEX_PREFIX", "pds-test")

            # Run Logstash with unique data directory
            cmd = ["logstash", "-f", tmp_conf_path, "--log.level=debug", "--path.data", str(unique_data_dir)]
            print(f"Running command: {' '.join(cmd)}")
            print(f"LS_SETTINGS_DIR: {env['LS_SETTINGS_DIR']}")
            print(f"OUTPUT_DIR: {env['OUTPUT_DIR']}")
            print(f"DATA_DIR: {unique_data_dir}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.workspace_dir),
                env=env,
                timeout=300,  # 5 minute timeout
            )

            # Always show Logstash output for debugging
            print(f"\nLogstash return code: {result.returncode}")
            if result.stdout:
                print(f"Logstash STDOUT:\n{result.stdout}")
            if result.stderr:
                print(f"Logstash STDERR:\n{result.stderr}")

            if result.returncode != 0:
                print(f"Logstash failed with return code {result.returncode}")
                return False, unique_output_dir

            print("Logstash completed successfully")

            # Show what files were actually created
            print(f"\nFiles created in output directory {unique_output_dir}:")
            if unique_output_dir.exists():
                for item in unique_output_dir.rglob("*"):
                    if item.is_file():
                        print(f"  {item.relative_to(unique_output_dir)}")
                    elif item.is_dir():
                        print(f"  {item.relative_to(unique_output_dir)}/ (directory)")
            else:
                print("  No output directory found!")

            return True, unique_output_dir

        except subprocess.TimeoutExpired:
            print("Logstash timed out after 5 minutes")
            return False, unique_output_dir
        finally:
            # Clean up temporary config file
            if os.path.exists(tmp_conf_path):
                os.unlink(tmp_conf_path)
            # Clean up temporary data directory
            # if unique_data_dir.exists():
            #     shutil.rmtree(unique_data_dir, ignore_errors=True)
            # Note: Don't clean up unique_output_dir here - let the test use it for validation

    def count_files_in_directory(self, directory: Path) -> int:
        """Count JSON files in a directory and all subdirectories."""
        if not directory.exists():
            return 0
        return len(list(directory.rglob("*.json")))

    def get_directory_contents(self, directory: Path) -> List[str]:
        """Get contents of JSON files in a directory for debugging."""
        if not directory.exists():
            return []

        contents = []
        for json_file in directory.glob("*.json"):
            try:
                with open(json_file, "r") as f:
                    data = json.load(f)
                    contents.append(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                with open(json_file, "r") as f:
                    contents.append(f"Invalid JSON: {f.read()}")

        return contents

    def validate_output_counts(self, output_dir: Path, config_name: str):
        """Validate output counts for a specific configuration."""
        expected_counts = self.EXPECTED_COUNTS[config_name]

        print(f"\nValidating output counts for {config_name}:")
        print("=" * 50)

        validation_results = []

        # Define the directory mappings
        dir_mappings = [
            ("parse-failures", "parse_failures"),
            ("bad-logs", "bad_logs"),
            ("invalid-methods", "invalid_methods"),
            ("template-errors", "template_errors"),
            ("empty-user-agents", "empty_user_agents"),
            ("duplicate-sources", "duplicate_sources"),
            ("processed-logs", "processed_logs"),
            ("corrupt-logs", "corrupt_logs"),
        ]

        for dir_name, count_key in dir_mappings:
            directory = output_dir / dir_name
            expected = expected_counts[count_key]
            actual = self.count_files_in_directory(directory)

            print(f"{count_key}: {actual} files (expected {expected})")

            if actual == expected:
                print("  ✅ PASS")
                validation_results.append(True)
            else:
                print("  ❌ FAIL")
                validation_results.append(False)

        print("=" * 50)

        # Show detailed results for debugging if any failed
        if not all(validation_results):
            self._show_detailed_results(output_dir)

        # Final assertion
        all_passed = all(validation_results)
        if all_passed:
            print(f"🎉 ALL VALIDATIONS PASSED for {config_name}!")
        else:
            print(f"💥 SOME VALIDATIONS FAILED for {config_name}!")

        self.assertTrue(all_passed, f"Output validation failed for {config_name}")

    def _show_detailed_results(self, output_dir: Path):
        """Show detailed results for debugging."""
        print("\nDetailed Results:")

        categories = [
            ("parse-failures", "Parse Failures"),
            ("bad-logs", "Bad Logs"),
            ("invalid-methods", "Invalid HTTP Methods"),
            ("template-errors", "Template Errors"),
            ("empty-user-agents", "Empty User Agents"),
            ("duplicate-sources", "Duplicate Source Addresses"),
            ("processed-logs", "Processed Logs"),
            ("corrupt-logs", "Corrupt Logs"),
        ]

        for dir_name, description in categories:
            directory = output_dir / dir_name
            print(f"\n{description}:")
            self._show_directory_contents(directory)

    def _show_directory_contents(self, directory: Path):
        """Show contents of a specific directory."""
        if not directory.exists():
            print("No files found")
            return

        contents = self.get_directory_contents(directory)
        if not contents:
            print("Directory exists but no JSON files found")
            return

        print("Found files:")
        for content in contents[:3]:  # Show first 3 files
            print(f"  {content[:200]}...")  # Truncate long content
        if len(contents) > 3:
            print(f"  ... and {len(contents) - 3} more files")

    def load_processed_events(self, output_dir: Path) -> List[Dict]:
        """Load all events written to the processed-logs output directory."""
        events = []
        processed_dir = output_dir / "processed-logs"
        if not processed_dir.exists():
            return events
        for json_file in processed_dir.rglob("*.json"):
            try:
                with open(json_file) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            events.append(json.loads(line))
            except (json.JSONDecodeError, OSError) as e:
                self.fail(f"Failed to parse processed event in {json_file}: {e}")
        return events

    def validate_url_field_parsing(self, output_dir: Path):
        """Verify url.path_parts, url.query_params, and url.query_parts are populated.

        Uses the dedicated test log lines added to test-input-https.conf:
          10.99.1.1 — Apache GET with query string (?target=lucy&version=2)
          10.99.1.2 — Apache GET with no query string (path only)
        """
        events = self.load_processed_events(output_dir)
        by_source: Dict[str, List[Dict]] = {}
        for event in events:
            addr = event.get("source", {}).get("address", "")
            by_source.setdefault(addr, []).append(event)

        # ── Test 1: path + query string ──────────────────────────────────────
        query_events = by_source.get("10.99.1.1", [])
        self.assertEqual(len(query_events), 1, "Expected 1 processed event for 10.99.1.1")
        url = query_events[0].get("url", {})

        self.assertEqual(
            url.get("path"),
            "/pds/data/LUCY/kernels",
            "url.path must not include the query string",
        )
        self.assertEqual(
            sorted(url.get("path_parts", [])),
            sorted(["pds", "data", "LUCY", "kernels"]),
            "url.path_parts must contain each path segment",
        )
        query_params = url.get("query_params", {})
        self.assertEqual(query_params.get("target"), "lucy", "url.query_params.target must be 'lucy'")
        self.assertEqual(query_params.get("version"), "2", "url.query_params.version must be '2'")
        query_parts = url.get("query_parts", [])
        self.assertIn("target=lucy", query_parts, "url.query_parts must contain 'target=lucy'")
        self.assertIn("version=2", query_parts, "url.query_parts must contain 'version=2'")

        # ── Test 1b: "_" cache-buster key must survive sanitizing as a non-empty key ──
        cache_events = by_source.get("91.107.144.23", [])
        self.assertEqual(len(cache_events), 1, "Expected 1 processed event for 91.107.144.23")
        cache_params = cache_events[0].get("url", {}).get("query_params", {})
        self.assertNotIn("", cache_params, "url.query_params must not contain an empty field name")
        self.assertEqual(cache_params.get("_"), "1706077556736", "url.query_params._ must hold the cache-buster")

        # ── Test 2: path only, no query string ───────────────────────────────
        no_query_events = by_source.get("10.99.1.2", [])
        self.assertEqual(len(no_query_events), 1, "Expected 1 processed event for 10.99.1.2")
        url2 = no_query_events[0].get("url", {})

        self.assertIn("LUCY", url2.get("path_parts", []), "url.path_parts must contain 'LUCY'")
        self.assertNotIn("query_params", url2, "url.query_params must not be set when there is no query string")
        self.assertNotIn("query_parts", url2, "url.query_parts must not be set when there is no query string")

    def validate_iis_referer_parsing(self, output_dir: Path):
        """Verify GEO IIS web lines keep their columns: client IP, port, user agent, referrer."""
        events = self.load_processed_events(output_dir)
        by_source = {e.get("source", {}).get("address"): e for e in events}
        plus_ua = "Mozilla/5.0+(Windows+NT+10.0;+Win64;+x64)"
        space_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        )
        expected = {
            "91.199.87.198": (plus_ua, None),
            "54.250.58.217": (plus_ua, None),
            "54.250.58.218": (plus_ua, "https://example.org/search?q=lro"),
            "156.68.99.212": (space_ua, None),
        }
        for address, (user_agent, referrer) in expected.items():
            self.assertIn(address, by_source, f"Expected a processed GEO IIS event for {address}")
            event = by_source[address]
            self.assertEqual(
                event.get("user_agent", {}).get("original"),
                user_agent,
                "user_agent.original must not include the client IP or the referer column",
            )
            self.assertEqual(
                event.get("http", {}).get("request", {}).get("referrer"),
                referrer,
                "http.request.referrer must hold the referer, and be unset when it is '-'",
            )
            self.assertEqual(str(event.get("server", {}).get("port")), "80", "server.port must be the numeric port")
            self.assertEqual(event.get("http", {}).get("response", {}).get("status_code"), 200)
            self.assertEqual(str(event.get("error", {}).get("code")), "0", "the win32 status must reach error.code")
            self.assertNotIn("iis", event, "sub-status and win32 status must use the http.response fields")

    def test_https_log_processing(self):
        """Test processing of HTTPS logs."""
        if "https" not in self.ENABLED_CONFIGS:
            self.skipTest("HTTPS configuration not enabled")

        # Run Logstash pipeline
        success, output_dir = self.run_logstash_pipeline("https", "HTTPS Log Processing")
        self.assertTrue(success, "Logstash pipeline failed for HTTPS logs")

        # Validate output counts
        self.validate_output_counts(output_dir, "https")

        # Validate URL field parsing (path_parts, query_params, query_parts)
        self.validate_url_field_parsing(output_dir)

        # Validate the referer column of GEO IIS lines
        self.validate_iis_referer_parsing(output_dir)

    def test_ftp_log_processing(self):
        """Test processing of FTP logs."""
        if "ftp" not in self.ENABLED_CONFIGS:
            self.skipTest("FTP configuration not enabled")

        # Run Logstash pipeline
        success, output_dir = self.run_logstash_pipeline("ftp", "FTP Log Processing")
        self.assertTrue(success, "Logstash pipeline failed for FTP logs")

        # Validate output counts
        self.validate_output_counts(output_dir, "ftp")

    def test_cloudfront_log_processing(self):
        """Test processing of CloudFront legacy W3C tab-delimited logs."""
        if "cloudfront" not in self.ENABLED_CONFIGS:
            self.skipTest("CloudFront configuration not enabled")

        # Run Logstash pipeline
        success, output_dir = self.run_logstash_pipeline("cloudfront", "CloudFront Legacy W3C Log Processing")
        self.assertTrue(success, "Logstash pipeline failed for CloudFront logs")

        # Validate output counts
        self.validate_output_counts(output_dir, "cloudfront")

    def test_cloudfront_json_log_processing(self):
        """Test processing of CloudFront JSON Standard Logging v2 logs."""
        if "cloudfront-json" not in self.ENABLED_CONFIGS:
            self.skipTest("CloudFront JSON configuration not enabled")

        success, output_dir = self.run_logstash_pipeline(
            "cloudfront-json", "CloudFront JSON Standard Logging v2 Processing"
        )
        self.assertTrue(success, "Logstash pipeline failed for CloudFront JSON logs")

        self.validate_output_counts(output_dir, "cloudfront-json")

    @unittest.skip("Skipping configuration file existence test")
    def test_configuration_files_exist(self):
        """Test that all required configuration files exist."""
        # Check input configs
        for config_name in self.ACTIVE_INPUT_CONFIGS:
            config_path = self.get_input_config_path(config_name)
            with self.subTest(input_config=config_name):
                self.assertTrue(config_path.exists(), f"Input configuration file missing: {config_path}")

        # Check filter configs
        for filter_path in self.get_filter_config_paths():
            with self.subTest(filter_config=str(filter_path)):
                self.assertTrue(filter_path.exists(), f"Filter configuration file missing: {filter_path}")

        # Check output configs
        for output_path in self.get_output_config_paths():
            with self.subTest(output_config=str(output_path)):
                self.assertTrue(output_path.exists(), f"Output configuration file missing: {output_path}")


if __name__ == "__main__":
    # Run the tests
    unittest.main(verbosity=2)
