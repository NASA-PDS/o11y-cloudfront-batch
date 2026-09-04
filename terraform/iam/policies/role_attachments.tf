resource "aws_iam_role_policy_attachment" "attach_access_to_ec2_role" {
  role       = data.aws_ssm_parameter.ec2_role_name.value
  policy_arn = module.o11y_cloudfront_batch.policy_arn
}
