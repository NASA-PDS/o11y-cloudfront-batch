data "aws_caller_identity" "current" {}

# Reads s3_bucket_name from SSM (/pds/o11y-cloudfront-batch/s3/bucket_name) so this
# module can be applied independently of the S3 root module.
data "aws_ssm_parameter" "s3_bucket_name" {
  name = "/pds/o11y-cloudfront-batch/s3/bucket_name"
}

data "aws_ssm_parameter" "opensearch_endpoint" {
  name = "/pds/o11y-platform/opensearch/opensearch_endpoint"
}

# Reads the EC2 instance profile name published by terraform/iam/.
data "aws_ssm_parameter" "ec2_instance_profile_name" {
  name = "/pds/${var.component}/iam/roles/ec2/instance-profile-name"
}

# Private hosted zone published by pdc-cds-infra (terraform/private-hosted-zone). The zone is read
# from SSM, not looked up by name. Only needed when this module creates the EC2 and its DNS record.
data "aws_ssm_parameter" "private_zone_id" {
  count = var.manage_ec2_instance ? 1 : 0
  name  = "/pds/private-hosted-zone/id"
}

data "aws_ssm_parameter" "private_zone_name" {
  count = var.manage_ec2_instance ? 1 : 0
  name  = "/pds/private-hosted-zone/name"
}

# TODO: vpc_id should be sourced from SSM once published under /pds/cds-infra/vpc/.
data "aws_subnets" "private" {
  count = var.manage_ec2_instance ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  filter {
    name   = "map-public-ip-on-launch"
    values = ["false"]
  }
}
