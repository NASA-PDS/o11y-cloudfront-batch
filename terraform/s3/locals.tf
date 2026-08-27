locals {
  # "-web-analytics" (not "-web-analytics-batch" or "-o11y-cloudfront-batch") is intentional and
  # permanent: it's a legacy name from an early design that used GitHub CD/OIDC to deploy this
  # bucket. That approach was dropped, but the live buckets (pds-dev-gh01dc-web-analytics,
  # pds-prod-gh01dc-web-analytics) were never renamed, and S3 bucket renames require
  # delete/recreate + data migration, so this stays fixed regardless of future component renames.
  s3_bucket_name = "${var.s3_bucket_prefix}-web-analytics"
}
