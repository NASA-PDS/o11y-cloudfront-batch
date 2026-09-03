data "aws_ssm_parameter" "ec2_role_name" {
  name = "/pds/${var.component}/iam/roles/ec2-instance-profile-name"
}
