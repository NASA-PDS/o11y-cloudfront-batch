# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

PDS Web Analytics processes web access logs from multiple NASA Planetary Data System (PDS) nodes. It ingests logs from S3, processes them through Logstash pipelines, and stores structured data in OpenSearch. Supported formats: Apache, IIS, FTP, Tomcat, and CloudFront (JSON and W3C). All data is structured as Elastic Common Schema (ECS) v8.

**Key Components:**
- **Logstash Pipelines**: Per-node pipelines that read from S3, parse logs, enrich data, and output to OpenSearch
- **Configuration System**: Template-based configuration using environment variable substitution via envsubst
- **S3 Sync Tool** (deprecated): Python package that uploads local log files to S3 with optional gzip compression (boto3). Nodes now upload with Data Upload Manager.

Documentation has one home per topic (see the README documentation map). Do not duplicate runbook content in this file.

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
# Run all Python unit tests
pytest

# Run specific test file
pytest tests/test_s3_sync.py -v

# Run with coverage
pytest --cov=pds -v

# Run the Logstash pipeline integration tests (needs Docker)
docker compose run --rm test

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

### S3 Sync Module (`src/pds/o11y_batch/s3_sync.py`)

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
   - `inputs/`: S3 input configurations (per-node, defines bucket prefixes, organization name, domain, dataset)
   - `shared/pds-filter.conf`: Main processing pipeline (grok parsing, field mapping, enrichment)
   - `shared/pds-output-opensearch.conf`: OpenSearch output and bad-log routing
   - `pipelines.yml.template`: Pipeline definitions (EN overrides workers and batch size)

3. **Per-Node Pipelines**: Each PDS node (ATM, EN, GEO, IMG, NAIF, PPI, RINGS, SBN) gets its own Logstash pipeline that runs independently

4. **Data Flow**: S3 buckets (node logs; CloudFront logs for EN) → Logstash S3 input → Grok parsing → ECS field mapping → GeoIP/DNS enrichment → OpenSearch

### Configuration System

**Environment Variables** (defined in `.env` file locally, `/etc/logstash/env` on the EC2):
- `S3_BUCKET_NAME`: node logs bucket
- `S3_CF_BUCKET_NAME`: CloudFront logs bucket (EN only)
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
- Namespace: `pds.o11y_batch`
- Source location: `src/pds/o11y_batch/`
- Version: Read from `src/pds/o11y_batch/VERSION.txt`

## Important Implementation Details

### Log Formats, ECS Mapping, Bad Logs

Formats, key ECS fields, and the node table are in the [README](README.md#data-processing). Bad-log routing is in the [Operations Runbook](docs/operations.md#bad-logs): only the tags listed in `shared/pds-output-opensearch.conf` (including `_grok_filter_initial_parse_failure`) are diverted to `/tmp/bad_logs_YYYY-MM.txt`; everything else is indexed. Keep that list in step with the tags `pds-filter.conf` sets.

The OpenSearch index template (`config/opensearch/ecs-8.17-custom-template.json`) is applied by `logstash-deploy.sh`; see `config/opensearch/README.md`.

### Testing Strategy

- **Unit tests**: `tests/test_s3_sync.py`, `tests/test_egress_report.py`, `tests/test_logstash_build_config.py`
- **Integration tests** (`tests/test_logstash_integration.py`): the shared filter against sample input; see `tests/README.md`
- **Test data**: inline `generator` inputs in `tests/config/test-input-*.conf`; CloudFront samples in `tests/data/`
- **Pytest markers**: `unit`, `integration`, `slow`, `s3`, `cli`, `gzip`, `regression`

## Common Workflows

Each task has one home; link to it instead of copying it here.

| Task | Where |
|---|---|
| Connect to the EC2, first-boot setup, verify | `terraform/logstash/README.md` |
| Deploy, subset of nodes (`ENABLED_NODES`), re-ingest, monitoring, troubleshooting, deployed file locations | `docs/operations.md` |
| Add a PDS node | `README.md` ("Adding a PDS node") |
| Add a log format test | `tests/README.md` |
| Deployment order, permission tiers, SSM contract | o11y-platform `terraform/README.md` |

### Modifying Log Processing

- **Parsing**: `config/logstash/config/shared/pds-filter.conf`
- **Output**: `config/logstash/config/shared/pds-output-opensearch.conf`
- **Per-node inputs**: `config/logstash/config/inputs/`
- After changes, rebuild and test: `./scripts/logstash_build_config.sh`, then `docker compose run --rm test`

## Dependencies

### Python Dependencies (setup.cfg)
- **boto3**: AWS S3 operations
- **python-box**: Dict-like config objects
- **pyyaml**: YAML config parsing

### External Dependencies
- **Logstash 8.x**: Log processing engine (bundled JDK; no separate Java install)
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

- The `scripts/s3_log_sync.py` is a legacy script; the actual implementation is in `src/pds/o11y_batch/s3_sync.py`
- Always run `./scripts/logstash_build_config.sh` after modifying Logstash configs to regenerate pipeline files
- The system uses `envsubst` for variable substitution in both Python config loading and Logstash config generation
- AWS profile is required for S3 operations - fails with helpful error if not provided
- Gzip is enabled by default; use `--no-gzip` to disable
