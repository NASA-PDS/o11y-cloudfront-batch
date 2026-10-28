# o11y-cloudfront-batch - Terraform

Reference for the three Terraform modules that deploy the PDS Web Analytics pipeline:

- **`iam`**: the Logstash EC2 role and instance profile, plus the access policy that grants S3 read and OpenSearch write.
- **`s3`**: the log bucket (versioning disabled, SSE, Intelligent-Tiering).
- **`logstash`**: the Logstash EC2 (Oracle Linux 9, Logstash installed from the RPM and run by systemd).

The deployment order, permission tiers, credentials setup, and the cross-repo SSM contract are owned by the o11y-platform [deployment runbook](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md). This page covers only what is specific to these modules. OpenSearch is managed in [o11y-platform](https://github.com/NASA-PDS/o11y-platform).

```text
terraform/
  ├── iam/         # EC2 role + profile, access policy
  ├── s3/          # S3 log bucket
  └── logstash/    # Logstash EC2, security group, DNS record
```

| Module | Runbook phase | Tier | State key | Publishes to SSM |
|---|---|---|---|---|
| `iam` | [Phase 2a](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-2---iam) | Admin | `o11y-cloudfront-batch/iam.tfstate` | `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-role-arn`, `.../instance-profile-name` |
| `s3` | [Phase 3](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-3---batch-s3-and-logstash-ec2) | Power User | `o11y-cloudfront-batch/s3.tfstate` | `/pds/o11y-cloudfront-batch/s3/bucket_name` |
| `logstash` | [Phase 3](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-3---batch-s3-and-logstash-ec2) | Platform Engineer | `o11y-cloudfront-batch/logstash.tfstate` | `/pds/o11y-cloudfront-batch/ec2/logstash_security_group_id`, `.../logstash_instance_id`, `.../logstash_fqdn` |

Each module's venue inputs are in `cds-infra-deploy` at `venues/<venue>/o11y-cloudfront-batch/<module>/terragrunt.hcl`. Apply each module in its runbook phase from the table above. The phase's Setup block assigns `VENUE`, `REGION`, the credentials for its permission tier, and the `cds-infra-deploy` directory, and its steps give the exact `task` commands.

Reaching the Logstash instance also needs SSH access to the CDS bastion host (your key enrolled for bastion access). System administrators, and developers in dev, who use SSM Session Manager need the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html).

## iam

Creates `<venue>-o11y-cloudfront-batch-ec2-role`, its instance profile, and the S3 and OpenSearch access policy attached to the role. `roles.tf` and `policies.tf` share one state.

- **Needs:** o11y-platform `opensearch` applied first (Phase 1). It reads `opensearch_arn` from SSM.
- **Apply and verify:** [Phase 2a](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-2---iam).
- **Update:** edit the policy documents in `iam/policies.tf` and re-apply. The policy updates in place. If the role is ever recreated, its ARN changes in SSM; re-run the runbook [Phase 5](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-5---grant-consumers-opensearch-access) so the OpenSearch access policy follows.

## s3

Creates the bucket that receives PDS node access logs.

- **Needs:** nothing. It can run while OpenSearch bootstraps.
- **Apply and verify:** [Phase 3](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-3---batch-s3-and-logstash-ec2).
- **Update:** lifecycle, encryption, and versioning changes take effect on re-apply.

## logstash

Creates the Logstash EC2, its security group, and a Route53 A record. The security group ID is published to SSM so o11y-platform can allow HTTPS from it. Module inputs, SSM dependencies, and outputs are in [`logstash/README.md`](logstash/README.md).

- **Needs:** `iam` (instance profile name), `s3` (bucket name), and `opensearch` (endpoint).
- **Apply and verify:** [Phase 3](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-3---batch-s3-and-logstash-ec2).
- **After apply:** the instance runs the userdata bootstrap (Logstash RPM, plugins, `pdsops` account, systemd unit) but has no pipeline config and is not started. Deploy it with [First-boot setup](logstash/README.md#first-boot-setup), then [Verify the deployment](logstash/README.md#verify-the-deployment). This is runbook [Phase 7](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-7---deploy-logstash-and-verify).
- **Access to OpenSearch:** Logstash gets 403s or timeouts until the runbook [Phase 5](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-5---grant-consumers-opensearch-access) applies. `apply` here succeeds either way.
- **CloudFront logs:** reading CloudFront logs from `pds-logs-<venue>` needs the `pdc-cds-infra` change in runbook [Phase 6](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-6---cloudfront-pds-main). It is required only when `S3_CF_BUCKET_NAME` is set.
- **Existing EC2:** set `manage_ec2_instance = false` to publish an externally managed instance instead. See [Using an existing EC2](logstash/README.md#using-an-existing-ec2-manage_ec2_instance--false).

### Update

| Change | Effect | Then |
|---|---|---|
| `logstash_version` (any userdata change) | Replaces the instance | Re-run [First-boot setup](logstash/README.md#first-boot-setup). Details: [Replacing the instance](logstash/README.md#replacing-the-instance). |
| `logstash_instance_type` | In place; the instance stops and restarts briefly. A different CPU architecture replaces it. | [Verify the deployment](logstash/README.md#verify-the-deployment) |
| `logstash_root_volume_size` | In place when growing the volume | None |
| `ami_id`, subnet | Replaces the instance | As for `logstash_version` |

The in-place and replacement rules come from the shared `ec2` module in [pdc-tf-modules](https://github.com/NASA-PDS/pdc-tf-modules/blob/main/terraform/modules/ec2/README.md#changing-an-existing-instance).

Pipeline config and `regexes.yaml` changes need no Terraform: see [Update pipeline configuration](../docs/operations.md#update-pipeline-configuration).

## Teardown

Destroy in reverse order from a `cds-infra-deploy` checkout. Roles must outlive the resources that use them. Use the same permission tier as the phase that created each module.

```bash
VENUE="dev"                                       # dev | test | prod
REGION="us-west-2"
CDS_INFRA_DEPLOY_DIR="<path-to-cds-infra-deploy-checkout>"
PROFILE_ADMIN="<admin-sso-profile>"
PROFILE_PLATFORM_ENGINEER="<platform-engineer-sso-profile>"
PROFILE_POWER_USER="<power-user-sso-profile>"

export AWS_DEFAULT_REGION="${REGION}"
cd "${CDS_INFRA_DEPLOY_DIR}"

eval $(aws configure export-credentials --profile "${PROFILE_PLATFORM_ENGINEER}" --format env)
unset AWS_PROFILE
task destroy VENUE="${VENUE}" COMPONENT=o11y-cloudfront-batch/logstash

eval $(aws configure export-credentials --profile "${PROFILE_POWER_USER}" --format env)
unset AWS_PROFILE
task destroy VENUE="${VENUE}" COMPONENT=o11y-cloudfront-batch/s3

eval $(aws configure export-credentials --profile "${PROFILE_ADMIN}" --format env)
unset AWS_PROFILE
task destroy VENUE="${VENUE}" COMPONENT=o11y-cloudfront-batch/iam
```

The full-stack teardown order is in the runbook [Teardown](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#teardown).

## Architecture notes

- **State** is stored in S3 in the venue's infra bucket, under the keys in the table above. The OpenSearch state (`o11y-platform/opensearch.tfstate`) is managed in o11y-platform.
- **Variable naming:** `s3_bucket_prefix` is for the S3 bucket name only and may include a CI/CD identifier. `resource_prefix` is for all other resources and should not.
- **VPC and security group values** are Terragrunt inputs in `cds-infra-deploy`. TODO: source them from SSM under `/pds/cds-infra/vpc/` once published.
