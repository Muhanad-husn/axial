set -e
LOG="data/logs/2026-08-05-gould-new-source"
for pass in extract envelope chunk interrogate artifacts; do
  echo "=== PASS $pass start $(date -u +%H:%M:%S) ==="
  uv run axial run "$pass" --worklist "$LOG/worklist.txt" --ledger "$LOG/ledger.tsv"
  echo "=== PASS $pass done $(date -u +%H:%M:%S) ==="
done
echo "=== CHAIN COMPLETE ==="
