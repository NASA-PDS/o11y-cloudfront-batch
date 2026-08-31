data "aws_caller_identity" "current" {}

# Reads s3_bucket_name from SSM (/pds/o11y-cloudfront-batch/s3/bucket_name) so this
# module can be applied independently of the S3 root module.
data "aws_ssm_parameter" "s3_bucket_name" {
  name = "/pds/o11y-cloudfront-batch/s3/bucket_name"
}

data "aws_ssm_parameter" "opensearch_endpoint" {
  name = "/pds/o11y-platform/opensearch/opensearch_endpoint"
}


# TODO: vpc_id and ec2_security_group_name should be sourced from SSM once
# published under /pds/cds-infra/vpc/ — the pattern exists for other
# SGs at /pds/cds-infra/vpc/security_groups/registry_api_ecs_app_sg_id etc.
data "aws_security_group" "mcp_ec2" {
  count = var.manage_ec2_instance ? 1 : 0

  name   = var.ec2_security_group_name
  vpc_id = var.vpc_id
}

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
