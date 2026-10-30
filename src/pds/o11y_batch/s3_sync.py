"""S3 synchronization module for PDS web analytics."""
import argparse
import gzip
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from multiprocessing import cpu_count
from typing import Dict
from typing import Optional
from typing import Tuple

import boto3  # type: ignore
import yaml  # type: ignore
from box import Box

# Configure logging
logger = logging.getLogger(__name__)


class S3Sync:
    """A class to sync directories from a local filesystem to an AWS S3 bucket.

    Attributes:
        src_paths (Dict[str, Dict[str, str]]): Source paths to sync, with include patterns.
        src_logdir (str): The base directory for source logs.
        bucket_name (str): The name of the target S3 bucket.
        s3_subdir (str): The target directory within the S3 bucket.
        profile_name (Optional[str]): AWS CLI profile name. Default is None.
        delete (bool): Flag to delete source files after sync. Default is False.
        workers (int): Number of worker processes to use. Default is the number of CPUs.
        s3_client: boto3 S3 client for AWS operations.
        enable_gzip (bool): Flag to enable/disable gzip compression. Default is True.
        force (bool): Flag to force upload even if files already exist in S3. Default is False.
    """

    def __init__(
        self,
        src_paths: Dict[str, Dict[str, str]],
        src_logdir: str,
        bucket_name: str,
        s3_subdir: str,
        profile_name: Optional[str] = None,
        delete: bool = False,
        workers: Optional[int] = None,
        enable_gzip: bool = True,
        force: bool = False,
    ) -> None:
        """Initialize the S3Sync object with configuration for syncing."""
        self.src_paths = src_paths
        self.src_logdir = src_logdir
        self.bucket_name = bucket_name
        self.s3_subdir = s3_subdir
        self.profile_name = profile_name
        self.delete = delete
        self.workers = workers if workers else cpu_count()
        self.enable_gzip = enable_gzip
        self.force = force

        # Initialize boto3 session and S3 client
        try:
            if self.profile_name:
                session = boto3.Session(profile_name=self.profile_name)
                self.s3_client = session.client("s3")
            else:
                self.s3_client = boto3.client("s3")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize AWS S3 client: {str(e)}")

    def is_gzipped(self, file_path: str) -> bool:
        """Check if a file is already gzipped by examining its magic bytes.

        Args:
            file_path (str): Path to the file to check.

        Returns:
            bool: True if the file is gzipped, False otherwise.
        """
        try:
            with open(file_path, "rb") as f:
                magic_bytes = f.read(2)
                return magic_bytes == b"\x1f\x8b"  # gzip magic bytes
        except OSError:
            return False

    def gzip_file_in_place(self, file_path: str) -> str:
        """Gzip a file in place and return the path to the gzipped version.

        Args:
            file_path (str): Path to the original file.

        Returns:
            str: Path to the gzipped file (same as input with .gz added).
        """
        gzipped_path = file_path + ".gz"

        with open(file_path, "rb") as f_in:
            with gzip.open(gzipped_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Remove the original file
        os.remove(file_path)

        return gzipped_path

    def ensure_files_are_gzipped(self, src_path: str) -> None:
        """Ensure all files in a directory are gzipped by compressing them in place.

        Args:
            src_path (str): Path to the source directory.
        """
        if not self.enable_gzip:
            logger.debug(f"Gzip compression disabled, skipping compression for: {src_path}")
            return

        # Process all files in the source directory
        for root, _dirs, files in os.walk(src_path):
            for file in files:
                file_path = os.path.join(root, file)

                # Skip files that are already gzipped
                if self.is_gzipped(file_path):
                    logger.debug(f"File already gzipped: {file_path}")
                    continue

                # Skip files that already have .gz extension
                if file.endswith(".gz"):
                    logger.debug(f"File already has .gz extension: {file_path}")
                    continue

                # Gzip the file in place
                try:
                    gzipped_path = self.gzip_file_in_place(file_path)
                    logger.info(f"Gzipped file in place: {file_path} -> {gzipped_path}")
                except Exception as e:
                    logger.error(f"Error gzipping {file_path}: {str(e)}")

    def upload_file(self, local_path: str, s3_key: str) -> bool:
        """Upload a single file to S3.

        Args:
            local_path (str): Local file path to upload.
            s3_key (str): S3 key (path) for the file.

        Returns:
            bool: True if upload was successful, False otherwise.
        """
        try:
            # Determine content type based on file extension
            content_type = None
            if local_path.endswith(".gz"):
                content_type = "application/gzip"
            elif local_path.endswith(".log") or local_path.endswith(".txt"):
                content_type = "text/plain"

            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type

            self.s3_client.upload_file(local_path, self.bucket_name, s3_key, ExtraArgs=extra_args)
            return True
        except Exception as e:
            logger.error(f"Error uploading {local_path} to s3://{self.bucket_name}/{s3_key}: {str(e)}")
            return False

    def should_upload_file(self, file_path: str, include_patterns: list) -> bool:
        """Check if a file should be uploaded based on include patterns.

        Args:
            file_path (str): Path to the file to check.
            include_patterns (list): List of include patterns.

        Returns:
            bool: True if file should be uploaded, False otherwise.
        """
        file_name = os.path.basename(file_path)

        for pattern in include_patterns:
            # Simple pattern matching - can be enhanced with fnmatch if needed
            if pattern == "*" or pattern == "*.*":
                return True
            if pattern.endswith("*") and file_name.startswith(pattern[:-1]):
                return True
            if pattern.startswith("*") and file_name.endswith(pattern[1:]):
                return True
            if file_name == pattern:
                return True
            if file_name.endswith(pattern):
                return True

        return False

    def file_exists_in_s3(self, s3_key: str) -> bool:
        """Check if a file already exists in S3.

        Args:
            s3_key (str): The S3 key to check.

        Returns:
            bool: True if the file exists in S3, False otherwise.
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except self.s3_client.exceptions.NoSuchKey:
            return False
        except Exception as e:
            logger.debug(f"File {s3_key} not found in S3 ({str(e)})")
            # If we can't check, assume it doesn't exist to be safe
            return False

    def run(self) -> None:
        """Execute the sync process for all configured source paths."""
        for src_path in self.src_paths.items():
            self.sync_directory(src_path)

    def sync_directory(self, path_tuple: Tuple[str, Dict[str, str]]) -> None:
        """Sync a single directory to S3, including progress logging and deletion if specified.

        Args:
            path_tuple (tuple): A tuple containing the source path and include patterns.
        """
        src_path, path_include = path_tuple

        # Ensure all files are gzipped before sync (if enabled)
        if self.enable_gzip:
            logger.info(f"Ensuring files are gzipped in: {src_path}")
            self.ensure_files_are_gzipped(src_path)
        else:
            logger.debug(f"Gzip compression disabled, syncing files as-is: {src_path}")

        s3_base_path = os.path.join(self.s3_subdir, os.path.relpath(src_path, self.src_logdir))

        # Collect all include patterns
        all_patterns = []
        for includes in path_include.values():
            for pattern in includes:
                # Update include patterns based on gzip setting
                if self.enable_gzip and not pattern.endswith(".gz"):
                    pattern += ".gz"
                all_patterns.append(pattern)

        # Upload files
        uploaded_count = 0
        total_files = 0

        for root, _dirs, files in os.walk(src_path):
            for file in files:
                file_path = os.path.join(root, file)

                if self.should_upload_file(file_path, all_patterns):
                    total_files += 1

                    # Calculate S3 key
                    rel_path = os.path.relpath(file_path, src_path)
                    s3_key = os.path.join(s3_base_path, rel_path).replace("\\", "/")

                    # Check if file already exists in S3
                    if self.file_exists_in_s3(s3_key):
                        logger.debug(f"Skipping (already exists): {file_path} -> s3://{self.bucket_name}/{s3_key}")
                        continue

                    logger.info(f"Uploading: {file_path} -> s3://{self.bucket_name}/{s3_key}")

                    if self.upload_file(file_path, s3_key):
                        uploaded_count += 1

                        # Delete source file if requested
                        if self.delete:
                            try:
                                os.remove(file_path)
                                logger.info(f"Deleted source file: {file_path}")
                            except Exception as e:
                                logger.error(f"Error deleting source file {file_path}: {str(e)}")

        if uploaded_count > 0:
            logger.info(
                f"{src_path} sync to {s3_base_path}: {uploaded_count}/{total_files} files uploaded successfully."
            )
        else:
            logger.info(f"{src_path} sync to {s3_base_path}: no files to upload.")

    @staticmethod
    def convert_size(size: int) -> str:
        """Convert a size in bytes to a human-readable string.

        Args:
            size (int): The size in bytes.

        Returns:
            str: The human-readable size.
        """
        if size == 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = int(math.floor(math.log(size, 1024)))
        p = math.pow(1024, i)
        s = round(size / p, 2)
        return f"{s}{size_name[i]}"

    @staticmethod
    def get_bytes(size: int, size_incre: str) -> int:
        """Convert a size with unit to bytes.

        Args:
            size (int): The numerical part of the size.
            size_incre (str): The unit of the size (e.g., "KiB", "MiB").

        Returns:
            int: The size in bytes.
        """
        # Convert size to bytes based on unit
        if size_incre == "KiB":
            size *= 2**10
        elif size_incre == "MiB":
            size *= 2**20
        elif size_incre == "GiB":
            size *= 2**30
        elif size_incre == "TiB":
            size *= 2**40
        return size

    @staticmethod
    def get_throughput(sent: int, start_time: float) -> str:
        """Calculate and return the data transfer throughput.

        Args:
            sent (int): The number of bytes sent.
            start_time (float): The start time of the transfer (must be set with time.monotonic()).

        Returns:
            str: The throughput in MB/s.
        """
        elapsed_time = time.monotonic() - start_time
        mb_sent = sent / (1024 * 1024)
        return f"{mb_sent / elapsed_time:.2f} MB/s"

    def process_progress(self, line: str, src_path: str, start_time: float) -> None:
        """Process and print the progress of the sync operation based on AWS CLI output.

        Args:
            line (str): The output line from AWS CLI.
            src_path (str): The source path being synced.
            start_time (float): The start time of the sync operation (must be set with time.monotonic()).
        """
        # Extract and process progress information from AWS CLI output
        line_components = line.split()
        sent = int(float(line_components[1]))
        sent_incre = line_components[2].split("/")[0]
        total_size = int(float(line_components[2].split("/")[1].replace("~", "")))
        total_size_incre = line_components[3]
        sent = self.get_bytes(sent, sent_incre)
        total_size = self.get_bytes(total_size, total_size_incre)
        progress = sent / total_size
        logger.info(
            f"{src_path} - "
            f"{self.convert_size(sent)} / {self.convert_size(total_size)} - "
            f"{progress:.0%} - "
            f"{self.get_throughput(sent, start_time)}"
        )


def parse_args():
    """Parse command line arguments for the script.

    Returns a Namespace object with parsed arguments if successful;
    otherwise, prints an error message and exits the script with a non-zero status.
    """
    parser = argparse.ArgumentParser(
        description="Sync directories to an AWS S3 bucket with optional gzip compression.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-c", "--config", required=True, help="Path to the configuration file.")
    parser.add_argument(
        "-d", "--log-directory", required=True, help="Base directory containing the log subdirectories to sync."
    )
    parser.add_argument(
        "--aws-profile",
        default=os.environ.get("AWS_PROFILE"),
        help="AWS CLI profile name to use for authentication. Defaults to AWS_PROFILE environment variable if set.",
    )
    parser.add_argument(
        "--no-gzip",
        action="store_true",
        help="Disable gzip compression. Files will be synced as-is without compression.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force upload even if files already exist in S3.",
    )

    args = parser.parse_args()

    # Check if aws-profile is required but not provided
    if not args.aws_profile:
        parser.error("--aws-profile is required when AWS_PROFILE environment variable is not set.")

    return args


def load_config_with_env_vars(config_path: str) -> Box:
    """Load YAML config file with environment variable substitution using envsubst."""
    try:
        # Read the config file and pipe it through envsubst
        with open(config_path, "r") as file:
            config_content = file.read()

        result = subprocess.run(["envsubst"], input=config_content, capture_output=True, text=True, check=True)
        processed_content = result.stdout

    except subprocess.CalledProcessError as e:
        logger.error(f"Error running envsubst: {e}")
        logger.error(f"stderr: {e.stderr}")
        raise
    except FileNotFoundError:
        logger.error("Error: envsubst command not found. Please install gettext package.")
        logger.error("On Ubuntu/Debian: sudo apt-get install gettext")
        logger.error("On CentOS/RHEL: sudo yum install gettext")
        logger.error("On macOS: brew install gettext")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during config processing: {str(e)}")
        raise

    config = yaml.safe_load(processed_content)
    # Handle empty config content
    if config is None:
        config = {}
    return Box(config)


def main():
    """Main entry point for the CLI."""
    # Configure basic logging
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    args = parse_args()

    try:
        config = load_config_with_env_vars(args.config)
    except FileNotFoundError:
        logger.error(f"Error: Configuration file '{args.config}' not found.")
        sys.exit(1)

    local_dirs = {
        args.log_directory + "/" + dir + "/" + subdir: config.subdirs[dir][subdir]
        for dir in config.subdirs.keys()
        for subdir in config.subdirs[dir]
    }

    s3_sync = S3Sync(
        src_paths=local_dirs,
        src_logdir=args.log_directory,
        bucket_name=config.s3_bucket,
        s3_subdir=config.s3_subdir,
        profile_name=args.aws_profile,
        enable_gzip=not args.no_gzip,
        force=args.force,
    )
    s3_sync.run()


if __name__ == "__main__":
    main()
