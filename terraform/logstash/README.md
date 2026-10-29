# Logstash Module

Deploys the Logstash EC2 (PDS Cloud Oracle Linux 9 AMI, Logstash from the RPM) that reads logs from S3 and writes to OpenSearch.

- **Tier:** Platform Engineer (`iam:PassRole`). See [permission tiers](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#required-aws-permissions).
- **Apply and verify:** [Phase 3](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-3---batch-s3-and-logstash-ec2). Deploy `iam`, `s3`, and the o11y-platform `opensearch` module first; the plan fails if their SSM parameters are missing.
- **Venue inputs:** `cds-infra-deploy`, `venues/<venue>/o11y-cloudfront-batch/logstash/terragrunt.hcl`.

By default the module creates the EC2 in every venue. `manage_ec2_instance = false` instead publishes an externally managed instance; see [Using an existing EC2](#using-an-existing-ec2-manage_ec2_instance--false).

## Resources

Created only when `manage_ec2_instance = true`, except the instance ID parameter.

- `module.ec2` ([pdc-tf-modules](https://github.com/NASA-PDS/pdc-tf-modules) `ec2`): the instance, tagged `Patch = "true"`, in a private subnet, with the bastion target security group attached. Userdata installs Logstash and sets up `pdsops` at first boot. See [Replacing the instance](#replacing-the-instance).
- `aws_security_group.logstash`: no inbound rules; all outbound allowed (SSM, DynamoDB SSH-key lookup, package repos, S3, OpenSearch). SSH ingress comes from the bastion target security group.
- `aws_route53_record.logstash`: A record `<Name tag>.<zone>` to the private IP, in the hosted zone named by SSM `/pds/hosted-zone/name` (the bastion's zone).
- SSM parameters, below.

## SSM parameters

| Parameter | Direction | Counterpart |
|---|---|---|
| `/pds/o11y-cloudfront-batch/s3/bucket_name` | read | `s3` module |
| `/pds/o11y-platform/opensearch/opensearch_endpoint` | read | o11y-platform `opensearch` |
| `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-profile-name` | read | `iam` module |
| `/pds/hosted-zone/name` | read | account baseline |
| `bastion_target_sg_ssm_path` (input) | read | pdc-cds-infra [bastion-core](https://github.com/NASA-PDS/pdc-cds-infra/blob/main/terraform/bastion-core/README.md#ssm-parameters-published) |
| `/pds/o11y-cloudfront-batch/ec2/logstash_instance_id` | published | SSM session target |
| `/pds/o11y-cloudfront-batch/ec2/logstash_fqdn` | published | SSH target via the bastion |
| `/pds/o11y-cloudfront-batch/ec2/logstash_security_group_id` | published | o11y-platform `opensearch` (HTTPS ingress) |

Cross-repo parameters are in the [SSM contract](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#ssm-contract).

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `manage_ec2_instance` | `bool` | `true` | Create the EC2. `false` publishes `existing_instance_id` only. |
| `existing_instance_id` | `string` | `""` | Instance to publish when `manage_ec2_instance = false`. Required in that mode. |
| `ami_id` | `string` | `""` | PDS Cloud AMI for the venue. Required when `manage_ec2_instance = true`. |
| `vpc_id` | `string` | `""` | VPC for the security group and private-subnet lookup. Required when `manage_ec2_instance = true`. |
| `bastion_target_sg_ssm_path` | `string` | `""` | SSM path of the bastion target security group. Required when `manage_ec2_instance = true`. |
| `logstash_instance_type` | `string` | `t3.large` | Instance type. |
| `logstash_root_volume_size` | `number` | `50` | Root volume in GB; at least the AMI snapshot size (32). |
| `logstash_version` | `string` | `8.18.0` | Logstash RPM version, baked into userdata. |
| `venue` | `string` | - | Deployment venue (`dev`, `test`, `prod`). |
| `tenant`, `component`, `cicd`, `managedby` | `string` | - | Tags. |
| `aws_region` | `string` | `us-west-2` | AWS region. |

## Outputs

| Name | Description |
|---|---|
| `logstash_instance_id` | Instance ID. |
| `logstash_fqdn` | Route53 FQDN; null when `manage_ec2_instance = false`. |

## Access model

Everyone connects through the CDS bastion: the EC2 has only a private IP. SSH to the bastion with your NASA ID, then to the EC2 with the same ID. The AMI checks it against the user-key store (DynamoDB) on every login, so your key must be enrolled; enrollment and the bastion itself are covered in the pdc-cds-infra [bastion-core README](https://github.com/NASA-PDS/pdc-cds-infra/blob/main/terraform/bastion-core/README.md#connecting-to-the-bastion). Then switch to the shared `pdsops` account, which owns Logstash.

```bash
# On your workstation: look up the hostnames.
NASA_ID="<nasa-id>"
ZONE=$(aws ssm get-parameter --name /pds/hosted-zone/name \
  --query Parameter.Value --output text)
FQDN=$(aws ssm get-parameter \
  --name /pds/o11y-cloudfront-batch/ec2/logstash_fqdn \
  --query Parameter.Value --output text)
echo "Target: ${FQDN}"
ssh ${NASA_ID}@pds-cds-bastion-core.${ZONE}

# On the bastion: set FQDN to the Target value printed above.
FQDN="<target-fqdn>"
ssh ${USER}@${FQDN}
sudo -iu pdsops
```

`logstash_fqdn` is published only when this module creates the EC2; otherwise use the instance's hostname.

### Local shortcut

`ProxyJump` in `~/.ssh/config` reaches the EC2 through the bastion in one command. Your workstation key authenticates both hops, so no key or agent forwarding is needed on the bastion, and `scp`, `rsync`, and port forwards work. `~/.ssh/config` is a static file, so this appends the entries with the values substituted when it is written. Set `FQDN` to the target looked up above:

```bash
NASA_ID="<nasa-id>"
BASTION="pds-cds-bastion-core.${ZONE}"
FQDN="<target-fqdn>"

cat >> ~/.ssh/config << EOF

Host cds-bastion
    HostName ${BASTION}
    User ${NASA_ID}

Host cds-logstash
    HostName ${FQDN}
    User ${NASA_ID}
    ProxyJump cds-bastion
EOF
```

`ProxyJump` hides the host-key prompts, so the first connection to each host hangs. Log in once the manual way ([above](#access-model)) to accept both host keys; after that `ssh cds-logstash` works. Then add an alias that lands you as `pdsops`, and a Logstash API tunnel if you want one:

```bash
cat >> ~/.bashrc << 'EOF'

alias ssh-logstash='ssh -t cds-logstash sudo -iu pdsops'
EOF
source ~/.bashrc

ssh -N -L 9600:localhost:9600 cds-logstash   # then browse http://localhost:9600
```

`-t` allocates the terminal that `sudo -iu` needs. See also the bastion-core [SSH config](https://github.com/NASA-PDS/pdc-cds-infra/blob/main/terraform/bastion-core/README.md#ssh-config-recommended).

**SSM Session Manager** is granted by your IAM role, not this module (system administrators; developers in dev). See the bastion-core [SSM access model](https://github.com/NASA-PDS/pdc-cds-infra/blob/main/terraform/bastion-core/README.md#ssm-access-model). Sessions land as `ssm-user`:

```bash
INSTANCE_ID=$(aws ssm get-parameter \
  --name /pds/o11y-cloudfront-batch/ec2/logstash_instance_id \
  --query Parameter.Value --output text)
aws ssm start-session --target ${INSTANCE_ID}
sudo -iu pdsops
```

Deploying, restarting, and monitoring Logstash need no sudo as `pdsops`. Root is needed only for installation: userdata does it on a Terraform-created EC2, and a system administrator runs `logstash-bootstrap.sh` on an externally managed one (also for its Logstash upgrades).

## Replacing the instance

A userdata change (for example `logstash_version`) replaces the instance (`user_data_replace_on_change = true`); other changes apply in place. See [Update](../README.md#update) for the full table.

A replacement:

- gets a new instance ID, IP, and host keys; the Route53 record and SSM parameters follow
- loses the S3 `sincedb`, so logs are re-read. `document_id` is a fingerprint, so documents are overwritten, not duplicated. For a large backlog, deploy with `ENABLED_NODES` ([First-boot setup](#first-boot-setup))
- deletes the old root volume
- needs the [First-boot setup](#first-boot-setup) operator steps re-run

## Using an existing EC2 (`manage_ec2_instance = false`)

Set `manage_ec2_instance = false` and `existing_instance_id` in the venue inputs. `task apply` then only publishes `logstash_instance_id`; it never changes the EC2, and `logstash_fqdn` and `logstash_security_group_id` are not published.

Prerequisites on the instance, outside this module's control:

- Oracle Linux 9 (PDS Cloud AMI), or another RPM distro where `dnf`, `systemd --user`, and `loginctl enable-linger` work
- the bastion target security group attached, operator SSH keys enrolled, and a hostname reachable from the bastion
- an instance profile with the [`iam`](../iam) module's policy, plus `AmazonSSMManagedInstanceCore`
- a system administrator to run `scripts/logstash-bootstrap.sh` as root once

## First-boot setup

**Terraform-created instances:** userdata runs the full bootstrap (packages, Logstash and plugins, `pdsops` setup, systemd unit). Allow 5-10 minutes after `task apply`; progress is in `/var/log/logstash-bootstrap.log`.

**Existing EC2s:** a system administrator runs `scripts/logstash-bootstrap.sh` as root once (see the script header).

**Operator steps (no sudo, both cases):**

1. Connect and switch to `pdsops` ([Access model](#access-model)).
2. Set the deploy variables. `S3_CF_BUCKET_NAME` is required on a first deploy: unset, it breaks the EN pipeline at runtime. It is the CloudFront logs bucket that pdc-cds-infra `pds-main` publishes to SSM (after [Phase 6](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-6---cloudfront-pds-main)). Look it up with your workstation credentials, or use `""` only if EN is not enabled:

   ```bash
   aws ssm get-parameter --name /pds/pdc-cds-infra/s3/pds-logs-bucket-name \
     --query Parameter.Value --output text
   ```

   Then, on the EC2:

   ```bash
   S3_CF_BUCKET_NAME="<cf-logs-bucket-or-empty-string>"
   REPO_BRANCH="main"

   # Optional: node IDs to enable (example: "en"); empty enables all.
   ENABLED_NODES=""

   # Optional: egress report recipients; empty skips the cron job.
   EGRESS_REPORT_RECIPIENTS=""

   export S3_CF_BUCKET_NAME REPO_BRANCH ENABLED_NODES EGRESS_REPORT_RECIPIENTS
   ```

   `ENABLED_NODES` and the egress report are described in the [Operations Runbook](../../docs/operations.md#deploying-with-a-subset-of-nodes).
3. Deploy the config and start the service. Re-running this is also how you apply a config change.

   ```bash
   bash <(curl -fsSL "https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/${REPO_BRANCH}/scripts/logstash-deploy.sh")
   ```
4. Confirm the service is running (expected: `active`), then continue with [Verify the deployment](#verify-the-deployment).

   ```bash
   systemctl --user is-active logstash
   ```

Later operations (restart, config updates, re-ingest) are in the [Operations Runbook](../../docs/operations.md#quick-reference-from-the-ec2-as-the-pdsops-user).

## Verify the deployment

Run every step on the EC2 as `pdsops`.

### 1. Bootstrap complete

```bash
rpm -q logstash
grep "Bootstrap complete" /var/log/logstash-bootstrap.log
loginctl show-user pdsops --property=Linger
```

| Command | Expected result |
|---|---|
| `rpm -q logstash` | `logstash-<version>` |
| `grep "Bootstrap complete" ...` | one matching line |
| `loginctl show-user pdsops --property=Linger` | `Linger=yes` |

On failure, read `/var/log/logstash-bootstrap.log` and `/var/log/cloud-init-output.log`. The bootstrap log exists on Terraform-created instances only; on an existing EC2, `logstash-bootstrap.sh` prints `=== Bootstrap complete ===` to the console.

### 2. Config deployed and service running

Run after `logstash-deploy.sh`, which refuses to run when Logstash is not installed.

```bash
systemctl --user is-active logstash
ls /etc/logstash/pipelines/
```

Expected: `active`, and one `.conf` file per enabled node.

### 3. Smoke test

Prerequisite: the o11y-platform `opensearch` module has been re-applied with `o11y_cloudfront_batch_enabled = true` ([Phase 5](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#phase-5---grant-consumers-opensearch-access)). Until then the OpenSearch checks time out or return 403.

```bash
bash /opt/o11y-cloudfront-batch/scripts/smoke-test.sh
```

Expected: exit code 0 and `Smoke test passed.`

| Section | Check | Expected |
|---|---|---|
| Logstash install | RPM installed; `Linger=yes`; at least one file in `/etc/logstash/pipelines` | `PASS` |
| AWS connectivity | Log bucket accessible | `PASS` |
| | CloudFront logs bucket: lists each EN input prefix | `PASS`; `SKIP` if `S3_CF_BUCKET_NAME` is empty or EN is not deployed |
| | OpenSearch reachable (an unsigned request returns 403) | `PASS` |
| | OpenSearch auth (SigV4) | `PASS`, with the cluster `status` and node count |
| Service | Service active; start time and restart count | `PASS` |
| | Monitoring API on `localhost:9600` responds | `PASS` |
| | Every pipeline in `/etc/logstash/pipelines.yml` is running, with no reload failures | `PASS` |
| | No `ERROR`/`FATAL` in the log since the service started | `PASS` |

The cluster `status` is reported, not enforced: `green`, or `yellow` on a single-node cluster, is healthy. The API and pipeline checks retry for up to 120 seconds after a start (`SMOKE_WAIT_SECS`). Data ingestion is confirmed in the next step.

### 4. Data flow

```bash
bash /opt/o11y-cloudfront-batch/scripts/os-doc-counts.sh
```

Expected: document counts increase between runs. See [Monitoring](../../docs/operations.md#monitoring).

## Before deploying

Test pipeline changes with the Docker suite in [`tests/README.md`](../../tests/README.md).
