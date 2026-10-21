# EC2 instance role + instance profile for Logstash.
#
# The upstream pdc-tf-modules iam/roles/ec2 module also publishes both SSM parameters
# consumed by logstash:
#   /pds/${component}/iam/roles/ec2/instance-role-arn
#   /pds/${component}/iam/roles/ec2/instance-profile-name
# Do NOT add aws_ssm_parameter resources here - they are already created by the
# module and adding them again will conflict on apply.
module "ec2_instance_role" {
  source = "git@github.com:NASA-PDS/pdc-tf-modules.git//terraform/modules/iam/roles/ec2?ref=develop"

  venue                       = var.venue
  component                   = var.component
  ec2users_dynamodb_table_arn = var.ec2users_dynamodb_table_arn

  required_tags = local.common_tags
}
