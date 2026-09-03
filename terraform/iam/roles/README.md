# IAM Roles Module

Creates the EC2 instance role and instance profile for the o11y-cloudfront-batch component.

> **Requires `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:CreateInstanceProfile`** — must be applied by a system administrator.

## Resources

Calls the `iam/roles/ec2` module from [pds-tf-modules](https://github.com/NASA-PDS/pds-tf-modules), which creates:

- `aws_iam_role` — EC2 instance role named `<venue>-o11y-cloudfront-batch-ec2-role`, trusted by `ec2.amazonaws.com`
- `aws_iam_instance_profile` — instance profile with the same name
- `aws_iam_role_policy_attachment` — attaches `AmazonSSMManagedInstanceCore` and `CloudWatchAgentServerPolicy`

### SSM outputs (published by this module)

| Parameter | Value |
|---|---|
| `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-role-arn` | IAM role ARN |
| `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-profile-name` | Instance profile name |

These are consumed automatically by `iam/policies` (role attachment) and `logstash` (instance profile assignment).

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `venue` | `string` | — | Deployment venue (e.g. `pds-cds-dev`). Used in role naming. |
| `component` | `string` | `o11y-cloudfront-batch` | Component name. Used in role naming and SSM paths. |
| `tenant` | `string` | `en` | Tag: tenant identifier. |
| `cicd` | `string` | `iac` | Tag: CI/CD method. |
| `managedby` | `string` | — | Tag: owner contact. |
| `aws_region` | `string` | `us-west-2` | AWS region. |

## Outputs

| Name | Description |
|---|---|
| `ec2_instance_profile_name` | Name of the EC2 instance profile. |
| `ec2_instance_role_arn` | ARN of the EC2 instance IAM role. |

## Deploy

All variables are managed as Terragrunt inputs in `cds-infra-deploy`. Run from that repo:

```bash
task plan  VENUE=dev COMPONENT=o11y-cloudfront-batch/iam/roles
task apply VENUE=dev COMPONENT=o11y-cloudfront-batch/iam/roles
```

Deploy this before `iam/policies` and `logstash` — both depend on the SSM parameters this module publishes.
