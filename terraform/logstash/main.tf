# ---------------------------------------------------------------------------
# Logstash EC2 instance
# ---------------------------------------------------------------------------
# AMI: PDS Cloud Oracle Linux 9 image (key-user pdsops pre-provisioned).
# Logstash is installed via RPM (not Docker) — baked into userdata so no
# manual root step is needed after first boot.
#
# Access: SSH via the CDS bastion host, or AWS Systems Manager.
# Instance role is managed separately in terraform/iam/ and its
# profile name is read from SSM at /pds/<component>/iam/roles/ec2/instance-profile-name
# (published by the iam module after apply).
#
# EC2 creation is optional (var.manage_ec2_instance, default true) — set to
# false to point this module at an existing, externally-managed EC2 (e.g.
# production reusing an instance that predates this module). In that mode,
# only the SSM Run-As session document and the SSM parameter outputs are
# managed; var.existing_instance_id is published in place of a created
# instance's ID. See terraform/logstash/README.md "Using an existing EC2"
# for the manual setup steps (logstash-bootstrap.sh + logstash-deploy.sh).
#
# All data sources (SSM parameters, SG/subnet lookups) live in data.tf.

locals {
  ec2_name = "pds-${var.component}"
  logstash_tags = {
    tenant    = var.tenant
    venue     = var.venue
    component = var.component
    managedby = var.managedby
    cicd      = var.cicd
    Name      = local.ec2_name
  }
}

module "ec2" {
  source = "git@github.com:NASA-PDS/pdc-tf-modules.git//terraform/modules/ec2?ref=feature/ec2-instance-type-in-place-resize"
  count  = var.manage_ec2_instance ? 1 : 0

  ami_id                     = var.ami_id
  instance_profile           = data.aws_ssm_parameter.ec2_instance_profile_name.value
  bastion_target_sg_ssm_path = var.bastion_target_sg_ssm_path

  ec2_instance_configs = [{
    instance_name    = local.ec2_name
    instance_type    = var.logstash_instance_type
    subnet_id        = sort(data.aws_subnets.private[0].ids)[0]
    security_groups  = [data.aws_security_group.logstash_ec2[0].id]
    root_volume_size = var.logstash_root_volume_size
    root_volume_type = "gp3"
    user_data = base64encode(templatefile("${path.module}/../templates/logstash-userdata.sh.tpl", {
      aws_region       = var.aws_region
      logstash_version = var.logstash_version
    }))
  }]

  required_tags = {
    tenant    = var.tenant
    venue     = var.venue
    component = var.component
    managedby = var.managedby
    cicd      = var.cicd
  }
}


# ---------------------------------------------------------------------------
# DNS - A record in the existing hosted zone (published by the account
# baseline at /pds/hosted-zone/name), the same zone as the bastion host. The
# record name matches the ec2 Name tag, so the SSH target and instance name
# are the same. Only created when this module manages the EC2
# (manage_ec2_instance = true).
# ---------------------------------------------------------------------------
data "aws_ssm_parameter" "hosted_zone_name" {
  count = var.manage_ec2_instance ? 1 : 0
  name  = "/pds/hosted-zone/name"
}

data "aws_route53_zone" "main" {
  count = var.manage_ec2_instance ? 1 : 0
  name  = data.aws_ssm_parameter.hosted_zone_name[0].value
}

resource "aws_route53_record" "logstash" {
  count   = var.manage_ec2_instance ? 1 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = local.ec2_name
  type    = "A"
  ttl     = 30
  records = [module.ec2[0].private_ips[local.ec2_name]]
}

# ---------------------------------------------------------------------------
# SSM Run-As session document
# ---------------------------------------------------------------------------
# Lets `aws ssm start-session --document-name <this>` land directly as the
# `pdsops` key-user instead of root/ssm-user, so operators never need sudo
# for logstash execution, logging, monitoring, or config (git) updates —
# `scripts/logstash-deploy.sh` runs entirely under this account.
#
# Deliberately a distinct document name (not the account-wide default
# `SSM-SessionManagerRunShell`), invoked explicitly via --document-name, so
# it can't collide with anything managed centrally for other instances.
#
# Note: granting operators `ssm:StartSession` on this document's ARN (in
# addition to the instance ARN) is an IAM/SSO concern owned outside this
# repo — this module only manages the EC2 instance role, not human roles.
resource "aws_ssm_document" "logstash_runas" {
  name            = "${local.ec2_name}-runas-pdsops"
  document_type   = "Session"
  document_format = "JSON"

  content = jsonencode({
    schemaVersion = "1.0"
    description   = "SSM session landing directly as the pdsops key-user (no sudo)."
    sessionType   = "Standard_Stream"
    inputs = {
      s3BucketName                = ""
      s3KeyPrefix                 = ""
      s3EncryptionEnabled         = true
      cloudWatchLogGroupName      = ""
      cloudWatchEncryptionEnabled = true
      cloudWatchStreamingEnabled  = false
      kmsKeyId                    = ""
      runAsEnabled                = true
      runAsDefaultUser            = "pdsops"
      idleSessionTimeout          = "20"
      maxSessionDuration          = ""
      shellProfile = {
        windows = ""
        linux   = "cd /opt/o11y-cloudfront-batch && export XDG_RUNTIME_DIR=\"/run/user/$(id -u)\""
      }
    }
  })

  tags = local.logstash_tags
}
