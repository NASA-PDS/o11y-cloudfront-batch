# IAM Policies Module

Creates the o11y-cloudfront-batch EC2 IAM policy and attaches it to the shared EC2 instance role.

> **Requires `iam:CreatePolicy` and `iam:AttachRolePolicy`** — must be applied by a system administrator.

## Resources

- `module.o11y_cloudfront_batch` — IAM policy granting the Logstash EC2 role read access to S3 and write access to OpenSearch; attaches the policy to `ec2_role_name`

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `logs_s3_bucket_name` | `string` | — | Full name of the S3 logs bucket (used in policy resource ARN). |
| `ec2_role_name` | `string` | — | Existing EC2 IAM role to attach the policy to. |
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
| `policy_arn` | ARN of the o11y-cloudfront-batch EC2 access policy. |
| `policy_name` | Name of the o11y-cloudfront-batch EC2 access policy. |

## Deploy

All variables are managed as Terragrunt inputs in `cds-infra-deploy`. Run from that repo:

```bash
task plan  VENUE=dev COMPONENT=o11y-cloudfront-batch/iam/policies
task apply VENUE=dev COMPONENT=o11y-cloudfront-batch/iam/policies
```
