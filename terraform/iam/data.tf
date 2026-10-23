data "aws_caller_identity" "current" {}

data "aws_ssm_parameter" "opensearch_arn" {
  name = "/pds/o11y-platform/opensearch/opensearch_arn"
}
