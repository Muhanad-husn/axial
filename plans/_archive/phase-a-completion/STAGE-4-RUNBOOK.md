# Stage 4 — the freeze: operator runbook

**Audience:** a fresh session running a stage-4 corpus operation. Read
[`TRACKER.md`](TRACKER.md) first for status; this file is *how to run it*.

Every planned Phase A slice is built (wave 4 merged #313/#314/#315). What remains is
operations. This runbook exists because stage 4 is long, expensive, and has three traps
that are invisible until you have already paid for them.

**Last updated:** 2026-07-21, after the wave-4 merge.

---

## The measured facts this plan rests on

Checked against the real repo on 2026-07-21, not assumed:

| Fact | Value | Why it matters |
|---|---|---|
| Cached structural trees | **32** (all 30 sources hit) | `extract()` returns at `out_path.exists()` **before docling loads** (`extract.py:558`). **Stage 4 never invokes docling** |
| Real chunks | **18,468** (excluding `.skips.jsonl`) | The tag denominator |
| `llm.votes_by_pass.tag` | **3** (DEC-31/#294) | Tag is 3 model calls per chunk → **~55,400 calls** for a corpus re-tag |
| Vault prose notes on disk | **18,410** | All carry fabricated slug titles + null authors until re-written |
| `data/run/ledger.tsv` | **absent** | Clean slate; nothing to reconcile |
| `data/source_meta/` | **empty** | 4.0 has not run |
| Runner concurrency | **none** | `run_pass` is a serial loop; `plans/run/README.md` deferred bounded concurrency |
| Tag checkpoints | **18,410 records**, all 30 sources | The corpus is **already fully tagged** (single-draw). A checkpointed chunk is reused verbatim and **never re-sent to the model** (`tag.py:1733`) |
| Artifacts checkpoints | **30 files** | Reused, 0 calls |
| **Xref checkpoints** | **0 — EMPTY** | Xref recomputes in full: 18,410 calls ≈ 16 h. See trap 3 |
| Gold label sheet | 120 chunks | 4.2's eval denominator — **120 × 3 = 360 calls**, not 55,400 |

### Model routing — check this before assuming

| Pass | Tier | Model | Reasoning |
|---|---|---|---|
| `envelope` | `production_high` | `deepseek-v4-pro` | **ON** |
| `holdings` (4.0's call, incl. the title-page read) | default `production_low` | **`deepseek-v4-flash`** | ON |
| `tag` | default `production_low` | **`deepseek-v4-flash`** | **OFF**, votes 3 |

Only `envelope` is overridden to `deepseek-v4-pro` (`model_by_pass`). **`tag` and
`holdings` both run on flash.** A plan that assumes pro-with-reasoning for the tag or
title-page passes is assuming something that is not configured.

---

## Trap 1 — `vault-write` is not a cheap tail step

`run_vault_write` internally calls `run_tag`, `run_artifacts` **and `run_xref`** for each
source (`vault.py:500-535`). `xref` is the ~2000 s/source pass. Running
`axial run vault-write --corpus` cold would do the entire pipeline tail in one serial
process — tens of hours.

**Split it.** Run `tag` to completion first; `vault-write` then reuses the per-source
checkpoints (`data/tags/`, `data/artifacts/`, `data/xref/`) instead of recomputing them.

## Trap 2 — checkpoints make a re-tag silently no-op

`data/tags/` already holds 31 `.jsonl` checkpoints from the last corpus pass, and the
ledger's done-predicate skips a source that is already done. A re-tag that does not first
clear its checkpoints **will skip every source and report OK**, leaving the old
single-draw tags in place — no error, no signal.

**Before 4.1:** clear `data/tags/*.jsonl` (keep `theory_school_candidates.jsonl`) and
ensure no stale `tag` rows are in `data/run/ledger.tsv`. Verify by checking that the run's
first source actually makes model calls.

## Trap 3 — `data/xref/` is empty, so xref recomputes — but it is MEASURED, and it is fine

`data/xref/` holds **0 entries** even though the corpus vault was built with xref links
(#272), so `run_xref` recomputes: one LLM call per chunk. Since `vault-write` calls
`run_xref` internally (trap 1), any corpus-wide `vault-write` pays it.

**Do not extrapolate this from the "~2000 s/source" figure in memory — that is the max,
not the median.** The 2026-07-20 #272 rollout measured the real thing, all 30 sources,
in `data/logs/xref-rerun.log`:

```
min 45 s · median 945 s · max 2168 s
total work 7.8 h  →  ~2.6 h wall clock at 3 workers
```

**A full corpus `vault-write` — xref from scratch, tag and artifacts reused — is a ~2.6-hour
job, not a 16-hour one.** Earlier versions of this runbook said 16 h. That was wrong.

**The driver already exists and is proven:** `data/logs/_drivers-archive/xref_rerun.py` —
`axial vault write` per source, 3 workers via `ThreadPoolExecutor` + `subprocess`,
resumable through per-source done-markers in `data/logs/xref-done/` (all 30 present). Its
own docstring independently confirms two things this runbook derived from the code:
"LLM-bound, no docling" and "reuses tag/artifact checkpoints (no re-tag)".

Note it bypasses `axial run` entirely, so it produces **no `RunSummary`, no #288 rates, and
no run-logging**. That is the argument for lane B: parallelising the *supported* runner
path rather than reaching for the driver again.

**After the next run, do not clear `data/xref/`** — populated checkpoints make every
subsequent vault-write nearly free.

## The decoupling — the #278 fix does NOT need a re-tag

These are two separate operations with wildly different costs, and the plan previously
bundled them:

| Operation | What it fixes | LLM cost | Wall clock, 3 workers |
|---|---|---|---|
| **4.0 + vault-write** | 18,410 notes carrying fabricated slug titles + null authors | ~30 holdings calls + 18,410 xref | **~2.6 h** (measured) |
| **Re-tag** (best-of-3) | Tag quality: single-draw 0.73 → best-of-3 0.918 on `theory_school` | **~55,400 calls** | ~8–15 h (est.) |

The metadata defect — the headline concern since #278 — is a **single ~2.6-hour run** away
and does not need a re-tag at all. Do it first and independently: the corpus stops lying
about its own bibliography regardless of what is decided about tagging.

The re-tag estimate is derived from the measured xref rate (~1.5 s/call) and is **not
measured** — tag echoes the chunk and emits structured output, so it is likely slower.
Probe one source before committing.

---

## Priorities closed before the long runs — ✅ both landed

| Lane | Work | Outcome |
|---|---|---|
| **A** | [#316](https://github.com/Muhanad-husn/axial/issues/316) title-page read | **Closed**, PR #319 (`02b9fb0`), plus PR #322 (`225fc79`) |
| **B** | `--ledger` on `axial run` | **Closed**, PR #318 (`50c954d`) |

### Lane A's root cause was not the prompt, and not the model — record this

This runbook previously advised trying `model_by_pass: holdings: production_high` before
rewriting the prompt. **That was measured and refuted: `production_high` scored 20/30 with
five regressions — worse than the flash baseline.** Do not retry it.

The real cause was upstream of the model entirely: the **running-furniture strip counted a
book's main title as a recurring header** — which it is, on every body page — and deleted
it from the title page itself. That removed the printed main title from **7 of 30 sources**;
on `ugur-paramilitarism` and `chouliaraki` the main title reached the model **on no page at
all**, so no prompt and no tier could have read it.

The fix renders the opening pages **twice**: cleaned (byte-unchanged) for the completeness
judgment, and *as printed* for the bibliographic read.

**Measured live:** the six multi-line-title sources went 6/30 → **30/30** correct draws
(five draws each); a full 30-source pass went 21/30 → **29/30**, no source made worse; zero
holdings flags.

The lesson generalises: "the model got it wrong" was wrong three times over here — the model
never saw the data. Check what actually reaches the prompt before tuning the prompt or the
tier.

### Still owed on main

**PR #322 merged (`ea753f7`, 02:41) with its validation outstanding** — the plan commit
four minutes earlier had named Step 1 as its merge gate. `data/source_meta/` is still
empty, so neither number has been taken. #322 only reframes the prompt's framing sentence,
but it is a live-prompt change that no test can score, so the two numbers are owed against
main: `holdings_flag` null in all 30, and titles no worse than 29/30.

Also open: **[#320](https://github.com/Muhanad-husn/axial/issues/320)** closed won't-fix
(`tilly`'s title layer is garbled in the file — 1 of 30, correct it by hand in the record),
and **[#323](https://github.com/Muhanad-husn/axial/issues/323)** — no live positive control
exists for the holdings flag, so every "flag raised" test pins plumbing, not judgment.

---

## What can actually run in parallel

The runner has no internal concurrency, so parallelism means **N detached OS processes over
disjoint source subsets** — the topology used for the gold ingest.

**Docling does not constrain this.** All 30 trees are cached and `extract()` returns before
docling loads, so the "never run two `axial extract` concurrently" rule does not bind stage
4. *Guard:* if any source file changed, its content-hashed `source_id` changes, the cache
misses, and docling runs — re-introducing the OOM risk. Confirm 30/30 cache hits before
launching workers.

What genuinely serializes under parallel workers is **shared append-mode files**:

1. `data/run/ledger.tsv` — one row per source completion (`_append_ledger_row`, mode `"a"`)
2. `data/tags/theory_school_candidates.jsonl` — one row per unlisted proposal

Disjoint worklists mean workers never contend for *work*; they contend only for these two
files. Lane B removes hazard 1. Hazard 2 is low-volume (1 row today) but feeds #288's
rates and therefore 4.3 — worth a per-worker path or a post-run integrity check.

### Per-step recommendation

| Step | Cost | Run it |
|---|---|---|
| **4.0** extract → writes `data/source_meta/` | 30 sources × (1 model call + #312's 10–410 s re-read) ≈ **50–70 min** | **Serially.** It is short, it is the load-bearing correctness step, and serial means zero shared-file risk. Do not parallelize the cheap step |
| **4.1a** tag | **~55,400 model calls** (18,468 × 3) | **Parallel, 3–4 workers**, disjoint worklists. This is the only step where parallelism is worth the coordination cost |
| **4.1b** vault-write | 18,410 notes, reusing tag/artifacts/xref checkpoints | Measure on one source first (see below), then parallelize if warranted |
| **4.2–4.4** eval, freeze, distribution | cheap, no model calls (`eval` records `model: null`) | Serially |

### Measure one source before launching thirty

Run 4.1a over a **single** source, time it, and multiply. A 55k-call pass is not something
to discover the cost of at hour six. `ugur-paramilitarism` (277 chunks) is a good probe:
cheap, and it is one of only two sources currently carrying `theory_school` sentinels.

### Worker topology

```
# after lane B lands
data/run/ledger.w1.tsv  worker 1  ← worklist.w1.txt  (10 sources)
data/run/ledger.w2.tsv  worker 2  ← worklist.w2.txt  (10 sources)
data/run/ledger.w3.tsv  worker 3  ← worklist.w3.txt  (10 sources)
```

Launch detached via `Start-Process cmd.exe /c` with `cmd`'s `>>` redirection — **not**
PowerShell `*>>`, which writes UTF-16 and breaks log monitors. Concatenate the per-worker
ledgers when all three finish.

Every run writes `data/logs/<YYYY-MM-DD>-<run-name>/` with `run.jsonl`, `console.log`, and
`summary.md`.

---

## Cross-session hazard — read this if you are running two Claude sessions

`tests/conftest.py` snapshots and restores `data/trees/`. **Running `pytest` while a corpus
pass is live will clobber the running pass's tree cache.** If one session is running 4.0 or
4.1, no other session may run the test suite — including the per-commit gate, which means
**no commits from a second session during a corpus run**.

Plan sessions accordingly: a corpus-running session does operations only; build work waits,
or happens before the run starts.

---

## Can a stratified sample replace the full re-tag?

Probably yes for the *decisions*, and this is worth settling before spending 55,400 calls.
What each remaining step actually needs:

| Step | Needs | Full corpus? |
|---|---|---|
| 4.2 eval | the **120** gold chunks tagged under the new regime | **No** — 360 calls |
| 4.3 freeze (`theory_school` KEEP, #288 rates) | a *proportion estimate* | **No** — a stratified n≈1,500–2,500 gives ±2% at 95% on a ~25% rate |
| 4.4 frozen distribution | a distribution estimate | **No** — same sample |
| Stage 5 #298 | **stratified teacher labels**, ~100–300/class | **No** — stratified by design |

Every one of these is served by **one** stratified sample. And note the circularity in the
current plan: paying 55,400 LLM calls to label the whole corpus, then running stage 5 to
learn how to avoid paying LLM calls to label the whole corpus. `docs/exploration/hybrid-tagging-classifier.md`
is explicit that distillation is a **post-schema-freeze** move — which puts the sample
before the freeze, not the full re-tag.

**Two methodological cautions:**

1. **Stratify on the existing single-draw tags, but not only on them.** They are a valid
   stratification variable (it need only correlate, not be perfect). But `not-applicable`
   and `unlisted` were only available to 2 of 30 sources, so the old tags **cannot**
   stratify for them. Add a proportional **random** stratum so values the old tagger never
   had access to can still surface.
2. **The vault ends mixed-provenance** — a re-tagged fraction at best-of-3, the rest at
   single-draw. Phase B reads the vault. Either mark provenance per note or accept it
   knowingly; do not discover it later.

**Residual risk:** if distillation fails to reach teacher parity, the full re-tag is still
owed — the sample is then a ~15% insurance premium, not a loss.

### …but the measured numbers weaken the cost case for sampling

Sampling was worth proposing when the re-tag looked like a multi-day ordeal. On the
measured rate it is **roughly one overnight run at 3–4 workers**. Against that, sampling
buys ~6–13 hours of unattended machine time and costs:

- **estimated** rather than exact rates for the 4.3 freeze,
- a **mixed-provenance vault** that Phase B then has to reason about,
- an extra decision and an extra sampling-design review.

Unattended overnight time is the cheapest resource in this project. **Recommend the full
re-tag** unless the one-source probe comes back far slower than the xref rate implies —
in which case the stratified design above is ready to use. The stage-5 circularity
argument (paying to label everything, then building the thing that avoids paying to label
everything) is real but is an argument about *sequencing stage 5*, not about skipping a
one-night run that makes the freeze exact.

## Sequence

1. ✅ Lanes A and B are landed (see *Priorities closed* above). **Do not retry the
   `production_high` tier on `holdings`** — measured at 20/30 with five regressions.
2. Verify 30/30 tree-cache hits.
3. **4.0** serial — **but stop after 3–5 sources and read the output** before letting it
   run to 30. This is the first real exercise of the wired holdings + title-page path at
   this tier; judge it on its own first responses.
4. Verify **30 records carry real author/title/date** — not just that files exist.
   Spot-check against the real books. The only control on this is a human reading it.
5. **Metadata rewrite (P0-1d)** — get #278's fix into all 18,410 notes without a re-tag.
6. **Decide sample-vs-full re-tag** (section above). If sampling: draw the stratified set,
   tag it, and carry it into 4.2/4.3/4.4 *and* stage 5's teacher set.
7. **4.2** eval → **4.3** freeze (#288's rates are only meaningful on re-tagged chunks;
   before that, 28 of 30 sources read 0.0% purely because they predate the sentinels) →
   **4.4** record the frozen distribution.

Phase A closes at 4.4. Stage 5 (HDBSCAN distillation) follows.

---

## Deliberately not scheduled

- **[#312](https://github.com/Muhanad-husn/axial/issues/312)** — `extract()` re-reads the
  full text layer and re-hashes on every call, even on a cache hit (10–410 s/source). Paid
  once, at 4.0, for ~50 min total. It touches `extract.py`/`intake.py`, the path the freeze
  depends on. Leave deferred.
- **Bounded concurrency inside the runner** (part of #277) — the detached-worker topology
  above is the 80/20 substitute. Do not build it for this run.
