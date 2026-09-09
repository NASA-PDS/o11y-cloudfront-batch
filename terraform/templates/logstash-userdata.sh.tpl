#!/bin/bash
set -euo pipefail

# Install SSM agent so the instance registers with Systems Manager immediately
# after boot. Everything else (Logstash, account provisioning, config deploy)
# is done manually by an SA/operator after connecting via SSM.
#
# RHEL does not include amazon-ssm-agent in its default repos — install
# directly from the AWS RPM. SSM is the only access path to this instance;
# failure here must be fatal so the instance does not boot unreachable.
SSM_RPM="https://s3.${aws_region}.amazonaws.com/amazon-ssm-${aws_region}/latest/linux_amd64/amazon-ssm-agent.rpm"
dnf install -y "$SSM_RPM"
systemctl enable amazon-ssm-agent
systemctl start amazon-ssm-agent
