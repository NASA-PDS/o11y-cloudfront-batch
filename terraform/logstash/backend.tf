# Backend configuration for S3 state storage
# The key is pinned here; all other values are supplied at init time via -backend-config.
#
# Usage:
#   terraform init -backend-config=backend-<venue>.hcl

terraform {
  backend "s3" {
    key = "o11y-cloudfront-batch/logstash.tfstate"
  }
}
