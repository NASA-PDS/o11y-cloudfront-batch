# Tests

| File | Covers |
|---|---|
| `test_logstash_integration.py` | Runs `shared/pds-filter.conf` against sample input and checks event counts per output directory |
| `test_logstash_build_config.py` | `scripts/logstash_build_config.sh`, including `ENABLED_NODES` |
| `test_s3_sync.py` | The deprecated `s3-log-sync` tool |
| `test_egress_report.py` | `egress_report.py` |
| `conftest.py` | Shared helpers |

Run the Python unit tests with `pytest`, or all supported Python versions and lint with `tox`. The integration tests need Logstash, so run them in Docker.

## Running the integration tests with Docker

```bash
docker compose run --rm test
```

Output files are written to `./output/` for inspection. To run one test:

```bash
docker compose run --rm test python3 -m unittest \
    tests.test_logstash_integration.TestLogstashIntegration.test_cloudfront_log_processing -v
```

Without Docker, run `python -m unittest tests.test_logstash_integration -v` with `logstash` on the `PATH`. Each pipeline run has a 5-minute timeout.

### Reading the output

Each test writes one JSON file per event into an `output/` subdirectory. `tests/config/test-output.conf` routes by tag; the first match wins, top to bottom:

| Directory | Tag |
|---|---|
| `corrupt-logs/` | `_datetimeparsefailure` |
| `parse-failures/` | `_grokparsefailure` or `_grok_filter_initial_parse_failure` |
| `bad-logs/` | `_missing_url_original` |
| `invalid-methods/` | `_invalid_http_method` |
| `template-errors/` | `_template_variable` |
| `empty-user-agents/` | `_empty_user_agent` |
| `duplicate-sources/` | `_duplicate_source_address` |
| `processed-logs/` | none of the above |

Each test asserts the exact file count per directory. A mismatch means the filter's behavior changed or the expected counts need updating. The test routing differs from production, which diverts a different tag set to the bad-logs file (see the [Operations Runbook](../docs/operations.md#bad-logs)).

## Adding tests for a new log format

1. **Input config.** Create `tests/config/test-input-<format>.conf`: a `generator` input with `count => 1` and representative `lines` (a success, a 4xx/5xx, and any edge cases). Set only the fields the filter reads from the real input, at minimum `[organization][name]`. Do not set fields the grok pattern derives, such as `[url][domain]`.
2. **Test class.** In `tests/test_logstash_integration.py`:
   - add the format to `ENABLED_CONFIGS`, `INPUT_CONFIGS`, and the `descriptions` dict in `get_enabled_configs()`
   - add an entry to `EXPECTED_COUNTS` with a count for each directory in the table above, setting `processed_logs` last
   - add a test method:

   ```python
   def test_<format>_log_processing(self):
       if "<format>" not in self.ENABLED_CONFIGS:
           self.skipTest("<format> configuration not enabled")
       success, output_dir = self.run_logstash_pipeline("<format>", "<Format> Log Processing")
       self.assertTrue(success, "Logstash pipeline failed for <Format> logs")
       self.validate_output_counts(output_dir, "<format>")
   ```
3. **Tune.** Run the single test (command above), inspect `output/`, then fix `shared/pds-filter.conf` or set the counts that match intended behavior.
