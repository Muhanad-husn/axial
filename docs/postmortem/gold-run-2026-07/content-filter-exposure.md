# content_filter exposure across the 2026-07 gold run (issue #115, task 1)

Method: every `finish_reason='content_filter'` occurrence in
`data/gold/ingest.w1-8.log`, mapped to its enclosing source-attempt block
(`=== <source> START/END ===`). Reproducible with `parse_run.py` in this folder.

## Measured events

Exactly **2** fatal moderation refusals across 119 source-attempts / 22 sources:

| source | worker / attempt start | where it hit | attempt cost | outcome |
|---|---|---|---|---|
| hall-schroeder-anatomy-of-power | w4, 2026-07-11T16:28 | vault pass | 2,163 s (0.6 h) | attempt fatal; the source landed later on a whole-source re-run |
| mann-sources-of-social-power-v4 | w7, 2026-07-12T09:21 | tag pass, ~chunk 858/1010 | 19,805 s (**5.5 h**) | attempt fatal; the source never landed (its 8th and final failure) |

Related, same status-field bucket: 1 × `finish_reason='error'`
(mann-sources-of-social-power-v3, w6, 2026-07-12T00:36) — a provider-side
error, also blind-retried as if it were truncation.

## What "2 events" actually means — a correction and a hard limit

Each logged event is **3 consecutive refusals of the same prompt**:
`OpenRouterClient.complete()` (src/axial/llm.py:756-764) retries a non-`stop`
finish twice before raising, and the retry loop **logs nothing** on
intermediate attempts. Two consequences:

1. **Correction to #115's framing.** The issue said hall-schroeder "hit one and
   completed anyway — one of its 3 retries rolled through." The logs do not
   support that: hall-schroeder *lost* all 3 in-process rolls (that is why the
   event is visible at all) and recovered only because the worker round-robin
   re-ran the entire source. Whether any in-process retry ever rolled through
   anywhere is unrecorded.
2. **The requested near-miss table cannot be built from these logs.** A
   moderation refusal on attempt 1 or 2 that passed on a later attempt left no
   trace. The 2 events are therefore a **lower bound on refusals** and an
   *exact* count of budget exhaustions only.

Answers to the three questions task 1 posed, within that limit:

- **How many sources rolled the moderation dice at all?** Unknowable from the
  logs (see above). Confirmed minimum: 2 of 22 (9% of sources).
- **How many won on retry 2/3?** Zero *visible* wins — invisible by
  construction. hall-schroeder's recovery was a source-level re-run, not an
  in-process retry win.
- **What would a smaller retry budget have cost?** With budget 1, every single
  refusal becomes attempt-fatal; since single refusals are invisible, the
  fatal count with budget 1 is ≥ 2 and otherwise unknowable. A larger budget
  would have bought mann-v4 more rolls at ~5.5 h per roll — treating the wrong
  disease with a more expensive dose of the wrong medicine.

## Is it a fluke or a time bomb?

Call-level: order of 30,000+ completions produced 2 visible budget
exhaustions — rare per call. Source-level: 2 of 22 sources (9%) lost at least
one full attempt to moderation, one of them terminally, and the whole corpus
shares the property that triggered it (violence-dense scholarly prose). Both
events hit the two *largest, densest* books, which is where the next run's
worst case also lives. Treat it as a low-frequency, high-cost standing hazard:
the expected loss per run is small in count but hours-per-hit is huge and the
worst case (a source that never lands) already happened once.

Consequences → `model-tier-decision.md` (policy) and the retry-observability
sub-issue (make the next run's exposure actually measurable).
