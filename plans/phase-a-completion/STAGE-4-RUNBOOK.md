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

## Trap 3 — do NOT re-run xref, and do not let it re-run by accident

Stage 4 changes **tags and source metadata**. It does not re-chunk. `xref` links chunks to
chunks, so its existing checkpoints stay valid — reusing them saves roughly
30 × 2000 s ≈ **16 hours**. This is a deliberate decision, recorded here so a later session
does not "helpfully" clear the xref cache along with the tag cache.

---

## Priorities to close BEFORE any long run

Both are small, module-disjoint, and can run as two concurrent worktrees.

| Lane | Work | Module | Why it must come first |
|---|---|---|---|
| **A** | [#316](https://github.com/Muhanad-husn/axial/issues/316) — title-page read returns the subtitle, drops the main title (2 of 6 measured) | `holdings.py` prompt | 4.0 writes all 30 records at one model call each. Fixing after means redoing the pass |
| **B** | Expose `--ledger` (and the tags/candidates path) on `axial run` | `cli.py` | `run_pass` already takes `ledger_path`; the CLI does not expose it. Without it, parallel workers share one append-mode TSV |

Lane B is the enabler for everything in the next section. It is an argparse flag threaded
to a parameter that already exists — small, but it is the difference between a safe
parallel 4.1 and one that races on a shared file.

**Validate lane A on more than six sources.** 2 of 6 is not a rate to plan around.

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

## Sequence

1. Land lane A (#316) and lane B (`--ledger`). Two worktrees, no serialization point.
2. Verify 30/30 tree-cache hits.
3. **4.0** serial. Then verify **30 records exist and carry real author/title/date** — not
   just that the files exist. Spot-check against the real books; this is the pass that
   fixes #278's defect in the corpus, and the only control on it is a human reading it.
4. Clear `data/tags/*.jsonl` (keep the candidates log). Leave `data/xref/` alone.
5. **4.1a** tag — probe one source, then 3–4 parallel workers.
6. **4.1b** vault-write — reuses checkpoints.
7. **4.2** eval against the sim gold set → **4.3** schema freeze (reads #288's rates —
   these are only meaningful *after* 4.1; before it, 28 of 30 sources read 0.0% purely
   because they predate the sentinels) → **4.4** record the frozen distribution.

Phase A closes at 4.4. Stage 5 (HDBSCAN distillation) follows.

---

## Deliberately not scheduled

- **[#312](https://github.com/Muhanad-husn/axial/issues/312)** — `extract()` re-reads the
  full text layer and re-hashes on every call, even on a cache hit (10–410 s/source). Paid
  once, at 4.0, for ~50 min total. It touches `extract.py`/`intake.py`, the path the freeze
  depends on. Leave deferred.
- **Bounded concurrency inside the runner** (part of #277) — the detached-worker topology
  above is the 80/20 substitute. Do not build it for this run.
