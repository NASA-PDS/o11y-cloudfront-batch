# S3 + OpenSearch + SMTP-config access policy for the Logstash EC2 role, and its attachment.

data "aws_iam_policy_document" "ec2_o11y_cloudfront_batch_access" {
  statement {
    effect = "Allow"
    actions = [
      "s3:List*",
      "s3:GetObject*",
      "s3:GetBucket*"
    ]
    resources = [
      "arn:${var.partition}:s3:::${var.logs_s3_bucket_name}",
      "arn:${var.partition}:s3:::${var.logs_s3_bucket_name}/*"
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "es:ESHttp*",
      "es:DescribeElasticsearchDomain",
      "es:DescribeDomain"
    ]
    resources = [
      data.aws_ssm_parameter.opensearch_arn.value,
      "${data.aws_ssm_parameter.opensearch_arn.value}/*"
    ]
  }

  # Lets the egress report (scripts/egress_report.py, cron on this EC2) read
  # SMTP credentials for sending its daily email - same SSM-sourced SMTP
  # pattern as data-upload-manager's send_email() (pds_status_app.py).
  statement {
    effect = "Allow"
    actions = [
      "ssm:GetParametersByPath",
      "ssm:GetParameter"
    ]
    resources = [
      "arn:${var.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.smtp_config_ssm_path}*"
    ]
  }
}

resource "aws_iam_policy" "ec2_o11y_cloudfront_batch_access" {
  name        = "pds-o11y-cloudfront-batch-access-policy"
  description = "Allow EC2 role to read from ${var.logs_s3_bucket_name} and write to OpenSearch (ARN from SSM)"
  policy      = data.aws_iam_policy_document.ec2_o11y_cloudfront_batch_access.json
  tags        = local.common_tags
}

resource "aws_iam_role_policy_attachment" "attach_access_to_ec2_role" {
  # The upstream role module exposes only the role ARN; the role name is its last path segment.
  role       = reverse(split("/", module.ec2_instance_role.role_arn))[0]
  policy_arn = aws_iam_policy.ec2_o11y_cloudfront_batch_access.arn
}
