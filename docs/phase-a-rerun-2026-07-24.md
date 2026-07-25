# Phase A rerun — 2026-07-24/25

**Status: COMPLETE.** All 31 sources fully ingested end-to-end (extract → chunk → envelope → tag → artifacts → xref → vault write).

## What this was

A full from-scratch Phase A ingestion rerun over all 31 sources in
`data/sources/` (the 30-source canonical bibliography plus one intentional
addition, *Muslim Society* by Ernest Gellner), triggered by a second
data-loss incident that wiped `data/` (trees, envelopes, vault, tags, gold —
everything). Run pipeline: `axial extract` (serial) → `chunk` → `envelope` →
`tag` → `artifacts`/`xref` → `vault write`, driven by a dedicated streaming
orchestrator so downstream passes for an already-extracted source started
immediately rather than waiting for the whole corpus to finish extraction.

## Result

- **31/31 sources extracted**, **31/31 fully complete** through vault-write.
- **17,884 prose notes + 910 artifact notes** written to the vault (18,794 total), after quarantine recovery (below).
- **19,906 chunks** produced corpus-wide; **577 quarantined** during the initial tagging pass (malformed/refused model responses isolated per-chunk, never blocking the source) — a ~2.9-3% quarantine rate, consistent with this repo's established per-chunk fault-isolation design (`tag.py`'s existing quarantine mechanism, `TagCheckpointCorruptError`/`AllChunksQuarantinedError` machinery). A post-run quarantine-log analysis (PR #393) found 574/577 (99.5%) were recoverable parser gaps, not genuinely bad model output — after the fix and a full recovery sweep, **3 quarantined chunks remain** (all genuine `empirical_scope` cardinality/parse conflicts — see below).
- **110,801 LLM calls**, mean latency 3.01s.
- **Zero unresolved failures.** Every FAIL/ERROR in `run.jsonl` across the whole run was one of a small number of real, since-fixed issues (see below) or a transient, harmless collision — all confirmed resolved by final verification (31 unique `vault-write: OK` ledger rows, 31 persisted trees).

## Code fixes shipped during this run (all merged to `main`)

Real fault-isolation and correctness gaps found live against the real
corpus, each landed as its own `/fix`-lane PR with a regression test
reproducing the actual failure:

- **PR #375** — `chunk.py`: content-apparatus classification call failure
  now fails open to "keep as prose" instead of aborting the whole source's
  chunk output.
- **PR #376** — `vault.py`: per-note write failure now quarantines that one
  note instead of aborting the whole source's vault-write.
- **PR #377** — `vault.py`: note filenames now stay under Windows' 260-char
  MAX_PATH via a length budget. Fixed real, measured content loss: before
  this fix, "Benjamin Thomas White..." lost 165/484 notes (~34%) and
  "Andreas Wimmer..." lost 59/483 (~12%) to silently-skipped over-length
  filenames. Both re-ran clean afterward (0 notes skipped).
- **PR #378** — `tag.py`: an object-shaped (malformed) subtag from the model
  now quarantines that one chunk instead of crashing the whole source's tag
  pass with an unhandled `TypeError`. Hit live on two sources ("Muslim
  society", "From Mobilization to Revolution").
- **PR #379** — `run.py`: outcome-table printing is now encoding-safe on
  Windows, fixing a crash on source filenames containing characters outside
  the console's legacy codepage (`cp1252`) — several real corpus filenames
  (Siniša Malešević ×2, Uğur Ümit Üngör) hit this on every pass, not just
  extract.
- **PR #393** — `tag.py`: `parse_multi_value_tag_response` now coerces a
  bare-string model response for every multi-value-cardinality axis (was
  scoped to one cardinality only, missing `field`'s
  `primary_plus_secondary`), and drops a blank/whitespace secondary entry
  instead of raising. Found by analyzing the 577-entry quarantine log after
  the run: 422 quarantines were the missing-cardinality gap, 152 were the
  blank-secondary gap — 574/577 (99.5%) recoverable, not genuinely bad model
  output. A targeted recovery swept all 31 sources (stripped the 574
  fixable quarantine markers from their tag checkpoints, cleared the
  affected ledger rows, reran tag → xref → vault-write) and added 575
  prose notes to the vault. The 3 remaining quarantines are genuine
  `empirical_scope` cardinality/parse conflicts, outside this fix's scope.

Two further hardening fixes were made to the **ops driver script** itself
(not committed — a session-local orchestrator, not product code), after a
~85-minute silent stall: the driver's own serial extraction loop and
downstream worker lacked fault isolation for an uncaught exception, and its
own `print()` calls hit the same Windows encoding issue PR #379 fixed in
`axial`'s code, just unfixed in the driver — both root-caused via a live
`py-spy` stack-trace dump, fixed, and confirmed working (a subsequent
transient collision was caught and logged cleanly instead of hanging again).

## Real recoveries during the run

- **Benjamin Thomas White / Andreas Wimmer** (`vault-write`, MAX_PATH) — fixed by PR #377, ledger rows for both reset and re-run clean (0 notes skipped, down from 165 and 59).
- **"From Mobilization to Revolution" / "Muslim society"** (`tag`, subtag `TypeError`) — fixed by PR #378, both retried clean.
- **Siniša Malešević** (`extract`, Unicode encoding crash) — fixed by PR #379, retried clean.
- **"Syrias Peasantry..."** (`tag`, `[Errno 11001] getaddrinfo failed` — a transient DNS lookup failure) — this one was **not** a code gap: axial's own existing per-source fault isolation (`run.py`'s `run_pass`) caught it correctly as a clean `FAIL`, isolated to that one source, run continued normally elsewhere. Recovered via a direct manual retry of the remaining passes (tag → artifacts → xref → vault-write) once the transient network issue cleared; results recorded into the tracked metrics.
- **"The Sources of Social Power, Volume 2"** (largest source in the corpus — 1,317 chunks, ~800+ pages) — its final vault-write pass needed a manual completion after the driver was killed externally mid-run (see below); finished clean, 0 notes skipped, 1,317 chunks tagged (28.3% not-applicable, 1.2% unlisted on `theory_school`).
- **Quarantine recovery sweep** (post-run, PR #393) — 31 sources with fixable quarantined chunks (574 chunks total) recovered concurrently (10-worker pool): tag checkpoint stripped of the fixable quarantine markers, affected ledger rows cleared, tag → xref → vault-write rerun per source. 28/31 completed in the first pass; the remaining 3 ("The Logic of Violence in Civil War", "The Sources of Social Power, Volume 2", "War, Institutions, and Social Change in the Middle East") had their tag+xref rerun before an external kill, and needed only a final `vault-write` completion, run manually afterward. All 31 finished clean.

## Operational notes

- **Streaming pipeline design**: serial docling extraction fed a bounded (10-worker) downstream pool, so a source's chunk/tag/artifacts/xref/vault-write started the moment its own extraction finished, rather than waiting for all 31 extractions to complete first. This is why total wall-clock tracked close to extraction time alone rather than extraction-plus-everything-else.
- **Unexplained external kills**: the driver and backup processes were killed simultaneously by something outside this session, four separate times during the run. Investigation traced one occurrence to a burst of `pytest src -q -m "not slow" -n auto` (this repo's own commit-gate command, run via `-n auto` pytest-xdist workers) in the main `D:\axial` checkout at the exact same moment — consistent with another concurrent session's commit-gate hook firing (that session did land several `docs(decisions)` commits, DEC-40 through DEC-45, during this window). Each recovery used the pipeline's ledger/checkpoint-based resume, which worked correctly every time — no data was lost or corrupted by any of the four interruptions.
- **Backups**: 32 rolling snapshots taken over the run (every 30 min, keeping the last 8 at any time — the count above is cumulative across the run's duration, not the current retained window), from `20260724T150252Z` through `20260725T043207Z`, plus a final manual snapshot (`20260725T081829Z`) immediately before this record was merged, under `D:\axial_backups\`.

## Follow-up filed

- ~~**Issue #392** — re-run the simulated gold-set labelling (DEC-29/30/31/39's method: concurrent, non-forked Sonnet-5 subagents) against the rebuilt corpus, since `data/gold/` was lost in the same incident and the rebuilt corpus's `source_id`s shifted (DEC-42).~~ **Closed 2026-07-25** (DEC-46) — also surfaced and fixed two real bugs blocking `axial gold sample` on the rebuilt corpus (PRs #395, #396).
