locals {
  # The "-web-analytics" suffix is fixed and does not follow the component name: an S3 bucket
  # rename requires delete/recreate plus data migration.
  s3_bucket_name = "${var.s3_bucket_prefix}-web-analytics"
}
