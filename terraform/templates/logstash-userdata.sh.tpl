#!/bin/bash
# Cloud-init userdata for the PDS Logstash EC2.
# Runs as root at first boot — confirms the AMI's SSM agent (used by system
# administrators, and by developers in dev) is running, then runs the full
# Logstash bootstrap: packages, Logstash RPM, plugins, pdsops key-user account
# configuration, and the systemd --user unit.
#
# After this script completes an operator can SSH in via the bastion, run
# `sudo -iu pdsops`, and run logstash-deploy.sh with no further sudo.
#
# Output is tee'd to /var/log/logstash-bootstrap.log and also captured
# by cloud-init at /var/log/cloud-init-output.log.
#
# Template variables (substituted by Terraform templatefile):
#   logstash_version - Logstash RPM version to install (e.g. 8.18.0)
set -euo pipefail

exec > >(tee /var/log/logstash-bootstrap.log) 2>&1

LOGSTASH_VERSION="${logstash_version}"
REPO_DIR="/opt/o11y-cloudfront-batch"
PDSOPS_USER="pdsops"

echo "=== o11y-cloudfront-batch userdata bootstrap ==="
echo "Logstash version : $LOGSTASH_VERSION"
echo "Started          : $(date -u)"

# ----------------------------------------
# 1. SSM agent — the AMI ships it; it is the system administrator access path
# ----------------------------------------
echo "--- Checking SSM agent ---"
if ! rpm -q amazon-ssm-agent >/dev/null 2>&1; then
  echo "ERROR: amazon-ssm-agent is not installed — the AMI must ship the SSM agent." >&2
  exit 1
fi
systemctl enable --now amazon-ssm-agent
echo "SSM agent installed and running"

# ----------------------------------------
# 2. System packages + Logstash RPM
# ----------------------------------------
echo "--- Installing system packages ---"
# Use python3.13 if available (RHEL 10+), fall back to python3 (RHEL 8/9).
PYTHON_BIN="python3.13"
PYTHON_PKGS="python3.13 python3.13-pip"
if ! dnf info python3.13 &>/dev/null; then
  PYTHON_BIN="python3"
  PYTHON_PKGS="python3 python3-pip"
fi
dnf install -y git $PYTHON_PKGS gettext --quiet
# The AMI ships an AWS CLI; install one only if it is missing.
if ! command -v aws >/dev/null 2>&1; then
  dnf install -y awscli2 --quiet
fi
# pip older than 23.0.1 (python3.9 on RHEL 9) rejects --break-system-packages.
PIP_HELP="$("$PYTHON_BIN" -m pip install --help 2>/dev/null || true)"
PIP_FLAGS=""
if grep -q -- "--break-system-packages" <<<"$PIP_HELP"; then
  PIP_FLAGS="--break-system-packages"
fi
"$PYTHON_BIN" -m pip install --quiet $PIP_FLAGS boto3 requests

echo "--- Installing Logstash $LOGSTASH_VERSION ---"
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
dnf install -y "logstash-$LOGSTASH_VERSION"
echo "Logstash $LOGSTASH_VERSION installed"

# ----------------------------------------
# 3. Logstash plugins
# ----------------------------------------
echo "--- Installing Logstash plugins ---"
# Update aws integration plugin — bundled version has a PageableResponse
# incompatibility with aws-sdk-core 3.213+
/usr/share/logstash/bin/logstash-plugin update logstash-integration-aws
/usr/share/logstash/bin/logstash-plugin install logstash-filter-tld logstash-output-opensearch
echo "Plugins installed"

# ----------------------------------------
# 4. Configure the pdsops key-user
# ----------------------------------------
echo "--- Configuring pdsops account ---"
if ! id "$PDSOPS_USER" &>/dev/null; then
  echo "ERROR: '$PDSOPS_USER' user not found — AMI must pre-provision this account." >&2
  exit 1
fi

PDSOPS_HOME="$(getent passwd "$PDSOPS_USER" | cut -d: -f6)"
if [ -z "$PDSOPS_HOME" ]; then
  echo "ERROR: could not determine home directory for $PDSOPS_USER." >&2
  exit 1
fi

# Don't assume the AMI gave pdsops a same-named primary group.
PDSOPS_GROUP="$(id -gn "$PDSOPS_USER")"
PDSOPS_OWNER="$PDSOPS_USER:$PDSOPS_GROUP"

# Ensure interactive shell and home dir
usermod --shell /bin/bash "$PDSOPS_USER"
mkdir -p "$PDSOPS_HOME"
chown "$PDSOPS_OWNER" "$PDSOPS_HOME"

# sincedb + app + service logs — owned by pdsops for no-sudo day-2 ops
mkdir -p /var/lib/logstash/plugins/inputs/s3 /var/log/logstash
chown -R "$PDSOPS_OWNER" /var/lib/logstash /var/log/logstash /usr/share/logstash/vendor

# Config dir: owned entirely by pdsops so deploy.sh never needs root.
# Deliberately loosens Elastic's default root:logstash hardening —
# accepted tradeoff for no-sudo operation.
mkdir -p /etc/logstash
chown -R "$PDSOPS_OWNER" /etc/logstash
chmod -R u+rwX /etc/logstash

# Repo dir: create and hand ownership to pdsops so deploy.sh can git-clone
# into it without needing sudo.
mkdir -p "$REPO_DIR"
chown -R "$PDSOPS_OWNER" "$REPO_DIR"

# Keep the pdsops systemd --user manager alive across reboots and
# reconnects without an active login session.
loginctl enable-linger "$PDSOPS_USER"

# systemd --user units inherit the account's PAM nofile limit, which
# defaults well below what Logstash needs under S3-polling load.
cat > /etc/security/limits.d/90-logstash.conf <<EOF
$PDSOPS_USER soft nofile 65536
$PDSOPS_USER hard nofile 65536
EOF

# Ensure XDG_RUNTIME_DIR is set in interactive sessions — belt-and-suspenders
# for `sudo -iu pdsops` sessions that may not set it via PAM/logind.
for f in "$PDSOPS_HOME/.bash_profile" "$PDSOPS_HOME/.bashrc"; do
  touch "$f"
  if ! grep -q 'XDG_RUNTIME_DIR' "$f"; then
    echo 'export XDG_RUNTIME_DIR="/run/user/$(id -u)"' >> "$f"
  fi
done
chown "$PDSOPS_OWNER" "$PDSOPS_HOME/.bash_profile" "$PDSOPS_HOME/.bashrc"

# ----------------------------------------
# 5. Systemd --user unit for Logstash
# ----------------------------------------
echo "--- Installing systemd --user unit ---"
mkdir -p "$PDSOPS_HOME/.config/systemd/user"
cat > "$PDSOPS_HOME/.config/systemd/user/logstash.service" <<'SERVICE'
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
chown -R "$PDSOPS_OWNER" "$PDSOPS_HOME/.config"

echo ""
echo "=== Bootstrap complete: $(date -u) ==="
echo "Next: connect as pdsops and run scripts/logstash-deploy.sh (no sudo)."
