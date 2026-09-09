data "aws_ssm_parameter" "ec2_instance_role_arn" {
  name = "/pds/${var.component}/iam/roles/ec2/instance-role-arn"
}
