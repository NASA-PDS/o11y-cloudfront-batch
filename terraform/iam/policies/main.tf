locals {
  common_tags = {
    venue     = var.venue
    tenant    = var.tenant
    component = var.component
    managedby = var.managedby
    cicd      = var.cicd
  }
}

moved {
  from = module.web_analytics
  to   = module.o11y_cloudfront_batch
}

module "o11y_cloudfront_batch" {
  source = "./o11y-cloudfront-batch"

  aws_region             = var.aws_region
  partition              = var.partition
  logs_s3_bucket_name = var.logs_s3_bucket_name
  ec2_role_name       = var.ec2_role_name
  common_tags         = local.common_tags
}
