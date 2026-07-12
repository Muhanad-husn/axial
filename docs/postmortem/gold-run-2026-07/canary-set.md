# Representative canary set and the "pipeline ready" bar (issue #115, task 3)

The old proving input — Üngör's paramilitarism paper — is the smallest file in
the corpus (0.2 MB, 27 notes, clean modern PDF). A suite validated against it
was green while never touching a single property that defines this corpus.
Üngör is hereby demoted to a smoke test. "Pipeline ready" is redefined against
the five sources below, chosen from the run's measured behavior to jointly
cover every input property that produced a failure class.

## The canaries

| canary | measured difficulty (this run) | properties it pins |
|---|---|---|
| mann-sources-of-social-power-v4 | 123 MB, ~1010 chunks; 0/8 attempts landed; 12.3 h burned; hit 5 distinct failure classes (missing envelope, transport reset, invalid JSON ×2 incl. a 107 KB bibliography response, content_filter) | the biggest OCR'd scan; giant back-matter; per-chunk risk compounding over a long book; moderation on violence-dense prose |
| tilly-from-mobilization-to-revolution | 23.9 MB 1978-era scan; 9 attempts; empty-`toc` envelope failure; one silent hang (no END line) | oldest/worst OCR; scan-quality TOC; stall behavior |
| kalyvas-logic-of-violence-in-civil-war | 8 attempts, 7 failed; 10.7 h; invalid JSON ×2 | the most violence-dense prose end-to-end (moderation hazard density) |
| ayubi-over-stating-the-arab-state | 5 attempts; 13.0 h; invalid JSON ×3, all on transliterated Arabic (`ra'k`, `I'ilat-ra'k` — escape sequences breaking the model's JSON) | non-English fragments / transliteration breaking structured output |
| hall-schroeder-anatomy-of-power | 9 attempts; 13.3 h; the one recovered content_filter hit; an uncaught empty-tag crash; one silent hang | moderation survivor case; tag-vocabulary drift; 23 MB scan |

Together the five cover: giant scans, worst OCR, back-matter blobs, non-English
fragments, violence density, vocabulary drift over 1000+ calls, and every
failure class the run exhibited except pure transport noise. All five are
already in `data/sources/`.

## The "pipeline ready" bar

Before any future corpus-scale run, and as the acceptance bar for any change
that claims to harden the pipeline:

1. **All five canaries ingest end-to-end, each in a single attempt, unattended**
   — no manual re-queues, no kills, no operator intervention.
2. **Zero source-fatal chunk errors.** Per-chunk problems must resolve to a
   logged quarantine/skip, and quarantined chunks stay under 2% per source.
3. **Bounded wall clock.** Every canary attempt finishes or fails loudly within
   its projected time envelope — no silent stalls (a hang that needs a human to
   notice it is a failure regardless of eventual output).
4. The unit/acceptance suite stays green — necessary, but **no longer
   sufficient**: a green suite without a green canary pass proves nothing about
   corpus readiness, as this run demonstrated.

Wiring the canaries into a runnable gate (fixture manifest + a
`pipeline-ready` runbook command that executes the five and checks 1–3) is a
scoped sub-issue under #115. Until that lands, the bar is applied manually:
run the five canaries and hold the results to the four criteria above.

Cost note: a canary pass is ~5 sources ≈ a quarter of the run's productive
compute — hours, not the 182 h the corpus consumed. It is the 80/20 point:
expensive enough to be representative, cheap enough to run before every
corpus-scale event.
