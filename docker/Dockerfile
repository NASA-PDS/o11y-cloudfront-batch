# Dockerfile for PDS Web Analytics - Logstash Pipeline
# =====================================================
#
# Multi-stage build:
#   base  — Logstash + plugins + PDS config (shared by prod and test)
#   prod  — Production image for ECS Fargate deployment
#   test  — Adds Python to run the integration test suite locally
#
# Production usage (ECS injects env vars via task definition):
#   docker build --target prod -t pds-web-analytics .
#   docker run --env-file .env pds-web-analytics
#
# Test usage:
#   docker compose run test
#

# -----------------------------------------------------------------------------
# base — Logstash + required plugins + PDS configuration
# -----------------------------------------------------------------------------
FROM docker.elastic.co/logstash/logstash:8.17.0 AS base

USER root

# gettext-base provides envsubst, used by logstash_build_config.sh at runtime
RUN apt-get update --quiet && \
    apt-get install --quiet --yes gettext-base && \
    rm -rf /var/lib/apt/lists/*

# Install required Logstash plugins
# logstash-filter-tld:         parses TLD/domain components from URLs
# logstash-output-opensearch:  writes events to AWS OpenSearch Service
RUN logstash-plugin install logstash-filter-tld logstash-output-opensearch

# Copy PDS Logstash configuration into the container
COPY config/logstash /usr/share/logstash/pds-config

# The pipelines/ dir is written at runtime by logstash_build_config.sh
RUN mkdir -p /usr/share/logstash/pds-config/config/pipelines && \
    chown -R logstash:root /usr/share/logstash/pds-config

COPY scripts/logstash_build_config.sh /usr/local/bin/logstash_build_config.sh
RUN chmod +x /usr/local/bin/logstash_build_config.sh

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV LS_SETTINGS_DIR=/usr/share/logstash/pds-config/config

# Logstash persistent queue — mount an EFS volume here in ECS
VOLUME ["/var/lib/logstash"]

USER logstash

# -----------------------------------------------------------------------------
# prod — Production image deployed to ECS Fargate
#
# Required env vars (set in ECS task definition, not baked in):
#   S3_BUCKET_NAME   — S3 bucket containing log files
#   OPENSEARCH_URL   — AWS OpenSearch Service endpoint
#   INDEX_PREFIX     — OpenSearch index name prefix
#   AWS_REGION       — AWS region (e.g. us-west-2)
# -----------------------------------------------------------------------------
FROM base AS prod

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# -----------------------------------------------------------------------------
# test — Python 3.13 + Logstash for integration testing.
#
# Starting from python:3.13-slim (Debian Bookworm) avoids having to install
# a newer Python on top of the Ubuntu 20.04 Logstash base image. The full
# Logstash installation — including its bundled JDK — is copied from base.
# The bundled JDK is self-contained and compatible with Bookworm's glibc.
# -----------------------------------------------------------------------------
FROM python:3.14-slim AS test

# envsubst (gettext-base) is required by logstash_build_config.sh
RUN apt-get update --quiet && \
    apt-get install --quiet --yes gettext-base && \
    rm -rf /var/lib/apt/lists/*

# Copy Logstash (with bundled JDK) and PDS build script from the base stage.
# No separate Java installation is needed — /usr/share/logstash/jdk is used.
COPY --from=base /usr/share/logstash /usr/share/logstash
COPY --from=base /usr/local/bin/logstash_build_config.sh /usr/local/bin/logstash_build_config.sh

ENV PATH="/usr/share/logstash/bin:$PATH"
ENV LS_SETTINGS_DIR=/usr/share/logstash/pds-config/config

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -e '.[dev]'

RUN mkdir -p /app/output

ENV OUTPUT_DIR=/app/output

CMD ["python", "-m", "unittest", "tests.test_logstash_integration", "-v"]
