output "ec2_instance_profile_name" {
  value       = module.ec2_instance_role.instance_profile_name
  description = "Name of the EC2 instance profile"
}

output "ec2_instance_role_arn" {
  value       = module.ec2_instance_role.role_arn
  description = "ARN of the EC2 instance IAM role"
}
