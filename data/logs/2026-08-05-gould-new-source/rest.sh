set -e
LOG="data/logs/2026-08-05-gould-new-source"
echo "=== STEP names merge start $(date -u +%H:%M:%S) ==="
uv run axial names merge --confirm-reask
echo "=== STEP names merge done $(date -u +%H:%M:%S) ==="
for step in "map build" "names materialize" "names gather"; do
  echo "=== STEP $step start $(date -u +%H:%M:%S) ==="
  uv run axial $step
  echo "=== STEP $step done $(date -u +%H:%M:%S) ==="
done
echo "=== ALL CORPUS PASSES COMPLETE ==="
