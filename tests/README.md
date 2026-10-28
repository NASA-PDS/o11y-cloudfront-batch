# PDS Web Analytics Testing

This directory contains tests for the PDS Web Analytics project, including both unit tests and integration tests, all using the unittest framework.

## Test Structure

### Unit Tests (unittest)
- **`test_s3_sync.py`**: Tests for S3 synchronization functionality
- **`conftest.py`**: Helper functions and utilities for testing

### Integration Tests (unittest)
- **`test_logstash_integration.py`**: End-to-end tests for Logstash pipeline processing
  - Replaces the functionality of the old `run_tests.sh` script
  - Tests Logstash configurations with various input formats
  - Validates output file counts and contents
  - Provides better error handling and cross-platform compatibility
  - Uses unittest framework for better standard library integration

### Test Configuration Files
- **`config/test-input-https.conf`**: Test configuration for HTTPS logs
- **`config/test-input-ftp.conf`**: Test configuration for FTP logs
- **`config/test-input-logs.conf`**: Test configuration for all log files in test/data/logs
- **`config/test-output.conf`**: Test output configuration

## Running Tests

### Running Tests Directly

#### Unit Tests
```bash
# Run all unit tests
python -m unittest tests.test_s3_sync

# Run specific test class
python -m unittest tests.test_s3_sync.TestS3Sync

# Run specific test method
python -m unittest tests.test_s3_sync.TestS3Sync.test_init_with_gzip_enabled

# Run with verbose output
python -m unittest tests.test_s3_sync -v
```

#### Integration Tests
```bash
# Run all integration tests
python -m unittest tests.test_logstash_integration

# Run specific test method
python -m unittest tests.test_logstash_integration.TestLogstashIntegration.test_https_log_processing

# Run with verbose output
python -m unittest tests.test_logstash_integration -v
```

#### All Tests
```bash
# Run all tests in the tests directory
python -m unittest discover tests

# Run with verbose output
python -m unittest discover tests -v
```

## Running the integration tests with Docker

The integration test suite runs a real Logstash pipeline against sample log data and validates that events are routed into the correct output buckets. The easiest way to run the tests is with Docker — no local Logstash installation required.

### Run all tests (Docker — recommended)

```bash
# Build the test image and run the full suite
docker compose run --rm test

# Output JSON files are written to ./output/ on the host for inspection
ls output/
```

### Run a single test

```bash
# Replace test_cloudfront_log_processing with the test method you want
docker compose run --rm test python3 -m unittest \
    tests.test_logstash_integration.TestLogstashIntegration.test_cloudfront_log_processing -v
```

### Run locally (requires Logstash installed)

If you have Logstash installed locally you can skip Docker:

```bash
source venv/bin/activate
python -m unittest tests.test_logstash_integration -v
```

### Understanding test output

Each test run writes JSON files into subdirectories of `output/`:

| Directory | Contents |
|-----------|----------|
| `processed-logs/` | Successfully parsed log events (ECS-mapped) |
| `parse-failures/` | Events that failed all grok patterns (`_grok_parse_failure`) |
| `bad-logs/` | Events tagged `bad_log` (e.g., invalid Unicode) |
| `invalid-methods/` | Events with non-standard HTTP methods |
| `empty-user-agents/` | Events where the user agent field is `-` or empty |
| `corrupt-logs/` | Events with other data quality issues |
| `template-errors/` | Events that failed OpenSearch template validation |
| `duplicate-sources/` | Events flagged as duplicate source addresses |

Each test method asserts exact counts in each directory. A mismatch means either the grok pattern changed behavior or the test data needs updating.

## Adding Tests for New Log Formats

When a new log format needs to be supported, follow these steps to wire up an integration test alongside the Logstash config change.

### 1. Add a test input configuration

Create `tests/config/test-input-<format>.conf`. This file replaces the real S3 input with inline data so the test runs without AWS credentials.

```
input {
  generator {
    lines => [
      # Paste representative sample log lines here, one per entry.
      # Include at least: a normal success line, a 4xx/5xx line,
      # and any edge cases your grok pattern needs to handle.
      "2026-01-01 00:00:00 example log line 1",
      "2026-01-01 00:00:01 example log line 2"
    ]
    count => 1
    add_field => {
      "[organization][name]" => "test-node"
      # Add any other fields the shared filter expects from the input plugin
    }
  }
}
```

Key rules for test input configs:
- Use `generator` with `count => 1` so each line is emitted exactly once and Logstash exits cleanly.
- Set only the fields the shared filter (`pds-filter.conf`) reads from the input — `[organization][name]` at minimum. Do **not** set fields that the grok pattern derives from the log line itself (e.g., `[url][domain]`, `[url][scheme]`).
- Use single spaces (not tabs) between fields unless your format is explicitly tab-delimited.

### 2. Add expected counts to the test class

In `tests/test_logstash_integration.py`, add an entry to `ENABLED_CONFIGS` and `EXPECTED_COUNTS`:

```python
ENABLED_CONFIGS = ["https", "ftp", "cloudfront", "<format>"]

EXPECTED_COUNTS = {
    ...
    "<format>": {
        "parse_failures": 0,    # events that hit no grok pattern
        "bad_logs": 0,          # events with invalid Unicode etc.
        "invalid_methods": 0,   # events with non-standard HTTP methods
        "template_errors": 0,   # events rejected by OpenSearch template
        "empty_user_agents": 0, # events where user-agent is "-" or absent
        "duplicate_sources": 0, # events flagged as duplicate IPs
        "processed_logs": N,    # events that parsed cleanly (set this last)
        "corrupt_logs": 0,      # events with other quality issues
    },
}
```

Add the config filename to `INPUT_CONFIGS` and a description to the `descriptions` dict inside `get_enabled_configs()`:

```python
INPUT_CONFIGS = {
    ...
    "<format>": "test-input-<format>.conf",
}

descriptions = {
    ...
    "<format>": "<Format> Log Processing",
}
```

### 3. Add a test method

```python
def test_<format>_log_processing(self):
    """Test processing of <Format> logs."""
    if "<format>" not in self.ENABLED_CONFIGS:
        self.skipTest("<Format> configuration not enabled")
    success, output_dir = self.run_logstash_pipeline("<format>", "<Format> Log Processing")
    self.assertTrue(success, "Logstash pipeline failed for <Format> logs")
    self.validate_output_counts(output_dir, "<format>")
```

### 4. Run the test and tune expected counts

Run with Docker and observe the actual counts printed to stdout:

```bash
docker compose run --rm test python3 -m unittest \
    tests.test_logstash_integration.TestLogstashIntegration.test_<format>_log_processing -v
```

If a count is wrong, inspect the JSON files in `./output/` to understand which events landed where, then either fix the grok pattern in `config/logstash/config/shared/pds-filter.conf` or adjust the expected counts to match intentional behavior.

## Test Framework Choice

### Why unittest?
- **Standard Library**: No additional dependencies required
- **Process Management**: Better handling of subprocess execution
- **Error Handling**: More explicit error handling for external tools
- **Cross-Platform**: Better compatibility across different operating systems
- **Consistency**: All tests use the same framework
- **Simplicity**: Easier to understand and maintain

## Test Data

The `data/logs/` directory contains sample log files for testing:
- Apache HTTP access logs
- FTP transfer logs
- Various PDS node log formats

## Prerequisites

### For All Tests
- Python 3.12 or 3.13
- No additional Python dependencies required

### For Integration Tests
- Logstash (must be in PATH)

## Configuration

Integration tests use configuration files in the `config/` directory:
- Input configurations specify log sources
- Output configurations specify where processed data should be written
- Filter configurations define data processing rules

## Helper Functions

The `conftest.py` module provides helper functions for testing:

```python
from tests.conftest import (
    create_test_data_dir,
    cleanup_test_data_dir,
    create_sample_log_files,
    get_sample_config,
    create_temp_config_file,
    cleanup_temp_config_file,
    MockAWSCredentials,
    MockSubprocess,
    TestDataManager
)

# Example usage in a test class
class TestExample(unittest.TestCase):
    def setUp(self):
        self.test_data_dir = create_test_data_dir()
        self.config_file = create_temp_config_file()

    def tearDown(self):
        cleanup_test_data_dir(self.test_data_dir)
        cleanup_temp_config_file(self.config_file)

    def test_with_mocked_aws(self):
        with MockAWSCredentials():
            # Test code here
            pass

    def test_with_mocked_subprocess(self):
        with MockSubprocess(stdout="success", returncode=0) as mock_run:
            # Test code here
            pass
```

## Troubleshooting

### Common Issues

1. **Logstash not found**: Ensure Logstash is installed and in your PATH
2. **Permission errors**: Check file permissions for test data and output directories
3. **Timeout errors**: Integration tests have a 5-minute timeout; increase if needed
4. **Missing dependencies**: Install required packages with `pip install -e .`

### Debug Mode

Run tests with verbose output to see detailed execution:
```bash
./run_unit_tests.sh -v
```

### Manual Testing

To manually test Logstash configurations:
```bash
# Test HTTPS logs
logstash -f tests/config/test-input-https.conf tests/config/shared/pds-filter.conf tests/config/test-output.conf

# Test FTP logs
logstash -f tests/config/test-input-ftp.conf tests/config/shared/pds-filter.conf tests/config/test-output.conf
```

## Contributing

When adding new tests:
1. Use unittest framework for all tests
2. Inherit from `unittest.TestCase`
3. Use `setUp()` and `tearDown()` methods for test setup/cleanup
4. Use unittest assertion methods (`self.assertEqual()`, `self.assertTrue()`, etc.)
5. Add appropriate test data to `data/logs/` if needed
6. Update this README with any new test procedures
7. Use helper functions from `conftest.py` for common testing tasks
