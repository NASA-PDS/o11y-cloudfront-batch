
resource "aws_ssm_parameter" "logstash_instance_id" {
  name        = "/pds/o11y-cloudfront-batch/ec2/logstash_instance_id"
  type        = "String"
  value       = var.manage_ec2_instance ? module.ec2[0].instance_ids[local.ec2_name] : var.existing_instance_id
  description = "Instance ID of the o11y-cloudfront-batch Logstash EC2 (created by this module, or an existing instance when manage_ec2_instance = false)"

  lifecycle {
    precondition {
      condition     = var.manage_ec2_instance || length(var.existing_instance_id) > 0
      error_message = "existing_instance_id must be set when manage_ec2_instance = false."
    }
  }
}

resource "aws_ssm_parameter" "logstash_fqdn" {
  count       = var.manage_ec2_instance ? 1 : 0
  name        = "/pds/o11y-cloudfront-batch/ec2/logstash_fqdn"
  type        = "String"
  value       = aws_route53_record.logstash[0].fqdn
  description = "FQDN of the Logstash EC2 in the shared hosted zone (SSH target from the bastion)"
}

resource "aws_ssm_parameter" "logstash_runas_document" {
  name        = "/pds/o11y-cloudfront-batch/ssm/logstash_runas_document"
  type        = "String"
  value       = aws_ssm_document.logstash_runas.name
  description = "SSM document name to pass as --document-name for a Run-As session landing as the pdsops user (no sudo)"
}

output "logstash_instance_id" {
  value       = aws_ssm_parameter.logstash_instance_id.value
  description = "Instance ID of the Logstash EC2 (created by this module, or existing_instance_id when manage_ec2_instance = false)"
  sensitive   = true
}

output "logstash_ssm_document_name" {
  value       = aws_ssm_document.logstash_runas.name
  description = "Pass as --document-name to land an SSM session as the pdsops user (no sudo)"
}

output "logstash_fqdn" {
  value       = var.manage_ec2_instance ? aws_route53_record.logstash[0].fqdn : null
  description = "FQDN of the Logstash EC2 in the shared hosted zone. SSH to this from the bastion. Null when manage_ec2_instance = false."
}
