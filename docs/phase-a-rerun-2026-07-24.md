# Phase A rerun — 2026-07-24/25

**Status: in progress, placeholder — this document will be completed once the run finishes.**

## What this is

A full from-scratch Phase A ingestion rerun over all 31 sources in
`data/sources/` (the 30-source canonical bibliography plus one intentional
addition, *Muslim Society* by Ernest Gellner), triggered by a second
data-loss incident that wiped `data/` (trees, envelopes, vault, tags, gold —
everything). Run pipeline: `axial extract` (serial) → `chunk` → `envelope` →
`tag` → `artifacts`/`xref` → `vault write`, driven by a dedicated streaming
orchestrator so downstream passes for an already-extracted source start
immediately rather than waiting for the whole corpus to finish extraction.

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
  MAX_PATH via a length budget, fixing real content loss (up to ~34% of one
  long-titled source's notes were silently skipped before this fix).
- **PR #378** — `tag.py`: an object-shaped (malformed) subtag from the model
  now quarantines that one chunk instead of crashing the whole source's tag
  pass with an unhandled `TypeError`.
- **PR #379** — `run.py`: outcome-table printing is now encoding-safe on
  Windows, fixing a crash on source filenames containing characters outside
  the console's legacy codepage (several real corpus filenames, e.g.
  authors with diacritics, hit this).

## Outstanding

- Final per-source pass/fail table, quarantine counts, total LLM spend, and
  backup snapshot locations — to be added once the run completes.
- This PR is opened early, before that completion, as a stable reference
  point for other in-flight work.
