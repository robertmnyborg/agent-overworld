#!/bin/zsh
# Open a child Claude session in a new tab next to the current one and record the parent->child edge.
# Usage: spinoff.sh "<tab title>" <handoff-brief.md> [--focus]
set -euo pipefail
export CMUX_QUIET=1
title=$1 brief=${2:A} focus=${3:-}
[[ -f "$brief" ]] || { echo "brief not found: $brief" >&2; exit 1; }
: "${CMUX_SURFACE_ID:?run inside a cmux terminal}"

pane=$(cmux --json identify | python3 -c 'import sys,json; print(json.load(sys.stdin)["caller"]["pane_ref"])')
cwd=$PWD
child=$(cmux --id-format uuids new-surface --type terminal --pane "$pane" --working-directory "$cwd" \
  | awk '{print $2}')
cmux rename-tab --surface "$child" "$title" >/dev/null
cmux send --surface "$child" "claude \"Read $brief, then continue that thread from where it leaves off.\"\n" >/dev/null

mkdir -p ~/.overworld
python3 -c 'import json,sys,time; print(json.dumps({"parent": sys.argv[1], "child": sys.argv[2], "workspace": sys.argv[3], "title": sys.argv[4], "brief": sys.argv[5], "at": time.time()}))' \
  "$CMUX_SURFACE_ID" "$child" "$CMUX_WORKSPACE_ID" "$title" "$brief" >> ~/.overworld/edges.jsonl

if [[ "$focus" == "--focus" ]]; then cmux focus-panel --panel "$child" >/dev/null; fi
echo "spun off $child ($title)"
