"""Unit tests for the S3Sync class."""
import gzip
import io
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

from box import Box
from pds.o11y_batch.s3_sync import S3Sync


class TestS3Sync(unittest.TestCase):
    """Test cases for the S3Sync class."""

    def setUp(self):
        """Set up test environment before each test."""
        # Create a temporary directory for testing
        self.temp_dir = tempfile.mkdtemp()

        # Sample configuration for testing
        self.sample_config = {
            "/test/logs/atm/atm-apache-http": {"include": ["*.log"]},
            "/test/logs/en/en-http": {"include": ["*.txt"]},
        }

    def tearDown(self):
        """Clean up after each test."""
        # Clean up temporary directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("boto3.Session")
    @patch("boto3.client")
    def test_init_with_profile(self, mock_client, mock_session):
        """Test S3Sync initialization with AWS profile."""
        mock_session_instance = MagicMock()
        mock_session.return_value = mock_session_instance
        mock_s3_client = MagicMock()
        mock_session_instance.client.return_value = mock_s3_client

        s3_sync = S3Sync(
            src_paths=self.sample_config,
            src_logdir="/test/logs",
            bucket_name="test-bucket",
            s3_subdir="logs",
            profile_name="test-profile",
            enable_gzip=True,
        )

        self.assertTrue(s3_sync.enable_gzip)
        self.assertEqual(s3_sync.bucket_name, "test-bucket")
        self.assertEqual(s3_sync.profile_name, "test-profile")
        mock_session.assert_called_once_with(profile_name="test-profile")
        mock_session_instance.client.assert_called_once_with("s3")

    @patch("boto3.client")
    def test_init_without_profile(self, mock_client):
        """Test S3Sync initialization without AWS profile."""
        mock_s3_client = MagicMock()
        mock_client.return_value = mock_s3_client

        s3_sync = S3Sync(
            src_paths=self.sample_config,
            src_logdir="/test/logs",
            bucket_name="test-bucket",
            s3_subdir="logs",
            enable_gzip=False,
        )

        self.assertFalse(s3_sync.enable_gzip)
        self.assertIsNone(s3_sync.profile_name)
        mock_client.assert_called_once_with("s3")

    @patch("boto3.client")
    def test_init_with_gzip_disabled(self, mock_client):
        """Test S3Sync initialization with gzip disabled."""
        mock_s3_client = MagicMock()
        mock_client.return_value = mock_s3_client

        s3_sync = S3Sync(
            src_paths=self.sample_config,
            src_logdir="/test/logs",
            bucket_name="test-bucket",
            s3_subdir="logs",
            enable_gzip=False,
        )

        self.assertFalse(s3_sync.enable_gzip)

    @patch("boto3.client")
    def test_init_failure(self, mock_client):
        """Test S3Sync initialization failure."""
        mock_client.side_effect = Exception("AWS credentials not found")

        with self.assertRaises(RuntimeError) as context:
            S3Sync(
                src_paths=self.sample_config,
                src_logdir="/test/logs",
                bucket_name="test-bucket",
                s3_subdir="logs",
            )

        self.assertIn("Failed to initialize AWS S3 client", str(context.exception))

    def test_is_gzipped_with_gzipped_file(self):
        """Test is_gzipped method with a gzipped file."""
        # Create a gzipped file
        gzipped_file = os.path.join(self.temp_dir, "test.gz")
        with gzip.open(gzipped_file, "wb") as f:
            f.write(b"test content")

        with patch("boto3.client"):
            s3_sync = S3Sync({}, "/test", "bucket", "logs")
            self.assertTrue(s3_sync.is_gzipped(gzipped_file))

    def test_is_gzipped_with_plain_file(self):
        """Test is_gzipped method with a plain text file."""
        # Create a plain text file
        plain_file = os.path.join(self.temp_dir, "test.txt")
        with open(plain_file, "w") as f:
            f.write("test content")

        with patch("boto3.client"):
            s3_sync = S3Sync({}, "/test", "bucket", "logs")
            self.assertFalse(s3_sync.is_gzipped(plain_file))

    def test_is_gzipped_with_nonexistent_file(self):
        """Test is_gzipped method with a nonexistent file."""
        with patch("boto3.client"):
            s3_sync = S3Sync({}, "/test", "bucket", "logs")
            self.assertFalse(s3_sync.is_gzipped("/nonexistent/file.txt"))

    def test_gzip_file_in_place(self):
        """Test gzip_file_in_place method."""
        # Create a test file
        test_file = os.path.join(self.temp_dir, "test.txt")
        test_content = "This is test content for gzipping"
        with open(test_file, "w") as f:
            f.write(test_content)

        with patch("boto3.client"):
            s3_sync = S3Sync({}, "/test", "bucket", "logs")
            gzipped_path = s3_sync.gzip_file_in_place(test_file)

            # Check that the original file is removed
            self.assertFalse(os.path.exists(test_file))

            # Check that the gzipped file exists
            self.assertTrue(os.path.exists(gzipped_path))
            self.assertEqual(gzipped_path, test_file + ".gz")

            # Check that the gzipped file contains the original content
            with gzip.open(gzipped_path, "rt") as f:
                content = f.read()
            self.assertEqual(content, test_content)

    def test_ensure_files_are_gzipped_with_mixed_files(self):
        """Test ensure_files_are_gzipped with mixed file types."""
        # Create test directory structure
        test_dir = os.path.join(self.temp_dir, "test_logs")
        os.makedirs(test_dir)

        # Create different types of files
        files = {
            "already_gzipped.gz": b"gzipped content",
            "plain_text.txt": "plain text content",
            "another_log.log": "log content",
            "already_gzipped_content": b"content that looks gzipped",
        }

        for filename, content in files.items():
            filepath = os.path.join(test_dir, filename)
            if isinstance(content, bytes):
                with open(filepath, "wb") as f:
                    f.write(content)
            else:
                with open(filepath, "w") as f:
                    f.write(content)

        # Create a gzipped file with proper magic bytes
        gzipped_file = os.path.join(test_dir, "properly_gzipped.gz")
        with gzip.open(gzipped_file, "wb") as f:
            f.write(b"properly gzipped content")

        with patch("boto3.client"):
            s3_sync = S3Sync({}, "/test", "bucket", "logs", enable_gzip=True)

            with patch("pds.o11y_batch.s3_sync.logger"):
                s3_sync.ensure_files_are_gzipped(test_dir)

            # Check that plain text files were gzipped
            self.assertFalse(os.path.exists(os.path.join(test_dir, "plain_text.txt")))
            self.assertTrue(os.path.exists(os.path.join(test_dir, "plain_text.txt.gz")))

            self.assertFalse(os.path.exists(os.path.join(test_dir, "another_log.log")))
            self.assertTrue(os.path.exists(os.path.join(test_dir, "another_log.log.gz")))

            # Check that already gzipped files were not re-gzipped
            self.assertTrue(os.path.exists(os.path.join(test_dir, "already_gzipped.gz")))
            self.assertTrue(os.path.exists(os.path.join(test_dir, "properly_gzipped.gz")))

    def test_ensure_files_are_gzipped_disabled(self):
        """Test ensure_files_are_gzipped when gzip is disabled."""
        test_dir = os.path.join(self.temp_dir, "test_logs")
        os.makedirs(test_dir)

        # Create a test file
        test_file = os.path.join(test_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test content")

        with patch("boto3.client"):
            s3_sync = S3Sync({}, "/test", "bucket", "logs", enable_gzip=False)

            with patch("pds.o11y_batch.s3_sync.logger") as mock_logger:
                s3_sync.ensure_files_are_gzipped(test_dir)

            # Check that the file was not gzipped
            self.assertTrue(os.path.exists(test_file))
            self.assertFalse(os.path.exists(test_file + ".gz"))

            # Check that the correct debug message was logged
            mock_logger.debug.assert_called_with(f"Gzip compression disabled, skipping compression for: {test_dir}")

    def test_should_upload_file(self):
        """Test should_upload_file method with various patterns."""
        with patch("boto3.client"):
            s3_sync = S3Sync({}, "/test", "bucket", "logs")

            # Test wildcard patterns
            self.assertTrue(s3_sync.should_upload_file("/path/to/file.txt", ["*"]))
            self.assertTrue(s3_sync.should_upload_file("/path/to/file.txt", ["*.txt"]))
            self.assertTrue(s3_sync.should_upload_file("/path/to/file.log", ["*.log"]))
            self.assertTrue(s3_sync.should_upload_file("/path/to/file.txt", ["file*"]))
            self.assertTrue(s3_sync.should_upload_file("/path/to/file.txt", ["*.txt"]))

            # Test exact matches
            self.assertTrue(s3_sync.should_upload_file("/path/to/file.txt", ["file.txt"]))
            self.assertFalse(s3_sync.should_upload_file("/path/to/file.txt", ["other.txt"]))

            # Test multiple patterns
            patterns = ["*.log", "*.txt"]
            self.assertTrue(s3_sync.should_upload_file("/path/to/file.txt", patterns))
            self.assertTrue(s3_sync.should_upload_file("/path/to/file.log", patterns))

    def test_upload_file_success(self):
        """Test upload_file method with successful upload."""
        with patch("boto3.client") as mock_client:
            mock_s3_client = MagicMock()
            mock_client.return_value = mock_s3_client

            s3_sync = S3Sync({}, "/test", "bucket", "logs")

            # Test upload with .gz file
            result = s3_sync.upload_file("/path/to/file.gz", "logs/file.gz")
            self.assertTrue(result)
            mock_s3_client.upload_file.assert_called_once_with(
                "/path/to/file.gz", "bucket", "logs/file.gz", ExtraArgs={"ContentType": "application/gzip"}
            )

    def test_upload_file_failure(self):
        """Test upload_file method with upload failure."""
        with patch("boto3.client") as mock_client:
            mock_s3_client = MagicMock()
            mock_s3_client.upload_file.side_effect = Exception("Upload failed")
            mock_client.return_value = mock_s3_client

            s3_sync = S3Sync({}, "/test", "bucket", "logs")

            with patch("pds.o11y_batch.s3_sync.logger") as mock_logger:
                result = s3_sync.upload_file("/path/to/file.txt", "logs/file.txt")
                self.assertFalse(result)
                mock_logger.error.assert_called()

    def test_convert_size(self):
        """Test convert_size static method."""
        self.assertEqual(S3Sync.convert_size(0), "0B")
        self.assertEqual(S3Sync.convert_size(1024), "1.0KB")
        self.assertEqual(S3Sync.convert_size(1024 * 1024), "1.0MB")
        self.assertEqual(S3Sync.convert_size(1024 * 1024 * 1024), "1.0GB")

    def test_get_bytes(self):
        """Test get_bytes static method."""
        self.assertEqual(S3Sync.get_bytes(1, "KiB"), 1024)
        self.assertEqual(S3Sync.get_bytes(1, "MiB"), 1024 * 1024)
        self.assertEqual(S3Sync.get_bytes(1, "GiB"), 1024 * 1024 * 1024)

    def test_get_throughput(self):
        """Test get_throughput static method."""
        # Test with known values
        start_time = time.monotonic() - 1.0  # 1 second ago
        throughput = S3Sync.get_throughput(1024 * 1024, start_time)  # 1MB in 1 second
        self.assertIn("1.00 MB/s", throughput)

    @patch("boto3.client")
    def test_file_exists_in_s3_exists(self, mock_client):
        """Test file_exists_in_s3 method when file exists in S3."""
        mock_s3_client = MagicMock()
        mock_client.return_value = mock_s3_client

        # Configure mock to return successfully (file exists)
        mock_s3_client.head_object.return_value = {"ContentLength": 1024}

        s3_sync = S3Sync({}, "/test", "test-bucket", "logs")

        # Test that method returns True when file exists
        result = s3_sync.file_exists_in_s3("test/file.txt")
        self.assertTrue(result)

        # Verify head_object was called with correct parameters
        mock_s3_client.head_object.assert_called_once_with(Bucket="test-bucket", Key="test/file.txt")

    @patch("boto3.client")
    def test_file_exists_in_s3_not_exists(self, mock_client):
        """Test file_exists_in_s3 method when file doesn't exist in S3."""
        mock_s3_client = MagicMock()
        mock_client.return_value = mock_s3_client

        # Configure mock to raise NoSuchKey exception (file doesn't exist)
        mock_s3_client.exceptions.NoSuchKey = Exception
        mock_s3_client.head_object.side_effect = Exception("NoSuchKey")

        s3_sync = S3Sync({}, "/test", "test-bucket", "logs")

        # Test that method returns False when file doesn't exist
        result = s3_sync.file_exists_in_s3("test/file.txt")
        self.assertFalse(result)

        # Verify head_object was called with correct parameters
        mock_s3_client.head_object.assert_called_once_with(Bucket="test-bucket", Key="test/file.txt")

    @patch("boto3.client")
    def test_file_exists_in_s3_other_exception(self, mock_client):
        """Test file_exists_in_s3 method when other exception occurs."""
        mock_s3_client = MagicMock()
        mock_client.return_value = mock_s3_client

        # Define two custom exceptions for this test
        class NoSuchKeyException(Exception):
            pass

        class CustomException(Exception):
            pass

        # Set up the NoSuchKey exception class
        mock_s3_client.exceptions.NoSuchKey = NoSuchKeyException
        # Set up a different exception to be raised
        mock_s3_client.head_object.side_effect = CustomException("ConnectionError")

        s3_sync = S3Sync({}, "/test", "test-bucket", "logs")

        # Test that method returns False when other exception occurs
        with patch("pds.o11y_batch.s3_sync.logger") as mock_logger:
            result = s3_sync.file_exists_in_s3("test/file.txt")
            self.assertFalse(result)

            # Verify debug message was logged
            mock_logger.debug.assert_called_once()
            call_args = mock_logger.debug.call_args[0][0]
            self.assertIn("File test/file.txt not found in S3", call_args)
            self.assertIn("ConnectionError", call_args)

        # Verify head_object was called with correct parameters
        mock_s3_client.head_object.assert_called_once_with(Bucket="test-bucket", Key="test/file.txt")

    @patch("boto3.client")
    def test_sync_directory_success(self, mock_client):
        """Test sync_directory method with successful uploads."""
        mock_s3_client = MagicMock()
        mock_client.return_value = mock_s3_client

        # Configure the mock to raise NoSuchKey exception for head_object calls
        # This simulates files not existing in S3, allowing uploads to proceed
        mock_s3_client.exceptions.NoSuchKey = Exception
        mock_s3_client.head_object.side_effect = Exception("NoSuchKey")

        # Create test directory and files
        test_dir = os.path.join(self.temp_dir, "test_logs")
        os.makedirs(test_dir)

        test_file = os.path.join(test_dir, "test.log")
        with open(test_file, "w") as f:
            f.write("test content")

        path_config = {"include": ["*.log"]}
        path_tuple = (test_dir, path_config)

        s3_sync = S3Sync({}, "/test", "bucket", "logs", enable_gzip=False)

        with patch("pds.o11y_batch.s3_sync.logger"):
            s3_sync.sync_directory(path_tuple)

        # Check that upload was called
        mock_s3_client.upload_file.assert_called_once()

    @patch("boto3.client")
    def test_sync_directory_no_files(self, mock_client):
        """Test sync_directory method with no files to upload."""
        mock_s3_client = MagicMock()
        mock_client.return_value = mock_s3_client

        # Create empty test directory
        test_dir = os.path.join(self.temp_dir, "test_logs")
        os.makedirs(test_dir)

        path_config = {"include": ["*.log"]}
        path_tuple = (test_dir, path_config)

        with patch("boto3.client"):
            s3_sync = S3Sync({}, "/test", "bucket", "logs", enable_gzip=False)

            with patch("pds.o11y_batch.s3_sync.logger"):
                s3_sync.sync_directory(path_tuple)

            # Check that no upload was called
            mock_s3_client.upload_file.assert_not_called()

    @patch("boto3.client")
    def test_sync_directory_with_gzip_disabled(self, mock_client):
        """Test sync_directory method with gzip disabled."""
        mock_s3_client = MagicMock()
        mock_client.return_value = mock_s3_client

        # Create test directory and files
        test_dir = os.path.join(self.temp_dir, "test_logs")
        os.makedirs(test_dir)

        test_file = os.path.join(test_dir, "test.log")
        with open(test_file, "w") as f:
            f.write("test content")

        path_config = {"include": ["*.log"]}
        path_tuple = (test_dir, path_config)

        with patch("boto3.client"):
            s3_sync = S3Sync({}, "/test", "bucket", "logs", enable_gzip=False)

            with patch("pds.o11y_batch.s3_sync.logger"):
                s3_sync.sync_directory(path_tuple)

            # Check that the file was not gzipped
            self.assertTrue(os.path.exists(test_file))
            self.assertFalse(os.path.exists(test_file + ".gz"))

    def test_process_progress(self):
        """Test process_progress method."""
        with patch("boto3.client"):
            s3_sync = S3Sync({}, "/test", "bucket", "logs")

            # Mock time.monotonic to return a fixed value
            with patch("time.monotonic", return_value=100.0):
                with patch("pds.o11y_batch.s3_sync.logger") as mock_logger:
                    # Use the correct format that the method expects
                    s3_sync.process_progress("upload: 1024.0 1024.0/2048.0 MiB 50% 2.5 MiB/s", "/test/path", 99.0)
                    mock_logger.info.assert_called_once()


class TestS3SyncIntegration(unittest.TestCase):
    """Integration tests for S3Sync class."""

    def setUp(self):
        """Set up test environment before each test."""
        # Create a temporary directory with sample log files
        self.temp_dir = tempfile.mkdtemp()

        # Create directory structure
        self.atm_dir = os.path.join(self.temp_dir, "atm", "atm-apache-http")
        self.en_dir = os.path.join(self.temp_dir, "en", "en-http")
        os.makedirs(self.atm_dir)
        os.makedirs(self.en_dir)

        # Create sample log files
        files = {
            os.path.join(
                self.atm_dir, "access.log"
            ): '192.168.1.1 - - [25/Dec/2023:10:30:45 +0000] "GET /data/file.txt HTTP/1.1" 200 1024',
            os.path.join(
                self.atm_dir, "error.log"
            ): '192.168.1.2 - - [25/Dec/2023:10:31:45 +0000] "POST /api/data HTTP/1.1" 404 0',
            os.path.join(
                self.en_dir, "search.log"
            ): '192.168.1.3 - - [25/Dec/2023:10:32:45 +0000] "GET /search?q=mars HTTP/1.1" 200 2048',
        }

        for filepath, content in files.items():
            with open(filepath, "w") as f:
                f.write(content)

        # Create an already gzipped file
        gzipped_file = os.path.join(self.atm_dir, "old.log.gz")
        with gzip.open(gzipped_file, "wb") as f:
            f.write(b"old gzipped content")

    def tearDown(self):
        """Clean up after each test."""
        # Clean up temporary directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("boto3.client")
    def test_full_sync_process(self, mock_client):
        """Test the complete sync process with real files."""
        mock_s3_client = MagicMock()
        mock_client.return_value = mock_s3_client

        # Configure the mock to raise NoSuchKey exception for head_object calls
        # This simulates files not existing in S3, allowing uploads to proceed
        mock_s3_client.exceptions.NoSuchKey = Exception
        mock_s3_client.head_object.side_effect = Exception("NoSuchKey")

        config = {
            os.path.join(self.temp_dir, "atm", "atm-apache-http"): {"include": ["*.log"]},
            os.path.join(self.temp_dir, "en", "en-http"): {"include": ["*.log"]},
        }

        s3_sync = S3Sync(
            src_paths=config, src_logdir=self.temp_dir, bucket_name="test-bucket", s3_subdir="logs", enable_gzip=True
        )

        # Run the sync process
        s3_sync.run()

        # Verify that files were processed
        # Check that plain log files were gzipped
        self.assertFalse(os.path.exists(os.path.join(self.atm_dir, "access.log")))
        self.assertTrue(os.path.exists(os.path.join(self.atm_dir, "access.log.gz")))

        self.assertFalse(os.path.exists(os.path.join(self.atm_dir, "error.log")))
        self.assertTrue(os.path.exists(os.path.join(self.atm_dir, "error.log.gz")))

        self.assertFalse(os.path.exists(os.path.join(self.en_dir, "search.log")))
        self.assertTrue(os.path.exists(os.path.join(self.en_dir, "search.log.gz")))

        # Check that already gzipped file was not re-gzipped
        self.assertTrue(os.path.exists(os.path.join(self.atm_dir, "old.log.gz")))

        # Verify that upload_file was called for the gzipped files
        self.assertGreater(mock_s3_client.upload_file.call_count, 0)

    @patch("boto3.client")
    def test_sync_with_gzip_disabled(self, mock_client):
        """Test sync process with gzip disabled."""
        mock_s3_client = MagicMock()
        mock_client.return_value = mock_s3_client

        # Configure the mock to raise NoSuchKey exception for head_object calls
        # This simulates files not existing in S3, allowing uploads to proceed
        mock_s3_client.exceptions.NoSuchKey = Exception
        mock_s3_client.head_object.side_effect = Exception("NoSuchKey")

        config = {
            os.path.join(self.temp_dir, "atm", "atm-apache-http"): {"include": ["*.log"]},
        }

        s3_sync = S3Sync(
            src_paths=config, src_logdir=self.temp_dir, bucket_name="test-bucket", s3_subdir="logs", enable_gzip=False
        )

        # Run the sync process
        s3_sync.run()

        # Verify that files were not gzipped
        self.assertTrue(os.path.exists(os.path.join(self.atm_dir, "access.log")))
        self.assertFalse(os.path.exists(os.path.join(self.atm_dir, "access.log.gz")))

        self.assertTrue(os.path.exists(os.path.join(self.atm_dir, "error.log")))
        self.assertFalse(os.path.exists(os.path.join(self.atm_dir, "error.log.gz")))

        # Verify that upload_file was called for the original files
        self.assertGreater(mock_s3_client.upload_file.call_count, 0)


class TestLoadConfigWithEnvVars(unittest.TestCase):
    """Test cases for the load_config_with_env_vars function."""

    def setUp(self):
        """Set up test environment before each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, "test_config.yaml")

    def tearDown(self):
        """Clean up after each test."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_config_file(self, content):
        """Helper method to create a config file with given content."""
        with open(self.config_path, "w") as f:
            f.write(content)

    @patch("subprocess.run")
    def test_load_config_with_env_vars_success(self, mock_run):
        """Test successful loading of config with environment variable substitution."""
        # Create a config file with environment variables
        config_content = """
s3_bucket: ${S3_BUCKET_NAME}
s3_logdir: ${S3_LOG_DIR}
subdirs:
  atm:
    atm-apache-http:
      include: ["*.log"]
  en:
    en-http:
      include: ["*.txt"]
"""
        self.create_config_file(config_content)

        # Mock envsubst output
        mock_run.return_value.stdout = """
s3_bucket: my-test-bucket
s3_logdir: logs
subdirs:
  atm:
    atm-apache-http:
      include: ["*.log"]
  en:
    en-http:
      include: ["*.txt"]
"""
        mock_run.return_value.returncode = 0

        # Import the function
        from pds.o11y_batch.s3_sync import load_config_with_env_vars

        # Call the function
        result = load_config_with_env_vars(self.config_path)

        # Verify the result
        self.assertEqual(result.s3_bucket, "my-test-bucket")
        self.assertEqual(result.s3_logdir, "logs")
        self.assertIn("atm", result.subdirs)
        self.assertIn("en", result.subdirs)

        # Verify envsubst was called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        self.assertEqual(call_args[0][0], ["envsubst"])
        self.assertEqual(call_args[1]["input"], config_content)
        self.assertTrue(call_args[1]["capture_output"])
        self.assertTrue(call_args[1]["text"])
        self.assertTrue(call_args[1]["check"])

    @patch("subprocess.run")
    def test_load_config_with_env_vars_envsubst_not_found(self, mock_run):
        """Test handling when envsubst command is not found."""
        config_content = "s3_bucket: ${S3_BUCKET_NAME}"
        self.create_config_file(config_content)

        # Mock FileNotFoundError
        mock_run.side_effect = FileNotFoundError("envsubst: command not found")

        from pds.o11y_batch.s3_sync import load_config_with_env_vars

        with self.assertRaises(FileNotFoundError):
            load_config_with_env_vars(self.config_path)

    @patch("subprocess.run")
    def test_load_config_with_env_vars_envsubst_error(self, mock_run):
        """Test handling when envsubst returns an error."""
        config_content = "s3_bucket: ${S3_BUCKET_NAME}"
        self.create_config_file(config_content)

        # Mock subprocess.CalledProcessError
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=["envsubst"], stderr="Invalid variable reference"
        )

        from pds.o11y_batch.s3_sync import load_config_with_env_vars

        with self.assertRaises(subprocess.CalledProcessError):
            load_config_with_env_vars(self.config_path)

    @patch("subprocess.run")
    def test_load_config_with_env_vars_invalid_yaml(self, mock_run):
        """Test handling when envsubst returns invalid YAML."""
        config_content = "s3_bucket: ${S3_BUCKET_NAME}"
        self.create_config_file(config_content)

        # Mock envsubst returning invalid YAML
        mock_run.return_value.stdout = "invalid: yaml: content: ["
        mock_run.return_value.returncode = 0

        from pds.o11y_batch.s3_sync import load_config_with_env_vars

        with self.assertRaises(Exception):  # yaml.safe_load will raise an exception
            load_config_with_env_vars(self.config_path)

    @patch("subprocess.run")
    def test_load_config_with_env_vars_empty_config(self, mock_run):
        """Test loading an empty config file."""
        self.create_config_file("")

        # Mock envsubst returning empty content
        mock_run.return_value.stdout = ""
        mock_run.return_value.returncode = 0

        from pds.o11y_batch.s3_sync import load_config_with_env_vars

        result = load_config_with_env_vars(self.config_path)
        # Should return an empty Box instead of None
        self.assertEqual(len(result), 0)
        self.assertIsInstance(result, Box)

    @patch("subprocess.run")
    def test_load_config_with_env_vars_complex_substitution(self, mock_run):
        """Test loading config with complex environment variable substitution."""
        config_content = """
s3_bucket: ${S3_BUCKET_NAME}
s3_logdir: ${S3_LOG_DIR:-logs}
subdirs:
  ${ORG_NAME}:
    ${SERVICE_NAME}:
      include: ["*.${FILE_EXTENSION}"]
"""
        self.create_config_file(config_content)

        # Mock envsubst output with substituted values
        mock_run.return_value.stdout = """
s3_bucket: my-production-bucket
s3_logdir: logs
subdirs:
  atm:
    atm-apache-http:
      include: ["*.log"]
"""
        mock_run.return_value.returncode = 0

        from pds.o11y_batch.s3_sync import load_config_with_env_vars

        result = load_config_with_env_vars(self.config_path)

        # Verify the result
        self.assertEqual(result.s3_bucket, "my-production-bucket")
        self.assertEqual(result.s3_logdir, "logs")
        self.assertIn("atm", result.subdirs)
        self.assertIn("atm-apache-http", result.subdirs.atm)

    def test_load_config_with_env_vars_file_not_found(self):
        """Test handling when config file does not exist."""
        from pds.o11y_batch.s3_sync import load_config_with_env_vars

        with self.assertRaises(FileNotFoundError):
            load_config_with_env_vars("/nonexistent/config.yaml")


class TestParseArgs(unittest.TestCase):
    """Test cases for the parse_args function."""

    def setUp(self):
        """Set up test environment before each test."""
        # Save original environment variables
        self.original_aws_profile = os.environ.get("AWS_PROFILE")

    def tearDown(self):
        """Clean up after each test."""
        # Restore original environment variables
        if self.original_aws_profile is not None:
            os.environ["AWS_PROFILE"] = self.original_aws_profile
        elif "AWS_PROFILE" in os.environ:
            del os.environ["AWS_PROFILE"]

    @patch("sys.argv", ["script.py", "-c", "config.yaml", "-d", "/logs"])
    def test_parse_args_with_aws_profile_env_var(self):
        """Test parse_args when AWS_PROFILE environment variable is set."""
        # Set AWS_PROFILE environment variable
        os.environ["AWS_PROFILE"] = "test-profile"

        from pds.o11y_batch.s3_sync import parse_args

        args = parse_args()

        self.assertEqual(args.config, "config.yaml")
        self.assertEqual(args.log_directory, "/logs")
        self.assertEqual(args.aws_profile, "test-profile")
        self.assertFalse(args.no_gzip)

    @patch("sys.argv", ["script.py", "-c", "config.yaml", "-d", "/logs", "--aws-profile", "override-profile"])
    def test_parse_args_with_aws_profile_arg_override(self):
        """Test parse_args when --aws-profile argument overrides environment variable."""
        # Set AWS_PROFILE environment variable
        os.environ["AWS_PROFILE"] = "env-profile"

        from pds.o11y_batch.s3_sync import parse_args

        args = parse_args()

        self.assertEqual(args.config, "config.yaml")
        self.assertEqual(args.log_directory, "/logs")
        self.assertEqual(args.aws_profile, "override-profile")  # Argument should override env var
        self.assertFalse(args.no_gzip)

    @patch("sys.argv", ["script.py", "-c", "config.yaml", "-d", "/logs"])
    def test_parse_args_without_aws_profile(self):
        """Test parse_args when neither AWS_PROFILE env var nor --aws-profile arg is provided."""
        # Ensure AWS_PROFILE is not set
        if "AWS_PROFILE" in os.environ:
            del os.environ["AWS_PROFILE"]

        from pds.o11y_batch.s3_sync import parse_args

        with self.assertRaises(SystemExit):
            parse_args()

    @patch("sys.argv", ["script.py", "-c", "config.yaml", "-d", "/logs", "--no-gzip"])
    def test_parse_args_with_no_gzip(self):
        """Test parse_args with --no-gzip flag."""
        # Set AWS_PROFILE environment variable
        os.environ["AWS_PROFILE"] = "test-profile"

        from pds.o11y_batch.s3_sync import parse_args

        args = parse_args()

        self.assertEqual(args.config, "config.yaml")
        self.assertEqual(args.log_directory, "/logs")
        self.assertEqual(args.aws_profile, "test-profile")
        self.assertTrue(args.no_gzip)


if __name__ == "__main__":
    # Run the tests
    unittest.main(verbosity=2)
