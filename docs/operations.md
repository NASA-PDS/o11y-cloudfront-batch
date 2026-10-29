# Operations Runbook

Day-2 operations for the Logstash EC2: deploy, monitor, troubleshoot. Run commands on the EC2 as `pdsops` unless noted.

In production, Logstash runs as a `systemd --user` service under the shared
`pdsops` key-user account on a PDS Cloud EC2. Day-2 operations (service control,
logs, config updates) never require sudo once you are the `pdsops` user.

- **Connect:** through the CDS bastion, then `sudo -iu pdsops` - see the
  [Access model](../terraform/logstash/README.md#access-model).
- **Verify a deployment:** see
  [Verify the deployment](../terraform/logstash/README.md#verify-the-deployment).
- **First deploy on a new instance:** see
  [First-boot setup](../terraform/logstash/README.md#first-boot-setup).
- **Deploy order across repos:** see the o11y-platform
  [Initial deployment](https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md#initial-deployment).

## Quick reference (from the EC2, as the pdsops user)

**Service control (no sudo):**
```bash
systemctl --user status logstash
systemctl --user stop logstash
systemctl --user start logstash
systemctl --user restart logstash
# journalctl requires adm/wheel group membership — use the log file instead:
tail -f /var/log/logstash/logstash-plain.log
```

When to restart:

| Situation | What to run |
|---|---|
| Config changed in the repo (filters, inputs, outputs, `logstash.yml`, `regexes.yaml`) | Re-run the deploy script below. It rebuilds the pipelines and restarts Logstash. A bare `restart` does not pick up repo changes. |
| Logstash is hung, or you want an S3 input to poll now (EN inputs poll every 15 minutes, other nodes every 2 hours) | `systemctl --user restart logstash` |
| Clearing S3 read history | `stop`, delete the sincedb files, then `start` (see below) |

After any stop, start, or restart, wait for the command to return (shutdown can take about a minute), then run the [smoke test](../terraform/logstash/README.md#3-smoke-test). Logstash starts again after an instance reboot.

**Update config (pull latest from GitHub and restart, no sudo):**
```bash
# Piped directly from GitHub — no local checkout needed; the script
# clones/updates its own working copy at REPO_DIR (default /opt/o11y-cloudfront-batch).
bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-deploy.sh)

# To deploy from a non-main branch:
REPO_BRANCH=<your-branch> bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-deploy.sh)
```

### Deploying with a Subset of Nodes

Set `ENABLED_NODES` (comma/space-separated, case-insensitive node IDs:
`atm`, `en`, `geo`, `img`, `naif`, `ppi`, `rings`, `sbn`) to restrict the
deploy to one or more nodes. Leaving it unset enables all nodes — the
default. This is useful for a staged rollout, e.g. on a brand-new venue
with a large S3 backlog: bring EN online by itself first, let it catch up,
then redeploy with all nodes enabled.

```bash
# First deploy: EN only, so its backlog catches up without competing for
# Logstash resources with the other 7 nodes.
ENABLED_NODES=en bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-deploy.sh)

# Once EN has caught up, redeploy with ENABLED_NODES unset (or the full
# list) to bring the rest of the nodes online:
bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-deploy.sh)
```

Re-running the deploy script always regenerates `pipelines.yml` and
`pipelines/*.conf` from scratch, so a node disabled in one run leaves no
stale config behind in a later run.

**Enable/update the daily egress report email:**

> **WARNING: The egress report scripts (`scripts/egress_report.py`, `src/pds/o11y_batch/egress_report.py`) have not been tested and are not known to work. The instructions below are retained for reference only — do not rely on them without first validating the scripts end-to-end.**

SMTP credentials are read from a local file on the EC2 — no AWS permissions
beyond reading a file already on disk. Create it once (as root or via sudo),
before or after the deploy step below:
```bash
sudo install -m 600 -o pdsops -g pdsops /dev/null /etc/logstash/smtp.env
sudo tee /etc/logstash/smtp.env > /dev/null <<'EOF'
username=<smtp-username>
password=<smtp-password>
server=<smtp-host>:587
sender=<verified-sender-address>
EOF
```
Then enable the cron job:
```bash
# EGRESS_REPORT_RECIPIENTS is REQUIRED to enable the report — logstash-deploy.sh
# skips installing the cron job silently if it's unset.
EGRESS_REPORT_RECIPIENTS=<comma-separated-addresses> bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-deploy.sh)

# Optional overrides (all have defaults — see scripts/logstash-deploy.sh header):
#   SMTP_ENV_FILE             path to the local file above (default: /etc/logstash/smtp.env)
#   SMTP_CONFIG_SSM_KEY_PATH  SSM path for SMTP creds instead — only used as a
#                             fallback if SMTP_ENV_FILE doesn't exist; requires an
#                             IAM grant this repo doesn't provision by default
#   EGRESS_REPORT_SCHEDULE    cron schedule (default: "0 6 * * *")
#   EGRESS_REPORT_HOURS       trailing report window in hours (default: 24)
```
Re-running `logstash-deploy.sh` without `EGRESS_REPORT_RECIPIENTS` set leaves
an already-installed cron job untouched (it only reinstalls when the var is
present) — to remove the report, edit the `logstash` user's crontab directly
and delete the `# egress-report` line.

**Clear S3 read history for one node (force re-ingest):**
```bash
systemctl --user stop logstash
# Replace 'naif' with the node name (atm, en, geo, img, naif, ppi, rings, sbn)
rm -f /var/lib/logstash/plugins/inputs/s3/sincedb_file_input_naif*
systemctl --user start logstash
```

**Clear history for all nodes:**
```bash
systemctl --user stop logstash
rm -f /var/lib/logstash/plugins/inputs/s3/sincedb_*
systemctl --user start logstash
```

**Smoke test:** see [Verify the deployment](../terraform/logstash/README.md#verify-the-deployment).

> Root is needed only for `scripts/logstash-bootstrap.sh`: Logstash version
> upgrades or re-provisioning the `pdsops` account on an existing instance. A
> system administrator runs it (via SSM). It is not needed for routine
> operations, nor at first boot on Terraform-managed instances (userdata does it).

## Update pipeline configuration

A config change needs no Terraform and no sudo. The deploy script is idempotent: it pulls the repo, redeploys the config, rebuilds the pipelines, and restarts Logstash.

1. Edit the files under `config/logstash/config/` locally:

   | File | Purpose |
   |---|---|
   | `shared/pds-filter.conf` | Log parsing, field mapping, enrichment |
   | `shared/pds-output-opensearch.conf` | OpenSearch index and routing settings |
   | `inputs/pds-input-s3-<node>.conf` | Per-node S3 prefix and metadata |
   | `logstash.yml` | JVM, queue, and pipeline settings |
   | `plugins/regexes.yaml` | User-agent regex patterns (see below) |

2. Test the change with the [pipeline integration tests](../tests/README.md#running-the-integration-tests-with-docker).
3. Merge to `main`, or push a branch and deploy it with `REPO_BRANCH`.
4. On the EC2 as `pdsops`, re-run the deploy script from the [Quick reference](#quick-reference-from-the-ec2-as-the-pdsops-user) ("Update config"). The script restarts Logstash; no separate restart is needed.
5. Check the result with [Verify the deployment](../terraform/logstash/README.md#verify-the-deployment).

### Update `regexes.yaml`

`regexes.yaml` comes from [ua-parser/uap-core](https://github.com/ua-parser/uap-core/blob/master/regexes.yaml). The `logstash-filter-useragent` plugin uses it to detect browsers, bots, and operating systems. Refresh it a few times a year to pick up new signatures:

```bash
curl -fsSL https://raw.githubusercontent.com/ua-parser/uap-core/master/regexes.yaml \
  -o config/logstash/config/plugins/regexes.yaml
```

Then follow steps 2 to 5 above.

## Monitoring

**On the EC2 (as the pdsops user — no sudo):**

```bash
# Logstash systemd --user service status
systemctl --user status logstash

# Live logs (journalctl requires adm/wheel group — use the log file instead)
tail -f /var/log/logstash/logstash-plain.log

# Bad / unparseable logs written by the Logstash pipeline
tail -f /tmp/bad_logs_$(date +%Y-%m).txt

# First-boot setup logs (root bootstrap phase, then logstash deploy phase)
tail -f /var/log/logstash-bootstrap.log
tail -f /var/log/logstash-deploy.log
```

**Real-time throughput (is it processing right now?):** Logstash exposes a
monitoring API on `localhost:9600`. Note each S3 input only polls on its
`interval` (900 seconds for EN, 7200 seconds for the other nodes) — a freshly
uploaded file won't show up until the next poll, or restart the service to
force one immediately. A quiet log is normal between polls; use the smoke test or
the API below to tell whether Logstash is running now.

```bash
# Per-pipeline in/out event counts, queue depth, worker/duration stats
curl -s http://localhost:9600/_node/stats/pipelines?pretty | less

# Just one pipeline (e.g. naif)
curl -s http://localhost:9600/_node/stats/pipelines/naif?pretty
```

Run it twice a few seconds apart — `events.in`/`events.out` moving means
it's actively working; `queue.events_count` climbing while `events.out`
stays flat usually means it's stuck (e.g. blocked on the OpenSearch output).

**Verify data is flowing into OpenSearch:**

```bash
# Connectivity + auth check (S3, OpenSearch reachable, SigV4 auth)
bash /opt/o11y-cloudfront-batch/scripts/smoke-test.sh

# Document counts — total, per-index, and per-node breakdown
bash /opt/o11y-cloudfront-batch/scripts/os-doc-counts.sh

# Narrow to a specific month's index
bash /opt/o11y-cloudfront-batch/scripts/os-doc-counts.sh pds-weblogs-2026-09
```

If the OpenSearch Dashboards index count appears stale, `os-doc-counts.sh` queries
`/_cat/indices` for per-index counts and `/_search` with a terms aggregation for the
per-node breakdown — all via SigV4-signed requests that bypass the UI and confirm
the true document count at the API level.

## Troubleshooting

### Common Issues

1. **Logstash won't start**
   - Check service status: `systemctl --user status logstash`
   - Check logs: `tail -n 50 /var/log/logstash/logstash-plain.log`
   - Check env file: `cat /etc/logstash/env`
   - Verify pipeline configs were generated: `ls /etc/logstash/pipelines/`
   - Re-run deploy to pull latest config and restart (as the pdsops user, no sudo): `bash <(curl -fsSL https://raw.githubusercontent.com/NASA-PDS/o11y-cloudfront-batch/main/scripts/logstash-deploy.sh)`
   - If Logstash itself isn't installed yet, a system administrator needs to run `logstash-bootstrap.sh` as root first

2. **No data in OpenSearch**
   - Run smoke test: `bash /opt/o11y-cloudfront-batch/scripts/smoke-test.sh`
   - Check S3 sincedb files: `ls -la /var/lib/logstash/plugins/inputs/s3/`
   - Check Logstash logs for S3 read errors: `tail -n 100 /var/log/logstash/logstash-plain.log`

3. **`AccessDenied ... not authorized to perform: s3:ListAllMyBuckets`** in the Logstash log
   - This means `S3_CF_BUCKET_NAME` was empty at deploy time, **not** that IAM is missing a real permission.
     EN's CloudFront pipeline templates it in as `bucket => ""`, and an empty bucket name makes the S3
     input plugin fall back to enumerating every bucket in the account (which the IAM policy correctly
     does *not* allow — it's scoped to one named bucket).
   - Fix: redeploy with the real bucket set — `S3_CF_BUCKET_NAME=<bucket>` — see
     [`terraform/logstash/README.md`](../terraform/logstash/README.md) for the value used in each venue.
   - As of the fix for this, `logstash-deploy.sh` also now warns loudly at deploy time if
     `S3_CF_BUCKET_NAME` is empty, and preserves the last-configured value across redeploys instead of
     silently resetting it to empty when the var isn't passed — but always pass it explicitly on a
     first-time manual install (see [First-boot setup](../terraform/logstash/README.md#first-boot-setup)).

4. **High memory usage**
   - Adjust `pipeline.batch.size` in `config/logstash/config/logstash.yml`
   - Reduce `pipeline.workers` if needed (default: 1)

5. **Parse failures**
   - Check log format matches expected patterns
   - Inspect bad logs: `tail -f /tmp/bad_logs_$(date +%Y-%m).txt`
   - Update grok patterns in `config/logstash/config/shared/pds-filter.conf`

### Log Locations

- **Logstash service logs**: `/var/log/logstash/logstash-plain.log` (`journalctl` requires adm/wheel group membership)
- **First-boot bootstrap log** (root phase): `/var/log/logstash-bootstrap.log`
- **First-boot deploy log** (logstash phase): `/var/log/logstash-deploy.log`
- **Bad / unparseable logs**: `/tmp/bad_logs_YYYY-MM.txt` (inside the EC2)
- **Test output**: `./output/` (Docker integration tests)

### Performance Tuning

For production deployments:

1. **Instance sizing**: Use t3.xlarge or larger for high-volume processing
2. **Batch processing**: Adjust `pipeline.batch.size` based on memory availability
3. **Queue settings**: Configure `queue.max_bytes` and `queue.max_events`
4. **Monitoring**: Set up CloudWatch metrics for Logstash performance
