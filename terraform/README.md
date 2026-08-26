# PDS Web Analytics — Terraform

Deploys the infrastructure for the PDS Web Analytics pipeline:

- **S3 bucket** — log storage (versioning suspended), SSE, and Intelligent-Tiering
- **IAM policy** — grants the Logstash EC2 role read access to S3 and write access to OpenSearch
- **Logstash EC2** — Amazon Linux 2023 instance running Logstash directly via RPM + systemd

> **OpenSearch** is managed separately in [pdc-observability-platform](https://github.com/NASA-PDS/pdc-observability-platform). Deploy it first — the endpoint is published to SSM and consumed automatically here. Its `opensearch` module bootstraps with `web_analytics_enabled = false`, so Logstash's role isn't actually allowed to write to OpenSearch until someone flips that flag and re-applies it *after* this repo's `iam:deploy` has run — see Step 2 below and pdc-observability's `terraform/README.md#deployment-flow`.

```
terraform/
  ├── iam/policies/         # IAM policy + role attachment  — 🔐 admin (iam:CreatePolicy, iam:AttachRolePolicy)
  ├── s3/                   # S3 log bucket
  └── logstash/             # Logstash EC2                   — 🔐 admin (iam:PassRole)
```

---

## Deployment flow

```mermaid
flowchart TD
    subgraph ext["(1a) pdc-observability-platform"]
        OS["OpenSearch\nweb_analytics_enabled = false\n(bootstrap)"]
    end

    subgraph phase1["(1b) o11y-cloudfront-batch"]
        IAM["IAM/Policies\n🔐 Admin"]
        S3["S3 bucket\n🔑 Power-User"]
    end

    subgraph ext2["(2) pdc-observability-platform"]
        OS2["OpenSearch\nweb_analytics_enabled = true\n(access-policy update only)"]
    end

    subgraph phase2["(3) o11y-cloudfront-batch"]
        LS["Logstash EC2\n🔐 Admin"]
    end

    OS -->|"endpoint → SSM"| IAM
    OS -->|"endpoint → SSM"| LS
    IAM -->|"ec2_role_arn → SSM"| OS2
    OS2 -->|"access policy now allows Logstash"| LS
    IAM --> LS
    S3 -->|"bucket → SSM"| LS
```

1. **(1a) Deploy OpenSearch** — See [pdc-observability-platform](https://github.com/NASA-PDS/pdc-observability-platform) (~15-20 min), bootstrapped with `web_analytics_enabled = false` (and `realtime_monitor_enabled` set however cf-realtime-monitor's status warrants — the two are independent)
2. **(1b) While OpenSearch provisions**, can be run in parallel with (1a):
   - `task iam:deploy VENUE=dev` 🔐 — requires `iam:CreatePolicy`, `iam:AttachRolePolicy`; publishes `ec2_role_arn` to SSM
   - `task s3:deploy VENUE=dev` — creates the log bucket, publishes name to SSM
3. **(2) After `iam:deploy` completes**, back in [pdc-observability-platform](https://github.com/NASA-PDS/pdc-observability-platform): set `web_analytics_enabled = true` and re-run `task opensearch:deploy` — this only updates the OpenSearch access policy (adds the Logstash role as a principal), no domain redeployment. Skip this if it's already `true` from a prior deploy.
4. **(3) After all above complete** — `task logstash:deploy VENUE=dev` 🔐 — requires `iam:PassRole`; reads OpenSearch endpoint and bucket name from SSM at plan time. **Note:** the EC2 role won't actually be able to write to OpenSearch until step (2) has run — `terraform apply` here will succeed either way, but Logstash will get 403s from OpenSearch until then.

---

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/downloads) >= 1.0
- [Task](https://taskfile.dev) — `brew install go-task/tap/go-task`
- AWS CLI + [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) — `brew install --cask session-manager-plugin`
- AWS credentials exported:
  ```bash
  eval $(aws configure export-credentials --profile <your-profile> --format env)
  ```

---

## Setup

### 1. tfvars

tfvars are tracked in the `cds-infra-deploy` repo (private GitLab, not GitHub) at
`venues/<venue>/o11y-cloudfront-batch/{common,s3,logstash,iam-policies}.tfvars`, not in this repo —
`tfvars/`, `s3/tfvars/`, `iam/policies/tfvars/`, and `logstash/tfvars/` here are all gitignored.
Point Task at a local checkout:

```bash
export CDS_INFRA_DEPLOY_DIR=/path/to/cds-infra-deploy
cd terraform/
task s3:plan VENUE=dev
```

For personal iteration before promoting values to `cds-infra-deploy`, pass `LOCAL=1` to use
this repo's own (gitignored) tfvars instead:

```bash
cd terraform/

# Shared values for root + IAM modules (aws_region, tenant, partition, s3_bucket_prefix, etc.)
cp tfvars/common.tfvars.example             tfvars/common-dev.tfvars
# Edit common-dev.tfvars: set managedby, resource_prefix, ec2_role_name

# Module-specific venue values
cp s3/tfvars/dev.tfvars.example                     s3/tfvars/dev.tfvars
cp iam/policies/tfvars/dev.tfvars.example           iam/policies/tfvars/dev.tfvars
cp logstash/tfvars/dev.tfvars.example               logstash/tfvars/dev.tfvars

task s3:plan VENUE=dev LOCAL=1
```

Key values to fill in:

| File (cds-infra-deploy path shown; `LOCAL=1` uses the repo-local path in parens) | Variable | Notes |
|---|---|---|
| `common.tfvars` (`tfvars/common-dev.tfvars`) | `managedby` | Your email address |
| `common.tfvars` (`tfvars/common-dev.tfvars`) | `resource_prefix`, `ec2_role_name` | `resource_prefix` drives IAM policy names; EC2 is named `pds-o11y-cloudfront-batch` (from `component`) |
| `s3.tfvars` (`s3/tfvars/dev.tfvars`) | `s3_bucket_prefix` | S3 bucket name; may include CI/CD identifiers |
| `iam-policies.tfvars` (`iam/policies/tfvars/dev.tfvars`) | `logs_s3_bucket_name` | Full S3 bucket name for the IAM policy resource ARN |
| `logstash.tfvars` (`logstash/tfvars/dev.tfvars`) | `vpc_id`, `ec2_security_group_name`, `s3_cf_bucket_name` | VPC and CloudFront bucket for the EC2 |

### 2. Configure credentials

```bash
eval $(aws configure export-credentials --profile <your-profile> --format env)
unset AWS_PROFILE  # required for Terraform S3 backend compatibility
```

---

## Deployment — step by step

### Step 0: OpenSearch domain — pdc-observability-platform repo

Deploy from the [pdc-observability-platform](https://github.com/NASA-PDS/pdc-observability-platform) repo first, bootstrapped with `web_analytics_enabled = false`. The endpoint is published to SSM automatically and consumed here at plan time. The Logstash EC2 role won't be allowed to write to OpenSearch yet — see Step 2.5.

---

### Step 1: S3 bucket — 🔑 Power-User

```bash
task s3:plan   VENUE=dev
task s3:deploy VENUE=dev
```

---

### 🔐 Step 2: IAM policy — admin only

Requires `iam:CreatePolicy` and `iam:AttachRolePolicy`. Must be run by a system administrator.

```bash
task iam:plan   VENUE=dev
task iam:deploy VENUE=dev
```

This publishes `/pds/o11y-cloudfront-batch/iam/ec2_role_arn` to SSM.

---

### Step 2.5: Grant OpenSearch access — pdc-observability-platform repo

Back in [pdc-observability-platform](https://github.com/NASA-PDS/pdc-observability-platform): set `web_analytics_enabled = true` in the `opensearch` tfvars and re-run `task opensearch:deploy`. This only updates the OpenSearch access policy to add the Logstash role as a principal — no domain redeployment (seconds, not minutes). Skip this if it's already `true` from a prior deploy.

---

### 🔐 Step 3: Logstash EC2 — admin only

Requires `iam:PassRole`. Must be run by a system administrator. Run after Steps 0–2.5 — **Logstash will get 403s from OpenSearch if Step 2.5 hasn't run yet**, even though this step's `terraform apply` succeeds regardless.

```bash
task logstash:plan   VENUE=dev
task logstash:deploy VENUE=dev
```

> EC2 creation is optional (`manage_ec2_instance`, default `true`). Prod
> typically reuses an existing EC2 instead — set `manage_ec2_instance =
> false` and `existing_instance_id` in `tfvars/prod.tfvars`. This step then
> only manages the SSM Run-As session document and publishes SSM
> parameters; it never touches the EC2. See
> [`terraform/logstash/README.md`](logstash/README.md#using-an-existing-ec2-manage_ec2_instance--false)
> for the manual Logstash install steps on that existing instance.

---

### Step 4: Initialize Logstash on the EC2

On **new EC2 deployments**, the userdata script runs `scripts/logstash-bootstrap.sh`
(root, one-time: packages, Logstash RPM, provisions the `logstash` account)
followed by `scripts/logstash-deploy.sh` (as the `logstash` user, no sudo:
config + service start) automatically at first boot.

For an **already-running EC2** (e.g., after recreating the OpenSearch domain, or after a manual deployment where the env file is wrong), SSM in and re-run the deploy script with the required env vars — no sudo needed once you're the `logstash` user:

```bash
# SSM into the EC2 — this lands as root regardless of the Run-As document
# unless your IAM identity has ssm:StartSession on that document's ARN, so
# don't count on landing as logstash automatically:
aws ssm start-session \
  --target $(aws ssm get-parameter \
    --name /pds/o11y-cloudfront-batch/ec2/logstash_instance_id \
    --query Parameter.Value --output text)

# Switch to logstash before doing anything else:
sudo runuser -l logstash
cd /opt/o11y-cloudfront-batch

# Verify what's currently in the env file
cat /etc/logstash/env

# Re-run the deploy script from the already-cloned, logstash-owned repo.
# S3_BUCKET_NAME and OPENSEARCH_ENDPOINT are fetched from SSM automatically.
# S3_CF_BUCKET_NAME must be set explicitly (not in SSM).
S3_CF_BUCKET_NAME=<cf-logs-bucket-name> bash scripts/logstash-deploy.sh

# To deploy from a non-main branch (e.g. during active development):
REPO_BRANCH=<your-branch> S3_CF_BUCKET_NAME=<cf-logs-bucket-name> bash scripts/logstash-deploy.sh
```

> If Logstash itself isn't installed yet (e.g. a fresh instance where
> bootstrap never ran), `logstash-deploy.sh` will refuse and tell you to
> have an admin run `sudo bash scripts/logstash-bootstrap.sh` first —
> that's the only step in this whole workflow that ever needs sudo, and
> it's rare (install/upgrade only).

The deploy script will:
1. Clone/update the web-analytics repo to `/opt/o11y-cloudfront-batch` (owned by `logstash`)
2. Copy Logstash pipeline config to `/etc/logstash`
3. Build `pipelines.yml` and `pipelines/*.conf` from templates
4. Apply the OpenSearch ECS index template to the new domain
5. Write `/etc/logstash/env` with the current OpenSearch endpoint from SSM
6. Restart the Logstash `systemd --user` service

> **Sincedb (S3 read position):** Each S3 input has a named sincedb file in `/var/lib/logstash/plugins/inputs/s3/` that tracks which objects have been read. Files are named after the input ID (e.g., `sincedb_file_input_naif1`).
>
> Reset all nodes to re-ingest everything from scratch:
> ```bash
> systemctl --user stop logstash
> rm -f /var/lib/logstash/plugins/inputs/s3/sincedb_*
> systemctl --user start logstash
> ```
>
> Reset a single node (e.g., NAIF only):
> ```bash
> systemctl --user stop logstash
> rm -f /var/lib/logstash/plugins/inputs/s3/sincedb_file_input_naif*
> systemctl --user start logstash
> ```
>
> Leave sincedb intact if you only want to process new S3 objects going forward.

**Tail logs and verify startup:**
```bash
# journalctl requires adm/wheel group membership the logstash user doesn't
# have — use the log file directly instead:
tail -f /var/log/logstash/logstash-plain.log
```

A healthy startup looks like this (in order):
```
Starting Logstash ...
Log4j configuration path used is: /etc/logstash/log4j2.properties
Pipelines running {:count=>8, :running_pipelines=>[:atm, :en, :geo, ...]}
```

> **Each S3 input polls on a 2-hour interval** (`interval => 7200` in every
> `config/logstash/config/inputs/*.conf`), not continuously — a file
> uploaded to S3 can sit unprocessed for up to ~2 hours until the next poll.
> `systemctl --user restart logstash` forces an immediate poll if you don't
> want to wait. Also double-check the object landed under the right node's
> `prefix` (e.g. NAIF is `naif/naif-httpdlogs` and `naif/naif-xferlogs`,
> not the bucket root) — wrong prefix means that input never sees it.

Once it polls, you should see it pick up the file:
```
[logstash.inputs.s3] Providing file ... {:key=>"path/to/logfile.gz"}
```

**Real-time throughput** — Logstash exposes a monitoring API on
`localhost:9600` by default. This is the most direct way to see whether a
pipeline is actively processing right now:
```bash
# Per-pipeline in/out event counts, queue depth, worker/duration stats
curl -s http://localhost:9600/_node/stats/pipelines?pretty | less

# Just one pipeline (e.g. naif)
curl -s http://localhost:9600/_node/stats/pipelines/naif?pretty
```
Run it twice a few seconds apart and watch `events.in` / `events.out`
increase — if they're moving, it's actively working. `queue.events_count`
climbing with `events.out` flat usually means it's stuck (e.g. blocked on
the OpenSearch output).

To confirm events are landing in OpenSearch, run a quick count from the EC2
(all nodes share one monthly index, `${INDEX_PREFIX}-YYYY-MM`):
```bash
eval $(aws configure export-credentials --format env)
ENDPOINT=$(aws ssm get-parameter --name /pds/o11y-platform/opensearch/opensearch_endpoint \
  --region us-west-2 --query Parameter.Value --output text)

curl -s -X GET "https://${ENDPOINT}/pds-*/_count" \
  --aws-sigv4 "aws:amz:us-west-2:es" \
  --user "${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}" \
  -H "x-amz-security-token: ${AWS_SESSION_TOKEN}" | python3 -m json.tool
```

To check a specific uploaded file, search by its S3 key instead of just counting:
```bash
curl -s --aws-sigv4 "aws:amz:us-west-2:es" \
  --user "${AWS_ACCESS_KEY_ID}:${AWS_SECRET_ACCESS_KEY}" \
  -H "x-amz-security-token: ${AWS_SESSION_TOKEN}" \
  "https://${ENDPOINT}/${INDEX_PREFIX}-$(date +%Y-%m)/_search?q=object.key:*your-file-name*&pretty"
```

**Bad logs / parse failures** — anything tagged `bad_log`,
`_grok_parse_failure`, `_datetimeparsefailure`, `_invalid_http_method`,
`_template_variable`, or `_missing_url_original` is routed to a file
instead of OpenSearch (see `config/logstash/config/shared/pds-output-opensearch.conf`):
```bash
tail -f /tmp/bad_logs_$(date +%Y-%m).txt
```

---

### Step 5: Smoke test

SSM into the EC2 and run:

```bash
bash /opt/o11y-cloudfront-batch/scripts/smoke-test.sh
```

Checks S3 access, OpenSearch network reachability, OpenSearch SigV4 auth, and Logstash service status. OpenSearch `status=green` is expected; `yellow` is acceptable on a single-node dev cluster (no replicas).

---

### Step 6 (optional): Grant Logstash access to CloudFront logs bucket

Required only if ingesting CloudFront logs. Apply in the `pdc-cds-infra` repo:

```bash
cd pdc-cds-infra/terraform/cloudfront/pds-main/
# Fill in tfvars/dev.tfvars: web_analytics_ec2_role_name, firehose_pds_main_cf_role_name
task plan   VENUE=dev
task deploy VENUE=dev
```

---

## Updating Logstash configuration

The deploy script is idempotent — re-running it pulls the latest repo, redeploys config, rebuilds pipelines, and restarts Logstash. This is the standard workflow for config changes, and it never requires sudo:

1. Edit files under `config/logstash/config/` locally
2. Test locally: `docker compose run --rm test`
3. Push to your branch
4. SSM into the EC2, switch to `logstash`, and re-run the deploy script:

```bash
aws ssm start-session \
  --target $(aws ssm get-parameter \
    --name /pds/o11y-cloudfront-batch/ec2/logstash_instance_id \
    --query Parameter.Value --output text)

# Lands as root — switch first:
sudo runuser -l logstash
cd /opt/o11y-cloudfront-batch

S3_CF_BUCKET_NAME=<cf-logs-bucket-name> bash scripts/logstash-deploy.sh
```

> If deploying from a non-`main` branch during active development:
> ```bash
> REPO_BRANCH=<your-branch> S3_CF_BUCKET_NAME=<cf-logs-bucket-name> bash scripts/logstash-deploy.sh
> ```

Common files to edit:
| File | Purpose |
|---|---|
| `config/logstash/config/shared/pds-filter.conf` | Log parsing, field mapping, enrichment |
| `config/logstash/config/shared/pds-output-opensearch.conf` | OpenSearch index/routing settings |
| `config/logstash/config/inputs/pds-input-s3-<node>.conf` | Per-node S3 prefix and metadata |
| `config/logstash/config/logstash.yml` | JVM, queue, pipeline settings |
| `config/logstash/config/plugins/regexes.yaml` | User-agent regex patterns (see below) |

#### Updating `regexes.yaml`

The `regexes.yaml` file is sourced from [ua-parser/uap-core](https://github.com/ua-parser/uap-core/blob/master/regexes.yaml) and provides the regex patterns used by the `logstash-filter-useragent` plugin to detect browsers, bots, and operating systems.

This file should be updated periodically (a few times per year) to pick up new browser and bot signatures:

```bash
curl -fsSL https://raw.githubusercontent.com/ua-parser/uap-core/master/regexes.yaml \
  -o config/logstash/config/plugins/regexes.yaml
```

Then test, commit, and redeploy via the standard config-update workflow above.

---

## Teardown

```bash
task logstash:destroy   VENUE=dev   # Logstash EC2 + launch template  🔐 admin
task iam:destroy        VENUE=dev   # IAM policy + role attachment     🔐 admin
task s3:destroy         VENUE=dev   # S3 bucket (does not delete objects)
```

OpenSearch teardown is managed in [pdc-observability-platform](https://github.com/NASA-PDS/pdc-observability-platform).

---

## Architecture notes

- **State files** stored in S3 (`pds-<venue>-<cicd>-infra`):
  - `o11y-cloudfront-batch/s3.tfstate` — S3 log bucket
  - `o11y-cloudfront-batch/iam-policies.tfstate` — IAM policies
  - `o11y-cloudfront-batch/logstash.tfstate` — Logstash EC2
  - `observability/opensearch.tfstate` — OpenSearch domain (managed in pdc-observability-platform, own bucket/key)
- **Variable naming** — `s3_bucket_prefix` is for the S3 bucket name only (may include CI/CD identifiers like `gh01dc`). `resource_prefix` is for all other resources and should not include CI/CD identifiers.
- **VPC/SG values** are in tfvars. TODO: source from SSM under `/pds/cds-infra/vpc/` once published.
- **Logstash sincedb** persists to `/var/lib/logstash/plugins/inputs/s3/` on the EC2 EBS volume (`delete_on_termination = false`) — S3 read position survives restarts and redeployments.
- **OpenSearch** is managed in [pdc-observability-platform](https://github.com/NASA-PDS/pdc-observability-platform). The endpoint is published to SSM at `/pds/o11y-platform/opensearch/opensearch_endpoint` and consumed automatically at plan time.
