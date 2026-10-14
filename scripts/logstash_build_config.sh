#!/bin/bash

# Builds pipelines.yml and per-node pipeline configs from the templates
# under $LS_SETTINGS_DIR.
#
# ENABLED_NODES (optional): comma/space-separated, case-insensitive list of
# node IDs (e.g. "en" or "en,geo") to restrict the build to. Unset/empty
# builds all nodes found under $LS_SETTINGS_DIR/inputs -- the default and
# historical behavior. Use this for a staged rollout: deploy with only one
# node enabled to let its S3 backlog catch up, then redeploy with
# ENABLED_NODES unset (or set to the full list) to bring the rest online.

set -euo pipefail

# Check if LS_SETTINGS_DIR is set
if [ -z "${LS_SETTINGS_DIR:-}" ]; then
  echo "Error: LS_SETTINGS_DIR environment variable is not set"
  echo "Please set LS_SETTINGS_DIR to the path of your Logstash configuration directory"
  exit 1
fi

INPUT_DIR="$LS_SETTINGS_DIR/inputs"
SHARED_FILTER="$LS_SETTINGS_DIR/shared/pds-filter.conf"
SHARED_OUTPUT="$LS_SETTINGS_DIR/shared/pds-output-opensearch.conf"
PIPELINE_DIR="$LS_SETTINGS_DIR/pipelines"

# Discover all known node IDs from the input configs (pds-input-s3-en.conf -> en)
AVAILABLE_NODES=""
for input_file in "$INPUT_DIR"/pds-input-s3-*.conf; do
  [ -e "$input_file" ] || continue
  base=$(basename "$input_file" .conf)
  AVAILABLE_NODES="$AVAILABLE_NODES ${base#pds-input-s3-}"
done
AVAILABLE_NODES=$(echo $AVAILABLE_NODES)

# Normalize ENABLED_NODES: commas -> spaces, lowercase, collapse whitespace.
ENABLED_NODES_NORM=$(echo "${ENABLED_NODES:-}" | tr ',' ' ' | tr '[:upper:]' '[:lower:]')
ENABLED_NODES_NORM=$(echo $ENABLED_NODES_NORM)

if [ -n "$ENABLED_NODES_NORM" ]; then
  for node in $ENABLED_NODES_NORM; do
    case " $AVAILABLE_NODES " in
      *" $node "*) ;;
      *)
        echo "Error: unknown node '$node' in ENABLED_NODES" >&2
        echo "Valid node IDs: $AVAILABLE_NODES" >&2
        exit 1
        ;;
    esac
  done
  echo "Enabled nodes: $ENABLED_NODES_NORM"
else
  echo "Enabled nodes: all ($AVAILABLE_NODES)"
fi

is_enabled() {
  [ -z "$ENABLED_NODES_NORM" ] && return 0
  case " $ENABLED_NODES_NORM " in
    *" $1 "*) return 0 ;;
    *) return 1 ;;
  esac
}

mkdir -p "$PIPELINE_DIR"

echo "Creating $LS_SETTINGS_DIR/pipelines.yml from template"
PIPELINES_YML_RAW="$(mktemp)"
envsubst < "$LS_SETTINGS_DIR/pipelines.yml.template" > "$PIPELINES_YML_RAW"

if [ -n "$ENABLED_NODES_NORM" ]; then
  # Keep only the blocks (paragraph-separated by blank lines in the
  # template) whose `- pipeline.id: <id>` matches an enabled node.
  awk -v enabled=" $ENABLED_NODES_NORM " '
    BEGIN { RS = ""; ORS = "\n\n" }
    {
      split($0, lines, "\n")
      id = lines[1]
      sub(/^- pipeline\.id: */, "", id)
      gsub(/^[ \t]+|[ \t]+$/, "", id)
      if (index(enabled, " " id " ") > 0) print $0
    }
  ' "$PIPELINES_YML_RAW" > "$LS_SETTINGS_DIR/pipelines.yml"
else
  mv "$PIPELINES_YML_RAW" "$LS_SETTINGS_DIR/pipelines.yml"
fi
rm -f "$PIPELINES_YML_RAW"

# Clear previously generated pipeline configs so a node disabled in this run
# doesn't leave a stale file behind from an earlier full/subset build.
rm -f "$PIPELINE_DIR"/pipeline-*.conf

for input_file in "$INPUT_DIR"/pds-input-s3-*.conf; do
  [ -e "$input_file" ] || continue
  name=$(basename "$input_file" .conf)
  node=${name#pds-input-s3-}
  if ! is_enabled "$node"; then
    echo "Skipping disabled node: $node"
    continue
  fi
  cat "$input_file" "$SHARED_FILTER" "$SHARED_OUTPUT" \
    > "$PIPELINE_DIR/pipeline-${name}.conf"
  echo "Created $PIPELINE_DIR/pipeline-${name}.conf"
done
