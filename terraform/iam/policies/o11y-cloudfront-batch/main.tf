moved {
  from = aws_iam_policy.ec2_web_analytics_access
  to   = aws_iam_policy.ec2_o11y_cloudfront_batch_access
}

resource "aws_iam_policy" "ec2_o11y_cloudfront_batch_access" {
  name        = "${var.resource_prefix}-o11y-cloudfront-batch-access-policy"
  description = "Allow EC2 role to read from ${var.logs_s3_bucket_name} and write to OpenSearch (ARN from SSM)"
  policy      = data.aws_iam_policy_document.ec2_o11y_cloudfront_batch_access.json
  tags        = var.common_tags
}
