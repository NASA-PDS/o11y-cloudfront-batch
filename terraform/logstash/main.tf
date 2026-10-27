# ---------------------------------------------------------------------------
# Logstash EC2 instance
# ---------------------------------------------------------------------------
# AMI: PDS Cloud Oracle Linux 9 image (key-user pdsops pre-provisioned).
# Logstash is installed via RPM (not Docker) — baked into userdata so no
# manual root step is needed after first boot.
#
# Access: SSH through the CDS bastion host with a NASA ID, then
# `sudo -iu pdsops`. The bastion target security group (var.bastion_target_sg_ssm_path) is required.
# SSM Session Manager is limited to system administrators (and to dev for
# developers); the instance profile carries the SSM agent permissions.
# Instance role is managed separately in terraform/iam/ and its
# profile name is read from SSM at /pds/<component>/iam/roles/ec2/instance-profile-name
# (published by the iam module after apply).
#
# EC2 creation is optional (var.manage_ec2_instance, default true) — set to
# false to point this module at an existing, externally-managed EC2 (e.g. an
# instance that predates this module). In that mode,
# only the SSM parameter outputs are managed; var.existing_instance_id is
# published in place of a created instance's ID. See
# terraform/logstash/README.md "Using an existing EC2" for the manual setup
# steps (logstash-bootstrap.sh + logstash-deploy.sh).
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

# Security group for the Logstash EC2. It has no inbound rules of its own (SSH
# ingress comes from the bastion target SG). Outbound is open so the instance can
# reach the SSM agent endpoints, DynamoDB (the AMI's SSH key lookup), package
# repositories, S3 and OpenSearch. The SG ID is published to SSM
# (outputs.tf) so o11y-platform's OpenSearch module can allow HTTPS from it.
resource "aws_security_group" "logstash" {
  count = var.manage_ec2_instance ? 1 : 0

  name        = "${local.ec2_name}-sg"
  description = "Logstash EC2 - outbound access (SSM, DynamoDB SSH auth, S3, OpenSearch, package repos)"
  vpc_id      = var.vpc_id

  tags = merge(local.logstash_tags, { Name = "${local.ec2_name}-sg" })
}

resource "aws_vpc_security_group_egress_rule" "logstash_all_outbound" {
  count = var.manage_ec2_instance ? 1 : 0

  security_group_id = aws_security_group.logstash[0].id
  description       = "Allow all outbound"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# TODO: change ref back to develop (or a release tag) before merging this branch to develop.
# feature/ec2-instance-type-in-place-resize is not yet merged into pdc-tf-modules develop.
module "ec2" {
  source = "git@github.com:NASA-PDS/pdc-tf-modules.git//terraform/modules/ec2?ref=feature/ec2-instance-type-in-place-resize"
  count  = var.manage_ec2_instance ? 1 : 0

  ami_id                     = var.ami_id
  instance_profile           = data.aws_ssm_parameter.ec2_instance_profile_name.value
  bastion_target_sg_ssm_path = var.bastion_target_sg_ssm_path

  # Nothing on the root volume needs to outlive the instance.
  root_volume_delete_on_termination = true

  ec2_instance_configs = [{
    instance_name    = local.ec2_name
    instance_type    = var.logstash_instance_type
    subnet_id        = sort(data.aws_subnets.private[0].ids)[0]
    security_groups  = [aws_security_group.logstash[0].id]
    root_volume_size = var.logstash_root_volume_size
    root_volume_type = "gp3"
    user_data = base64encode(templatefile("${path.module}/../templates/logstash-userdata.sh.tpl", {
      logstash_version = var.logstash_version
    }))
    # Userdata runs only at first boot, so a change must replace the instance.
    user_data_replace_on_change = true
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
