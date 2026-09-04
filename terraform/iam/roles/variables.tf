variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "us-west-2"
}

variable "venue" {
  type        = string
  description = "Deployment venue (e.g. pds-cds-dev)"
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
