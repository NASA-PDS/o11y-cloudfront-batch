
resource "aws_ssm_parameter" "logstash_instance_id" {
  name        = "/pds/o11y-cloudfront-batch/ec2/logstash_instance_id"
  type        = "String"
  value       = var.manage_ec2_instance ? module.ec2[0].instance_ids[local.ec2_name] : var.existing_instance_id
  description = "Instance ID of the o11y-cloudfront-batch Logstash EC2 (created by this module, or an existing instance when manage_ec2_instance = false). SSM session target for system administrators (and developers in dev)."

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

resource "aws_ssm_parameter" "logstash_security_group_id" {
  count       = var.manage_ec2_instance ? 1 : 0
  name        = "/pds/o11y-cloudfront-batch/ec2/logstash_security_group_id"
  type        = "String"
  value       = aws_security_group.logstash[0].id
  description = "Security group ID of the Logstash EC2. Read by o11y-platform's opensearch module to allow HTTPS from Logstash"
}

output "logstash_instance_id" {
  value       = aws_ssm_parameter.logstash_instance_id.value
  description = "Instance ID of the Logstash EC2 (created by this module, or existing_instance_id when manage_ec2_instance = false)"
  sensitive   = true
}

output "logstash_fqdn" {
  value       = var.manage_ec2_instance ? aws_route53_record.logstash[0].fqdn : null
  description = "FQDN of the Logstash EC2 in the shared hosted zone. SSH to this from the bastion. Null when manage_ec2_instance = false."
}
