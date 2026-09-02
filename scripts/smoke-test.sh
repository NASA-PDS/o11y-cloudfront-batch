#!/bin/bash
# smoke-test.sh — Verify S3, OpenSearch, and Logstash are all reachable and auth works.
# Run from the Logstash EC2 after deployment, as the pdsops user (no sudo).
#
# Usage:
#   bash /opt/o11y-cloudfront-batch/scripts/smoke-test.sh

set -euo pipefail

python3.13 - <<'EOF'
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
systemctl --user is-active logstash && echo "logstash: active" || echo "logstash: INACTIVE"
tail -n 5 /var/log/logstash/logstash-plain.log
