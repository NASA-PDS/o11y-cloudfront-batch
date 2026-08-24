# S3 Module

Creates the S3 log bucket for PDS Web Analytics and publishes its name to SSM.

## Resources

- `module.s3_bucket` — S3 bucket via [pds-tf-modules](https://github.com/NASA-PDS/pds-tf-modules) with SSE, public-access blocks disabled (enforced at the account level), and an EC2-role allow + SSL-only deny bucket policy
- `aws_s3_bucket_lifecycle_configuration.lifecycle` — aborts incomplete multipart uploads after 7 days; transitions all objects to Intelligent-Tiering immediately
- `aws_ssm_parameter.s3_bucket_name` — publishes the bucket name to `/pds/o11y-cloudfront-batch/s3/bucket_name` for consumption by the logstash module

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `s3_bucket_prefix` | `string` | — | Prefix for the S3 bucket name (e.g. `pds-dev-gh01dc`). Bucket is named `<prefix>-web-analytics-batch`. |
| `ec2_role_name` | `string` | — | Existing EC2 IAM role name — granted `s3:*` on the bucket. |
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
| `s3_bucket_name` | Name of the S3 bucket created for web analytics logs. |
| `s3_bucket_arn` | ARN of the S3 bucket. |

## Deploy

```bash
cp tfvars/dev.tfvars.example tfvars/dev.tfvars
# edit tfvars/dev.tfvars

task s3:plan   VENUE=dev
task s3:deploy VENUE=dev
```

Shared values (`aws_region`, `tenant`, `ec2_role_name`, etc.) come from `../tfvars/common-<venue>.tfvars`.

> **Expected warning:** `common-<venue>.tfvars` includes `resource_prefix` (used by the logstash and iam modules) but the S3 module does not declare it. Terraform will emit a "Value for undeclared variable" warning for `resource_prefix` on every plan/apply — this is harmless and expected.
