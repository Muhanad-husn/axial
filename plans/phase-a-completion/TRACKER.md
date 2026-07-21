# Phase A completion — live tracker

**Cold-start handoff.** A fresh session reads this file first, then the plan. It is
the single place that says *what is done and what is next*. Update the checkboxes
as slices land. Issues remain the system of record; this is the map over them.

- **Branch:** `claude/phase-a-hybrid-tagging-sqx2xc`
- **Plan:** [`README.md`](README.md) (stages, waves, deferred decisions)
- **Decision:** `docs/DECISIONS.md` → DEC-32
- **Last updated:** 2026-07-21 — wave 2 dispatched; three PRs open awaiting review (#305, #306, #307)

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
- ◐ 0b #270 — structured run logging — plan ✅ `plans/run-logging/` (2 slices). Slice 01 (seam + `extract`) **PR #305 open**; slice 02 still held back (the serialization point)
- ☐ 0c #289 — verify gold-sheet dropdowns (`gold.py`) — ✎ fix-lane, verify-first

### Stage 1 — metadata correctness (one ordered chain, before any re-tag) — plan ✅ `plans/intake-metadata/`
- ✅ 1·01 #284 — holdings check → model-adjudicated rewrite (`holdings.py`) — PR #304 merged `affd369`. **Built but NOT wired into the ingest path → #303** (after #285)
- ◐ 1·02 #285 — persisted source-metadata record; **sole origin of author/title/date (P0-1d)** (needs 01) — also unblocks #303. **PR #307 open — HELD: real-corpus check failed** (1 crash, 1 confidently-wrong record, title-page fallback 2/13 correct). Founder decision pending on heuristic → model call
- ☐ 1·03 #278 — **resolved: remove** author/date from the envelope (intake owns them); vault writer composes from both (needs 02). *No longer a Wave-1 independent slice.*

### Stage 2 — tag quality (before any re-tag)
- ✅ 2a #294 — best-of-N voting on blind axes (`tag.py`; **predecessor of stage 5**) — PR #302 merged `aa0607d`; abstention settled in **DEC-33** + spec §7.14
- ☐ 2b #288 — report not-applicable / unlisted rates — ✎ fix-lane (attaches to #277 slice-03 summary)

### Stage 3 — runner — plan ✅ `plans/run/` (3 slices)
- ✅ 3·01 #277 — runner core + pass registry + failure isolation (walking skeleton) — PR #300 merged `e8f9661`
- ◐ 3·02 #277 — unified resume ledger + done-predicate (replaces today's 3 mechanisms) — **PR #306 open**
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

**Wave 2 is built; three PRs are open and none is merged.** Worktrees live under
`.claude/worktrees/{intake-metadata-02, run-02, run-logging-01}`.

| Lane | Slice | PR | State |
|------|-------|----|-------|
| intake-metadata | #285 source-meta record | [#307](https://github.com/Muhanad-husn/axial/pull/307) | ⚠️ **held — real-corpus check failed** |
| run | #277·02 unified resume ledger | [#306](https://github.com/Muhanad-husn/axial/pull/306) | ready for review |
| run-logging | #270·01 seam + `extract` | [#305](https://github.com/Muhanad-husn/axial/pull/305) | ready for review |

**The open decision is on #307.** Gate-4 validation over all 30 real sources found:
(1) `hall-schroeder-anatomy-of-power` crashes intake on a pypdf `NullObject`;
(2) `heydemann-war-institutions-social-change` carries embedded metadata for *a different
book* and would be recorded as a confident value with provenance; (3) the title-page
fallback reads **2 of 13** real cases correctly — the #268 pattern. Recommendation is to
replace the fallback with one model call reusing slice 01's front-matter read, which
addresses (2) and (3) together, and to guard the `NullObject`. Full table in the PR body.

Two review notes carried up from the other lanes:

- **#306 edits a locked slice-01 test** (`tests/test_run.py`, `OK` → `SKIP` on two
  sources). Justified and correct — the file-exists predicate now reads the fixtures that
  test pre-places — but the consequence is that no source in *that* test exercises the
  success path end to end; the new outer test covers it instead.
- **#306's ledger sits at `data/logs/run/ledger.tsv`**, beside the per-run
  `data/logs/<date>-<name>/` dirs, though it is a cross-run artifact. Cheap to move now.

Still held back: **#270 slice 02** (fans out into `envelope`/`tag`/`eval` — the one
real serialization point; hold until the intake-metadata and tag lanes settle),
**#277·03** (source sets + summary), **#288** (after run·03), **#289** (fix-lane,
anytime), **#303** (holdings wiring — after #285). Then **stage 4** (freeze = Phase A
closes), then **stage 5**.

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
