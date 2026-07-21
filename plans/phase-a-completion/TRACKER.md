# Phase A completion — live tracker

**Cold-start handoff.** A fresh session reads this file first, then the plan. It is
the single place that says *what is done and what is next*. Update the checkboxes
as slices land. Issues remain the system of record; this is the map over them.

- **Branch:** `claude/phase-a-hybrid-tagging-sqx2xc`
- **Plan:** [`README.md`](README.md) (stages, waves, deferred decisions)
- **Decision:** `docs/DECISIONS.md` → DEC-32
- **Last updated:** 2026-07-21 — planning complete, implementation not started

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

### Stage 0 — clean the shop (hygiene, parallel with stage 1)
- ☐ 0a #291 — safe GC for orphaned derived artifacts (`reconcile.py`, new)
- ☐ 0b #270 — structured run logging (cross-cutting; **serialize**, land just before stage 4)
- ☐ 0c #289 — verify gold-sheet dropdowns (`gold.py`; verify-first, likely just a test)

### Stage 1 — metadata correctness (before any re-tag)
- ☐ 1a #278 — envelope author/date null bug (`envelope.py`)
- ☐ 1b #284 — holdings check → model-adjudicated rewrite (`holdings.py`)
- ☐ 1c #285 — persisted source-metadata record (`intake.py` + `data/source_meta/`; needs 1b)

### Stage 2 — tag quality (before any re-tag)
- ☐ 2a #294 — best-of-N voting on blind axes (`tag.py`; **predecessor of stage 5**)
- ☐ 2b #288 — report not-applicable / unlisted rates (attaches to #277 summary)

### Stage 3 — runner
- ☐ 3 #277 — corpus-wide resumable pass runner (`ingest.py` → generalized)

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

**Start Wave 1** — the conflict-free front, up to 4 parallel worktrees, disjoint modules:
`#278 (envelope.py)`, `#284 (holdings.py)`, `#291 (reconcile.py)`, `#289 (gold.py)`.
Highest value first: #278 and #284 are the correctness fixes. Then Wave 2
(`#294`, `#277`, `#285`), then serial Wave 3 (`#270`, `#288`), then stage 4.

See [`README.md`](README.md) → *Execution — parallel waves & worktrees* for the full
wave/conflict rationale.

## How to resume in a fresh session

1. Read this file, then `README.md`, then DEC-32.
2. `git checkout claude/phase-a-hybrid-tagging-sqx2xc && git pull`.
3. Check the status board above and each issue's open PRs for anything ◐ in flight.
4. Pick the next ☐ slice per the wave order; run it through the harness; open a PR;
   update its checkbox to ◐ (PR #), then ✅ on merge.
