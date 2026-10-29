variable "aws_region" {
  description = "The AWS region to deploy in"
  type        = string
  default     = "us-west-2"
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

variable "manage_ec2_instance" {
  description = "Whether this module creates the Logstash EC2 instance. Set to false to reuse an existing, externally-managed EC2 - see existing_instance_id and terraform/logstash/README.md 'Using an existing EC2'."
  type        = bool
  default     = true
}

variable "existing_instance_id" {
  description = "Instance ID of an existing EC2 to publish as /pds/o11y-cloudfront-batch/ec2/logstash_instance_id. Required when manage_ec2_instance = false; ignored otherwise."
  type        = string
  default     = ""
}

variable "vpc_id" {
  description = "VPC ID for the Logstash EC2, its security group, and the private subnet lookup. Required when manage_ec2_instance = true. TODO: replace with SSM data source under /pds/cds-infra/vpc/id once published."
  type        = string
  sensitive   = true
  default     = ""
}

variable "logstash_instance_type" {
  description = "EC2 instance type for the Logstash instance. t3.large provides 8GB RAM, sufficient for a 4GB JVM heap."
  type        = string
  default     = "t3.large"
}

variable "logstash_root_volume_size" {
  description = "Root volume size in GB for the Logstash instance. Must be >= the AMI root snapshot size (32 GB)."
  type        = number
  default     = 50
}

variable "logstash_version" {
  description = "Logstash RPM version to install"
  type        = string
  default     = "8.18.0"
}

variable "ami_id" {
  description = "AMI ID for the Logstash EC2 instance. Required when manage_ec2_instance = true."
  type        = string
  default     = ""
}

variable "bastion_target_sg_ssm_path" {
  description = "SSM parameter path for the bastion target SG ID. The SG is attached to the Logstash EC2 so it accepts SSH from the bastion. Required when manage_ec2_instance = true; ignored otherwise (an existing EC2 must already accept SSH from the bastion)."
  type        = string
  default     = ""

  validation {
    condition     = !var.manage_ec2_instance || length(var.bastion_target_sg_ssm_path) > 0
    error_message = "bastion_target_sg_ssm_path must be set when manage_ec2_instance = true."
  }
}
