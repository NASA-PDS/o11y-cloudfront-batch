#!/bin/bash
set -euo pipefail

# Install SSM agent so the instance registers with Systems Manager immediately
# after boot. Everything else (Logstash, account provisioning, config deploy)
# is done manually by an SA/operator after connecting via SSM.
#
# RHEL does not include amazon-ssm-agent in its default repos — install
# directly from the AWS RPM. Wrapped in if/then so a failure here does not
# abort the script and leave the instance in an unknown state.
SSM_RPM="https://s3.${aws_region}.amazonaws.com/amazon-ssm-${aws_region}/latest/linux_amd64/amazon-ssm-agent.rpm"
if dnf install -y "$SSM_RPM" --quiet 2>/dev/null; then
  systemctl enable amazon-ssm-agent
  systemctl start amazon-ssm-agent
else
  echo "WARNING: SSM agent install failed — instance will not be reachable via SSM" >&2
fi
