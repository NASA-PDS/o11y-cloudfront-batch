#!/bin/bash
# logstash-deploy.sh — Deploy config and (re)start Logstash on the
# o11y-cloudfront-batch EC2. No sudo required — run entirely as the `logstash` user.
#
# Safe to re-run: pulls latest config, updates the env file, and restarts
# the systemd --user logstash service.
#
# Can be piped directly from GitHub (no prior repo checkout needed):
#   bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-deploy.sh)
#
# Or run from an existing checkout:
#   bash /opt/o11y-cloudfront-batch/scripts/logstash-deploy.sh
#
# Requires scripts/logstash-bootstrap.sh to have been run first (root, once)
# to install Logstash and provision this account — this script will refuse
# to run otherwise.
#
# Optional env overrides (all auto-populated from SSM/metadata if not set):
#   REPO_DIR                 — where to clone/update the repo (default: /opt/o11y-cloudfront-batch)
#                              override to /usr/local/applications/o11y-cloudfront-batch if required
#   REPO_BRANCH              — git branch to deploy (default: main)
#   OPENSEARCH_ENDPOINT      — OpenSearch domain endpoint (without https://)
#   S3_BUCKET_NAME           — S3 bucket for log ingestion
#   AWS_REGION               — AWS region (default: us-west-2)
#   INDEX_PREFIX             — OpenSearch index prefix (default: pds-weblogs)
#   S3_CF_BUCKET_NAME        — CloudFront logs bucket (EN only; default: empty)
#
# Daily egress report cron job — installed only when EGRESS_REPORT_RECIPIENTS
# is set (REQUIRED at deploy time to enable the report; everything else has
# a default):
#   EGRESS_REPORT_RECIPIENTS — comma-separated report recipient addresses.
#                              REQUIRED — the cron job is skipped without it.
#   SMTP_ENV_FILE            — path to a local KEY=VALUE file (username,
#                              password, server, sender) on the EC2 itself.
#                              Default: /etc/logstash/smtp.env. This is the
#                              recommended source — no AWS permissions needed
#                              beyond reading a file already on disk. Create
#                              it once by hand (mode 600, owned by logstash);
#                              see README.md "Enable/update the daily egress
#                              report email".
#   SMTP_CONFIG_SSM_KEY_PATH — SSM path prefix holding SMTP creds instead of
#                              a local file — only used as a fallback if
#                              SMTP_ENV_FILE doesn't exist. Requires
#                              ssm:GetParametersByPath/GetParameter on this
#                              path (not granted by default). Unset by
#                              default; see egress_report.py.
#   EGRESS_REPORT_SCHEDULE   — cron schedule (default: "0 6 * * *")
#   EGRESS_REPORT_HOURS      — trailing window, in hours (default: 24)

set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
  echo "ERROR: logstash-deploy.sh must NOT be run as root — run it as the logstash user." >&2
  exit 1
fi

REPO_URL="https://github.com/NASA-PDS/o11y-cloudfront-batch.git"
REPO_BRANCH="${REPO_BRANCH:-main}"
REPO_DIR="${REPO_DIR:-/opt/o11y-cloudfront-batch}"
LOGSTASH_CONFIG_DIR="/etc/logstash"
INDEX_PREFIX="${INDEX_PREFIX:-pds-weblogs}"

# If S3_CF_BUCKET_NAME isn't explicitly passed, fall back to whatever was set
# on the last successful deploy (persisted in the env file below) instead of
# silently defaulting to empty -- an empty bucket name templates into the EN
# CloudFront pipeline as `bucket => ""`, which fails at Logstash runtime with
# a confusing "not authorized to perform: s3:ListAllMyBuckets" AccessDenied
# error rather than a clear "bucket not set" message. See README.md
# Troubleshooting > Common Issues.
if [ -z "${S3_CF_BUCKET_NAME:-}" ] && [ -f "$LOGSTASH_CONFIG_DIR/env" ]; then
  S3_CF_BUCKET_NAME="$(grep -E '^S3_CF_BUCKET_NAME=' "$LOGSTASH_CONFIG_DIR/env" | tail -1 | cut -d= -f2-)"
fi
S3_CF_BUCKET_NAME="${S3_CF_BUCKET_NAME:-}"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

if [ ! -f /usr/share/logstash/bin/logstash ]; then
  echo "ERROR: Logstash is not installed. An admin must run 'sudo bash scripts/logstash-bootstrap.sh' first." >&2
  exit 1
fi

AWS_REGION="${AWS_REGION:-us-west-2}"
OPENSEARCH_ENDPOINT="${OPENSEARCH_ENDPOINT:-$(aws ssm get-parameter \
  --name /pds/o11y-platform/opensearch/opensearch_endpoint \
  --region "$AWS_REGION" \
  --query Parameter.Value --output text)}"

echo "=== o11y-cloudfront-batch Logstash deploy ==="
echo "Repo:     $REPO_URL ($REPO_BRANCH)"
echo "Endpoint: $OPENSEARCH_ENDPOINT"
if [ -z "$S3_CF_BUCKET_NAME" ]; then
  echo "WARNING: S3_CF_BUCKET_NAME is empty. If this venue runs the EN CloudFront pipeline, it will fail"
  echo "  at runtime with 'not authorized to perform: s3:ListAllMyBuckets' rather than a clear error --"
  echo "  set S3_CF_BUCKET_NAME to the real bucket name to fix. Safe to ignore if EN's CloudFront input"
  echo "  isn't used in this venue."
else
  echo "CF Bucket: $S3_CF_BUCKET_NAME"
fi
echo ""

# ----------------------------------------
# 1. Clone or update the repo
# ----------------------------------------
echo "--- Deploying o11y-cloudfront-batch repo ---"
if [ -d "$REPO_DIR/.git" ]; then
  echo "Repo already exists — pulling latest $REPO_BRANCH"
  git -C "$REPO_DIR" fetch origin
  git -C "$REPO_DIR" checkout "$REPO_BRANCH"
  git -C "$REPO_DIR" pull origin "$REPO_BRANCH"
else
  git clone --branch "$REPO_BRANCH" "$REPO_URL" "$REPO_DIR"
fi

# ----------------------------------------
# 2. Copy Logstash config into place and build pipeline configs
# ----------------------------------------
echo "--- Deploying Logstash pipeline config ---"
cp -r "$REPO_DIR/config/logstash/config/"* "$LOGSTASH_CONFIG_DIR/"
echo "Config deployed to $LOGSTASH_CONFIG_DIR"

echo "--- Building Logstash pipeline configs ---"
LS_SETTINGS_DIR="$LOGSTASH_CONFIG_DIR" \
  bash "$REPO_DIR/scripts/logstash_build_config.sh"
echo "pipelines.yml and pipeline configs generated"

# ----------------------------------------
# 3. Apply OpenSearch index template
# ----------------------------------------
echo "--- Applying OpenSearch ECS index template ---"
eval "$(aws configure export-credentials --format env)"

TEMPLATE_FILE="$REPO_DIR/config/opensearch/ecs-8.17-custom-template.json"
TEMPLATE_RESPONSE_FILE="$(mktemp)"
CURL_EXIT=0
RESPONSE=$(curl -s --connect-timeout 10 --max-time 60 -o "$TEMPLATE_RESPONSE_FILE" -w "%{http_code}" \
  -X PUT "https://${OPENSEARCH_ENDPOINT}/_index_template/pds-o11y-cloudfront-batch" \
  -H 'Content-Type: application/json' \
  -H "x-amz-security-token: ${AWS_SESSION_TOKEN}" \
  --aws-sigv4 "aws:amz:${AWS_REGION}:es" \
  --user "${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}" \
  -d @"$TEMPLATE_FILE") || CURL_EXIT=$?

if [ "$CURL_EXIT" -ne 0 ]; then
  echo "ERROR: curl failed (exit $CURL_EXIT) applying index template — connect/max-time exceeded or a transport error, not an HTTP error."
  rm -f "$TEMPLATE_RESPONSE_FILE"
  exit 1
elif [ "$RESPONSE" = "200" ]; then
  echo "Index template applied successfully"
  rm -f "$TEMPLATE_RESPONSE_FILE"
else
  echo "ERROR: Index template apply failed (HTTP $RESPONSE)"
  cat "$TEMPLATE_RESPONSE_FILE"
  rm -f "$TEMPLATE_RESPONSE_FILE"
  exit 1
fi

# ----------------------------------------
# 4. Write environment file
# ----------------------------------------
echo "--- Configuring Logstash service ---"
ENV_FILE="$LOGSTASH_CONFIG_DIR/env"

S3_BUCKET_NAME="${S3_BUCKET_NAME:-$(aws ssm get-parameter \
  --name /pds/o11y-cloudfront-batch/s3/bucket_name \
  --region "$AWS_REGION" \
  --query Parameter.Value --output text)}"

cat > "$ENV_FILE" <<EOF
AWS_REGION=${AWS_REGION}
S3_BUCKET_NAME=${S3_BUCKET_NAME}
OPENSEARCH_URL=https://${OPENSEARCH_ENDPOINT}:443
INDEX_PREFIX=${INDEX_PREFIX}
S3_CF_BUCKET_NAME=${S3_CF_BUCKET_NAME}
LS_SETTINGS_DIR=${LOGSTASH_CONFIG_DIR}
EOF
echo "Environment file written to $ENV_FILE"

# ----------------------------------------
# 5. Start Logstash (systemd --user — no sudo)
# ----------------------------------------
echo "--- Starting Logstash ---"
systemctl --user daemon-reload
systemctl --user enable --now logstash
systemctl --user restart logstash

# ----------------------------------------
# 6. Install daily egress report cron job (optional)
# ----------------------------------------
SMTP_ENV_FILE="${SMTP_ENV_FILE:-/etc/logstash/smtp.env}"
SMTP_CONFIG_SSM_KEY_PATH="${SMTP_CONFIG_SSM_KEY_PATH:-}"
EGRESS_REPORT_RECIPIENTS="${EGRESS_REPORT_RECIPIENTS:-}"
EGRESS_REPORT_SCHEDULE="${EGRESS_REPORT_SCHEDULE:-0 6 * * *}"
EGRESS_REPORT_HOURS="${EGRESS_REPORT_HOURS:-24}"

echo "--- Configuring daily egress report ---"
if [ -z "$EGRESS_REPORT_RECIPIENTS" ]; then
  echo "EGRESS_REPORT_RECIPIENTS not set — skipping egress report cron job. Set it (comma-separated addresses) to enable."
else
  if [ ! -f "$SMTP_ENV_FILE" ] && [ -z "$SMTP_CONFIG_SSM_KEY_PATH" ]; then
    echo "WARNING: $SMTP_ENV_FILE does not exist and SMTP_CONFIG_SSM_KEY_PATH is not set — the cron"
    echo "job will be installed but will fail until you create $SMTP_ENV_FILE (mode 600, owned by"
    echo "logstash) with username/password/server/sender lines. See README.md 'Enable/update the"
    echo "daily egress report email'."
  fi
  CRON_CMD="PYTHONPATH=\"$REPO_DIR/src\" AWS_REGION=\"$AWS_REGION\" python3.13 \"$REPO_DIR/scripts/egress_report.py\" --opensearch-endpoint \"$OPENSEARCH_ENDPOINT\" --index-pattern \"${INDEX_PREFIX}-*\" --region \"$AWS_REGION\" --smtp-env-file \"$SMTP_ENV_FILE\""
  if [ -n "$SMTP_CONFIG_SSM_KEY_PATH" ]; then
    CRON_CMD="$CRON_CMD --smtp-config-ssm-path \"$SMTP_CONFIG_SSM_KEY_PATH\""
  fi
  CRON_CMD="$CRON_CMD --recipients \"$EGRESS_REPORT_RECIPIENTS\" --hours \"$EGRESS_REPORT_HOURS\" >> /var/log/egress-report.log 2>&1"
  (crontab -l 2>/dev/null | grep -v '# egress-report'; echo "$EGRESS_REPORT_SCHEDULE $CRON_CMD # egress-report") | crontab -
  echo "Egress report cron job installed: $EGRESS_REPORT_SCHEDULE (SMTP source: $SMTP_ENV_FILE)"
fi
systemctl --user status logstash --no-pager

echo ""
echo "=== Deploy complete ==="
echo "Tail logs with: tail -f /var/log/logstash/logstash-plain.log"
