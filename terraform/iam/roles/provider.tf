provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      tenant    = var.tenant
      venue     = var.venue
      component = var.component
      managedby = var.managedby
      cicd      = var.cicd
    }
  }
}
