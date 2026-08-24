resource "aws_iam_policy" "ec2_web_analytics_access" {
  name        = "${var.resource_prefix}-web-analytics-batch-access-policy"
  description = "Allow EC2 role to read from ${var.logs_s3_bucket_name} and write to OpenSearch (ARN from SSM)"
  policy      = data.aws_iam_policy_document.ec2_web_analytics_access.json
  tags        = var.common_tags
}
