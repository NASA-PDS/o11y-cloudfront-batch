# o11y-cloudfront-batch — Terraform

Deploys the infrastructure for the PDS Web Analytics pipeline:

- **S3 bucket** — log storage (versioning suspended), SSE, and Intelligent-Tiering
- **IAM role** — EC2 instance role + instance profile for Logstash; baseline SSM and CloudWatch policies attached
- **IAM policy** — grants the Logstash EC2 role read access to S3 and write access to OpenSearch
- **Logstash EC2** — Oracle Linux 9 instance running Logstash directly via RPM + systemd

> **OpenSearch** is managed separately in [o11y-platform](https://github.com/NASA-PDS/o11y-platform). Deploy it first — the endpoint is published to SSM and consumed automatically here. Its `opensearch` module bootstraps with `o11y_cloudfront_batch_enabled = false`, so Logstash's role isn't actually allowed to write to OpenSearch until someone flips that flag and re-applies it *after* this repo's `iam` has run — see the [first deployment phases](https://github.com/NASA-PDS/o11y-platform#first-deployment) in o11y-platform.

```
terraform/
  ├── iam/                  # EC2 role + profile, access policy + attachment — 🔐 admin (iam:CreateRole, iam:CreatePolicy, iam:AttachRolePolicy)
  ├── s3/                   # S3 log bucket
  └── logstash/             # Logstash EC2                   — 🔐 admin (iam:PassRole)
```

---

## Deployment order

The cross-repo order (OpenSearch, then IAM, S3 and Logstash here, then the OpenSearch
access-policy update) is owned by the
[o11y-platform first deployment](https://github.com/NASA-PDS/o11y-platform#first-deployment)
phase table. This repo covers its phases 2a (IAM) and 2d (S3 + Logstash EC2). Two
dependencies to remember:

- `iam` reads the OpenSearch ARN from SSM, so OpenSearch must be applied first.
- Logstash gets 403s from OpenSearch until o11y-platform re-applies `opensearch` with
  `o11y_cloudfront_batch_enabled = true` (access-policy update only, seconds). `apply`
  here succeeds either way.

---

## Prerequisites

- [Terragrunt](https://terragrunt.gruntwork.io/docs/getting-started/install/) >= 0.55
- [Task](https://taskfile.dev) — `brew install go-task/tap/go-task`
- AWS CLI
- SSH access to the CDS bastion host (your key enrolled for bastion access). The [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) is needed only by system administrators (and developers in dev) who use SSM
- A local checkout of `cds-infra-deploy` — all Terragrunt inputs live in `venues/<venue>/o11y-cloudfront-batch/`
- AWS credentials exported:
  ```bash
  eval $(aws configure export-credentials --profile <your-profile> --format env)
  unset AWS_PROFILE  # required for Terraform S3 backend compatibility
  ```

---

## Deployment — step by step

All commands run from the `cds-infra-deploy` checkout. See the [o11y-platform first deployment](https://github.com/NASA-PDS/o11y-platform#first-deployment) for the full cross-repo flow; the steps below are the o11y-cloudfront-batch subset.

### 🔐 Step 1: IAM (platform phase 2a) — Admin (`iam:CreateRole`, `iam:CreatePolicy`, `iam:AttachRolePolicy`)

```bash
task plan  VENUE=dev COMPONENT=o11y-cloudfront-batch/iam
task apply VENUE=dev COMPONENT=o11y-cloudfront-batch/iam
```

Creates `<venue>-o11y-cloudfront-batch-ec2-role`, its instance profile, and the S3 and OpenSearch access policy attached to the role (`roles.tf` and `policies.tf`, one state). Requires o11y-platform's `opensearch` module applied first (reads `opensearch_arn` from SSM). Publishes to SSM:
- `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-role-arn`
- `/pds/o11y-cloudfront-batch/iam/roles/ec2/instance-profile-name`

---

### Step 2: S3 bucket (platform phase 2d) — 👤 Power User

```bash
task plan  VENUE=dev COMPONENT=o11y-cloudfront-batch/s3
task apply VENUE=dev COMPONENT=o11y-cloudfront-batch/s3
```

Step 2 (`s3`) can run while OpenSearch bootstraps. Step 1 (`iam`) needs the OpenSearch domain applied first, because it reads `opensearch_arn` from SSM.

---

### 🔑 Step 3: Logstash EC2 (platform phase 2d) — Platform Engineer (`iam:PassRole`)

```bash
task plan  VENUE=dev COMPONENT=o11y-cloudfront-batch/logstash
task apply VENUE=dev COMPONENT=o11y-cloudfront-batch/logstash
```

**Logstash will get 403s from OpenSearch until o11y-platform re-applies `opensearch` with `o11y_cloudfront_batch_enabled = true`** — `apply` succeeds either way, but OpenSearch access requires that access-policy update first.

---

### Step 4: Initialize Logstash on the EC2

Userdata on a Terraform-created EC2 confirms the SSM agent is running and runs the full
bootstrap (Logstash RPM, plugins, `pdsops` account, systemd unit). It does
**not** deploy config or start Logstash. Every instance (a fresh one, or an
already-running one after recreating the OpenSearch domain or fixing a bad env
file) needs the deploy step run manually.

Connect through the bastion and switch to `pdsops` — see the
[Access model](logstash/README.md#access-model). For an externally managed EC2
(`manage_ec2_instance = false`), a system administrator first runs
`logstash-bootstrap.sh` as root, once — see
[`logstash/README.md`](logstash/README.md#first-boot-setup).

```bash
# As pdsops (no sudo from here on).
# Verify what's currently in the env file, if this isn't the first deploy
cat /etc/logstash/env

# Deploy config and start the service. Piped directly from GitHub — no
# prior repo checkout needed; the script clones/updates its own working
# copy to REPO_DIR (default /opt/o11y-cloudfront-batch).
# S3_BUCKET_NAME and OPENSEARCH_ENDPOINT are fetched from SSM automatically.
# S3_CF_BUCKET_NAME must be set explicitly (not in SSM) — use "" if this
# venue doesn't use EN's CloudFront input.
export S3_CF_BUCKET_NAME=<cf-logs-bucket-name>
bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/refs/heads/main/scripts/logstash-deploy.sh)

# To deploy from a non-main branch (e.g. during active development):
export REPO_BRANCH=<your-branch>
export S3_CF_BUCKET_NAME=<cf-logs-bucket-name>
bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/refs/heads/${REPO_BRANCH}/scripts/logstash-deploy.sh)

# To stage the rollout on a venue with a large initial S3 backlog, bring up
# only EN first (ENABLED_NODES, comma/space-separated node IDs), then
# redeploy with it unset once EN has caught up to enable the rest:
export ENABLED_NODES=en
bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/refs/heads/main/scripts/logstash-deploy.sh)
```

> `logstash-deploy.sh` must run as `pdsops`, never root — it checks and
> refuses to run as root. If Logstash itself isn't installed yet, it will
> also refuse and tell you to run `logstash-bootstrap.sh` first — the only
> step in this workflow that needs root, and it's rare (install/upgrade only).

The deploy script will:
1. Clone/update the o11y-cloudfront-batch repo to `/opt/o11y-cloudfront-batch` (owned by `pdsops`)
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
# journalctl requires adm/wheel group membership the pdsops user doesn't
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

### Step 5: Verify

Follow [Verify the deployment](logstash/README.md#verify-the-deployment) in the Logstash module README. It covers the install, service, and end-to-end checks (`scripts/smoke-test.sh`).

---

### Step 6 (optional): Grant Logstash access to CloudFront logs bucket

Required only if ingesting CloudFront logs. `enable_o11y_batch = true` is set in `cds-infra-deploy/venues/<venue>/pdc-cds-infra/cloudfront/pds-main/terragrunt.hcl` — it reads the EC2 role ARN from SSM automatically.

```bash
task plan  VENUE=dev COMPONENT=pdc-cds-infra/cloudfront/pds-main
task apply VENUE=dev COMPONENT=pdc-cds-infra/cloudfront/pds-main
```

---

## Updating Logstash configuration

The deploy script is idempotent — re-running it pulls the latest repo, redeploys config, rebuilds pipelines, and restarts Logstash. This is the standard workflow for config changes, and it never requires sudo:

1. Edit files under `config/logstash/config/` locally
2. Test locally: `docker compose run --rm test`
3. Push to your branch
4. Connect to the EC2 as `pdsops` ([Access model](logstash/README.md#access-model)) and re-run the deploy script (piped from GitHub — no local checkout needed):

```bash
S3_CF_BUCKET_NAME=<cf-logs-bucket-name> bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-deploy.sh)
```

> If deploying from a non-`main` branch during active development:
> ```bash
> REPO_BRANCH=<your-branch> S3_CF_BUCKET_NAME=<cf-logs-bucket-name> bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-deploy.sh)
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

## Upgrade

Each component can be upgraded independently once the stack is fully deployed.

**Logstash version** — update `logstash_version` in `cds-infra-deploy/venues/<venue>/o11y-cloudfront-batch/logstash/terragrunt.hcl` and re-apply. The EC2 is replaced (new instance with updated RPM). Run the smoke test after. See [logstash/README.md](logstash/README.md) for manual steps on an existing EC2.

**Logstash configuration** — edit files under `config/logstash/config/`, push to main, then connect to the EC2 as `pdsops` and re-run `scripts/logstash-deploy.sh`. No Terraform change needed.

**IAM policy** — update policy documents in `iam/policies.tf` and re-apply via Terragrunt. No resource replacement.

**S3 bucket settings** — lifecycle, encryption, and versioning changes take effect on re-apply of `s3/`.

---

## Teardown

```bash
# Destroy in reverse order from cds-infra-deploy
task destroy VENUE=dev COMPONENT=o11y-cloudfront-batch/logstash      # 🔑 Platform Engineer
task destroy VENUE=dev COMPONENT=o11y-cloudfront-batch/s3            # 👤 Power User
task destroy VENUE=dev COMPONENT=o11y-cloudfront-batch/iam           # 🔐 Admin
```

OpenSearch teardown is managed in [o11y-platform](https://github.com/NASA-PDS/o11y-platform).

---

## Architecture notes

- **State files** stored in S3 (`pds-<venue>-<cicd>-infra`):
  - `o11y-cloudfront-batch/iam.tfstate` — EC2 instance role + profile, IAM policy + attachment
  - `o11y-cloudfront-batch/s3.tfstate` — S3 log bucket
  - `o11y-cloudfront-batch/logstash.tfstate` — Logstash EC2
  - `o11y-platform/opensearch.tfstate` — OpenSearch domain (managed in o11y-platform, own bucket/key)
- **Variable naming** — `s3_bucket_prefix` is for the S3 bucket name only (may include CI/CD identifiers like `gh01dc`). `resource_prefix` is for all other resources and should not include CI/CD identifiers.
- **VPC/SG values** are Terragrunt inputs in `cds-infra-deploy`. TODO: source from SSM under `/pds/cds-infra/vpc/` once published.
- **Logstash sincedb** persists to `/var/lib/logstash/plugins/inputs/s3/` on the EC2 EBS volume (`delete_on_termination = false`) — S3 read position survives restarts and redeployments.
- **OpenSearch** is managed in [o11y-platform](https://github.com/NASA-PDS/o11y-platform). The endpoint is published to SSM at `/pds/o11y-platform/opensearch/opensearch_endpoint` and consumed automatically at plan time.
