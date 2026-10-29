# IAM Module

Creates the Logstash EC2 role, its instance profile, and the S3 / OpenSearch / SMTP-config access policy in one root module (one state).

- **Tier:** Admin (`iam:CreateRole`, `iam:CreateInstanceProfile`, `iam:CreatePolicy`, `iam:AttachRolePolicy`). See [permission tiers](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#required-aws-permissions).
- **Apply and verify:** [Phase 2a](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-2---iam) of the deployment runbook. Apply after the o11y-platform `opensearch` module and before `logstash`.

## Layout

| File | Contents |
|---|---|
| `roles.tf` | EC2 role and instance profile (`iam/roles/ec2` from [pdc-tf-modules](https://github.com/NASA-PDS/pdc-tf-modules)) |
| `policies.tf` | Access policy and its attachment to the role |
| `data.tf` | OpenSearch domain ARN (SSM) |
| `locals.tf` | Common tags |

## Resources

The `iam/roles/ec2` module creates:

- `aws_iam_role` `<venue>-o11y-cloudfront-batch-ec2-role`, trusted by `ec2.amazonaws.com`, and an instance profile of the same name
- attachments for `AmazonSSMManagedInstanceCore` and `CloudWatchAgentServerPolicy`
- inline policy `ec2users-dynamodb` (`Get*`, `Query`, `Scan` on the `ec2users` table), which the AMI uses to look up SSH keys

`policies.tf` creates one policy, attached to the role, that grants:

| Access | Resource |
|---|---|
| Read (`s3:List*`, `s3:GetObject*`, `s3:GetBucket*`) | the log bucket from the `s3` module only |
| `es:ESHttp*`, `es:DescribeDomain`, `es:DescribeElasticsearchDomain` | the OpenSearch domain |
| `ssm:GetParameter`, `ssm:GetParametersByPath` | the `smtp_config_ssm_path` prefix |

Read access to the CloudFront logs bucket is not granted here. It comes from the `AllowO11yBatchLogstashRead` statement on that bucket's policy, managed by the pdc-cds-infra [`pds-main` module](https://github.com/NASA-PDS/pdc-cds-infra/blob/main/terraform/cloudfront/pds-main/README.md#o11y-integration).

## SSM parameters

| Parameter | Direction | Counterpart |
|---|---|---|
| `/pds/o11y-platform/opensearch/opensearch_arn` | read at plan time | o11y-platform `opensearch` |
| `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-role-arn` | published | o11y-platform `opensearch`, pdc-cds-infra `pds-main` |
| `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-profile-name` | published | `logstash` module |

Cross-repo parameters are listed in the [SSM contract](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#ssm-contract). The `iam/roles/ec2` module publishes both outputs; do not add `aws_ssm_parameter` resources here.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `venue` | `string` | - | Deployment venue (`dev`, `test`, `prod`). Used in role naming and tags. |
| `logs_s3_bucket_name` | `string` | - | Name of the `s3` module's bucket (`<s3_bucket_prefix>-web-analytics`), used in the policy ARN. |
| `ec2users_dynamodb_table_arn` | `string` | - | ARN of the `ec2users` DynamoDB table. |
| `smtp_config_ssm_path` | `string` | `/pds/dum/smtp/` | SSM path prefix holding SMTP credentials for the daily egress report. |
| `component` | `string` | `o11y-cloudfront-batch` | Component name. Used in role naming and SSM paths. |
| `aws_region` | `string` | `us-west-2` | AWS region. |
| `partition` | `string` | `aws` | AWS partition. |
| `tenant` | `string` | `en` | Tag: tenant identifier. |
| `cicd` | `string` | `iac` | Tag: CI/CD method. |
| `managedby` | `string` | - | Tag: owner contact. |

## Outputs

| Name | Description |
|---|---|
| `ec2_instance_profile_name` | Name of the EC2 instance profile. |
| `ec2_instance_role_arn` | ARN of the EC2 instance role. |
| `policy_arn` | ARN of the access policy. |
| `policy_name` | Name of the access policy. |
