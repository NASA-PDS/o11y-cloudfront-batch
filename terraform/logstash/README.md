# Logstash Module

Deploys a Logstash EC2 instance (Amazon Linux 2023, RPM install) that reads logs from S3 and writes to OpenSearch.

Reads the S3 bucket name and OpenSearch endpoint from SSM at plan time — deploy the S3 and pdc-observability-platform OpenSearch modules first.

EC2 creation is optional (`manage_ec2_instance`, default `true`) — production
will likely reuse an existing EC2, in which case this module only manages
the SSM Run-As document and parameter outputs. See
["Using an existing EC2"](#using-an-existing-ec2-manage_ec2_instance--false)
below.

> **Requires `iam:PassRole`** — must be applied by a system administrator.

## Resources

- `aws_launch_template.logstash`, `aws_instance.logstash` — EC2 launch template + instance, only created when `manage_ec2_instance = true`; userdata installs Logstash via RPM (root, `logstash-bootstrap.sh`) then deploys config and starts Logstash as a `systemd --user` service under the `logstash` account (`logstash-deploy.sh`). No SSH; access via SSM Session Manager.
- `aws_ssm_document.logstash_runas` — custom SSM Session document (Run-As `logstash`) so operators never need sudo for day-2 ops; always created, works against any instance (created here or existing)
- `aws_ssm_parameter.ec2_role_arn` — publishes EC2 role ARN to `/pds/o11y-cloudfront-batch/iam/ec2_role_arn`
- `aws_ssm_parameter.logstash_instance_id` — publishes the instance ID (created, or `existing_instance_id`) to `/pds/o11y-cloudfront-batch/ec2/logstash_instance_id`
- `aws_ssm_parameter.logstash_runas_document` — publishes the Run-As document name to `/pds/o11y-cloudfront-batch/ssm/logstash_runas_document`

### Access model

Session access is SSM Session Manager only (no SSH keys, no inbound security
group rules). `aws_ssm_document.logstash_runas` exists so a session started
with `--document-name` set to it *can* land directly as the shared
`logstash` OS account — but that requires an IAM grant
(`ssm:StartSession` on the document's ARN, separate from the grant on the
instance ARN) that may not be provisioned for your identity. **In
practice, expect `aws ssm start-session` to land you as `root`** regardless
of `--document-name`, and switch explicitly:

```bash
sudo runuser -l logstash    # or: su - logstash
```

From there, execution, logging, monitoring, and git-based config updates
are all done as that account with **no sudo**. The only step that still
requires root is `scripts/logstash-bootstrap.sh` (package/RPM install and
initial account provisioning), run automatically at first boot and
otherwise only for deliberate admin actions like a Logstash version
upgrade.

> Granting operators `ssm:StartSession` on the `logstash_runas` document's
> ARN (in addition to the instance ARN) is an IAM/SSO concern owned outside
> this repo — this module only manages the EC2 instance role. Until/unless
> that's granted, `sudo runuser -l logstash` after connecting is the
> reliable path, and works regardless of IAM state.

## SSM dependencies (read at plan time)

| Parameter | Published by |
|---|---|
| `/pds/o11y-cloudfront-batch/s3/bucket_name` | `s3` module |
| `/pds/o11y-platform/opensearch/opensearch_endpoint` | `pdc-observability-platform` repo |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `manage_ec2_instance` | `bool` | `true` | Whether this module creates the EC2. Set `false` to reuse an existing instance. |
| `existing_instance_id` | `string` | `""` | Instance ID to publish when `manage_ec2_instance = false`. Required in that mode. |
| `ec2_role_name` | `string` | — | Existing EC2 IAM role / instance profile name. Always required. |
| `vpc_id` | `string` | `""` | VPC ID for subnet and security group lookup. Required when `manage_ec2_instance = true`. |
| `ec2_security_group_name` | `string` | `""` | Name of the EC2 security group to attach. Required when `manage_ec2_instance = true`. |
| `mcp_ami_owner_id` | `string` | `""` | AWS account ID that owns the Amazon Linux 2023 AMIs. Required when `manage_ec2_instance = true`. |
| `resource_prefix` | `string` | — | Prefix for all resource names (e.g. `pds-dev`). No CI/CD identifiers. |
| `s3_cf_bucket_name` | `string` | `""` | S3 bucket containing CloudFront logs (EN node only). Leave empty to skip. |
| `logstash_instance_type` | `string` | `t3.large` | EC2 instance type. Only used when `manage_ec2_instance = true`. |
| `logstash_version` | `string` | `8.18.0` | Logstash RPM version to install. |
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
| `logstash_ssm_document_name` | Pass as `--document-name` to land an SSM session as the `logstash` user (no sudo). |

## Deploy

```bash
cp tfvars/dev.tfvars.example tfvars/dev.tfvars
# edit tfvars/dev.tfvars

task logstash:plan   VENUE=dev
task logstash:deploy VENUE=dev
```

Shared values come from `../tfvars/common-<venue>.tfvars`.

## Using an existing EC2 (`manage_ec2_instance = false`)

Set in tfvars:

```hcl
manage_ec2_instance  = false
existing_instance_id = "i-0123456789abcdef0"
```

`task logstash:deploy` then only creates/updates the SSM Run-As document and
publishes `/pds/o11y-cloudfront-batch/ec2/logstash_instance_id` (from
`existing_instance_id`) and `/pds/o11y-cloudfront-batch/iam/ec2_role_arn` — it never
touches the EC2 itself.

**Connecting to the box is entirely outside this module's control.** These
instructions work regardless of *how* you get a root shell — an SSM
session, a locked-down bastion/gateway with SSH, port-forwarding, whatever
your SA team configures for that instance. `aws_ssm_document.logstash_runas`
is created either way and is one option if SSM access is available, but
nothing here depends on it.

### Prerequisites on the existing EC2 (outside this module's control)

- Amazon Linux 2023, or another systemd-based RPM distro (`dnf`, `systemd
  --user`, `loginctl enable-linger` all need to work)
- However access is configured (SSM, SSH via a gateway, etc.), it needs to
  be able to reach the box as root (or a sudo-capable user) for the
  one-time install below
- Instance profile with the app-level S3 + OpenSearch policy from
  [`../iam/policies`](../iam/policies) (the same `ec2_role_name` this
  module reads for `ec2_role_arn`) — plus SSM connectivity
  (`AmazonSSMManagedInstanceCore`) if SSM access will be used at all

### One-time manual install

This replicates exactly what `terraform/templates/logstash-userdata.sh.tpl`
automates for a newly created instance — run it once, by hand, as root,
however you reach the box:

```bash
# 1. Connect as root (or a sudo-capable user)

# 2. Install git and clone the repo — logstash-bootstrap.sh needs it on disk first
sudo dnf install -y git --quiet
sudo git clone --branch main https://github.com/NASA-PDS/o11y-cloudfront-batch.git /opt/o11y-cloudfront-batch

# 3. Root, one-time: installs Logstash + plugins, and provisions the
#    logstash account (home dir, login shell, linger, nofile limits,
#    systemd --user unit) — see scripts/logstash-bootstrap.sh
sudo LOGSTASH_VERSION=8.18.0 REPO_DIR=/opt/o11y-cloudfront-batch \
  bash /opt/o11y-cloudfront-batch/scripts/logstash-bootstrap.sh

# 4. As the logstash user, no sudo: deploy config and start the service —
#    see scripts/logstash-deploy.sh
#
#    ALWAYS pass S3_CF_BUCKET_NAME on a first-time manual install, even if
#    this venue doesn't use EN's CloudFront pipeline (in which case set it to
#    an explicit "" so that's a deliberate choice, not an accidental omission).
#    Leaving it unset here defaults to empty, which is NOT the same as this
#    module's own s3_cf_bucket_name tfvar and will NOT be picked up
#    automatically -- an empty value silently breaks the EN CloudFront input
#    at Logstash runtime with a confusing s3:ListAllMyBuckets AccessDenied
#    error instead of a clear "not configured" message. See root README.md
#    Troubleshooting > Common Issues for that failure mode. (Redeploys after
#    this first one preserve whatever was last configured if you omit the
#    var, so this only bites on the very first manual deploy.)
sudo runuser -l logstash
# You're now in a real login shell as logstash — everything below is a plain
# command, no more sudo/runuser wrapping needed for the rest of this session.
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
cd /opt/o11y-cloudfront-batch

AWS_REGION=us-west-2 \
S3_BUCKET_NAME=$(aws ssm get-parameter --name /pds/o11y-cloudfront-batch/s3/bucket_name --query Parameter.Value --output text) \
OPENSEARCH_ENDPOINT=$(aws ssm get-parameter --name /pds/o11y-platform/opensearch/opensearch_endpoint --query Parameter.Value --output text) \
INDEX_PREFIX=pds-weblogs \
S3_CF_BUCKET_NAME=<cf-logs-bucket-name-or-explicit-empty-string> \
EGRESS_REPORT_RECIPIENTS=<comma-separated-report-recipients> \
bash scripts/logstash-deploy.sh

# 5. Verify (still inside the same logstash login shell)
systemctl --user status logstash
```

`EGRESS_REPORT_RECIPIENTS` in step 4 is **required to enable the daily
egress report cron job** — `logstash-deploy.sh` skips installing it silently
if unset. SMTP credentials are read from a local file on the EC2
(`/etc/logstash/smtp.env` by default, override with `SMTP_ENV_FILE`) — no
extra AWS permissions needed. Create that file once by hand before (or
after) this step; see [`../../README.md`](../../README.md#quick-reference-from-an-ssm-session-on-the-ec2-as-the-logstash-user)
for the exact format and the full list of egress-report env vars. (SSM is
also supported as a fallback via `SMTP_CONFIG_SSM_KEY_PATH`, but requires an
IAM grant this module doesn't provision by default — the local file avoids
that entirely.)

Step 4 also sets up the account for direct login as `logstash` afterward
(real shell, home dir) — so if your SA team's locked-down access to this
box is SSH-based (e.g. a gateway/bastion that ends in `ssh
logstash@localhost`), it works against the same account with no extra
configuration on this module's side. Whatever they add for SSH auth
(`authorized_keys`, bastion security group rules, etc.) is entirely their
setup, not something these scripts touch.

### Day-2 operations from here on — no sudo

However you reconnect (SSH directly as `logstash`, or an SSM session using
the `logstash_runas` document if that's available for this instance), the
workflow is identical to a freshly-provisioned instance — `bash
scripts/logstash-deploy.sh` to update config, `systemctl --user restart
logstash`, `tail -f /var/log/logstash/logstash-plain.log` for logs
(`journalctl` needs adm/wheel group membership `logstash` doesn't have) —
see the root [`README.md`](../../README.md) Quick Reference. If using the
SSM Run-As document:

```bash
aws ssm start-session \
  --target $(aws ssm get-parameter --name /pds/o11y-cloudfront-batch/ec2/logstash_instance_id --query Parameter.Value --output text) \
  --document-name $(aws ssm get-parameter --name /pds/o11y-cloudfront-batch/ssm/logstash_runas_document --query Parameter.Value --output text)
```

If that still lands you as `root` (missing IAM grant on the document — see
above), fall back to `sudo runuser -l logstash` after connecting.

The only step that ever needs sudo/root again is re-running
`logstash-bootstrap.sh` for a deliberate admin action like a Logstash
version upgrade.
