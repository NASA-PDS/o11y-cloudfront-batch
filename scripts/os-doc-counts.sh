#!/bin/bash
# os-doc-counts.sh — Query OpenSearch for document counts per index and per node.
# Run from the Logstash EC2 as the pdsops user (no sudo). Uses instance role credentials.
#
# Usage:
#   bash /opt/o11y-cloudfront-batch/scripts/os-doc-counts.sh
#   bash /opt/o11y-cloudfront-batch/scripts/os-doc-counts.sh pds-weblogs-2026-09

set -euo pipefail

# Derive INDEX_PREFIX from the deployed env file if available, fall back to pds-weblogs
_DEPLOYED_PREFIX=""
if [[ -f /etc/logstash/env ]]; then
    _DEPLOYED_PREFIX="$(grep -E '^INDEX_PREFIX=' /etc/logstash/env | cut -d= -f2- | tr -d '"' | tr -d "'")"
fi
_DEFAULT_PREFIX="${_DEPLOYED_PREFIX:-pds-weblogs}"

INDEX_PATTERN="${1:-${_DEFAULT_PREFIX}-*}"
REGION="${AWS_REGION:-us-west-2}"
# Prefer the region from the deployed env file when not set in the environment
if [[ -z "${AWS_REGION:-}" && -f /etc/logstash/env ]]; then
    _ENV_REGION="$(grep -E '^AWS_REGION=' /etc/logstash/env | cut -d= -f2- | tr -d '"' | tr -d "'")"
    REGION="${_ENV_REGION:-us-west-2}"
fi

PYTHON_BIN="$(command -v python3.13 2>/dev/null || echo python3)"

"$PYTHON_BIN" - "$INDEX_PATTERN" "$REGION" <<'EOF'
import boto3, json, sys, urllib.request, urllib.error
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

index_pattern, region = sys.argv[1], sys.argv[2]
session = boto3.Session(region_name=region)
ssm = boto3.client('ssm', region_name=region)
endpoint = ssm.get_parameter(Name='/pds/o11y-platform/opensearch/opensearch_endpoint')['Parameter']['Value']
creds = session.get_credentials().get_frozen_credentials()

TIMEOUT = 30

def signed_request(method, path, body=None, content_type=None):
    url = f'https://{endpoint}{path}'
    headers = {'Content-Type': content_type} if content_type else {}
    aws_req = AWSRequest(method=method, url=url, data=body, headers=headers)
    SigV4Auth(creds, 'es', region).add_auth(aws_req)
    http_req = urllib.request.Request(url, data=body, headers=dict(aws_req.headers), method=method)
    try:
        r = urllib.request.urlopen(http_req, timeout=TIMEOUT)
        return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors='replace')
        return None, f'HTTP {e.code} {e.reason}: {body_text[:300]}'
    except (urllib.error.URLError, TimeoutError) as e:
        return None, f'Connection error: {e}'

# Verify connectivity with a cluster health check first
data, err = signed_request('GET', '/_cluster/health')
if err:
    print(f'ERROR: Cannot reach OpenSearch: {err}')
    sys.exit(1)
print(f'Cluster: {endpoint}  status={data["status"]}  nodes={data["number_of_nodes"]}')

# List all indices matching the pattern
cat, err = signed_request('GET', f'/_cat/indices/{index_pattern}?h=index,docs.count,store.size&s=index&format=json')
if err:
    # Distinguish a genuine "no match" (404) from auth/server failures
    if 'HTTP 404' in err:
        print(f'\nNo indices found matching "{index_pattern}".')
        print('Listing all non-system indices for reference:')
        cat, err2 = signed_request('GET', '/_cat/indices?h=index,docs.count,store.size&s=index&format=json')
        if err2:
            print(f'  ERROR listing indices: {err2}')
            sys.exit(1)
        ref = [r for r in (cat or []) if not r['index'].startswith('.')]
        if not ref:
            print('  (no non-system indices found — OpenSearch may be empty)')
        else:
            print(f'  {"Index":<40} {"Docs":>12}  {"Size":>10}')
            for row in ref:
                docs = int(row.get('docs.count') or 0)
                print(f'  {row["index"]:<40} {docs:>12,}  {row.get("store.size","?"):>10}')
        sys.exit(0)
    else:
        print(f'ERROR querying indices: {err}')
        sys.exit(1)

if not cat:
    print(f'\nNo indices found matching "{index_pattern}".')
    sys.exit(0)

print(f'\n{"Index":<40} {"Docs":>12}  {"Size":>10}')
print('-' * 67)
total_docs = 0
for row in cat:
    docs = int(row.get('docs.count') or 0)
    total_docs += docs
    print(f'{row["index"]:<40} {docs:>12,}  {row.get("store.size","?"):>10}')
print('-' * 67)
print(f'{"TOTAL":<40} {total_docs:>12,}')

# Per-node breakdown via aggregation
print(f'\nDocuments by organization.name (node) across {index_pattern}:')
agg_body = json.dumps({
    "size": 0,
    "aggs": {"by_node": {"terms": {"field": "organization.name", "size": 50}}}
}).encode()
data, err = signed_request('POST', f'/{index_pattern}/_search?size=0',
                           body=agg_body, content_type='application/json')
if err:
    print(f'  (aggregation failed: {err})')
else:
    buckets = data.get('aggregations', {}).get('by_node', {}).get('buckets', [])
    if buckets:
        print(f'  {"Node":<25} {"Docs":>12}')
        print('  ' + '-' * 39)
        for b in sorted(buckets, key=lambda x: -x['doc_count']):
            print(f'  {b["key"]:<25} {b["doc_count"]:>12,}')
    else:
        print('  (no results — indices may be empty or organization.name field not present)')
EOF
