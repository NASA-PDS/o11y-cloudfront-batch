resource "aws_ssm_parameter" "s3_bucket_name" {
  name        = "/pds/web-analytics/s3/bucket_name"
  type        = "String"
  value       = module.s3_bucket.bucket_name
  description = "Name of the web-analytics S3 log bucket"
}

output "s3_bucket_name" {
  value       = module.s3_bucket.bucket_name
  description = "Name of the S3 bucket created for web analytics logs."
}

output "s3_bucket_arn" {
  value       = module.s3_bucket.bucket_arn
  description = "ARN of the S3 bucket."
}
