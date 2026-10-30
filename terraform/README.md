# o11y-cloudfront-batch - Terraform

Three modules deploy the PDS Web Analytics pipeline:

- **`iam`**: the Logstash EC2 role and instance profile, plus the policy granting S3 read, OpenSearch write, and SMTP-config read.
- **`s3`**: the log bucket (versioned, SSE, Intelligent-Tiering).
- **`logstash`**: the Logstash EC2 (Oracle Linux 9, Logstash from the RPM, run by systemd).

The deployment order, permission tiers, credentials setup, and cross-repo SSM contract are owned by the o11y-platform [deployment runbook](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md). This page covers only what is specific to these modules. OpenSearch is managed in [o11y-platform](https://github.com/NASA-PDS/o11y-platform).

```text
terraform/
  ├── iam/         # EC2 role + profile, access policy
  ├── s3/          # S3 log bucket
  ├── logstash/    # Logstash EC2, security group, DNS record
  └── templates/   # Logstash userdata
```

| Module | Tier | Runbook phase | State key |
|---|---|---|---|
| `iam` | Admin | [Phase 2a](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-2---iam) | `o11y-cloudfront-batch/iam.tfstate` |
| `s3` | Power User | [Phase 3](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-3---batch-s3-and-logstash-ec2) | `o11y-cloudfront-batch/s3.tfstate` |
| `logstash` | Platform Engineer | [Phase 3](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-3---batch-s3-and-logstash-ec2) | `o11y-cloudfront-batch/logstash.tfstate` |

Each module's venue inputs are in `cds-infra-deploy` at `venues/<venue>/o11y-cloudfront-batch/<module>/terragrunt.hcl`. Apply each module in its runbook phase; the phase's Setup block assigns the variables and credentials for its tier, and its steps give the `task` commands. Reaching the instance afterwards is covered in the [Access model](logstash/README.md#access-model).

## iam

Inputs, resources, and outputs: [`iam/README.md`](iam/README.md).

- **Update:** edit the policy documents in `iam/policies.tf` and re-apply. The policy updates in place.

## s3

Inputs, resources, and outputs: [`s3/README.md`](s3/README.md).

- **Update:** lifecycle, encryption, and versioning changes take effect on re-apply.

## logstash

Inputs, SSM parameters, and outputs: [`logstash/README.md`](logstash/README.md).

- **After apply:** the instance has bootstrapped Logstash but has no pipeline config and is not started. Deploy it with [First-boot setup](logstash/README.md#first-boot-setup), then [Verify the deployment](logstash/README.md#verify-the-deployment).
- **Existing EC2:** `manage_ec2_instance = false` publishes an externally managed instance instead. See [Using an existing EC2](logstash/README.md#using-an-existing-ec2-manage_ec2_instance--false).

### Update

| Change | Effect | Then |
|---|---|---|
| `logstash_version` (any userdata change) | Replaces the instance | Re-run [First-boot setup](logstash/README.md#first-boot-setup). Details: [Replacing the instance](logstash/README.md#replacing-the-instance). |
| `logstash_instance_type` | In place; the instance stops and restarts briefly. A different CPU architecture replaces it. | [Verify the deployment](logstash/README.md#verify-the-deployment) |
| `logstash_root_volume_size` | In place when growing the volume | None |
| `ami_id`, subnet | Replaces the instance | As for `logstash_version` |

The in-place and replacement rules come from the shared `ec2` module in [pdc-tf-modules](https://github.com/NASA-PDS/pdc-tf-modules/blob/main/terraform/modules/ec2/README.md#changing-an-existing-instance).

Pipeline config and `regexes.yaml` changes need no Terraform: see [Update pipeline configuration](../docs/operations.md#update-pipeline-configuration).

## Local iteration

For local runs only. Operational deploys use Terragrunt from `cds-infra-deploy`. The Task wrapper reads this repo's gitignored tfvars; `task --list` shows all tasks.

**Setup**

```bash
VENUE="dev"                                       # dev | test | prod
PROFILE_NAME="<sso-profile>"
TFSTATE_BUCKET="<terraform-state-bucket>"
O11Y_BATCH_DIR="<path-to-this-checkout>"

eval $(aws configure export-credentials --profile "${PROFILE_NAME}" --format env)
unset AWS_PROFILE
export TFSTATE_BUCKET
cd "${O11Y_BATCH_DIR}/terraform"
```

**Steps**

1. Copy the example tfvars, then edit them. Examples exist for `dev` and `prod` only, and `logstash` has none: write `logstash/tfvars/${VENUE}.tfvars` from the inputs in [`logstash/README.md`](logstash/README.md).

   ```bash
   cp -p tfvars/common.tfvars.example "tfvars/common-${VENUE}.tfvars"
   for MODULE in iam s3; do
     cp -p "${MODULE}/tfvars/${VENUE}.tfvars.example" "${MODULE}/tfvars/${VENUE}.tfvars"
   done
   ```

2. Plan a module:

   ```bash
   task s3:plan VENUE="${VENUE}"
   ```

## Teardown

Destroy in reverse order, with the tier that created each module: `logstash`, then `s3`, then `iam`. Roles must outlive the resources that use them. The full-stack order, including the OpenSearch access flags that must be turned off first, and the credentials commands are in the runbook [Teardown](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#teardown).

## Notes

- **State** is in the venue's infra bucket under the keys above. The OpenSearch state (`o11y-platform/opensearch.tfstate`) belongs to o11y-platform.
- **Variable naming:** `s3_bucket_prefix` is for the S3 bucket name only and may include a CI/CD identifier.
- **VPC and security group IDs** are Terragrunt inputs. TODO: source them from SSM under `/pds/cds-infra/vpc/` once published.
