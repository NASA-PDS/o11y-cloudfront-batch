module "ec2_instance_role" {
  source = "git@github.com:NASA-PDS/pdc-tf-modules.git//terraform/modules/iam/roles/ec2?ref=feature/update-ec2-module-oracle-linux-pdc"

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
