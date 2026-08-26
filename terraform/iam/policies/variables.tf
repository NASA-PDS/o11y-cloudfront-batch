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

variable "logs_s3_bucket_name" {
  type        = string
  description = "Full name of the S3 logs bucket (e.g. pds-logs-dev)"
}

variable "ec2_role_name" {
  type        = string
  description = "Name of the existing EC2 IAM role to attach the policy to"
}

variable "venue" {
  type        = string
  description = "Deployment venue (dev, test, prod)"
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
  default = "terraform"
}

variable "managedby" {
  type = string
}
