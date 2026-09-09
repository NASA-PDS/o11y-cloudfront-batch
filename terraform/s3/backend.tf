# Backend configuration for S3 state storage
# The key is pinned here; all other values are supplied at init time via -backend-config.
#
# Usage:
#   terraform init -backend-config=backend-<venue>.hcl
#
# Example backend-<venue>.hcl content:
#   bucket         = "pds-<venue>-infra"
#   region         = "us-west-2"
#   dynamodb_table = "terraform-state-lock"
#   encrypt        = true
#   profile        = "your-aws-profile"

terraform {
  backend "s3" {
    key = "o11y-cloudfront-batch/s3.tfstate"
  }
}
