#!/bin/bash
# smoke-test.sh — Verify Logstash is installed and running, and that S3 and
# OpenSearch are reachable and auth works.
# Run from the Logstash EC2 after deployment, as the pdsops user (no sudo).
# Exits non-zero if any check fails.
#
# Usage:
#   bash /opt/o11y-cloudfront-batch/scripts/smoke-test.sh

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

echo "--- Logstash install ---"
bcheck "Logstash RPM installed" rpm -q logstash
bcheck "systemd --user linger enabled" linger_enabled
bcheck "Pipeline configs deployed" pipelines_present

echo ""
echo "--- AWS connectivity ---"
PY_RC=0
PYTHON_BIN="$(command -v python3.13 2>/dev/null || echo python3)"
"$PYTHON_BIN" - <<'EOF' || PY_RC=$?
import boto3, json, sys
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
echo "--- Logstash service ---"
bcheck "Logstash service active" systemctl --user is-active logstash
tail -n 5 /var/log/logstash/logstash-plain.log || true

echo ""
if [ "$PY_RC" -eq 0 ] && [ "$FAILED" -eq 0 ]; then
  echo "Smoke test passed."
else
  echo "Smoke test FAILED - see FAIL lines above."
  exit 1
fi
