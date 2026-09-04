variable "aws_region" {
  type    = string
  default = "us-west-2"
}

variable "partition" {
  type    = string
  default = "aws"
}

variable "logs_s3_bucket_name" {
  type        = string
  description = "Full name of the S3 logs bucket (e.g. pds-logs-dev)"
}

variable "common_tags" {
  type        = map(string)
  description = "Common tags to apply to all resources"
  default     = {}
}

variable "smtp_config_ssm_path" {
  type        = string
  description = "SSM parameter path prefix holding SMTP credentials (username, password, server, sender) for the daily egress report — see scripts/egress_report.py. Defaults to data-upload-manager's existing verified SMTP relay config (/pds/dum/smtp/) rather than provisioning a new one."
  default     = "/pds/dum/smtp/"
}
