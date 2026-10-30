"""Unittest helper functions and utilities for testing."""
import os
import shutil
import tempfile
from unittest.mock import patch

import yaml

# Constants for test patterns
LOG_PATTERN = "*.log"
TXT_PATTERN = "*.txt"


def create_test_data_dir():
    """Create a test data directory for testing."""
    temp_dir = tempfile.mkdtemp(prefix="pds_o11y_batch_test_")
    return temp_dir


def cleanup_test_data_dir(temp_dir):
    """Clean up a test data directory."""
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


def create_sample_log_files(test_data_dir):
    """Create sample log files for testing."""
    log_dir = os.path.join(test_data_dir, "sample_logs")
    os.makedirs(log_dir, exist_ok=True)

    # Create sample log files with different formats
    log_files = {
        "apache_access.log": [
            '192.168.1.1 - - [25/Dec/2023:10:30:45 +0000] "GET /data/file.txt HTTP/1.1" 200 1024',
            '192.168.1.2 - - [25/Dec/2023:10:31:45 +0000] "POST /api/data HTTP/1.1" 404 0',
            '192.168.1.3 - - [25/Dec/2023:10:32:45 +0000] "GET /search?q=mars HTTP/1.1" 200 2048',
        ],
        "iis_access.log": [
            "2023-12-25 10:30:45 192.168.1.1 GET /data/file.txt 200 1024",
            "2023-12-25 10:31:45 192.168.1.2 POST /api/data 404 0",
            "2023-12-25 10:32:45 192.168.1.3 GET /search 200 2048",
        ],
        "ftp_transfer.log": [
            '192.168.1.1 [25/Dec/2023:10:30:45] "GET /ftp/data.zip" 200 1024',
            '192.168.1.2 [25/Dec/2023:10:31:45] "PUT /ftp/upload.txt" 226 512',
            '192.168.1.3 [25/Dec/2023:10:32:45] "GET /ftp/image.jpg" 200 4096',
        ],
    }

    for filename, lines in log_files.items():
        filepath = os.path.join(log_dir, filename)
        with open(filepath, "w") as f:
            f.write("\n".join(lines))

    return log_dir


def get_sample_config():
    """Get a sample configuration for testing."""
    return {
        "s3_bucket": "test-pds-logs-bucket",
        "s3_logdir": "logs",
        "subdirs": {
            "atm": {"atm-apache-http": {"include": [LOG_PATTERN]}, "atm-atmos-ftp": {"include": [LOG_PATTERN]}},
            "en": {"en-http": {"include": [TXT_PATTERN]}},
            "geo": {"geo-http": {"include": [LOG_PATTERN, TXT_PATTERN]}},
        },
    }


def create_temp_config_file(sample_config=None):
    """Create a temporary configuration file."""
    if sample_config is None:
        sample_config = get_sample_config()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(sample_config, f)
        temp_file = f.name

    return temp_file


def cleanup_temp_config_file(temp_file):
    """Clean up a temporary configuration file."""
    if temp_file and os.path.exists(temp_file):
        os.unlink(temp_file)


class MockAWSCredentials:
    """Context manager for mocking AWS credentials."""

    def __init__(self):
        self.patcher = patch.dict(
            os.environ,
            {
                "AWS_ACCESS_KEY_ID": "test-access-key",
                "AWS_SECRET_ACCESS_KEY": "test-secret-key",
                "AWS_DEFAULT_REGION": "us-west-2",
            },
        )

    def __enter__(self):
        self.patcher.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.patcher.stop()


class MockSubprocess:
    """Context manager for mocking subprocess."""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.patcher = patch("subprocess.run")

    def __enter__(self):
        self.mock_run = self.patcher.start()

        # Create mock result
        mock_result = type(
            "MockResult", (), {"stdout": self.stdout, "stderr": self.stderr, "returncode": self.returncode}
        )()
        self.mock_run.return_value = mock_result

        return self.mock_run

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.patcher.stop()


class TestDataManager:
    """Helper class for managing test data in unittest classes."""

    def __init__(self):
        self.test_data_dir = None
        self.temp_files = []

    def setup(self):
        """Set up test data directory."""
        self.test_data_dir = create_test_data_dir()
        return self.test_data_dir

    def cleanup(self):
        """Clean up all test data."""
        if self.test_data_dir:
            cleanup_test_data_dir(self.test_data_dir)

        for temp_file in self.temp_files:
            cleanup_temp_config_file(temp_file)

        self.test_data_dir = None
        self.temp_files = []

    def create_log_files(self):
        """Create sample log files."""
        if not self.test_data_dir:
            self.setup()
        return create_sample_log_files(self.test_data_dir)

    def create_config_file(self, config=None):
        """Create a temporary configuration file."""
        temp_file = create_temp_config_file(config)
        self.temp_files.append(temp_file)
        return temp_file


# Convenience functions for use in test classes
def mock_aws_credentials():
    """Mock AWS credentials for testing."""
    return MockAWSCredentials()


def mock_subprocess(stdout="", stderr="", returncode=0):
    """Mock subprocess for testing."""
    return MockSubprocess(stdout, stderr, returncode)
