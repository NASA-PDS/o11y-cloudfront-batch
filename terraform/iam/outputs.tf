output "ec2_instance_profile_name" {
  value       = module.ec2_instance_role.instance_profile_name
  description = "Name of the EC2 instance profile"
}

output "ec2_instance_role_arn" {
  value       = module.ec2_instance_role.role_arn
  description = "ARN of the EC2 instance IAM role"
}

output "policy_arn" {
  value       = aws_iam_policy.ec2_o11y_cloudfront_batch_access.arn
  description = "ARN of the IAM policy granting EC2 access to S3 and OpenSearch"
}

output "policy_name" {
  value       = aws_iam_policy.ec2_o11y_cloudfront_batch_access.name
  description = "Name of the IAM policy"
}
