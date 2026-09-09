output "policy_arn" {
  value       = module.o11y_cloudfront_batch.policy_arn
  description = "ARN of the o11y-cloudfront-batch EC2 access policy"
}

output "policy_name" {
  value       = module.o11y_cloudfront_batch.policy_name
  description = "Name of the o11y-cloudfront-batch EC2 access policy"
}
