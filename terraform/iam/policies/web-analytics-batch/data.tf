data "aws_caller_identity" "current" {}

data "aws_ssm_parameter" "opensearch_arn" {
  name = "/pds/observability/opensearch/opensearch_arn"
}

data "aws_iam_policy_document" "ec2_web_analytics_access" {
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
  # SMTP credentials for sending its daily email — same SSM-sourced SMTP
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
