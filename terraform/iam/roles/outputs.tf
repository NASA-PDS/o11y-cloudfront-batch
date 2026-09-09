# The upstream pdc-tf-modules iam/roles/ec2 module publishes both SSM parameters
# consumed by iam/policies and logstash:
#   /pds/${component}/iam/roles/ec2/instance-role-arn
#   /pds/${component}/iam/roles/ec2/instance-profile-name
# Do NOT add aws_ssm_parameter resources here — they are already created by the
# module and adding them again will conflict on apply.

output "ec2_instance_profile_name" {
  value       = module.ec2_instance_role.instance_profile_name
  description = "Name of the EC2 instance profile"
}

output "ec2_instance_role_arn" {
  value       = module.ec2_instance_role.role_arn
  description = "ARN of the EC2 instance IAM role"
}
