#!/bin/bash
# logstash-bootstrap.sh — SA-only (requires root): install system packages,
# Logstash RPM + plugins, and provision the `logstash` OS account for
# no-sudo day-2 operations.
#
# Run manually once after first boot via SSM, and again only for deliberate
# SA actions such as a Logstash version upgrade. Does NOT require the
# o11y-cloudfront-batch repo to be checked out — download and run directly:
#
#   curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-bootstrap.sh \
#     | sudo bash
#
# Or if the repo is already on disk:
#   sudo bash /opt/o11y-cloudfront-batch/scripts/logstash-bootstrap.sh
#
# After bootstrap completes, an operator (no sudo) runs logstash-deploy.sh
# to clone the repo, deploy config, and start the service.
#
# Env overrides:
#   LOGSTASH_VERSION — Logstash version to install if missing (default: 8.18.0)
#   REPO_DIR         — path to hand off repo ownership if already on disk (default: /opt/o11y-cloudfront-batch)

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: logstash-bootstrap.sh must be run as root (it installs packages and provisions the logstash account)." >&2
  exit 1
fi

LOGSTASH_VERSION="${LOGSTASH_VERSION:-8.18.0}"
REPO_DIR="${REPO_DIR:-/opt/o11y-cloudfront-batch}"

echo "=== o11y-cloudfront-batch Logstash bootstrap ==="

# ----------------------------------------
# 1. Install Logstash if not present
# ----------------------------------------
if [ ! -f /usr/share/logstash/bin/logstash ]; then
  echo "--- Installing Logstash ${LOGSTASH_VERSION} ---"
  # Use python3.13 if available (RHEL 10+), fall back to python3 (RHEL 8/9)
  PYTHON_PKGS="python3.13 python3.13-pip"
  if ! dnf info python3.13 &>/dev/null; then
    PYTHON_PKGS="python3 python3-pip"
  fi
  dnf install -y git $PYTHON_PKGS gettext awscli2 --quiet
  python3 -m pip install --quiet --break-system-packages boto3 requests

  rpm --import https://artifacts.elastic.co/GPG-KEY-elasticsearch
  cat > /etc/yum.repos.d/elastic.repo <<'REPO'
[elasticsearch]
name=Elasticsearch repository for 8.x packages
baseurl=https://artifacts.elastic.co/packages/8.x/yum
gpgcheck=1
gpgkey=https://artifacts.elastic.co/GPG-KEY-elasticsearch
enabled=1
autorefresh=1
type=rpm-md
REPO
  dnf install -y "logstash-${LOGSTASH_VERSION}"
  echo "Logstash installed"
else
  echo "Logstash already installed — skipping"
fi

echo "--- Installing Logstash plugins ---"
# Update aws integration plugin — bundled version has a PageableResponse incompatibility with aws-sdk-core 3.213+
/usr/share/logstash/bin/logstash-plugin update logstash-integration-aws
/usr/share/logstash/bin/logstash-plugin install logstash-filter-tld logstash-output-opensearch
echo "Plugins installed"

# ----------------------------------------
# 2. Provision the logstash account for interactive, no-sudo use
# ----------------------------------------
echo "--- Provisioning logstash account ---"

LOGSTASH_HOME="/home/logstash"
current_home="$(getent passwd logstash | cut -d: -f6)"
if [ "$current_home" != "$LOGSTASH_HOME" ]; then
  mkdir -p "$LOGSTASH_HOME"
  usermod --shell /bin/bash --home "$LOGSTASH_HOME" --move-home logstash \
    || usermod --shell /bin/bash --home "$LOGSTASH_HOME" logstash
else
  usermod --shell /bin/bash logstash
fi
mkdir -p "$LOGSTASH_HOME"
chown logstash:logstash "$LOGSTASH_HOME"

# sincedb: persists S3 read position across restarts; app + service logs
mkdir -p /var/lib/logstash/plugins/inputs/s3 /var/log/logstash
chown -R logstash:logstash /var/lib/logstash /var/log/logstash /usr/share/logstash/vendor

# Config dir: owned entirely by logstash so day-2 config deploys never need
# root. This deliberately loosens Elastic's default root:logstash (group
# read-only) hardening — accepted tradeoff for no-sudo operation.
mkdir -p /etc/logstash
chown -R logstash:logstash /etc/logstash
chmod -R u+rwX /etc/logstash

# Repo dir: cloned as root by userdata before this script ran — hand it off.
if [ -d "$REPO_DIR" ]; then
  chown -R logstash:logstash "$REPO_DIR"
fi

# Keep the account running (and its systemd --user manager alive) without an
# active login session, so `systemctl --user` works across reboots/reconnects.
loginctl enable-linger logstash

# systemd --user units inherit the account's PAM nofile limit, which
# defaults well below what Logstash needs under S3-polling load.
cat > /etc/security/limits.d/90-logstash.conf <<'EOF'
logstash soft nofile 65536
logstash hard nofile 65536
EOF

# Defensive XDG_RUNTIME_DIR export — belt-and-suspenders in case whatever
# session mechanism (SSM Run-As, runuser) doesn't set it via PAM/logind.
for f in "$LOGSTASH_HOME/.bash_profile" "$LOGSTASH_HOME/.bashrc"; do
  touch "$f"
  if ! grep -q 'XDG_RUNTIME_DIR' "$f"; then
    echo 'export XDG_RUNTIME_DIR="/run/user/$(id -u)"' >> "$f"
  fi
done
chown logstash:logstash "$LOGSTASH_HOME/.bash_profile" "$LOGSTASH_HOME/.bashrc"

# ----------------------------------------
# 3. Install the user-level systemd unit
# ----------------------------------------
echo "--- Installing systemd --user unit ---"
mkdir -p "$LOGSTASH_HOME/.config/systemd/user"
cat > "$LOGSTASH_HOME/.config/systemd/user/logstash.service" <<'SERVICE'
[Unit]
Description=Logstash o11y-cloudfront-batch pipeline
After=network.target

[Service]
Type=simple
EnvironmentFile=/etc/logstash/env
ExecStart=/usr/share/logstash/bin/logstash --path.settings /etc/logstash
Restart=on-failure
RestartSec=30
LimitNOFILE=65536

[Install]
WantedBy=default.target
SERVICE
chown -R logstash:logstash "$LOGSTASH_HOME/.config"

echo ""
echo "=== Bootstrap complete ==="
echo "Next: run scripts/logstash-deploy.sh as the logstash user (no sudo) to deploy config and start the service."
