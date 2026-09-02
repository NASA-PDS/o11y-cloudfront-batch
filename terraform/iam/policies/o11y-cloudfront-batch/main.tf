moved {
  from = aws_iam_policy.ec2_web_analytics_access
  to   = aws_iam_policy.ec2_o11y_cloudfront_batch_access
}

resource "aws_iam_policy" "ec2_o11y_cloudfront_batch_access" {
  name        = "pds-o11y-cloudfront-batch-access-policy"
  description = "Allow EC2 role to read from ${var.logs_s3_bucket_name} and write to OpenSearch (ARN from SSM)"
  policy      = data.aws_iam_policy_document.ec2_o11y_cloudfront_batch_access.json
  tags        = var.common_tags
}

resource "aws_ssm_parameter" "ec2_role_arn" {
  name        = "/pds/o11y-cloudfront-batch/iam/ec2_role_arn"
  type        = "String"
  value       = "arn:${var.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${var.ec2_role_name}"
  description = "ARN of the EC2 role used by the Logstash instance — currently the shared instance profile, update when a dedicated role exists"
}
