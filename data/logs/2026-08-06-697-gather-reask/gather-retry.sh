#!/usr/bin/env bash
# Relaunch `axial names gather` until it exits clean. Gather resumes from
# data/names/disagreements.jsonl, so a transient provider fault costs the
# in-flight batch and nothing else.
cd /d/axial || exit 1
LOG=data/logs/2026-08-06-697-gather-reask
for attempt in 1 2 3 4 5 6 7 8; do
  echo "=== ATTEMPT $attempt $(date -u +%H:%M:%SZ) ===" >> "$LOG/retry.log"
  .venv/Scripts/axial names gather >> "$LOG/console.log" 2>&1
  code=$?
  done_count=$(wc -l < data/names/disagreements.jsonl)
  echo "attempt $attempt exit=$code records=$done_count" >> "$LOG/retry.log"
  if [ "$code" -eq 0 ]; then
    echo "=== GATHER COMPLETE ===" >> "$LOG/retry.log"
    exit 0
  fi
done
echo "=== GAVE UP AFTER 8 ATTEMPTS ===" >> "$LOG/retry.log"
exit 1
