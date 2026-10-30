#!/bin/bash
# smoke-test.sh — Verify Logstash is installed and running right now (service
# state, monitoring API, every configured pipeline up), and that S3 and
# OpenSearch are reachable and auth works.
# Run from the Logstash EC2 after deployment, as the pdsops user (no sudo).
# Exits non-zero if any check fails.
#
# Usage:
#   bash /opt/o11y-cloudfront-batch/scripts/smoke-test.sh
#
# Optional:
#   SMOKE_WAIT_SECS   seconds to wait for the API and pipelines after a start (default: 120)

set -euo pipefail

FAILED=0

# bcheck <label> <command...> — PASS/FAIL line from a command's output and exit status.
bcheck() {
  local label="$1" out
  shift
  if out="$("$@" 2>&1)"; then
    echo "  PASS  ${label}: ${out}"
  else
    echo "  FAIL  ${label}: ${out}"
    FAILED=1
  fi
}

linger_enabled() {
  local v
  v="$(loginctl show-user "$(id -un)" --property=Linger --value)"
  echo "Linger=${v}"
  [ "$v" = "yes" ]
}

pipelines_present() {
  local n
  n="$(find /etc/logstash/pipelines -maxdepth 1 -name '*.conf' 2>/dev/null | wc -l | tr -d ' ')"
  echo "${n} pipeline config(s) in /etc/logstash/pipelines"
  [ "$n" -gt 0 ]
}

# The checks below query the running process (systemd and the Logstash monitoring
# API), not old log lines, so they fail when Logstash is down or crash-looping even
# if the log file shows earlier activity. After a restart the API and pipelines take
# a while to come up; they are retried for up to SMOKE_WAIT_SECS seconds.
LS_API="http://localhost:9600"
LS_LOG="/var/log/logstash/logstash-plain.log"
SMOKE_WAIT_SECS="${SMOKE_WAIT_SECS:-120}"

service_started() {
  local ts restarts
  ts="$(systemctl --user show logstash --property=ActiveEnterTimestamp --value)"
  restarts="$(systemctl --user show logstash --property=NRestarts --value)"
  echo "active since ${ts} (automatic restarts: ${restarts:-0})"
  [ -n "$ts" ]
}

logstash_api_up() {
  local deadline=$((SECONDS + SMOKE_WAIT_SECS)) out
  until out="$(curl -fsS --max-time 5 "${LS_API}/" 2>&1)"; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "no response from ${LS_API} within ${SMOKE_WAIT_SECS}s: ${out}"
      return 1
    fi
    sleep 5
  done
  "$PYTHON_BIN" -c 'import json, sys; d = json.load(sys.stdin); print("version=%s status=%s" % (d["version"], d["status"]))' <<<"$out"
}

# Every pipeline.id in the generated /etc/logstash/pipelines.yml (so ENABLED_NODES
# is respected) must be reported by the running process with no reload failures.
pipelines_running() {
  "$PYTHON_BIN" - "$LS_API" "$SMOKE_WAIT_SECS" <<'EOF'
import json, re, sys, time, urllib.error, urllib.request

api, wait = sys.argv[1], int(sys.argv[2])
expected = []
with open('/etc/logstash/pipelines.yml') as f:
    for line in f:
        m = re.match(r'^-\s*pipeline\.id:\s*["\']?([^"\'\s]+)', line)
        if m:
            expected.append(m.group(1))
if not expected:
    print('no pipeline.id entries in /etc/logstash/pipelines.yml')
    sys.exit(1)

deadline = time.time() + wait
while True:
    try:
        with urllib.request.urlopen(f'{api}/_node/stats/pipelines', timeout=5) as r:
            pipelines = json.load(r)['pipelines']
        missing = [p for p in expected if p not in pipelines]
        if not missing:
            break
        detail = 'not running: ' + ', '.join(missing)
    except (OSError, ValueError, KeyError) as e:
        detail = f'API error: {e}'
    if time.time() >= deadline:
        print(f'{detail} (waited {wait}s)')
        sys.exit(1)
    time.sleep(5)

def section(p, name):
    # The API reports null (not a missing key) for sections with no data yet.
    return pipelines[p].get(name) or {}

summary = ', '.join(
    f"{p}(in={section(p, 'events').get('in') or 0} out={section(p, 'events').get('out') or 0})"
    for p in expected
)
failed = [p for p in expected if section(p, 'reloads').get('failures')]
if failed:
    print('reload failures: ' + ', '.join(failed))
    sys.exit(1)
print(summary)
EOF
}

# ERROR/FATAL entries logged at or after the current service start (ISO timestamps
# compare lexically); earlier entries belong to a previous run.
errors_since_start() {
  local start errors
  start="$(date -d "$(systemctl --user show logstash --property=ActiveEnterTimestamp --value)" +%Y-%m-%dT%H:%M:%S)"
  errors="$(awk -v s="$start" 'substr($0, 2, 19) >= s && $0 ~ /\]\[(ERROR|FATAL)/' "$LS_LOG")"
  if [ -n "$errors" ]; then
    echo "$(echo "$errors" | wc -l | tr -d ' ') since ${start}; first: $(echo "$errors" | head -n 1)"
    return 1
  fi
  echo "none since ${start}"
}

echo "--- Logstash install ---"
bcheck "Logstash RPM installed" rpm -q logstash
bcheck "systemd --user linger enabled" linger_enabled
bcheck "Pipeline configs deployed" pipelines_present

echo ""
echo "--- AWS connectivity ---"
PY_RC=0
PYTHON_BIN="$(command -v python3.13 2>/dev/null || echo python3)"
"$PYTHON_BIN" - <<'EOF' || PY_RC=$?
import boto3, json, re, sys
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.request, urllib.error

REGION = 'us-west-2'
session = boto3.Session(region_name=REGION)
ssm = boto3.client('ssm', region_name=REGION)
ok = True

def check(label, fn):
    global ok
    try:
        result = fn()
        print(f'  PASS  {label}: {result}')
    except Exception as e:
        print(f'  FAIL  {label}: {e}')
        ok = False

S3_BUCKET  = ssm.get_parameter(Name='/pds/o11y-cloudfront-batch/s3/bucket_name')['Parameter']['Value']
ENDPOINT   = ssm.get_parameter(Name='/pds/o11y-platform/opensearch/opensearch_endpoint')['Parameter']['Value']

# 1. S3 access
check('S3 bucket accessible',
    lambda: boto3.client('s3', region_name=REGION).head_bucket(Bucket=S3_BUCKET) or S3_BUCKET)

# 1b. CloudFront logs bucket used by the EN pipeline. The name comes from the env file
# Logstash runs with, and each prefix is listed the way the S3 input lists it, so a
# bucket policy that only allows specific prefixes is exercised too.
def env_value(name):
    try:
        with open('/etc/logstash/env') as f:
            for line in f:
                if line.startswith(name + '='):
                    return line.split('=', 1)[1].strip()
    except OSError:
        pass
    return ''

def cf_prefixes():
    try:
        with open('/etc/logstash/pipelines/pipeline-pds-input-s3-en.conf') as f:
            conf = f.read()
    except OSError:
        return []
    found = re.findall(r'bucket\s*=>\s*"\$\{S3_CF_BUCKET_NAME\}"\s*\n(?:[^\n]*\n)*?\s*prefix\s*=>\s*"([^"]*)"', conf)
    return sorted(set(found))

CF_LABEL = 'CloudFront logs bucket accessible'
CF_BUCKET = env_value('S3_CF_BUCKET_NAME')
CF_PREFIXES = cf_prefixes()
if not CF_BUCKET:
    print(f'  SKIP  {CF_LABEL}: S3_CF_BUCKET_NAME is empty in /etc/logstash/env')
elif not CF_PREFIXES:
    print(f'  SKIP  {CF_LABEL}: no CloudFront input in the deployed EN pipeline (EN not enabled?)')
else:
    def cf_access():
        s3 = boto3.client('s3', region_name=REGION)
        for prefix in CF_PREFIXES:
            s3.list_objects_v2(Bucket=CF_BUCKET, Prefix=prefix, MaxKeys=1)
        return f'{CF_BUCKET}: listed {len(CF_PREFIXES)} input prefix(es)'
    check(CF_LABEL, cf_access)

# 2. OpenSearch reachable (unsigned — expect 403, not a connection error)
def os_reachable():
    try:
        urllib.request.urlopen(f'https://{ENDPOINT}/_cluster/health', timeout=5)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return f'{ENDPOINT} reachable (403 unsigned, expected)'
        raise
check('OpenSearch reachable', os_reachable)

# 3. OpenSearch auth (signed request)
def os_auth():
    creds = session.get_credentials().get_frozen_credentials()
    url = f'https://{ENDPOINT}/_cluster/health'
    req = AWSRequest(method='GET', url=url)
    SigV4Auth(creds, 'es', REGION).add_auth(req)
    r = urllib.request.urlopen(urllib.request.Request(url, headers=dict(req.headers)))
    data = json.loads(r.read())
    return f'status={data["status"]} nodes={data["number_of_nodes"]}'
check('OpenSearch auth (SigV4)', os_auth)

print()
print('All checks passed.' if ok else 'One or more checks FAILED — see above.')
sys.exit(0 if ok else 1)
EOF

echo ""
echo "--- Logstash service (live state) ---"
bcheck "Logstash service active" systemctl --user is-active logstash
bcheck "Logstash service start time" service_started
bcheck "Monitoring API responding" logstash_api_up
bcheck "All configured pipelines running" pipelines_running
bcheck "No ERROR/FATAL log entries since service start" errors_since_start

echo ""
if [ "$PY_RC" -eq 0 ] && [ "$FAILED" -eq 0 ]; then
  echo "Smoke test passed."
else
  echo "Smoke test FAILED - see FAIL lines above."
  exit 1
fi
