set -e
LOG="data/logs/2026-08-05-gould-new-source"
for step in "names build" "names merge" "map build" "names materialize" "names gather"; do
  echo "=== STEP $step start $(date -u +%H:%M:%S) ==="
  uv run axial $step
  echo "=== STEP $step done $(date -u +%H:%M:%S) ==="
done
echo "=== CORPUS PASSES COMPLETE ==="
