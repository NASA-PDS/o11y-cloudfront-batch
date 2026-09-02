# S3 Module

Creates the S3 log bucket for o11y-cloudfront-batch and publishes its name to SSM.

## Resources

- `module.s3_bucket` — S3 bucket via [pds-tf-modules](https://github.com/NASA-PDS/pds-tf-modules) with SSE, public-access blocks disabled (enforced at the account level), and an SSL-only deny bucket policy
- `aws_s3_bucket_lifecycle_configuration.lifecycle` — aborts incomplete multipart uploads after 7 days; transitions all objects to Intelligent-Tiering immediately
- `aws_ssm_parameter.s3_bucket_name` — publishes the bucket name to `/pds/o11y-cloudfront-batch/s3/bucket_name` for consumption by the logstash module

The bucket name suffix (`-web-analytics`, not `-web-analytics-batch` or `-o11y-cloudfront-batch`)
is a legacy holdover from an early design that deployed this bucket via GitHub CD/OIDC. That
approach was dropped, but the live buckets (`pds-dev-gh01dc-web-analytics`,
`pds-prod-gh01dc-web-analytics`) were never renamed — S3 bucket renames require delete/recreate
plus data migration — so `local.s3_bucket_name` stays fixed regardless of future component renames.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `s3_bucket_prefix` | `string` | — | Prefix for the S3 bucket name (e.g. `pds-dev-gh01dc`). Bucket is named `<prefix>-web-analytics`. |
| `aws_region` | `string` | `us-west-2` | AWS region. |
| `partition` | `string` | `aws` | AWS partition. |
| `venue` | `string` | — | Deployment venue (`dev`, `test`, `prod`). |
| `tenant` | `string` | — | Tag: tenant identifier. |
| `component` | `string` | — | Tag: component name. |
| `cicd` | `string` | — | Tag: CI/CD method. |
| `managedby` | `string` | — | Tag: owner contact. |

## Outputs

| Name | Description |
|---|---|
| `s3_bucket_name` | Name of the S3 bucket created for o11y-cloudfront-batch logs. |
| `s3_bucket_arn` | ARN of the S3 bucket. |

## Deploy

All variables are managed as Terragrunt inputs in `cds-infra-deploy`. Run from that repo:

```bash
task plan  VENUE=dev COMPONENT=o11y-cloudfront-batch/s3
task apply VENUE=dev COMPONENT=o11y-cloudfront-batch/s3
```
