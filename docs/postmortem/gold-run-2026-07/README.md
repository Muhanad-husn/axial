# Post-mortem: gold-corpus ingestion run, 2026-07-09 → 2026-07-12 (issue #115)

The run landed 21 of 22 sources (13,175 notes) but consumed roughly 40 hours of
wall clock and constant operator attention. This document is the evidence-backed
account of where that time went and why. Numbers come from parsing all eight
worker logs (`data/gold/ingest.w1-8.log`, ~3.5 MB, kept in the operator checkout,
not committed); the parser is `parse_run.py` in this folder and every table is
reproducible from it.

Companion documents:

- [`content-filter-exposure.md`](content-filter-exposure.md) — acceptance
  criterion 1: the moderation-refusal exposure table.
- [`model-tier-decision.md`](model-tier-decision.md) — acceptance criterion 2:
  the model-tier policy decision draft.
- [`canary-set.md`](canary-set.md) — acceptance criterion 3: the representative
  canary set and the new "pipeline ready" bar.

## The run in numbers

| measure | value |
|---|---|
| sources attempted / landed | 22 / 21 (mann-sources-of-social-power-v4 never landed) |
| source-attempt blocks in the logs | 119 (116 terminated, 3 with no END line) |
| logged compute across 8 workers | 182.0 h |
| sources that landed on their first attempt | **1 of 22** (agamben — the smallest PDF in the set, 0.4 MB) |
| notes produced | 13,175 |

Where the 182 hours went:

| bucket | attempts | hours | share |
|---|---|---|---|
| failed attempts (vault=FAIL) | 69 | 125.5 | **69%** |
| productive (first vault=OK with notes) | 21 | 41.8 | 23% |
| redundant re-runs of already-completed sources (vault=OK, 0 new notes) | 26 | 14.7 | 8% |

Two structural facts, not any single failure class, produced the 69%:

1. **A per-chunk error is source-fatal.** Extraction and envelopes are cached,
   but the chunk/tag/vault pass has no checkpoint: one bad tag on chunk 858 of
   1010 throws away the whole attempt. Long books make this compound — the
   probability that *some* chunk among a thousand trips *some* failure class is
   near 1, which is exactly what the first-try success rate (1/22) shows.
2. **The worker loop re-runs completed sources.** `ingest_worker.sh` has no
   vault=OK skip, so every round-robin pass re-burned finished sources (26
   attempts, 14.7 h, zero new notes).

## Failure taxonomy

Fatal diagnostics found in the logs: 44 `error:`-prefixed lines plus at least 9
uncaught Python tracebacks. 24 of the 69 failed attempts ended with **no**
`error:` line at all — 9 of those carry raw tracebacks; the rest died silently
(killed after stalls, or run wind-down).

| class | fatal events | issue(s) | preventable by input-representative validation? |
|---|---|---|---|
| tag out-of-vocab / empty tag / tag-shape violations | ~33 (20 logged out-of-vocab or unknown-country, 6 uncaught empty-tag `TagNotInSchemaError` crashes, 7 shape violations) | #102, #105, #106 | **Yes** — vocabulary drift only appears over hundreds of calls on real prose; a 27-note sample can never surface it |
| model response not valid JSON | 12 (10 logged, 2 uncaught `JSONDecodeError` crashes) | #72, #73, #100 | **Yes** — triggered by transliterated Arabic escapes, control characters, and giant back-matter responses (one 107 KB single response over a bibliography) |
| silent stalls / hangs (no diagnostic, killed) | 3 blocks with no END line + ~15 FAIL blocks with no diagnostic | #108, #110, #111 | **Yes** — 40 KB+ OCR'd index/bibliography chunks stall the LLM; only giant scans have those |
| `content_filter` moderation refusal | 2 | this issue (root cause A/B) | **Yes** — the corpus is *about* war and genocide; any violence-dense source would have hit it |
| `finish_reason='error'` (provider-side error) | 1 | none yet — same bucket-split as content_filter | Partially — needs volume |
| `finish_reason='length'` truncation | 1 | #67, #69, #70 | Partially |
| transport (WinError 10054 connection reset) | 1 | — | No — genuinely transient |
| envelope validation (`toc` empty) | 1 | — | **Yes** — a property of scan-quality TOCs |
| MAX_PATH `FileNotFoundError` on a long vault filename | 1 (uncaught) | #94 | **Yes** — long academic section titles |
| stale operational state (`no stored envelope found`) | 1 | — | No — sequencing error during babysitting |

**The pattern:** nothing here is exotic. Every major class is a direct,
foreseeable property of real scanned academic books — long (per-chunk risk
compounds), OCR'd (garbage sections, huge back-matter), non-English fragments
(JSON escaping), sensitive subject matter (moderation), long titles (MAX_PATH).
The suite was green throughout, because it was validated against Üngör's
paramilitarism paper: 27 notes, 0.2 MB, the *smallest and cleanest* input in the
corpus. Roughly 50 of the ~54 identified fatal diagnostics — everything except
the transport reset and operator sequencing errors — sat in classes an
input-representative validation set would have exercised before the run.

## Root causes

- **A. One status branch, two different failures.** `src/axial/llm.py` buckets
  every `finish_reason != "stop"` as "truncated" and retries the identical
  prompt 3×. That is the right remedy for `length` and the wrong one for
  `content_filter` (a moderation refusal) and `error` (a provider fault). See
  `content-filter-exposure.md` for the measured impact and
  `model-tier-decision.md` for the fix.
- **B. Corpus/model mismatch.** The whole corpus — scholarship about war,
  genocide, and state violence — ran on the cheap flash tier, which carries
  consumer-grade moderation. This is a standing hazard of the corpus, not a
  property of one book. Decision in `model-tier-decision.md`.
- **C. Wrong validation sample.** The proving input was the easiest source in
  the set, so green meant nothing. Fix in `canary-set.md`.
- **D. No failure isolation.** Per-chunk errors kill whole sources; nothing
  checkpoints the tag pass; the worker re-runs finished work. These amplified
  every class above into the 69% waste share.
- **E. Retries are invisible.** `complete()` retries silently, so the logs
  record only final failures. We cannot measure how often retries saved us —
  which is why the exposure table in `content-filter-exposure.md` has a
  lower-bound caveat.

## What falls out

Code fixes are filed as scoped sub-issues linked from #115 (this folder's PR
carries only evidence and decisions): the `content_filter` split and fallback
reroute, retry-attempt logging, the chunk-pass size guard, the worker
skip-completed guard, tag-pass checkpoint + per-chunk quarantine, and wiring the
canary set as the pipeline-ready gate.
