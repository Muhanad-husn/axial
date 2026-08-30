# Run: map-build — the forced replicate, killed mid-extraction by the founder

Run directory: map-build-20260830T032209Z

**Command:** `uv run axial map build --grouping category --force`, detached,
unbuffered, in `D:/axial`. The forced replicate of the category-grouped
variant, whose purpose was to supply the measured error bar every D1 and D2
margin in #831 is quoted against.

**Killed at ~206 of 226 extraction reads, before the consolidation stage.**
Founder's call, on the reading that the replicate buys an error bar on a
verdict it cannot change: `axial map compare` had already returned **D2
failed** (held-out purity 0.6620 against 0.7597) and **D4 failed** (8.5% of
selected passages reaching no position against a 6.9% ceiling), and neither is
a margin an error bar moves — D4 is arithmetic, and D2's gap is 0.0977 in the
wrong direction.

**Cost:** ~$0.30 spent on the extraction reads that completed; ~$1.80 and
~6.8 hours avoided by stopping before consolidation. The partial ledger was
kept, not deleted, at
`data/logs/2026-08-30-map-structural-comparison/reads.partial-replicate.jsonl`.

**Outlier worth recording:** one extraction call burned the full 600s deadline
and retried cleanly. It is the only error in the run.

**Directory handling.** `map build --grouping category` writes to
`data/map/<pin>-category/` and takes no output-directory flag, and `--force`
sets that directory's ledgers aside and rewrites its artifacts in place. The
paid first draw was copied out before launch and restored afterwards, with all
five artifacts verified byte-identical by md5 and the copy then dropped.
`--force` never destroyed a paid ledger, as its help promises.

**Next action:** none. The direction was shelved the same day (DEC-74). Full
account: `data/logs/2026-08-30-map-structural-comparison/summary.md`.
