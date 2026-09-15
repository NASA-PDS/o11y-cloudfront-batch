# Dockerfile for PDS Web Analytics - Logstash Pipeline
# =====================================================
#
# Multi-stage build:
#   base  — Logstash + plugins + PDS config (shared by both targets)
#   prod  — Minimal Logstash image used as a base for local testing
#   test  — Adds Python to run the integration test suite locally
#
# NOTE: The prod target is NOT deployed anywhere. It exists only as
# an intermediate stage for the test target. All production Logstash
# runs are on an EC2 instance managed via systemd (see terraform/README.md).
#
# Test usage (the only supported use case):
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

VOLUME ["/var/lib/logstash"]

USER logstash

# -----------------------------------------------------------------------------
# prod — Minimal Logstash image used as an intermediate stage for testing.
#
# NOT deployed to production. Production runs on EC2 via systemd RPM install.
# See terraform/README.md for the actual deployment process.
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
FROM python:3.13-slim AS test

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
