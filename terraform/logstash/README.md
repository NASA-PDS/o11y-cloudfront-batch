# Logstash Module

Deploys a Logstash EC2 instance (Oracle Linux 9 PDS Cloud AMI, RPM install) that reads logs from S3 and writes to OpenSearch.

Reads the S3 bucket name and OpenSearch endpoint from SSM at plan time — deploy the S3 and o11y-platform OpenSearch modules first.

EC2 creation is optional (`manage_ec2_instance`, default `true`).

**Production uses `manage_ec2_instance = false`** — Logstash runs on an
existing EC2 managed outside Terraform. In that mode this module only
creates the SSM Run-As document and publishes SSM parameter outputs; it
never touches the EC2.
See ["Using an existing EC2"](#using-an-existing-ec2-manage_ec2_instance--false)
below.

> **Requires `iam:PassRole`** — must be applied by a system administrator.

## Resources

- `module.ec2` (from `pdc-tf-modules//terraform/modules/ec2`) — EC2 instance, only created when `manage_ec2_instance = true`; userdata runs the full bootstrap at first boot (Logstash RPM + plugins, pdsops account setup, systemd unit) — no manual root step required. Access via SSM and SSH through the bastion.
- `aws_route53_zone.private` — Route53 **private** hosted zone (`private_zone_name`) attached to `vpc_id` (the bastion's VPC). Names in it resolve only inside the VPC, so the EC2's private IP is never published publicly. Only created when `manage_ec2_instance = true`.
- `aws_route53_record.logstash` — A record in that private zone pointing to the EC2 private IP; name matches the EC2 `Name` tag. Only created when `manage_ec2_instance = true`.
- `aws_ssm_document.logstash_runas` — custom SSM Session document (Run-As `pdsops`) so operators never need sudo for day-2 ops; always created, works against any instance (created here or existing)
- `aws_ssm_parameter.logstash_instance_id` — publishes the instance ID (created, or `existing_instance_id`) to `/pds/o11y-cloudfront-batch/ec2/logstash_instance_id`
- `aws_ssm_parameter.logstash_runas_document` — publishes the Run-As document name to `/pds/o11y-cloudfront-batch/ssm/logstash_runas_document`
- `aws_ssm_parameter.logstash_fqdn` — publishes the Route53 FQDN to `/pds/o11y-cloudfront-batch/ec2/logstash_fqdn` (SSH target via bastion). Only created when `manage_ec2_instance = true`.

### Access model

Two access paths are available:

**SSH via bastion (preferred for interactive work):** The EC2 has the bastion
target security group attached (`bastion_target_sg_ssm_path`) and a Route53 A
record in a VPC-private hosted zone. The FQDN resolves only inside the VPC, so
SSH to the bastion first (its name is in the public zone) and hop from there:

```bash
ZONE=$(aws ssm get-parameter --name /pds/hosted-zone/name \
  --query Parameter.Value --output text)
FQDN=$(aws ssm get-parameter \
  --name /pds/o11y-cloudfront-batch/ec2/logstash_fqdn \
  --query Parameter.Value --output text)
NASA_ID="<nasa-id>"
ssh ${NASA_ID}@pds-cds-bastion-core.${ZONE}
# then from the bastion:
ssh ${NASA_ID}@${FQDN}
sudo -iu pdsops
```

**SSM Session Manager (no bastion required):** `aws_ssm_document.logstash_runas`
exists so a session started with `--document-name` set to it *can* land
directly as `pdsops` — but that requires an IAM grant (`ssm:StartSession` on
the document's ARN) that may not be provisioned. **In practice, expect
`aws ssm start-session` to land you as `root`** and switch explicitly:

```bash
sudo -iu pdsops
```

From either path, execution, logging, monitoring, and git-based config updates
are all done as `pdsops` with **no sudo**. No root step is needed after first
boot — userdata handles the full bootstrap automatically.

> Granting operators `ssm:StartSession` on the `logstash_runas` document's
> ARN is an IAM/SSO concern outside this repo. Until/unless that's granted,
> `sudo -iu pdsops` after connecting is the reliable fallback.

## SSM dependencies (read at plan time)

| Parameter | Published by |
|---|---|
| `/pds/o11y-cloudfront-batch/s3/bucket_name` | `s3` module |
| `/pds/o11y-platform/opensearch/opensearch_endpoint` | `o11y-platform` repo |
| `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-profile-name` | `iam/roles` module |

Deploy `iam/roles`, `s3`, and the o11y-platform OpenSearch module before applying this module.

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
| `logstash_version` | `string` | `8.18.0` | Logstash RPM version to install (baked into userdata at apply time). |
| `private_zone_name` | `string` | `""` | Name of the Route53 private hosted zone created here and attached to `vpc_id`. Required when `manage_ec2_instance = true`. Must differ from the account's public zone name (a private zone shadows a same-named public zone inside the VPC); use a `*.internal` name. Set in `cds-infra-deploy`. |
| `bastion_target_sg_ssm_path` | `string` | `""` | SSM path for the bastion target SG ID. When set, attaches the SG so the EC2 accepts SSH from the bastion. Leave empty to skip. |
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
| `logstash_ssm_document_name` | Pass as `--document-name` to land an SSM session as the `pdsops` user (no sudo). |
| `logstash_fqdn` | Route53 FQDN of the Logstash EC2 (SSH target via bastion). Null when `manage_ec2_instance = false`. |

## Deploy

All variables are managed as Terragrunt inputs in `cds-infra-deploy`. Run from that repo:

```bash
task plan  VENUE=dev COMPONENT=o11y-cloudfront-batch/logstash
task apply VENUE=dev COMPONENT=o11y-cloudfront-batch/logstash
```

## Using an existing EC2 (`manage_ec2_instance = false`)

Production is configured in `cds-infra-deploy/venues/prod/o11y-cloudfront-batch/logstash/terragrunt.hcl`
with `manage_ec2_instance = false` and `existing_instance_id` set to the prod instance.

`task apply VENUE=prod COMPONENT=o11y-cloudfront-batch/logstash` then only creates/updates
the SSM Run-As document and publishes `/pds/o11y-cloudfront-batch/ec2/logstash_instance_id`
(from `existing_instance_id`) — it never provisions, modifies, or destroys the EC2 itself.

**Connecting to the box is entirely outside this module's control.** These
instructions work regardless of *how* you get a root shell — an SSM
session, a locked-down bastion/gateway with SSH, port-forwarding, whatever
your SA team configures for that instance. `aws_ssm_document.logstash_runas`
is created either way and is one option if SSM access is available, but
nothing here depends on it.

### Prerequisites on the existing EC2 (outside this module's control)

- Oracle Linux 9 (PDS Cloud AMI), or another systemd-based RPM distro
  (`dnf`, `systemd --user`, `loginctl enable-linger` all need to work)
- Root (or sudo-capable) access to run `scripts/logstash-bootstrap.sh` once
  for Logstash install and pdsops account setup (this step is automated by
  userdata on Terraform-created instances)
- Instance profile with the app-level S3 + OpenSearch policy from
  [`../iam/policies`](../iam/policies) (the same `ec2_role_name` this
  module reads for `ec2_role_arn`) — plus SSM connectivity
  (`AmazonSSMManagedInstanceCore`) if SSM access will be used at all

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
# 1. Connect as pdsops.
#    Via bastion (preferred):
FQDN=$(aws ssm get-parameter \
  --name /pds/o11y-cloudfront-batch/ec2/logstash_fqdn \
  --query Parameter.Value --output text)
ZONE=$(aws ssm get-parameter \
  --name /pds/hosted-zone/name \
  --query Parameter.Value --output text)
NASA_ID="<nasa-id>"
ssh ${NASA_ID}@pds-cds-bastion-core.${ZONE}
# then from the bastion:
ssh ${NASA_ID}@${FQDN}
sudo -iu pdsops

#    Via SSM (no bastion required):
INSTANCE_ID=$(aws ssm get-parameter \
  --name /pds/o11y-cloudfront-batch/ec2/logstash_instance_id \
  --query Parameter.Value --output text)
aws ssm start-session --target ${INSTANCE_ID}
sudo -iu pdsops

# 2. Deploy config and start the service.
#    ALWAYS set S3_CF_BUCKET_NAME on a first-time deploy (use "" if EN
#    CloudFront isn't used here) — an unset value silently breaks the EN
#    pipeline at runtime.
S3_CF_BUCKET_NAME="<cf-logs-bucket-or-empty-string>"
REPO_BRANCH=main
EGRESS_REPORT_RECIPIENTS="<comma-separated-recipients>"
export S3_CF_BUCKET_NAME REPO_BRANCH EGRESS_REPORT_RECIPIENTS
bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-deploy.sh)

# 3. Verify
systemctl --user status logstash
```

`EGRESS_REPORT_RECIPIENTS` is **required to enable the daily egress report
cron job** — `logstash-deploy.sh` skips it silently if unset. SMTP
credentials are read from `/etc/logstash/smtp.env` — see the root
[`README.md`](../../README.md#quick-reference-from-an-ssm-session-on-the-ec2-as-the-pdsops-user)
for the exact format.

### Day-2 operations — no sudo

Connect as `pdsops` via bastion SSH or SSM (same as above). Then:
- `bash scripts/logstash-deploy.sh` — pull latest config and restart
- `systemctl --user restart logstash` — restart without config change
- `tail -f /var/log/logstash/logstash-plain.log` — live logs

See the root [`README.md`](../../README.md) Quick Reference for the full list.

The only operation that ever requires root again is running
`scripts/logstash-bootstrap.sh` for a deliberate admin action such as a
Logstash version upgrade on an existing instance.
