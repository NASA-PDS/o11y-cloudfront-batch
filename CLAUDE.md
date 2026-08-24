# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

PDS Web Analytics is a system that processes web access logs from multiple NASA Planetary Data System (PDS) nodes. It ingests logs from S3, processes them through Logstash pipelines, and stores structured data in OpenSearch for analysis. The system supports multiple log formats (Apache, IIS, FTP, Tomcat) and structures all data according to Elastic Common Schema (ECS) v8.

**Key Components:**
- **S3 Sync Tool**: Python package that uploads local log files to S3 with optional gzip compression (uses boto3)
- **Logstash Pipelines**: Per-node pipelines that read from S3, parse logs, enrich data, and output to OpenSearch
- **Configuration System**: Template-based configuration using environment variable substitution via envsubst

## Pre-Push Requirements

**Before pushing any changes**, one of the following must be true:

1. **Pre-commit hooks are installed** (preferred): Run the full setup below so hooks run automatically on every commit/push.
2. **OR run tox manually** before pushing: `tox` (runs linting + tests across Python versions).

Skipping both will likely cause CI failures.

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode with dev dependencies
pip install -e '.[dev]'

# Set up pre-commit hooks (required — or run tox manually before pushing)
pre-commit install
pre-commit install -t pre-push
pre-commit install -t prepare-commit-msg
pre-commit install -t commit-msg
```

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_s3_sync.py -v

# Run with coverage
pytest --cov=pds -v

# Run integration tests
python -m unittest tests.test_logstash_integration

# Run tests using tox (multiple Python versions)
tox

# Run linting
tox -e lint
```

### Linting and Code Quality
```bash
# Run pre-commit checks manually
pre-commit run --all-files

# Run black formatter
black src/ tests/

# Run flake8 linter
flake8 src/ tests/

# Run mypy type checker
mypy src/
```

### Building Documentation
```bash
# Build Sphinx documentation
tox -e docs
# Output will be in docs/build/html/

# Or manually:
sphinx-build -b html docs/source docs/build/html
```

## Architecture

### S3 Sync Module (`src/pds/web_analytics/s3_sync.py`)

The `S3Sync` class handles uploading log files from local directories to S3:

- **Key functionality**: Walks local directories, optionally gzips files in-place, uploads to S3 using boto3, and can delete source files after upload
- **Authentication**: Uses boto3 sessions with AWS profiles (via `--aws-profile` or `AWS_PROFILE` env var)
- **Gzip handling**: Checks magic bytes (`\x1f\x8b`) to detect already-gzipped files before compression
- **Skip logic**: Uses `head_object` to check if files already exist in S3 to avoid re-uploading
- **Entry point**: The `s3-log-sync` CLI command is defined in setup.cfg under `console_scripts`

### Logstash Pipeline Architecture

The Logstash configuration uses a **modular template system**:

1. **Build Script** (`scripts/logstash_build_config.sh`): Combines configuration files at build time
   - Reads input configs from `config/logstash/config/inputs/pds-input-s3-*.conf` (one per PDS node)
   - Concatenates each input with shared filter + output configs
   - Generates final pipeline configs in `config/logstash/config/pipelines/`
   - Uses envsubst to substitute environment variables in `pipelines.yml.template`

2. **Configuration Structure**:
   - `inputs/`: S3 input configurations (per-node, defines bucket prefix, organization name, domain)
   - `shared/pds-filter.conf`: Main processing pipeline (grok parsing, field mapping, enrichment)
   - `shared/pds-output-opensearch.conf`: OpenSearch output configuration
   - `pipelines.yml.template`: Pipeline definitions with environment variables

3. **Per-Node Pipelines**: Each PDS node (ATM, EN, GEO, IMG, NAIF, PPI, RINGS, SBN) gets its own Logstash pipeline that runs independently

4. **Data Flow**: S3 bucket → Logstash S3 input → Grok parsing → ECS field mapping → GeoIP/DNS enrichment → OpenSearch

### Configuration System

**Environment Variables** (defined in `.env` file):
- `S3_BUCKET_NAME`: S3 bucket for log storage
- `OPENSEARCH_URL`: OpenSearch endpoint URL
- `INDEX_PREFIX`: Prefix for OpenSearch indices
- `LS_SETTINGS_DIR`: Path to Logstash config directory
- `AWS_REGION`, `AWS_PROFILE`: AWS configuration

**Build Process**:
1. Source `.env` file
2. Run `scripts/logstash_build_config.sh` to generate pipeline configs with variable substitution
3. Start Logstash with generated `pipelines.yml`

### Package Structure

This is a Python namespace package under the `pds` namespace:
- Package name: `pds-o11y-cloudfront-batch`
- Namespace: `pds.web_analytics`
- Source location: `src/pds/web_analytics/`
- Version: Read from `src/pds/web_analytics/VERSION.txt`

## Important Implementation Details

### Log Format Support

The Logstash filter configuration handles multiple formats via conditional grok patterns:
- Apache Combined format (most common)
- Microsoft IIS logs
- FTP transfer logs (xferlog format)
- Tomcat access logs

**Error Handling**: Bad logs are tagged (e.g., `_grok_parse_failure`, `bad_log`) and written to `/tmp/bad_logs_YYYY-MM.txt` via a separate file output.

### ECS Field Mapping

All log data is mapped to ECS v8 schema fields. Key mappings:
- `[source][address]` ← client IP
- `[url][path]` ← request path
- `[url][path_parts]` ← array of path segments split on `/` (e.g. `["pds", "data", "LUCY", "kernels"]`) — filter by mission/instrument anywhere in the path
- `[url][query_params]` ← key-value object parsed from the query string (e.g. `{"target": "lucy"}`) — filter on a specific param with `url.query_params.target: "lucy"`
- `[url][query_parts]` ← array of `"key=value"` strings (e.g. `["target=lucy", "version=2"]`) — wildcard search across all params with `url.query_parts: "*lucy*"`
- `[http][request][method]` ← HTTP method
- `[http][response][status_code]` ← status code
- `[organization][name]` ← PDS node identifier (set in input config)
- `[event][dataset]` ← data source identifier (e.g., "en.http", "naif.ftp")

The OpenSearch index template (`config/opensearch/ecs-8.17-custom-template.json`) must be installed before processing logs.

### Testing Strategy

- **Unit tests** (`tests/test_s3_sync.py`): Test S3Sync class methods (gzip detection, pattern matching, boto3 interactions)
- **Integration tests** (`tests/test_logstash_integration.py`): Test full Logstash pipeline with sample logs
- **Test data**: Sample logs in `tests/data/logs/` for each supported format
- **Pytest markers**: `unit`, `integration`, `slow`, `s3`, `cli`, `gzip`, `regression`

## Common Workflows

### Adding a New PDS Node

1. Create new input config in `config/logstash/config/inputs/pds-input-s3-<node>.conf`:
   - Set S3 bucket prefix
   - Define `[organization][name]`, `[url][domain]`, `[event][dataset]` fields
2. Add pipeline entry to `config/logstash/config/pipelines.yml.template`
3. Update S3 sync config (`config/config.yaml`) to include new log directories
4. Add test cases with sample logs from the new node
5. Rebuild configs: `./scripts/logstash_build_config.sh`

### Modifying Log Processing

- **Parsing changes**: Edit `config/logstash/config/shared/pds-filter.conf`
- **Output changes**: Edit `config/logstash/config/shared/pds-output-opensearch.conf`
- **Node-specific inputs**: Edit individual files in `config/logstash/config/inputs/`
- After changes, rebuild and test: `./scripts/logstash_build_config.sh && logstash -t -f config/logstash/config/pipelines.yml`

### Debugging Failed Log Parsing

1. Check bad logs file: `tail -f /tmp/bad_logs_$(date +%Y-%m).txt`
2. Look for grok parse failures and tagged errors
3. Test grok patterns using Logstash's `-t` flag for config validation
4. Add test cases in `tests/` to prevent regressions

### Connecting to the Logstash EC2 (SSM)

Access is via AWS Systems Manager Session Manager only — no SSH keys, no
inbound security group rules:

```bash
aws ssm start-session --target <instance-id>
```

**This lands as `root`.** Logstash runs as a `systemd --user` service under
a shared `logstash` account, and day-2 operations (service control, logs,
config redeploys via `scripts/logstash-deploy.sh`) are meant to run as that
account with no sudo — but the session does not land there automatically.
Switch in place immediately after connecting:

```bash
sudo runuser -l logstash    # or: su - logstash
cd /opt/o11y-cloudfront-batch
```

A custom SSM Run-As document (`aws_ssm_document.logstash_runas` in
`terraform/logstash/main.tf`) can make `--document-name <doc>` land
directly as `logstash`, but it requires an IAM grant
(`ssm:StartSession` on the document ARN) that may not be provisioned —
don't assume it works without confirming; the `runuser` switch above is
the reliable fallback regardless of IAM state.

Once you're `logstash`: `systemctl --user status logstash`,
`tail -f /var/log/logstash/logstash-plain.log` for logs (`journalctl`
needs adm/wheel group membership `logstash` doesn't have), `bash
scripts/logstash-deploy.sh` to redeploy config. Full runbooks:
`terraform/logstash/README.md` and the root `README.md` Quick Reference.

## Dependencies

### Python Dependencies (setup.cfg)
- **boto3**: AWS S3 operations
- **python-box**: Dict-like config objects
- **pyyaml**: YAML config parsing

### External Dependencies
- **Logstash 8.x**: Log processing engine (requires Java 11+)
- **Logstash plugins**: `logstash-filter-tld`, `logstash-output-opensearch`
- **envsubst**: Environment variable substitution (from gettext package)
- **AWS credentials**: For S3 and OpenSearch access

## Code Style and Standards

- **Formatting**: Black with 120 char line length
- **Linting**: Flake8 with PEP8, docstring checks
- **Type hints**: Required (checked with mypy)
- **Docstrings**: Google style
- **Testing**: All new code must have tests
- **Pre-commit hooks**: Enforce formatting, linting, secrets detection before commits

## Notes for Development

- The `scripts/s3_log_sync.py` is a legacy script; the actual implementation is in `src/pds/web_analytics/s3_sync.py`
- Always run `./scripts/logstash_build_config.sh` after modifying Logstash configs to regenerate pipeline files
- The system uses `envsubst` for variable substitution in both Python config loading and Logstash config generation
- AWS profile is required for S3 operations - fails with helpful error if not provided
- Gzip is enabled by default; use `--no-gzip` to disable
