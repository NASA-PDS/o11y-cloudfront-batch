resource "aws_iam_role_policy_attachment" "attach_access_to_ec2_role" {
  role       = var.ec2_role_name
  policy_arn = module.o11y_cloudfront_batch.policy_arn
}
