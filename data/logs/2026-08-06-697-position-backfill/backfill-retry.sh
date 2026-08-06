# Windows holds a handle on the freshly written .tmp (AV / indexer), so the
# atomic replace intermittently fails with WinError 5 and kills the whole
# corpus run. The pass selects notes lacking `position`, so a retry is free and
# resumes exactly where it stopped -- this loop turns a fatal lock into a pause.
LOG="data/logs/2026-08-06-697-position-backfill"
for src in data/sources/*.pdf; do
  for attempt in 1 2 3 4 5; do
    rm -f data/answers/*.tmp 2>/dev/null
    if uv run axial position-backfill "$src" >> "$LOG/console.log" 2>&1; then
      echo "OK   $src (attempt $attempt)"
      break
    fi
    echo "RETRY $src attempt $attempt failed"
    sleep 5
  done
done
rm -f data/answers/*.tmp 2>/dev/null
echo "=== BACKFILL SWEEP COMPLETE ==="
