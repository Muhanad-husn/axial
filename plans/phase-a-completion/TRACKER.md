# Phase A completion — live tracker

**Cold-start handoff.** A fresh session reads this file first, then the plan. It is
the single place that says *what is done and what is next*. Update the checkboxes
as slices land. Issues remain the system of record; this is the map over them.

- **Branch:** `claude/phase-a-hybrid-tagging-sqx2xc`
- **Plan:** [`README.md`](README.md) (stages, waves, deferred decisions)
- **Decision:** `docs/DECISIONS.md` → DEC-32
- **Last updated:** 2026-07-21 — all slice plans written; implementation not started

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
- ☐ 0b #270 — structured run logging — plan ✅ `plans/run-logging/` (2 slices; **decided: slice, not fix-lane**; slice 02 is the serialization point)
- ☐ 0c #289 — verify gold-sheet dropdowns (`gold.py`) — ✎ fix-lane, verify-first

### Stage 1 — metadata correctness (one ordered chain, before any re-tag) — plan ✅ `plans/intake-metadata/`
- ☐ 1·01 #284 — holdings check → model-adjudicated rewrite (`holdings.py`)
- ☐ 1·02 #285 — persisted source-metadata record; **sole origin of author/title/date (P0-1d)** (needs 01)
- ☐ 1·03 #278 — **resolved: remove** author/date from the envelope (intake owns them); vault writer composes from both (needs 02). *No longer a Wave-1 independent slice.*

### Stage 2 — tag quality (before any re-tag)
- ☐ 2a #294 — best-of-N voting on blind axes (`tag.py`; **predecessor of stage 5**) — plan ✅ `plans/tag/06-best-of-n.md` (**abstention = per-axis `abstained:true` + null primary, distinct from `not-applicable`**)
- ☐ 2b #288 — report not-applicable / unlisted rates — ✎ fix-lane (attaches to #277 slice-03 summary)

### Stage 3 — runner — plan ✅ `plans/run/` (3 slices)
- ✅ 3·01 #277 — runner core + pass registry + failure isolation (walking skeleton) — PR #300 merged `e8f9661`
- ☐ 3·02 #277 — unified resume ledger + done-predicate (replaces today's 3 mechanisms)
- ☐ 3·03 #277 — source-set inputs (worklist + corpus glob) + end-of-run summary

### Stage 4 — freeze (operation, not a slice) → **PHASE A CLOSES HERE**
- ☐ 4.1 re-tag the corpus via #277 with stages 1–2 in place
- ☐ 4.2 score against the sim gold set (P0-10 eval)
- ☐ 4.3 freeze schema (ratify `theory_school` KEEP, DEC-31, on corpus-wide numbers)
- ☐ 4.4 record the frozen tag distribution (input to stage 5)

### Stage 5 — HDBSCAN distillation eval (gated behind stage 4)
- ☐ 5a #296 — embedding pass + vector store
- ☐ 5b #297 — HDBSCAN readiness map + cluster-(-1) router
- ☐ 5c–5e #298 — stratified teacher labels → head classifiers → quality-per-dollar verdict

## Next action

All slice plans are written — the four feature lanes below can start concurrently
(one worktree each, slices sequential inside a lane). Reviewer bandwidth is the cap
(≤3–4 at once), not file conflict.

| Lane | Order | Plan |
|------|-------|------|
| **intake-metadata** | #284 → #285 → #278 | `plans/intake-metadata/` |
| **tag** | #294 | `plans/tag/06-best-of-n.md` |
| **run** | #277 core → ledger → sources+summary | `plans/run/` |
| **reconcile** | #291 | `plans/reconcile/` |

Then: **#270 run-logging** (slice 01 early; slice 02 *after* the intake-metadata +
tag lanes — the one conflict point), the two fix-lane issues (#289 anytime, #288
after run·03), then **stage 4** (freeze = Phase A closes), then **stage 5**.

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
