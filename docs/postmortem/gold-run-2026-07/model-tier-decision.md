# Model-tier policy for sensitive content (issue #115, task 2)

**Status: DRAFT — recommendation prepared by the orchestrator, awaiting founder
ratification.** Once ratified, the decision line below moves from "proposed" to
"decided" and the implementation sub-issue proceeds.

## The problem

The corpus is scholarship about war, genocide, and political violence. The run
executed every call on the flash tier (`llm_tier = "production_low"`,
deepseek-v4-flash), whose consumer-grade moderation refuses some of that prose
(`finish_reason='content_filter'`). Measured exposure (see
`content-filter-exposure.md`): rare per call, but 2 of 22 sources lost a full
multi-hour attempt to it and one source never landed. Separately,
`src/axial/llm.py` treats every non-`stop` finish reason as truncation and
blind-retries the same prompt 3× — the right remedy for `length`, the wrong one
for a moderation refusal.

## Options weighed

| option | reliability | cost | verdict |
|---|---|---|---|
| (a) whole corpus on a higher/unmoderated tier | fixes moderation; does nothing for the other 95% of failure classes | multiplies the price of ~100% of calls to treat a hazard measured on ≪1% of them | rejected as default |
| (b) flash default + `content_filter`-specific reroute of only the refused chunk to a designated fallback model | targets exactly the failing calls; also forces the correct `finish_reason` split in `llm.py` | flash + ε (fallback price paid only on refusals) | **recommended** |
| (c) per-source tier selection | coarse — a whole book pays the higher tier for a handful of hot chunks; needs manual pre-classification; still needs (b)'s machinery for surprises | intermediate, unpredictable | rejected as primary; possible later overlay |

## Proposed decision

1. **Adopt (b).** Keep `production_low` as the corpus default. On
   `finish_reason='content_filter'`, do not re-ask the same model — reroute
   that single completion to a designated fallback model (a
   `content_fallback_model` key in `secrets.toml`, chosen for not moderating
   scholarly descriptions of violence; candidate selection happens in the
   implementation sub-issue). If the fallback also refuses, quarantine the
   chunk (skip, log, continue) — a refused chunk must never be source-fatal
   again.
2. **Split the `finish_reason` taxonomy in `llm.py`** (this is root cause A,
   and it is required regardless of which option is chosen):
   - `length` → retry the same prompt (retry genuinely helps here); keep the
     current budget.
   - `content_filter` → no same-prompt retry against the same model; reroute
     per (1).
   - `error` → treat as a transient provider fault: backoff retry, same as
     transport errors and 5xx (observed once in this run, on mann-v3).
   - transport / 429 / 5xx → existing backoff behavior, unchanged.
   The general principle: **blind same-prompt retry is a remedy for transient
   faults only, never for content-caused failures** (moderation, out-of-vocab,
   malformed-output classes), which need a reroute, a quarantine, or a
   re-ask-with-feedback — not the same dice again.
3. **Make retries observable** so the next run can measure real moderation
   exposure instead of a lower bound: log every retry attempt with pass name,
   attempt number, and finish reason.

Items 1–3 are filed as scoped sub-issues under #115; none of them are
implemented in the post-mortem PR that carries this document.

## Residual risk

The fallback model's own moderation behavior is unverified until tested — and
the refused prompts were not recorded, so validation needs the retry-logging
sub-issue (or a canary re-run) to supply real refused chunks. The quarantine
path in (1) bounds the damage either way: worst case is a logged skipped chunk,
not a lost source.
