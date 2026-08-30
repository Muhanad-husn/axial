# Run: map-build — launched and killed at startup, no spend

Run directory: map-build-20260830T032123Z

**Command:** `uv run axial map build --grouping category --force`, detached, in
`D:/axial`. The forced replicate of the category-grouped variant, for #831's
D1/D2 error bar.

**Killed at ~2 minutes, before any model call.** The launcher piped the
build's stdout through PowerShell without `PYTHONUNBUFFERED`, so Python
block-buffered it and the console log would have been useless for stall
detection on a ~7.5-hour run. Nothing had been spent: no ledger had been set
aside and `reads.jsonl` was untouched. Relaunched immediately as
`map-build-20260830T032209Z`.

**Cost:** $0. **Counts:** none — the run did not reach extraction.

**Next action:** none. See `data/logs/2026-08-30-map-structural-comparison/`
for the run this belongs to.
