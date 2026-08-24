locals {
  common_tags = {
    venue     = var.venue
    tenant    = var.tenant
    component = var.component
    managedby = var.managedby
    cicd      = var.cicd
  }
}

module "web_analytics" {
  source = "./web-analytics-batch"

  aws_region             = var.aws_region
  partition              = var.partition
  logs_s3_bucket_name = var.logs_s3_bucket_name
  resource_prefix     = var.resource_prefix
  ec2_role_name       = var.ec2_role_name
  common_tags         = local.common_tags
}
