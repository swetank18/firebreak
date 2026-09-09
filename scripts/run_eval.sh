#!/usr/bin/env bash
# Regenerate every number in eval/results/, in dependency order.
#
# docs/03-EVALUATION.md: "eval/results/ is produced entirely by
# scripts/run_eval.sh. Nothing in it is ever hand-edited."
#
# This takes tens of minutes. The ablation dominates: the oracle is greedy over
# a 30-candidate pool and every candidate is evaluated by RE-RUNNING THE ENGINE,
# which is the price of the ceiling being real rather than a heuristic.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
PY="${PYTHON:-python}"

echo "== realism gate =="   && $PY eval/realism.py
echo "== chain recovery ==" && $PY eval/recovery.py
echo "== H1 =="             && $PY eval/h1.py
echo "== H2 =="             && $PY eval/h2.py
echo "== seven arms =="     && $PY eval/arms.py
echo "== report =="         && $PY eval/report.py
echo "== demo scenario ==" && $PY scripts/export_demo.py
echo "== site =="          && $PY scripts/build_site.py
echo
echo "eval/results/ regenerated. Nothing in it was typed by hand."
