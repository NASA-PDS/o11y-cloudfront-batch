# IAM Module

Creates the EC2 instance role, instance profile, and S3/OpenSearch access policy for the o11y-cloudfront-batch component in a single Terraform root module (one state, one apply).

> **Requires `iam:CreateRole`, `iam:CreateInstanceProfile`, `iam:CreatePolicy`, `iam:AttachRolePolicy`** - must be applied by a system administrator.

## Layout

| File | Contents |
|---|---|
| `roles.tf` | EC2 instance role and instance profile (calls `iam/roles/ec2` from [pdc-tf-modules](https://github.com/NASA-PDS/pdc-tf-modules)) |
| `policies.tf` | S3 + OpenSearch + SMTP-config access policy, and its attachment to the EC2 role |
| `data.tf` | Caller identity and the OpenSearch domain ARN (read from SSM) |
| `locals.tf` | Common tags |

## Resources

The `iam/roles/ec2` module creates:

- `aws_iam_role` - EC2 instance role named `<venue>-o11y-cloudfront-batch-ec2-role`, trusted by `ec2.amazonaws.com`
- `aws_iam_instance_profile` - instance profile with the same name
- `aws_iam_role_policy_attachment` - attaches `AmazonSSMManagedInstanceCore` and `CloudWatchAgentServerPolicy`

`policies.tf` creates:

- `aws_iam_policy` - grants read access to the logs S3 bucket, `es:ESHttp*` on the OpenSearch domain, and read access to the SMTP config SSM path
- `aws_iam_role_policy_attachment` - attaches that policy to the EC2 role

## SSM dependencies (read at plan time)

| Parameter | Published by |
|---|---|
| `/pds/o11y-platform/opensearch/opensearch_arn` | o11y-platform `opensearch` module |

Deploy o11y-platform's `opensearch` module before this module.

## SSM outputs (published by this module)

| Parameter | Value |
|---|---|
| `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-role-arn` | IAM role ARN |
| `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-profile-name` | Instance profile name |

`logstash` reads the instance profile name; pdc-cds-infra and o11y-platform read the role ARN.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `venue` | `string` | - | Deployment venue (`dev`, `test`, `prod`). Used in role naming and tags. |
| `component` | `string` | `o11y-cloudfront-batch` | Component name. Used in role naming and SSM paths. |
| `logs_s3_bucket_name` | `string` | - | Full name of the S3 logs bucket (used in policy resource ARN). |
| `ec2users_dynamodb_table_arn` | `string` | - | ARN of the DynamoDB ec2users table; grants Get*/Query access on the EC2 role. |
| `smtp_config_ssm_path` | `string` | `/pds/dum/smtp/` | SSM path prefix holding SMTP credentials for the daily egress report. |
| `aws_region` | `string` | `us-west-2` | AWS region. |
| `partition` | `string` | `aws` | AWS partition. |
| `tenant` | `string` | `en` | Tag: tenant identifier. |
| `cicd` | `string` | `iac` | Tag: CI/CD method. |
| `managedby` | `string` | - | Tag: owner contact. |

## Outputs

| Name | Description |
|---|---|
| `ec2_instance_profile_name` | Name of the EC2 instance profile. |
| `ec2_instance_role_arn` | ARN of the EC2 instance IAM role. |
| `policy_arn` | ARN of the o11y-cloudfront-batch EC2 access policy. |
| `policy_name` | Name of the o11y-cloudfront-batch EC2 access policy. |

## Deploy

All variables are managed as Terragrunt inputs in `cds-infra-deploy`. Run from that repo:

```bash
task plan  VENUE=dev COMPONENT=o11y-cloudfront-batch/iam
task apply VENUE=dev COMPONENT=o11y-cloudfront-batch/iam
```

Deploy this before `logstash`.
