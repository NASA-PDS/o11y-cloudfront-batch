resource "aws_ssm_parameter" "s3_bucket_name" {
  name        = "/pds/o11y-cloudfront-batch/s3/bucket_name"
  type        = "String"
  value       = module.s3_bucket.bucket_name
  description = "Name of the o11y-cloudfront-batch S3 log bucket"
}

output "s3_bucket_name" {
  value       = module.s3_bucket.bucket_name
  description = "Name of the S3 bucket created for o11y-cloudfront-batch logs."
}

output "s3_bucket_arn" {
  value       = module.s3_bucket.bucket_arn
  description = "ARN of the S3 bucket."
}
