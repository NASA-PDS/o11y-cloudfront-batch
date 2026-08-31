#!/bin/bash
set -euo pipefail

# Install and start SSM agent first so the instance registers with Systems Manager
# regardless of whether the Logstash bootstrap succeeds. RHEL does not include
# amazon-ssm-agent in its default repos — install directly from the AWS RPM.
# Wrapped in if/then so a failure here doesn't abort the rest of the script.
SSM_RPM="https://s3.${aws_region}.amazonaws.com/amazon-ssm-agent-${aws_region}/latest/linux_amd64/amazon-ssm-agent.rpm"
if dnf install -y "$SSM_RPM" --quiet 2>/dev/null; then
  systemctl enable amazon-ssm-agent
  systemctl start amazon-ssm-agent
else
  echo "WARNING: SSM agent install failed — instance will not be reachable via SSM" >&2
fi

# Minimal root bootstrap just to get the repo onto disk — the real
# bootstrap/deploy logic lives in scripts/ within the repo itself so it can
# be re-run later without going back through userdata.
dnf install -y git --quiet

REPO_DIR="/opt/o11y-cloudfront-batch"
REPO_BRANCH="${repo_branch}"

git clone --branch "$REPO_BRANCH" https://github.com/NASA-PDS/o11y-cloudfront-batch.git "$REPO_DIR"

# Root, one-time: packages, Logstash RPM/plugins, provision the logstash
# account (home dir, shell, linger, nofile limits, systemd --user unit).
env \
  LOGSTASH_VERSION="${logstash_version}" \
  REPO_DIR="$REPO_DIR" \
  bash "$REPO_DIR/scripts/logstash-bootstrap.sh" >> /var/log/logstash-bootstrap.log 2>&1

# Day-2, as the logstash user, no sudo: deploy config and start the service.
LOGSTASH_UID="$(id -u logstash)"
runuser -u logstash -- env \
  XDG_RUNTIME_DIR="/run/user/$${LOGSTASH_UID}" \
  REPO_DIR="$REPO_DIR" \
  REPO_BRANCH="$REPO_BRANCH" \
  AWS_REGION="${aws_region}" \
  S3_BUCKET_NAME="${s3_bucket_name}" \
  OPENSEARCH_ENDPOINT="${opensearch_endpoint}" \
  INDEX_PREFIX="${index_prefix}" \
  S3_CF_BUCKET_NAME="${s3_cf_bucket_name}" \
  bash "$REPO_DIR/scripts/logstash-deploy.sh" >> /var/log/logstash-deploy.log 2>&1
