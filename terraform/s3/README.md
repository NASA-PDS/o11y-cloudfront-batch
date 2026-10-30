# S3 Module

Creates the bucket that receives PDS node access logs and publishes its name to SSM.

- **Tier:** Power User ([permission tiers](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#required-aws-permissions)).
- **Apply and verify:** [Phase 3](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-3---batch-s3-and-logstash-ec2) of the deployment runbook.

## Resources

- `module.s3_bucket`: bucket from [pdc-tf-modules](https://github.com/NASA-PDS/pdc-tf-modules) with SSE, versioning, and an SSL-only deny policy. Public-access blocks are left to the account level. Lifecycle:
  - abort incomplete multipart uploads after 7 days
  - move current objects to Intelligent-Tiering immediately
  - expire noncurrent versions after 14 days
- `aws_ssm_parameter.s3_bucket_name`: publishes the name to `/pds/o11y-cloudfront-batch/s3/bucket_name`, read by the `logstash` module.

The bucket is named `<s3_bucket_prefix>-web-analytics`. The suffix is fixed and does not follow the component name, because an S3 bucket rename needs delete/recreate and data migration.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `s3_bucket_prefix` | `string` | - | Prefix for the bucket name only; may include a CI/CD identifier. |
| `aws_region` | `string` | `us-west-2` | AWS region. |
| `partition` | `string` | `aws` | AWS partition. |
| `venue` | `string` | - | Deployment venue (`dev`, `test`, `prod`). |
| `tenant` | `string` | - | Tag: tenant identifier. |
| `component` | `string` | - | Tag: component name. |
| `cicd` | `string` | - | Tag: CI/CD method. |
| `managedby` | `string` | - | Tag: owner contact. |

## Outputs

| Name | Description |
|---|---|
| `s3_bucket_name` | Name of the bucket. |
| `s3_bucket_arn` | ARN of the bucket. |
