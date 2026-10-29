module "s3_bucket" {
  source      = "git@github.com:NASA-PDS/pdc-tf-modules.git//terraform/modules/s3/bucket?ref=develop"
  bucket_name = local.s3_bucket_name
  partition   = var.partition
  versioning  = "Enabled"

  # Lifecycle rules: current objects go to Intelligent-Tiering immediately (module default),
  # incomplete multipart uploads abort after 7 days, and every noncurrent version expires after 14 days.
  storage_class                          = "INTELLIGENT_TIERING"
  storage_class_transition_days          = 0
  abort_incomplete_multipart_upload_days = 7
  noncurrent_version_expiration_days     = 14
  newer_noncurrent_versions              = 0

  # Public access blocks are enforced at the account level; enable_blocks=false avoids a redundant conflict
  enable_blocks = false
  enable_policy = true

  bucket_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid       = "AllowSSLRequestsOnly",
        Effect    = "Deny",
        Principal = "*",
        Action    = "s3:*",
        Resource = [
          "arn:${var.partition}:s3:::${local.s3_bucket_name}",
          "arn:${var.partition}:s3:::${local.s3_bucket_name}/*"
        ],
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })

  required_tags = {
    tenant    = var.tenant
    venue     = var.venue
    component = var.component
    cicd      = var.cicd
    managedby = var.managedby
  }
}
