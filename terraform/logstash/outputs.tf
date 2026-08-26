resource "aws_ssm_parameter" "ec2_role_arn" {
  name        = "/pds/web-analytics/iam/ec2_role_arn"
  type        = "String"
  value       = "arn:${var.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${var.ec2_role_name}"
  description = "ARN of the EC2 role used by the Logstash instance — currently the shared instance profile, update when a dedicated role exists"
}

resource "aws_ssm_parameter" "logstash_instance_id" {
  name        = "/pds/web-analytics/ec2/logstash_instance_id"
  type        = "String"
  value       = var.manage_ec2_instance ? aws_instance.logstash[0].id : var.existing_instance_id
  description = "Instance ID of the web-analytics Logstash EC2 (created by this module, or an existing instance when manage_ec2_instance = false)"

  lifecycle {
    precondition {
      condition     = var.manage_ec2_instance || length(var.existing_instance_id) > 0
      error_message = "existing_instance_id must be set when manage_ec2_instance = false."
    }
  }
}

resource "aws_ssm_parameter" "logstash_runas_document" {
  name        = "/pds/web-analytics/ssm/logstash_runas_document"
  type        = "String"
  value       = aws_ssm_document.logstash_runas.name
  description = "SSM document name to pass as --document-name for a Run-As session landing as the logstash user (no sudo)"
}

output "logstash_instance_id" {
  value       = aws_ssm_parameter.logstash_instance_id.value
  description = "Instance ID of the Logstash EC2 (created by this module, or existing_instance_id when manage_ec2_instance = false)"
}

output "logstash_ssm_document_name" {
  value       = aws_ssm_document.logstash_runas.name
  description = "Pass as --document-name to land an SSM session as the logstash user (no sudo)"
}
