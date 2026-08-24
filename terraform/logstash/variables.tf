variable "aws_region" {
  description = "The AWS region to deploy in"
  type        = string
  default     = "us-west-2"
}

variable "partition" {
  description = "AWS partition (aws, aws-us-gov, aws-cn)"
  type        = string
  default     = "aws"
}

variable "tenant" {
  description = "Tag value for Tenant"
  type        = string
}

variable "cicd" {
  description = "Tag value for CICD deployment method"
  type        = string
}

variable "venue" {
  description = "Tag value for Venue"
  type        = string
}

variable "component" {
  description = "Tag value for application component"
  type        = string
}

variable "managedby" {
  description = "Tag value for owner managing the resource"
  type        = string
}

variable "resource_prefix" {
  description = "Prefix for all resources (e.g. pds-dev). No CI/CD pipeline identifiers."
  type        = string
}

variable "ec2_role_name" {
  description = "Existing PDS EC2 IAM role name (used as instance profile)"
  type        = string
}

variable "manage_ec2_instance" {
  description = "Whether this module creates the Logstash EC2 (launch template + instance). Set to false to reuse an existing, externally-managed EC2 (e.g. production) — see existing_instance_id and terraform/logstash/README.md 'Using an existing EC2'."
  type        = bool
  default     = true
}

variable "existing_instance_id" {
  description = "Instance ID of an existing EC2 to publish as /pds/o11y-cloudfront-batch/ec2/logstash_instance_id. Required when manage_ec2_instance = false; ignored otherwise."
  type        = string
  default     = ""
}

variable "vpc_id" {
  description = "VPC ID for the Logstash EC2 and security group lookup. Required when manage_ec2_instance = true. TODO: replace with SSM data source under /pds/cds-infra/vpc/id once published."
  type        = string
  sensitive   = true
  default     = ""
}

variable "ec2_security_group_name" {
  description = "Name of the EC2 security group to attach to the Logstash instance. Required when manage_ec2_instance = true. TODO: replace with SSM lookup under /pds/cds-infra/vpc/security_groups/ once published."
  type        = string
  default     = ""
}

variable "logstash_instance_type" {
  description = "EC2 instance type for the Logstash instance. t3.large provides 8GB RAM, sufficient for a 4GB JVM heap."
  type        = string
  default     = "t3.large"
}

variable "logstash_version" {
  description = "Logstash RPM version to install"
  type        = string
  default     = "8.18.0"
}

variable "s3_cf_bucket_name" {
  description = "Name of the S3 bucket containing CloudFront access logs (EN node only). Leave empty to skip."
  type        = string
  default     = ""
}

variable "mcp_ami_owner_id" {
  description = "AWS account ID that owns the Amazon Linux 2023 AMIs used for the Logstash instance. Required when manage_ec2_instance = true."
  type        = string
  default     = ""
}

variable "repo_branch" {
  description = "Branch of the o11y-cloudfront-batch repo to clone at EC2 first boot."
  type        = string
  default     = "main"
}
