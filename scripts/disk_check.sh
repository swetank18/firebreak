#!/usr/bin/env bash
# Fails above 85%. 9.2GB free at project start; MC output and node_modules will
# eat it. Run at every phase gate, not at the end.
set -euo pipefail
USED=$(df --output=pcent / | tail -1 | tr -dc 0-9)
echo "disk: ${USED}% used"
if [ "$USED" -gt 85 ]; then
  echo "FAIL: disk above 85%. Store rollout summaries, never trajectories." >&2
  du -sh scenarios eval 2>/dev/null || true
  exit 1
fi
