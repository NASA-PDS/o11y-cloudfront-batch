# Logstash Module

Deploys a Logstash EC2 instance (Oracle Linux 9 PDS Cloud AMI, RPM install) that reads logs from S3 and writes to OpenSearch.

Reads the S3 bucket name and OpenSearch endpoint from SSM at plan time — deploy the S3 and o11y-platform OpenSearch modules first.

EC2 creation is optional (`manage_ec2_instance`, default `true`).

Every venue, including prod, creates its own EC2. Setting
`manage_ec2_instance = false` instead points the module at an existing,
externally managed EC2; in that mode it only publishes SSM parameter outputs and
never touches the EC2. See
["Using an existing EC2"](#using-an-existing-ec2-manage_ec2_instance--false) below.

> **Requires `iam:PassRole`** — must be applied by a system administrator.

## Resources

- `module.ec2` (from `pdc-tf-modules//terraform/modules/ec2`) — EC2 instance, only created when `manage_ec2_instance = true`; userdata runs the full bootstrap at first boot (Logstash RPM + plugins, pdsops account setup, systemd unit) — no manual root step required. Attaches the bastion target security group (`bastion_target_sg_ssm_path`, required).
- `aws_route53_record.logstash` — A record in the existing hosted zone (SSM `/pds/hosted-zone/name`, same zone as the bastion) pointing to the EC2 private IP; name matches the EC2 `Name` tag. Only created when `manage_ec2_instance = true`.
- `aws_ssm_parameter.logstash_instance_id` — publishes the instance ID (created, or `existing_instance_id`) to `/pds/o11y-cloudfront-batch/ec2/logstash_instance_id` (SSM session target for system administrators, and for developers in dev)
- `aws_ssm_parameter.logstash_fqdn` — publishes the Route53 FQDN to `/pds/o11y-cloudfront-batch/ec2/logstash_fqdn` (SSH target via bastion). Only created when `manage_ec2_instance = true`.

### Access model

**Everyone connects through the bastion host.** The EC2 has only a private IP
and carries the bastion target security group, so SSH to the bastion first and
hop from there. SSH to the bastion with your NASA ID, then to the EC2 with the same
ID; the AMI checks it against the user-key store (DynamoDB) on every login, so your
key must be enrolled. Once on the EC2, switch to the shared `pdsops` key-user
account, which owns Logstash.

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
ssh ${NASA_ID}@${FQDN}
sudo -iu pdsops
```

`logstash_fqdn` is published only when this module creates the EC2. For an
externally managed EC2, use its hostname.

**SSM Session Manager** is limited to system administrators in prod. In dev it
is also available to developers. Sessions land as `ssm-user`; switch to `pdsops`:

```bash
INSTANCE_ID=$(aws ssm get-parameter \
  --name /pds/o11y-cloudfront-batch/ec2/logstash_instance_id \
  --query Parameter.Value --output text)
aws ssm start-session --target ${INSTANCE_ID}
sudo -iu pdsops
```

Running, updating, and monitoring Logstash are all done as `pdsops` with no
further sudo. Root is needed only for the one-time install: userdata does it on a
Terraform-created EC2, and a system administrator does it on an externally managed
EC2 (`logstash-bootstrap.sh`, also used for Logstash version upgrades there).
On a Terraform-created EC2 a version upgrade replaces the instance.

## SSM dependencies (read at plan time)

| Parameter | Published by |
|---|---|
| `/pds/o11y-cloudfront-batch/s3/bucket_name` | `s3` module |
| `/pds/o11y-platform/opensearch/opensearch_endpoint` | `o11y-platform` repo |
| `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-profile-name` | `iam` module |

Deploy `iam`, `s3`, and the o11y-platform OpenSearch module before applying this module.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `manage_ec2_instance` | `bool` | `true` | Whether this module creates the EC2. Set `false` to reuse an existing instance. |
| `existing_instance_id` | `string` | `""` | Instance ID to publish when `manage_ec2_instance = false`. Required in that mode. |
| `ami_id` | `string` | — | AMI ID for the EC2 instance. Must be the exact SA-provided AMI ID for the target venue. |
| `vpc_id` | `string` | `""` | VPC ID for subnet and security group lookup. Required when `manage_ec2_instance = true`. |
| `ec2_security_group_name` | `string` | `""` | Name of the EC2 security group to attach. Required when `manage_ec2_instance = true`. |
| `resource_prefix` | `string` | — | Prefix for all resource names (e.g. `pds-dev`). No CI/CD identifiers. |
| `s3_cf_bucket_name` | `string` | `""` | S3 bucket containing CloudFront logs (EN node only). Leave empty to skip. |
| `logstash_instance_type` | `string` | `t3.large` | EC2 instance type. Only used when `manage_ec2_instance = true`. |
| `logstash_root_volume_size` | `number` | `50` | Root volume size in GB. Must be >= the AMI root snapshot size (32 GB). Only used when `manage_ec2_instance = true`. |
| `logstash_version` | `string` | `8.18.0` | Logstash RPM version to install (baked into userdata at apply time). |
| `bastion_target_sg_ssm_path` | `string` | `""` | SSM path for the bastion target SG ID, attached so the EC2 accepts SSH from the bastion. Required when `manage_ec2_instance = true`. |
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
| `logstash_instance_id` | EC2 instance ID of the Logstash instance. |
| `logstash_fqdn` | Route53 FQDN of the Logstash EC2 (SSH target via bastion). Null when `manage_ec2_instance = false`. |

## Deploy

All variables are managed as Terragrunt inputs in `cds-infra-deploy`. Run from that repo:

```bash
task plan  VENUE=dev COMPONENT=o11y-cloudfront-batch/logstash
task apply VENUE=dev COMPONENT=o11y-cloudfront-batch/logstash
```

## Using an existing EC2 (`manage_ec2_instance = false`)

Set `manage_ec2_instance = false` and `existing_instance_id` in the venue's Terragrunt
inputs. `task apply` then only publishes
`/pds/o11y-cloudfront-batch/ec2/logstash_instance_id` (from `existing_instance_id`) —
it never provisions, modifies, or destroys the EC2 itself, and `logstash_fqdn` is not
published.

Operators reach the box through the bastion ([Access model](#access-model)).
Root-level steps (`logstash-bootstrap.sh`) are performed by a system
administrator, who can use SSM.

### Prerequisites on the existing EC2 (outside this module's control)

- Oracle Linux 9 (PDS Cloud AMI), or another systemd-based RPM distro
  (`dnf`, `systemd --user`, `loginctl enable-linger` all need to work)
- The bastion target security group attached, and operator SSH keys enrolled
  for bastion access
- A DNS name in the shared hosted zone (or another hostname operators can
  reach from the bastion) for the EC2
- A system administrator to run `scripts/logstash-bootstrap.sh` as root once
  for Logstash install and pdsops account setup (automated by userdata on
  Terraform-created instances)
- Instance profile with the app-level S3 + OpenSearch policy from
  [`../iam`](../iam) (the same role this module reads for `ec2_role_arn`),
  plus `AmazonSSMManagedInstanceCore` so system administrators can use SSM

### First-boot setup

**For Terraform-created instances (`manage_ec2_instance = true`):** userdata
runs the full bootstrap automatically — no root step needed. Wait a few
minutes after `task apply` completes for the EC2 to finish (Logstash install
and plugin installation take 5-10 minutes), then connect as `pdsops`.
Bootstrap progress is logged to `/var/log/logstash-bootstrap.log`.

**For existing EC2s (`manage_ec2_instance = false`):** run
`scripts/logstash-bootstrap.sh` as root once first (see script header), then
follow the operator steps below.

**Operator steps (no sudo, same for both cases):**

```bash
# 1. Connect through the bastion and switch to pdsops (see Access model).

# 2. Deploy config and start the service.
#    ALWAYS set S3_CF_BUCKET_NAME on a first-time deploy (use "" if EN
#    CloudFront isn't used here) — an unset value silently breaks the EN
#    pipeline at runtime.
S3_CF_BUCKET_NAME="<cf-logs-bucket-or-empty-string>"
REPO_BRANCH=main
EGRESS_REPORT_RECIPIENTS="<comma-separated-recipients>"
export S3_CF_BUCKET_NAME REPO_BRANCH EGRESS_REPORT_RECIPIENTS
bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-deploy.sh)

# 3. Verify (see "Verify the deployment" below)
systemctl --user status logstash
```

On a venue with a large initial S3 backlog, consider staging the rollout in
step 2 instead: set `ENABLED_NODES=en` (comma/space-separated node IDs) so
only EN's pipeline runs at first, then redeploy later with `ENABLED_NODES`
unset to bring the rest of the nodes online once EN has caught up. See
[`../../docs/operations.md`](../../docs/operations.md#deploying-with-a-subset-of-nodes) for
details.

`EGRESS_REPORT_RECIPIENTS` in step 2 is **required to enable the daily
egress report cron job** — `logstash-deploy.sh` skips installing it silently
if unset. SMTP credentials are read from a local file on the EC2
(`/etc/logstash/smtp.env` by default, override with `SMTP_ENV_FILE`) — no
extra AWS permissions needed. Create that file once by hand before (or
after) this step; see [`../../docs/operations.md`](../../docs/operations.md)
for the exact format and the full list of egress-report env vars. (SSM is
also supported as a fallback via `SMTP_CONFIG_SSM_KEY_PATH`, but requires an
IAM grant this module doesn't provision by default — the local file avoids
that entirely.)

### Day-2 operations — no sudo

Connect as `pdsops` ([Access model](#access-model)). Then:
- `bash scripts/logstash-deploy.sh` — pull latest config and restart
- `systemctl --user restart logstash` — restart without config change
- `tail -f /var/log/logstash/logstash-plain.log` — live logs

See the [Operations Runbook](../../docs/operations.md) for the full list.

The only operation that ever requires root again is running
`scripts/logstash-bootstrap.sh` for a deliberate admin action such as a
Logstash version upgrade on an existing instance.

## Verify the deployment

Run these on the EC2 as `pdsops`.

**1. Instance is up and bootstrapped** (Logstash installed, `pdsops` configured):

```bash
rpm -q logstash
grep "Bootstrap complete" /var/log/logstash-bootstrap.log
loginctl show-user pdsops --property=Linger
```

`rpm -q` prints the installed version. `Linger=yes` confirms the
`systemd --user` service survives logouts. The bootstrap log exists on
Terraform-created instances only (on an existing EC2, `logstash-bootstrap.sh`
prints `=== Bootstrap complete ===` to the console). If a check fails on a
Terraform-created instance, read `/var/log/logstash-bootstrap.log` and
`/var/log/cloud-init-output.log`.

**2. Config is deployed and the service is running** (after `logstash-deploy.sh`):

```bash
systemctl --user is-active logstash
ls /etc/logstash/pipelines/
tail -n 20 /var/log/logstash/logstash-plain.log
```

`logstash-deploy.sh` refuses to run if Logstash is not installed, so a
completed deploy confirms the install.

**3. One command for all of the above plus AWS connectivity** (after `logstash-deploy.sh`):

```bash
bash /opt/o11y-cloudfront-batch/scripts/smoke-test.sh
```

It checks the Logstash RPM, linger, deployed pipeline configs, S3 access,
OpenSearch reachability and SigV4 auth, and the service state, and exits
non-zero if any check fails. OpenSearch `status=green` is expected; `yellow` is
acceptable on a single-node dev cluster. To confirm data is landing, run
`scripts/os-doc-counts.sh` (see the
[Operations Runbook](../../docs/operations.md#monitoring)).

**Before deploying**, test pipeline changes locally with the Docker suite in
[`tests/README.md`](../../tests/README.md) (`docker compose run --rm test`).
