#!/bin/bash
# os-doc-counts.sh — Query OpenSearch for document counts per index and per node.
# Run from the Logstash EC2 as the pdsops user (no sudo). Uses instance role credentials.
#
# Usage:
#   bash /opt/o11y-cloudfront-batch/scripts/os-doc-counts.sh
#   bash /opt/o11y-cloudfront-batch/scripts/os-doc-counts.sh pds-weblogs-2026-09

set -euo pipefail

INDEX_PATTERN="${1:-pds-weblogs-*}"
REGION="${AWS_REGION:-us-west-2}"
PYTHON_BIN="$(command -v python3.13 2>/dev/null || echo python3)"

"$PYTHON_BIN" - "$INDEX_PATTERN" "$REGION" <<'EOF'
import boto3, json, sys, urllib.request
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

index_pattern, region = sys.argv[1], sys.argv[2]
session = boto3.Session(region_name=region)
ssm = boto3.client('ssm', region_name=region)
endpoint = ssm.get_parameter(Name='/pds/o11y-platform/opensearch/opensearch_endpoint')['Parameter']['Value']
creds = session.get_credentials().get_frozen_credentials()

def signed_get(path):
    url = f'https://{endpoint}{path}'
    req = AWSRequest(method='GET', url=url)
    SigV4Auth(creds, 'es', region).add_auth(req)
    r = urllib.request.urlopen(urllib.request.Request(url, headers=dict(req.headers)))
    return json.loads(r.read())

# Total count across all matching indices
total = signed_get(f'/{index_pattern}/_count')
print(f'\nTotal documents in {index_pattern}: {total["count"]:,}\n')

# Per-index breakdown
cat = signed_get(f'/_cat/indices/{index_pattern}?h=index,docs.count,store.size&s=index&format=json')
if not cat:
    print('No matching indices found.')
    sys.exit(0)

print(f'{"Index":<35} {"Docs":>12}  {"Size":>10}')
print('-' * 62)
for row in cat:
    print(f'{row["index"]:<35} {int(row["docs.count"] or 0):>12,}  {row.get("store.size","?"):>10}')

# Per-node breakdown using aggregation
print('\nDocuments by organization.name (node):')
agg = signed_get(f'/{index_pattern}/_search?size=0')
# Use a terms agg via POST
import urllib.parse
agg_body = json.dumps({
    "size": 0,
    "aggs": {"by_node": {"terms": {"field": "organization.name", "size": 50}}}
}).encode()
url = f'https://{endpoint}/{index_pattern}/_search?size=0'
req = AWSRequest(method='POST', url=url, data=agg_body, headers={'Content-Type': 'application/json'})
SigV4Auth(creds, 'es', region).add_auth(req)
r = urllib.request.urlopen(urllib.request.Request(url, data=agg_body, headers=dict(req.headers)))
data = json.loads(r.read())
buckets = data.get('aggregations', {}).get('by_node', {}).get('buckets', [])
if buckets:
    print(f'  {"Node":<20} {"Docs":>12}')
    print('  ' + '-' * 34)
    for b in sorted(buckets, key=lambda x: -x['doc_count']):
        print(f'  {b["key"]:<20} {b["doc_count"]:>12,}')
else:
    print('  (no aggregation results — index may be empty or organization.name not mapped)')
EOF
