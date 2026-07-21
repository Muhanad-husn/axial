# Phase A completion — live tracker

**Cold-start handoff.** A fresh session reads this file first, then the plan. It is
the single place that says *what is done and what is next*. Update the checkboxes
as slices land. Issues remain the system of record; this is the map over them.

- **Branch:** `claude/phase-a-hybrid-tagging-sqx2xc`
- **Plan:** [`README.md`](README.md) (stages, waves, deferred decisions)
- **Decision:** `docs/DECISIONS.md` → DEC-32
- **Last updated:** 2026-07-21 — **wave 3 in flight**: #309 (run·03) and #310 (run-logging·02) merged; #303 still building

## Read-me-first (30-second orient)

1. This plan finishes **Phase A** (the `sub:ingestion-v0` ingestion pipeline). Phase B
   (`sub:analysis-v0`) is out of scope.
2. **Operating stance (DEC-32):** we build against the *simulated* academic gold set
   now (DEC-29/30/31). Every number is a provisional dev signal; the mechanism is
   real. Real labels re-run the same eval later; the sim path is torn down first (#295).
3. **Phase A closes at stage 4** (frozen corpus + gold validation + schema freeze).
   Stage 5 (HDBSCAN distillation) is the closing *eval* on top; its build is separate.
4. Work runs through the TDD harness: one slice = one worktree = one red-green PR.
   Worktrees prepare PRs; **the founder approves every merge** (DEC-3).

## Status board

Legend: ☐ todo · ◐ in progress (note PR/worktree) · ✅ merged

**Plan-ready:** ✅ = slice plan written · ✎ = fix-lane, no plan needed (build from the issue).

### Stage 0 — clean the shop (hygiene, parallel with stage 1)
- ✅ 0a #291 — safe GC for orphaned derived artifacts (`reconcile.py`, new) — PR #301 merged `209bfec`
- ✅ 0b #270 — structured run logging — plan ✅ `plans/run-logging/` (2 slices). ✅ slice 01 (seam + `extract`) — PR #305 merged `853f780`; ✅ slice 02 (`envelope`/`tag`/`eval`) — PR #310 merged `301e37a`. **`eval` records `model: null`** — it makes no LLM call; the plan was wrong to call it model-bearing and was corrected, not the code
- ☐ 0c #289 — verify gold-sheet dropdowns (`gold.py`) — ✎ fix-lane, verify-first

### Stage 1 — metadata correctness (one ordered chain, before any re-tag) — plan ✅ `plans/intake-metadata/`
- ✅ 1·01 #284 — holdings check → model-adjudicated rewrite (`holdings.py`) — PR #304 merged `affd369`. **Now live in the ingest path via #303.**
- ✅ 1·01b #303 — wire the judgment into the ingest path — PR #311 merged `41aba59`. `extract()` builds a client only for an unjudged source; the §7.12 record gains `holdings_checked`, so a judged source constructs **no client at all**. Gate 4 over all 30: pass 1 = 30 calls (one each), pass 2 = **0 calls, 0 clients**; biblio coverage identical to #307 (author 29/30, title 28/30, date 30/30, 0 crashes); 0 flags raised. **P0-1b is true of the pipeline now, not just of `intake()`.**
- ✅ 1·02 #285 — persisted source-metadata record; **sole origin of author/title/date (P0-1d)** — PR #307 merged `fa6b2d9`. Took two rounds: the first failed gate 4, the rework deleted the heuristic and extended slice 01's model call to read + cross-check the title page (author 29/30, title 28/30, date 30/30, 0 crashes). **No longer dormant — #303 passes the client.**
- ☐ 1·03 #278 — **resolved: remove** author/date from the envelope (intake owns them); vault writer composes from both (needs 02). **Released and startable** — its two blockers (#285, and #270·02's `envelope.py` fan-out) have both merged. **Sequence it after #303, never beside it** — same lane, same intake/envelope metadata boundary.

### Stage 2 — tag quality (before any re-tag)
- ✅ 2a #294 — best-of-N voting on blind axes (`tag.py`; **predecessor of stage 5**) — PR #302 merged `aa0607d`; abstention settled in **DEC-33** + spec §7.14
- ☐ 2b #288 — report not-applicable / unlisted rates — ✎ fix-lane. **Now startable**: #277·03 landed the `RunSummary.rates` attachment point it was waiting on

### Stage 3 — runner — plan ✅ `plans/run/` (3 slices)
- ✅ 3·01 #277 — runner core + pass registry + failure isolation (walking skeleton) — PR #300 merged `e8f9661`
- ✅ 3·02 #277 — unified resume ledger + done-predicate (replaces today's 3 mechanisms) — PR #306 merged `6047450`, ledger relocated by PR #308. Ledger at `data/run/ledger.tsv`, keyed `(pass, source_id)`; `extract`/`envelope` use a file-exists predicate, the rest use the ledger. **P1-4 is satisfied for a named worklist** — the corpus glob is still slice 03.
- ✅ 3·03 #277 — source-set inputs (worklist + corpus glob) + end-of-run summary — PR #309 merged `1237e8d`. `RunSummary` is a returned structured value with a `rates` attachment point, so **#288 is unblocked**. **#277 stays open**: the issue's bounded-concurrency scenario is deferred by `plans/run/README.md`, so the PR said `Part of #277`, not `Closes`

### Stage 4 — freeze (operation, not a slice) → **PHASE A CLOSES HERE**

> ⚠️ **4.0 is new and load-bearing. Do not skip it.** `data/source_meta/` on the real
> corpus is **empty** — #303's gate-4 validation deliberately wrote to a scratch
> directory, so no source has a persisted record yet. #278 makes the vault writer
> compose author/title/date **from those records**. Re-tagging before a real ingest
> pass has written them freezes ~17k chunks carrying empty bibliographic metadata —
> the exact defect #278 exists to fix, baked in and expensive to undo.

- ☐ **4.0 run a real ingest pass over all 30 sources to write `data/source_meta/`** — one
  reasoning-ON call per source (~30 calls); verify 30 records exist and carry real
  author/title/date before proceeding
- ☐ 4.1 re-tag the corpus via #277 with stages 1–2 in place
- ☐ 4.2 score against the sim gold set (P0-10 eval)
- ☐ 4.3 freeze schema (ratify `theory_school` KEEP, DEC-31, on corpus-wide numbers) —
  reads #288's not-applicable/unlisted rates, so **land #288 before this**
- ☐ 4.4 record the frozen tag distribution (input to stage 5)

### Stage 5 — HDBSCAN distillation eval (gated behind stage 4)
- ☐ 5a #296 — embedding pass + vector store
- ☐ 5b #297 — HDBSCAN readiness map + cluster-(-1) router
- ☐ 5c–5e #298 — stratified teacher labels → head classifiers → quality-per-dollar verdict

## Next action

**Wave 3 is complete.** All three PRs merged — #309 (`1237e8d`, run·03), #310
(`301e37a`, run-logging·02), #311 (`41aba59`, #303 holdings wiring). `main` is green
at **1124 passed** on the src tier. Every worktree and branch is torn down; the repo
is `main` only, local and remote, working tree clean.

**Wave 4 has not started** — the founder is running it in a fresh session.

Two things a cold start should know about wave 3:

- **A harness bug was fixed mid-wave.** `.claude/hooks/block-merge.ps1` resolved the
  current branch from `$PSScriptRoot`, which only exists in the launch checkout
  (always `main`), so it false-blocked **every** subagent push from a worktree. It
  now uses `commit-gate.ps1`'s cwd resolution (leading `cd <dir> &&` → `$j.cwd` →
  session dir). Verified the gate still blocks pushes from a main checkout, pushes
  naming `main`, and `gh pr merge`. Snapshot `d0b5e41` in `axial-harness`.
- **#270 slice 02 was released from serialization and landed clean.** The lanes that
  contended for `envelope`/`tag` had merged first, as planned. `llm.py` gained
  `model_for_pass()` — a cross-phase shared module, so CI green was the gate.

**RESOLVED — the "model path is dormant in production" warning that stood here through
wave 2 is closed by #311.** `extract()` now supplies a client for an unjudged source, so
the reasoning-ON holdings + title-page call runs in the real pipeline. The wave-2 concern
that a real ingest would record the wrong Heydemann metadata no longer applies: gate 4
re-measured the wired path over all 30 and got #307's numbers exactly (author 29/30,
title 28/30, date 30/30, 0 crashes, 0 flags), with Heydemann correctly `unavailable`.

**The lesson that carried wave 2 into wave 3 still stands: a green suite is not evidence.**
#307's suite was green and its corpus check was not — it took a second round after gate 4
found a pypdf `NullObject` crash, embedded metadata for *a different book* recorded as a
confident value, and a title-page fallback reading 2 of 13 real cases. Wave 3 confirmed the
rule twice more: #303's own cross-cutting regression (four envelope record-transcript tests
asserting "exactly ONE recorded prompt") was caught by **CI**, not by the local suite.

One note carried forward from the merged lanes:

- **#306 edited a locked slice-01 test** (`tests/test_run.py`, `OK` → `SKIP` on two
  sources) — correct, since the file-exists predicate now reads the fixtures that test
  pre-places, but no source in *that* test exercises the success path end to end any more;
  `tests/test_run_resume.py` covers it instead.

*(Resolved: the ledger's placement under `data/logs/` — moved to `data/run/` by PR #308,
merged. `data/logs/` is one directory per run; the ledger outlives every run and is read
at the start of the next one, so it is runner state, not a log. No migration was needed —
nothing had been written to disk yet.)*

### Wave 4 — what to start in the fresh session

All three are unblocked and **module-disjoint, so they can run as three concurrent
worktrees**. Nothing is in flight; `main` is clean.

| Lane | Work | Plan | Notes |
|------|------|------|-------|
| **intake-metadata** | **#278** envelope cleanup (slice 03) | ✅ `plans/intake-metadata/03-envelope-metadata-cleanup.md` | The only planned slice left in Phase A. Drops author/title/date from the envelope's locked shape; vault composes from record + envelope. Both blockers (#285, #270·02) have merged |
| **stage 2** | **#288** not-applicable / unlisted rates | ✎ fix-lane | Reads `RunSummary.rates` (landed in #309) and the candidates log. **Land before stage 4.3** — the `theory_school` KEEP ratification reads these rates |
| **stage 0** | **#289** gold-sheet dropdowns | ✎ fix-lane | Verify-first; likely already correct. Smallest of the three |

Then **stage 4** (freeze = Phase A closes), respecting **4.0 first** — see the ⚠️ on the
stage-4 checklist above. Then **stage 5**.

**Deferred, filed, not scheduled:** [#312](https://github.com/Muhanad-husn/axial/issues/312)
— `extract()` re-reads the full pypdf text layer and re-hashes the file on every call, even
on a tree-cache hit. Measured at gate 4: a no-op corpus pass costs 10–410 s per source with
**zero** model calls (~50 min per pass). Pre-existing; #303 made it dominant. Deliberately
**not** scheduled before stage 4 — it touches `extract.py`/`intake.py`, the path the freeze
depends on.

See [`README.md`](README.md) → *Execution — parallel feature lanes & worktrees* for
the full conflict rationale.

## Decisions settled during planning (a builder should know)

- **#278 → remove, not populate.** Envelope drops author/title/date; intake's
  source-meta record (P0-1d) is their sole origin; vault writer composes `source_meta`
  from both. This couples #278 to #285. Founder should sanity-check.
- **#294 abstention** = per-axis `abstained: true` + `primary: null` + preserved
  draws; a distinct signal from `not-applicable`/`unlisted`, never a vocab value.
- **#270 = slice** (2 slices), not fix-lane — new cross-cutting seam.
- **#277 = 3 slices** (core → unified ledger → sources+summary); the "3 resume
  mechanisms" are, in the real code, a TSV ledger + file-exists + per-source xref
  checkpoint (the issue's `loop_worker.py` / `xref-done/` names don't exist here).
- **#291 = 1 slice**, dry-run-by-default, delete only under `--apply` + confirm.

## How to resume in a fresh session

1. Read this file, then `README.md`, then DEC-32, then the relevant lane's plan.
2. `git checkout main && git pull` (the plans live on `main`; cut each slice's
   `feat/<feature>/NN-slug` branch from there).
3. Check the status board above and each issue's open PRs for anything ◐ in flight.
4. Pick the next ☐ slice per its lane order; run it through the harness; open a PR;
   update its checkbox to ◐ (PR #), then ✅ on merge.
