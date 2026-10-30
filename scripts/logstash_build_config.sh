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
#
# LOG_YEARS (optional): comma/space-separated list of four-digit years or
# year ranges (e.g. "2023", "2021 2023", "2021-2024"). Each s3 input in the
# enabled nodes is emitted once per year with an exclude_pattern that skips
# every object whose key carries no date in that year, and with a per-year
# sincedb_path, temporary_directory and id (suffixed _<year>) so a year added later is read from
# the start. Unset/empty leaves the inputs unchanged and loads every year.

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

# Normalize LOG_YEARS: commas -> spaces, expand YYYY-YYYY ranges, validate, de-duplicate.
LOG_YEARS_NORM=""
LOG_YEARS_RAW=$(echo "${LOG_YEARS:-}" | tr ',' ' ')
if [ -n "${LOG_YEARS_RAW// /}" ]; then
  IFS=' ' read -r -a LOG_YEAR_TOKENS <<< "$LOG_YEARS_RAW"
  for token in "${LOG_YEAR_TOKENS[@]}"; do
    case "$token" in
      [0-9][0-9][0-9][0-9])
        first=$token
        last=$token
        ;;
      [0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9])
        first=${token%-*}
        last=${token#*-}
        ;;
      *)
        echo "Error: invalid LOG_YEARS entry '$token' (expected YYYY or YYYY-YYYY)" >&2
        exit 1
        ;;
    esac
    if [ "$((10#$first))" -gt "$((10#$last))" ]; then
      echo "Error: LOG_YEARS range '$token' ends before it starts" >&2
      exit 1
    fi
    year=$((10#$first))
    while [ "$year" -le "$((10#$last))" ]; do
      case " $LOG_YEARS_NORM " in
        *" $year "*) ;;
        *) LOG_YEARS_NORM="$LOG_YEARS_NORM $year" ;;
      esac
      year=$((year + 1))
    done
  done
  LOG_YEARS_NORM=$(echo $LOG_YEARS_NORM)
  echo "Log years: $LOG_YEARS_NORM"
else
  echo "Log years: all"
fi

# Rewrites each top-level two-space-indented `s3 { ... }` block once per year in
# `years`: appends _<year> to its sincedb_path, temporary_directory and id, and sets an exclude_pattern
# that matches (and so skips) every key without a date in that year. Recognised
# date shapes: YYYY-MM[-DD], YYYYMMDD, a /YYYY/ or =YYYY/ path segment, and the
# two-digit YYMMDD in u_ex*, *log.* and *xferlog.* names. An exclude_pattern already
# on the block is kept and OR-ed in.
read -r -d '' EXPAND_YEARS_AWK <<'AWK' || true
function year_exclude(y,    yy) {
  yy = substr(y, 3, 2)
  return "^(?!.*(?:(?:^|[^0-9])" y "(?:-[0-9]{2}|[0-9]{4}|/)|(?:u_ex|log[.]|xferlog[.])" yy "[0-9]{3,4}))"
}
function emit_block(    base, k, i, y, pat, line) {
  base = ""
  for (i = 1; i <= n; i++) {
    if (buf[i] ~ /^[[:space:]]*exclude_pattern[[:space:]]*=>/) {
      base = buf[i]
      sub(/^[^"]*"/, "", base)
      sub(/"[[:space:]]*$/, "", base)
    }
  }
  for (k = 1; k <= ny; k++) {
    y = yrs[k]
    pat = year_exclude(y)
    if (base != "") pat = "(?:" base ")|" pat
    for (i = 1; i <= n; i++) {
      line = buf[i]
      if (line ~ /^[[:space:]]*exclude_pattern[[:space:]]*=>/) continue
      if (line ~ /^[[:space:]]*(sincedb_path|temporary_directory|id)[[:space:]]*=>/) sub(/"[[:space:]]*$/, "_" y "\"", line)
      print line
      if (line ~ /^[[:space:]]*prefix[[:space:]]*=>/) print "    exclude_pattern => \"" pat "\""
    }
  }
}
BEGIN { ny = split(years, yrs, " ") }
/^  s3 \{[[:space:]]*$/ { inblock = 1; n = 0 }
inblock {
  buf[++n] = $0
  if ($0 ~ /^  \}[[:space:]]*$/) { emit_block(); inblock = 0 }
  next
}
{ print }
AWK

# Print an input config, expanded per LOG_YEARS_NORM; unchanged when no years are set.
emit_input() {
  if [ -z "$LOG_YEARS_NORM" ]; then
    cat "$1"
  else
    awk -v years="$LOG_YEARS_NORM" "$EXPAND_YEARS_AWK" "$1"
  fi
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
  { emit_input "$input_file"; cat "$SHARED_FILTER" "$SHARED_OUTPUT"; } \
    > "$PIPELINE_DIR/pipeline-${name}.conf"
  echo "Created $PIPELINE_DIR/pipeline-${name}.conf"
done
