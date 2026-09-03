module "ec2_instance_role" {
  source = "../../../../../pds-tf-modules/terraform/modules/iam/roles/ec2"

  venue     = var.venue
  component = var.component

  required_tags = {
    tenant    = var.tenant
    venue     = var.venue
    component = var.component
    managedby = var.managedby
    cicd      = var.cicd
  }
}
