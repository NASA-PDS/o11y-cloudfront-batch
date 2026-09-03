resource "aws_ssm_parameter" "ec2_instance_profile_name" {
  name        = "/pds/${var.component}/iam/roles/ec2-instance-profile-name"
  type        = "String"
  value       = module.ec2_instance_role.instance_profile_name
  description = "Name of the EC2 instance profile for ${var.component}"
}

resource "aws_ssm_parameter" "ec2_instance_role_arn" {
  name        = "/pds/${var.component}/iam/roles/ec2-instance-role-arn"
  type        = "String"
  value       = module.ec2_instance_role.role_arn
  description = "ARN of the EC2 instance IAM role for ${var.component}"
}

output "ec2_instance_profile_name" {
  value       = module.ec2_instance_role.instance_profile_name
  description = "Name of the EC2 instance profile"
}

output "ec2_instance_role_arn" {
  value       = module.ec2_instance_role.role_arn
  description = "ARN of the EC2 instance IAM role"
}
