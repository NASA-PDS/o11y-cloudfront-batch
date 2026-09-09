module "ec2_instance_role" {
  source = "git@github.com:NASA-PDS/pdc-tf-modules.git//terraform/modules/iam/roles/ec2?ref=main"

  venue                       = var.venue
  component                   = var.component
  ec2users_dynamodb_table_arn = var.ec2users_dynamodb_table_arn

  required_tags = {
    tenant    = var.tenant
    venue     = var.venue
    component = var.component
    managedby = var.managedby
    cicd      = var.cicd
  }
}
