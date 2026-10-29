# Operations Runbook

Day-2 operations for the Logstash EC2: deploy, monitor, troubleshoot. Run commands on the EC2 as `pdsops` (no sudo) unless noted. Logstash runs as a `systemd --user` service under `pdsops`.

- **Connect:** through the CDS bastion, then `sudo -iu pdsops`. See the [Access model](../terraform/logstash/README.md#access-model).
- **First deploy on a new instance:** [First-boot setup](../terraform/logstash/README.md#first-boot-setup).
- **Verify a deployment:** [Verify the deployment](../terraform/logstash/README.md#verify-the-deployment).
- **Deploy order across repos:** o11y-platform [Initial deployment](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#initial-deployment).

## Quick reference (from the EC2, as the pdsops user)

**Service control:**

```bash
systemctl --user status logstash
systemctl --user stop logstash
systemctl --user start logstash
systemctl --user restart logstash
tail -f /var/log/logstash/logstash-plain.log   # journalctl needs adm/wheel, which pdsops lacks
```

| Situation | What to run |
|---|---|
| Config changed in the repo (filters, inputs, outputs, `logstash.yml`, `regexes.yaml`) | Re-run the deploy script below. A bare `restart` does not pick up repo changes. |
| Logstash is hung, or an S3 input should poll now | `systemctl --user restart logstash` |
| Re-ingest S3 history | Stop, delete the sincedb files, start (see below) |

After any stop, start, or restart, wait for the command to return (shutdown can take about a minute), then run the [smoke test](../terraform/logstash/README.md#3-smoke-test). Logstash starts again after an instance reboot.

**Deploy (pull the latest config and restart).** The script clones or updates its own working copy at `/opt/o11y-cloudfront-batch`. Set these once per session; use a branch name in `REPO_BRANCH` to deploy something other than `main`:

```bash
REPO_BRANCH="main"
DEPLOY_URL="https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/${REPO_BRANCH}/scripts/logstash-deploy.sh"
export REPO_BRANCH

bash <(curl -fsSL "${DEPLOY_URL}")
```

The deploy also reapplies the [index template](../config/opensearch/README.md) and rewrites `/etc/logstash/env`. `S3_CF_BUCKET_NAME` keeps its last value if you do not pass it, and the script warns when it is empty.

### Deploying with a subset of nodes

`ENABLED_NODES` (comma- or space-separated, case-insensitive: `atm`, `en`, `geo`, `img`, `naif`, `ppi`, `rings`, `sbn`) limits the deploy to those nodes; unset enables all. Use it for a staged rollout on a venue with a large S3 backlog: run EN alone until it catches up, then redeploy with all nodes. Every deploy regenerates `pipelines.yml` and `pipelines/*.conf`, so a disabled node leaves no stale config.

```bash
ENABLED_NODES="en"
export ENABLED_NODES
bash <(curl -fsSL "${DEPLOY_URL}")

# After EN has caught up:
unset ENABLED_NODES
bash <(curl -fsSL "${DEPLOY_URL}")
```

### Loading specific years

`LOG_YEARS` (comma- or space-separated years or `YYYY-YYYY` ranges, e.g. `2023` or `2021-2024`) limits every S3 input to objects dated in those years; unset loads every year. It combines with `ENABLED_NODES`.

```bash
LOG_YEARS="2021-2022"
export LOG_YEARS
bash <(curl -fsSL "${DEPLOY_URL}")

# Later, add a year; 2021 and 2022 keep their read position:
LOG_YEARS="2021-2023"
bash <(curl -fsSL "${DEPLOY_URL}")
```

How it works:

- The build emits each `s3` input once per year, with an `exclude_pattern` that skips every key without a date in that year, and a per-year `sincedb_path` and `id` (`..._<year>`). Dates are recognised as `YYYY-MM[-DD]`, `YYYYMMDD`, `YYMMDD` in `u_ex*`, `*log.*` and `*xferlog.*` names, and `year=YYYY/` or `/YYYY/` path segments.
- A year is selected by the date in the object key, not by the event timestamps inside the file.
- Objects with no date in the key (for example rotated `access_log.3.gz`) are skipped whenever `LOG_YEARS` is set.
- Each year has its own sincedb, so adding a year reads only that year. Unsetting `LOG_YEARS` switches to the plain inputs, which keep their own sincedb files and do not know what the year inputs loaded: with no sincedb they re-read every year (documents are overwritten, not duplicated), and with an old one they resume from its timestamp. To finish a catch-up, list every year through the current one (for example `LOG_YEARS="2021-2026"`) instead of unsetting it, and add the new year each January.
- Every input lists its prefix on each poll, so the number of inputs is the number of prefixes times the number of years. Keep the list to the years you need.
- A year that is still receiving logs (CloudFront, the `weblogs/` prefixes) stops being ingested if it is not in the list.

### Re-ingest from S3

Each S3 input records its read position in a sincedb file. Deleting it re-reads the prefix; `document_id` is a fingerprint, so documents are overwritten, not duplicated.

```bash
NODE="naif"   # atm | en | geo | img | naif | ppi | rings | sbn ; use "" for all nodes
systemctl --user stop logstash
rm -f /var/lib/logstash/plugins/inputs/s3/sincedb_file_input_${NODE}*
systemctl --user start logstash
```

### Daily egress report

> **WARNING: the egress report (`scripts/egress_report.py`, `src/pds/o11y_batch/egress_report.py`) has not been tested end to end and is not known to work. Validate it before relying on it.**

The deploy installs a cron job in the `pdsops` crontab when `EGRESS_REPORT_RECIPIENTS` is set; without it the job is skipped, and a job already installed is left untouched. Output goes to `/var/log/egress-report.log`.

SMTP credentials come from `/etc/logstash/smtp.env`. Create it once, as root or via sudo:

```bash
SMTP_USERNAME="<smtp-username>"
SMTP_SERVER="<smtp-host>:587"
SMTP_SENDER="<verified-sender-address>"
read -rsp "SMTP password: " SMTP_PASSWORD

sudo install -m 600 -o pdsops -g pdsops /dev/null /etc/logstash/smtp.env
sudo tee /etc/logstash/smtp.env > /dev/null <<EOF
username=${SMTP_USERNAME}
password=${SMTP_PASSWORD}
server=${SMTP_SERVER}
sender=${SMTP_SENDER}
EOF
```

Then enable the job:

```bash
EGRESS_REPORT_RECIPIENTS="<comma-separated-addresses>"
export EGRESS_REPORT_RECIPIENTS
bash <(curl -fsSL "${DEPLOY_URL}")
```

| Variable | Default | Purpose |
|---|---|---|
| `SMTP_ENV_FILE` | `/etc/logstash/smtp.env` | Credentials file |
| `SMTP_CONFIG_SSM_KEY_PATH` | unset | SSM prefix to read credentials from when the file is missing; the EC2 role can read the `iam` module's `smtp_config_ssm_path` |
| `EGRESS_REPORT_SCHEDULE` | `0 6 * * *` | Cron schedule |
| `EGRESS_REPORT_HOURS` | `24` | Trailing window in hours |

To remove the job, run `crontab -e` as `pdsops` and delete the `# egress-report` line.

> Root is needed only for `scripts/logstash-bootstrap.sh`: Logstash version upgrades or re-provisioning `pdsops` on an externally managed instance. A system administrator runs it (via SSM). It is not needed for routine operations, or at first boot on Terraform-managed instances (userdata does it).

## Update pipeline configuration

A config change needs no Terraform and no sudo; the deploy script pulls the repo, rebuilds the pipelines, and restarts Logstash.

1. Edit the files under `config/logstash/config/`:

   | File | Purpose |
   |---|---|
   | `shared/pds-filter.conf` | Parsing, field mapping, enrichment |
   | `shared/pds-output-opensearch.conf` | OpenSearch index, bad-log routing |
   | `inputs/pds-input-s3-<node>.conf` | Per-node S3 prefixes, poll interval, dataset metadata |
   | `pipelines.yml.template` | Per-pipeline settings (EN overrides workers and batch size) |
   | `logstash.yml`, `jvm.options` | Defaults for all pipelines; queue; heap ceiling |
   | `plugins/regexes.yaml` | User-agent patterns (below) |

2. Test with the [pipeline integration tests](../tests/README.md#running-the-integration-tests-with-docker).
3. Merge to `main`, or push a branch to deploy with `REPO_BRANCH`.
4. Run the deploy script from the [Quick reference](#quick-reference-from-the-ec2-as-the-pdsops-user).
5. Check with [Verify the deployment](../terraform/logstash/README.md#verify-the-deployment).

### Update `regexes.yaml`

`regexes.yaml` is the [ua-parser/uap-core](https://github.com/ua-parser/uap-core/blob/master/regexes.yaml) file that the useragent filter uses to detect browsers, bots, and operating systems. Refresh it a few times a year:

```bash
curl -fsSL https://raw.githubusercontent.com/ua-parser/uap-core/master/regexes.yaml \
  -o config/logstash/config/plugins/regexes.yaml
```

Then follow steps 2 to 5 above.

## Deployed files

The deploy script writes runtime config to `/etc/logstash/`, not the repo checkout. The repo at `/opt/o11y-cloudfront-batch` holds the templates.

| Path | Contents |
|---|---|
| `/etc/logstash/env` | `AWS_REGION`, `S3_BUCKET_NAME`, `S3_CF_BUCKET_NAME`, `OPENSEARCH_URL`, `INDEX_PREFIX`, `LS_SETTINGS_DIR`; loaded by the systemd unit |
| `/etc/logstash/pipelines.yml` | Active pipelines, generated from the template |
| `/etc/logstash/pipelines/pipeline-pds-input-s3-<node>.conf` | Per-node input + filter + output, generated |
| `/etc/logstash/shared/`, `inputs/`, `logstash.yml`, `jvm.options` | Copied from the repo |
| `/var/lib/logstash/plugins/inputs/s3/` | S3 sincedb files |

`INDEX_PREFIX` defaults to `pds-weblogs`; events go to `${INDEX_PREFIX}-YYYY-MM`. To see what a pipeline writes to: `grep "index =>" /etc/logstash/pipelines/pipeline-pds-input-s3-en.conf`.

## Monitoring

```bash
systemctl --user status logstash
tail -f /var/log/logstash/logstash-plain.log
tail -f /var/log/logstash-bootstrap.log   # first-boot bootstrap (root phase)
```

**Is it processing right now?** Each S3 input polls on its `interval`: 900 seconds for EN, 7200 seconds for the other nodes. A new file appears only after the next poll (restart the service to poll immediately), and a quiet log between polls is normal. Logstash serves stats on `localhost:9600`:

```bash
curl -s "http://localhost:9600/_node/stats/pipelines?pretty" | less
curl -s "http://localhost:9600/_node/stats/pipelines/naif?pretty"   # one pipeline
```

Run it twice a few seconds apart. `events.in` and `events.out` moving means it is working; `queue.events_count` growing while `events.out` stays flat usually means the OpenSearch output is blocked.

**Is data reaching OpenSearch?**

```bash
bash /opt/o11y-cloudfront-batch/scripts/smoke-test.sh      # service, pipelines, S3, OpenSearch auth
bash /opt/o11y-cloudfront-batch/scripts/os-doc-counts.sh   # totals per index and per node
bash /opt/o11y-cloudfront-batch/scripts/os-doc-counts.sh pds-weblogs-2026-09   # one index
```

`os-doc-counts.sh` makes signed API calls (`_cat/indices` and a terms aggregation on `organization.name`), so it gives the true count when the Dashboards index count looks stale.

### Bad logs

The output diverts events with any of these tags to `/tmp/bad_logs_YYYY-MM.txt` on the EC2 instead of indexing them: `bad_log`, `_grok_parse_failure`, `_grok_filter_initial_parse_failure` (no grok pattern matched), `_datetimeparsefailure`, `_invalid_http_method`, `_template_variable`, `_missing_url_original`. Every other event is indexed with its tags. The file lives in `/tmp`, so it does not survive a reboot.

```bash
tail -f /tmp/bad_logs_$(date +%Y-%m).txt
```

## Troubleshooting

| Symptom | Check and fix |
|---|---|
| Logstash will not start | `systemctl --user status logstash`; `tail -n 50 /var/log/logstash/logstash-plain.log`; `cat /etc/logstash/env`; `ls /etc/logstash/pipelines/`. Re-run the deploy. If Logstash is not installed, a system administrator must run `logstash-bootstrap.sh` first. |
| No data in OpenSearch | Run `smoke-test.sh`. Look at `ls -la /var/lib/logstash/plugins/inputs/s3/` and the Logstash log for S3 read errors. Check the node's S3 prefix has files. |
| `not authorized to perform: s3:ListAllMyBuckets` in the log | `S3_CF_BUCKET_NAME` was empty at deploy. EN's CloudFront inputs template it in as `bucket => ""`, and the S3 plugin then tries to list every bucket, which the IAM policy does not allow. Redeploy with the real bucket (below). |
| Heap or memory pressure, slow pipelines | See [Tuning](#tuning). |
| Parse failures | See [Bad logs](#bad-logs). Fix grok patterns in `shared/pds-filter.conf` and add a test case ([tests/README.md](../tests/README.md#adding-tests-for-a-new-log-format)). |
| Config error after a change | Run the [integration tests](../tests/README.md#running-the-integration-tests-with-docker). To syntax-check one pipeline locally, build the configs and run `logstash -t -f config/logstash/config/pipelines/pipeline-pds-input-s3-<node>.conf` with the `.env` values exported. |
| Need more detail in the log | Set `log.level: debug` in `config/logstash/config/logstash.yml`, deploy, and set it back to `info` afterwards. |
| Local build prints empty values or `envsubst: command not found` | Install `gettext` and export the variables first: `set -a; source .env; set +a`. |
| `s3-log-sync` fails (deprecated tool) | Check credentials (`aws sts get-caller-identity --profile "${AWS_PROFILE}"`), that `--aws-profile` or `AWS_PROFILE` is set, that the bucket is reachable, and that there is disk space for gzip (`df -h`). |

Redeploy with the CloudFront logs bucket (look it up as in [First-boot setup](../terraform/logstash/README.md#first-boot-setup)):

```bash
S3_CF_BUCKET_NAME="<cf-logs-bucket>"
export S3_CF_BUCKET_NAME
bash <(curl -fsSL "${DEPLOY_URL}")
```

**Log locations (on the EC2):** `/var/log/logstash/logstash-plain.log`; `/var/log/logstash-bootstrap.log` (userdata bootstrap); `/tmp/bad_logs_YYYY-MM.txt`; `/var/log/egress-report.log`. Docker integration-test output is in `./output/` on your workstation.

### Tuning

- **Heap:** the deploy sets `-Xms`/`-Xmx` to half of system RAM, capped at the 8 GB in `jvm.options`. The default `t3.large` (8 GB) gets a 4 GB heap. Change the instance type with `logstash_instance_type` ([Update](../terraform/README.md#update)).
- **Pipelines:** `logstash.yml` sets 1 worker, batch size 100, and a 2 GB persisted queue for every pipeline. `pipelines.yml.template` overrides the EN pipeline to 6 workers and batch size 500.
- Apply any change with the deploy script.
