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
- ✅ 1·01 #284 — holdings check → model-adjudicated rewrite (`holdings.py`) — PR #304 merged `affd369`. **Built but NOT wired into the ingest path → #303.** #285 is now merged, so #303 is unblocked — and it now gates the bibliographic cross-check too, not just the holdings flag
- ✅ 1·02 #285 — persisted source-metadata record; **sole origin of author/title/date (P0-1d)** — PR #307 merged `fa6b2d9`. Took two rounds: the first failed gate 4, the rework deleted the heuristic and extended slice 01's model call to read + cross-check the title page (author 29/30, title 28/30, date 30/30, 0 crashes). **Dormant until #303 passes a client.**
- ☐ 1·03 #278 — **resolved: remove** author/date from the envelope (intake owns them); vault writer composes from both (needs 02). *No longer a Wave-1 independent slice.*

### Stage 2 — tag quality (before any re-tag)
- ✅ 2a #294 — best-of-N voting on blind axes (`tag.py`; **predecessor of stage 5**) — PR #302 merged `aa0607d`; abstention settled in **DEC-33** + spec §7.14
- ☐ 2b #288 — report not-applicable / unlisted rates — ✎ fix-lane. **Now startable**: #277·03 landed the `RunSummary.rates` attachment point it was waiting on

### Stage 3 — runner — plan ✅ `plans/run/` (3 slices)
- ✅ 3·01 #277 — runner core + pass registry + failure isolation (walking skeleton) — PR #300 merged `e8f9661`
- ✅ 3·02 #277 — unified resume ledger + done-predicate (replaces today's 3 mechanisms) — PR #306 merged `6047450`, ledger relocated by PR #308. Ledger at `data/run/ledger.tsv`, keyed `(pass, source_id)`; `extract`/`envelope` use a file-exists predicate, the rest use the ledger. **P1-4 is satisfied for a named worklist** — the corpus glob is still slice 03.
- ✅ 3·03 #277 — source-set inputs (worklist + corpus glob) + end-of-run summary — PR #309 merged `1237e8d`. `RunSummary` is a returned structured value with a `rates` attachment point, so **#288 is unblocked**. **#277 stays open**: the issue's bounded-concurrency scenario is deferred by `plans/run/README.md`, so the PR said `Part of #277`, not `Closes`

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

**Wave 3 is two-thirds landed.** #309 (`1237e8d`, run·03) and #310 (`301e37a`,
run-logging·02) are merged; `main` is green at **1109 passed** on the src tier and
both worktrees are torn down. **#303 is still building** in
`D:\axial-wt\303-holdings-wiring` — it is the last slice of this wave and the one
that gates stage 4.

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

**#307 took a second round, and that is the wave's main lesson.** Its suite was green and
its corpus check was not. Gate-4 validation over all 30 real sources found: a pypdf
`NullObject` crash; `heydemann-war-institutions-social-change` carrying embedded metadata
for *a different book* (`Michael Hanby` / `AUGUSTINE AND MODERNITY`) recorded as a confident
value; and a title-page fallback reading **2 of 13** real cases. Founder ruled: delete the
heuristic, extend slice 01's reasoning-ON front-matter call to also read and cross-check the
title page, guard the `NullObject`. Re-measured on all 30:

| Field | Before | After |
|---|---|---|
| author with a value | 22/30 | **29/30** |
| title with a value | 23/30 | **28/30** |
| date with a value | 3/30 | **30/30** |
| crashes | 1 | **0** |

Heydemann now records `unavailable` for author and title. Two honest residuals: `batatu`'s
title is a partial read, and `ayubi` moved from a wrong value to `unavailable` — a coverage
loss that is a quality gain.

> ⚠️ **The model path is dormant in production.** `read_bibliographic_fields` takes it only
> when a caller supplies a `client`, and **no production call site passes one** — not
> `extract()`, not `cli._intake`. Until **#303** lands, a real ingest run still records the
> wrong Heydemann metadata. Two consequences: **#303 is now the switch that makes
> bibliographic correctness real**, not just holdings wiring; and **stage 4's re-tag must
> run after #303**, or the frozen corpus bakes embedded-metadata-only `source_meta` into
> ~17k chunks.

One note carried forward from the merged lanes:

- **#306 edited a locked slice-01 test** (`tests/test_run.py`, `OK` → `SKIP` on two
  sources) — correct, since the file-exists predicate now reads the fixtures that test
  pre-places, but no source in *that* test exercises the success path end to end any more;
  `tests/test_run_resume.py` covers it instead.

*(Resolved: the ledger's placement under `data/logs/` — moved to `data/run/` by PR #308,
merged. `data/logs/` is one directory per run; the ledger outlives every run and is read
at the start of the next one, so it is runner state, not a log. No migration was needed —
nothing had been written to disk yet.)*

### What is startable next

| Lane | Next slice | Notes |
|------|-----------|-------|
| **intake-metadata** | **#303** holdings + client wiring | ◐ **in flight** — worktree `D:\axial-wt\303-holdings-wiring`, branch `feat/intake-metadata/04-holdings-client-wiring`. Cut from `acd6ded`, so it will need a rebase onto `301e37a` |
| **intake-metadata** | #278 envelope cleanup (slice 03) | ☐ held back all of wave 3 by design — it edits `envelope.py`, which #270·02 fanned into. #270·02 has now merged, so **#278 is released** |
| **stage 2** | #288 not-applicable/unlisted rates | ☐ fix-lane, **now startable** — #277·03 landed the `RunSummary.rates` seam |
| **stage 0** | #289 gold dropdown | ☐ fix-lane, anytime (verify-first) |

Ordering note for the next wave: **#278 and #303 are the same lane and both touch the
intake/envelope metadata boundary** — sequence them, do not run them concurrently.
Then **stage 4** (freeze = Phase A closes) — **which must not precede #303** — then
**stage 5**.

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
