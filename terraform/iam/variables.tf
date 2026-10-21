variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "us-west-2"
}

variable "partition" {
  type        = string
  description = "AWS partition"
  default     = "aws"
}

variable "venue" {
  type        = string
  description = "Deployment venue (dev, test, prod). Used in role naming and tags."
}

variable "tenant" {
  type    = string
  default = "en"
}

variable "component" {
  type    = string
  default = "o11y-cloudfront-batch"
}

variable "cicd" {
  type    = string
  default = "iac"
}

variable "managedby" {
  type        = string
  description = "Email address of the team or person managing this resource"
}

variable "ec2users_dynamodb_table_arn" {
  type        = string
  description = "ARN of the DynamoDB ec2users table to grant Get*/Query access on the EC2 instance role."
}

variable "logs_s3_bucket_name" {
  type        = string
  description = "Full name of the S3 logs bucket (e.g. pds-logs-dev)"
}

variable "smtp_config_ssm_path" {
  type        = string
  description = "SSM parameter path prefix holding SMTP credentials (username, password, server, sender) for the daily egress report - see scripts/egress_report.py. Defaults to data-upload-manager's existing verified SMTP relay config (/pds/dum/smtp/) rather than provisioning a new one."
  default     = "/pds/dum/smtp/"
}
