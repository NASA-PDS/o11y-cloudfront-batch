resource "aws_iam_role_policy_attachment" "attach_access_to_ec2_role" {
  role       = element(split("/", data.aws_ssm_parameter.ec2_instance_role_arn.value), length(split("/", data.aws_ssm_parameter.ec2_instance_role_arn.value)) - 1)
  policy_arn = module.o11y_cloudfront_batch.policy_arn
}
