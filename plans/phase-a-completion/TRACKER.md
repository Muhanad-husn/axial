# Phase A completion — live tracker

**Cold-start handoff.** A fresh session reads this file first, then the plan. It is
the single place that says *what is done and what is next*. Update the checkboxes
as slices land. Issues remain the system of record; this is the map over them.

- **Branch:** `claude/phase-a-hybrid-tagging-sqx2xc`
- **Plan:** [`README.md`](README.md) (stages, waves, deferred decisions)
- **Running stage 4?** Two files: [`STAGE-4-EXECUTION.md`](STAGE-4-EXECUTION.md) is the
  operator session's plan — what to run, when, how, and the failure playbook.
  [`STAGE-4-RUNBOOK.md`](STAGE-4-RUNBOOK.md) is the *why* — measured costs, traps, and the
  sample-vs-full-re-tag analysis. Read both before launching any corpus pass
- **Decision:** `docs/DECISIONS.md` → DEC-32
- **Last updated:** 2026-07-24 — **Stage 5 mechanism pivoted (DEC-37), then refined
  (DEC-38).** #296 (5a, embeddings) and #297 (5b, HDBSCAN readiness map) both merged and
  real-corpus-validated — but the real-corpus validation of #297 (PR #358) led to a full
  data-science exploration that overturned 5b/5c's original design: **density clustering
  does not recover any tag axis on this corpus's embeddings (ARI≈0, exhaustively
  measured), and a direct supervised classifier on the corpus's *already-tagged* chunks
  strictly beats every clustering variant tried.** Gold-checking that classifier then
  reversed the optimistic internal read: on dense embeddings it loses to the LLM teacher
  on both blind axes (`claim_type`/`theory_school`) it could be checked against. A
  follow-up TF-IDF baseline (DEC-38) found a **narrower positive**: at a confidence
  threshold, TF-IDF (not embeddings) automates ~28–35% of chunks on those two axes at
  accuracy that clears the teacher's own gold agreement — real but on a thin ~35-sample
  evidence base. **#347/#348–#353 need re-scoping before any of them are picked up** —
  see *Stage 5 — live state* below for the full findings and DEC-37/DEC-38 for the
  authoritative record. Stage 4 remains closed; its *live state* section is kept as
  incident history, not current state.

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
- ✅ 0c #289 — verify gold-sheet dropdowns (`gold.py`) — ✎ fix-lane, verify-first — PR #313 merged `6ef14d9`. Verified: no code fix needed. The dropdown resolves to `vocab!$D$2:$D$31`, 30 values, both sentinels present in the rendered sheet — reproduced independently against a real workbook build. The PR is the regression test only (+28 lines in `test_gold.py`), pinning the vocabulary to an independent YAML parse of `axes.theory_school` so a future curated subset or hardcoded list goes red

### Stage 1 — metadata correctness (one ordered chain, before any re-tag) — plan ✅ `plans/intake-metadata/`
- ✅ 1·01 #284 — holdings check → model-adjudicated rewrite (`holdings.py`) — PR #304 merged `affd369`. **Now live in the ingest path via #303.**
- ✅ 1·01b #303 — wire the judgment into the ingest path — PR #311 merged `41aba59`. `extract()` builds a client only for an unjudged source; the §7.12 record gains `holdings_checked`, so a judged source constructs **no client at all**. Gate 4 over all 30: pass 1 = 30 calls (one each), pass 2 = **0 calls, 0 clients**; biblio coverage identical to #307 (author 29/30, title 28/30, date 30/30, 0 crashes); 0 flags raised. **P0-1b is true of the pipeline now, not just of `intake()`.**
- ✅ 1·02 #285 — persisted source-metadata record; **sole origin of author/title/date (P0-1d)** — PR #307 merged `fa6b2d9`. Took two rounds: the first failed gate 4, the rework deleted the heuristic and extended slice 01's model call to read + cross-check the title page (author 29/30, title 28/30, date 30/30, 0 crashes). **No longer dormant — #303 passes the client.**
- ✅ 1·03 #278 — **resolved: remove** author/date from the envelope (intake owns them); vault writer composes from both — PR #315 merged `635bf8c`. **The last planned slice in Phase A.** Envelope shape is now `{source_id, thesis, toc[], scope, stated_argument}`; `_fallback_title` deleted (its second caller, `_fallback_toc`'s deepest fallback, now emits `(no headings detected)` rather than a filename label); `vault.py` composes author/title/date from the record and thesis/scope from the envelope, with all three record states (`{value, provenance}` / `unavailable` / `not_attempted`) surviving into the note. Validated on **6 real sources with live model calls** — slug titles replaced with real printed titles, real authors, real dates; `unavailable` demonstrated model-free. Nothing written to the real `data/source_meta/`.
  - ⚠️ **#278 had been closed on GitHub while unimplemented** (envelope still built the three fields; vault still read them from the envelope). Reopened so PR #315 closes it for real.
  - ⚠️ **Two of six titles came back partial** — the title-page read returned the subtitle and dropped the main title (`ugur`, `batatu`). Filed as **[#316](https://github.com/Muhanad-husn/axial/issues/316)**, and it is a **decide-before-4.0** item: 4.0 writes all 30 records at one call each, so fixing the prompt afterwards means redoing that pass.

### Stage 2 — tag quality (before any re-tag)
- ✅ 2a #294 — best-of-N voting on blind axes (`tag.py`; **predecessor of stage 5**) — PR #302 merged `aa0607d`; abstention settled in **DEC-33** + spec §7.14
- ✅ 2b #288 — report not-applicable / unlisted rates — ✎ fix-lane — PR #314 merged `ffabada`. `RunSummary.rates` is filled by `attach_theory_school_rates` *after* `run_pass` returns, not inside the loop (computing it inside would force the runner to special-case pass names, against the pass registry's design note); `cli.py`'s `_run` renders the table and never touches `exit_code`. Real-corpus numbers, re-derived independently by the orchestrator: **Üngör 27.8% not-applicable (77/277), Mann v2 15.4% + 1.1% unlisted (208/15 of 1347)**. ⚠️ **The other 28 sources read 0.0%/0.0% because they were tagged before #286/#287 added the sentinels** — a true reading of what is on disk, but "not measured under the current schema", not "no not-applicable chunks". Resolves itself at 4.1; **do not read stale zeros as signal at 4.3**

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

- ✅ **4.0 write `data/source_meta/` for all 30 sources** — done 03:50Z, 30/30, 0 FAIL
- ✅ **Step 2, vault metadata rewrite** — done 2026-07-22 ~10:01 local, 30/30, 0 FAIL across
  3 workers. Gate verified: 5 notes across 5 sources (agamben, batatu, mann-v2, tilly,
  zaum) in `data/vault/prose/` all carry correct author/title/date matching
  `data/source_meta/`. See *Step 2 findings* below for two things worth knowing before
  Step 3.
- ✅ **4.1 re-tag — COMPLETE 2026-07-23 ~14:31 UTC.** The 3-worker launch's escalation
  below is history, not current state: PR #327 (quarantine + checkpoint threading) and
  PR #331 (missing-polity + persisting out-of-vocab quarantine) both landed, the run
  scaled to 5 workers, and every source that FAILed mid-run (ugur-paramilitarism #325,
  zaum-sovereignty-paradox, heydemann-war-institutions-social-change, vignal-war-torn,
  tilly-from-mobilization-to-revolution) self-recovered via the run's own retry cadence
  before it finished — all 30 sources, 0 unresolved fails. Post-retag `vault-write` also
  complete (30/30, 0 fails; survived a mid-run tree-cache incident, see the standing
  session's notes on issue #329). See **⚠️ Step 3 escalation** below for the historical
  incident narrative only.
- ✅ **4.2 score against the sim gold set (P0-10 eval) — run 2026-07-23, SIMULATED.** No
  real Academic labels exist yet; per founder instruction, ran a simulated stand-in
  (independent single-draw LLM judgments on the two blind axes, blind to the tagger's
  own values, over a freshly re-sampled 120-chunk gold set). `claim_type` 56.0%,
  `theory_school` 54.3% agreement (116/120 chunks scored). **Provisional only per
  DEC-32 — never promote as the real eval number.** Full detail on issue #329.
- ✅ **4.3 freeze schema (ratify `theory_school` KEEP, DEC-31, on corpus-wide numbers) —
  DONE 2026-07-23, DEC-34.** Real (non-simulated) data straight from the completed
  retag's own tag checkpoints: 48.8% not-applicable, 0.6% unlisted across all 17,824
  non-quarantined chunks, every one of the 30 sources reporting real data for the first
  time (28/30 previously read a false 0.0%/0.0% because they predated the sentinels).
  `theory_school` stays KEPT.
- ✅ **4.4 record the frozen tag distribution (input to stage 5) — DONE 2026-07-23.**
  Full per-axis distribution recorded in
  [`docs/eval/04-frozen-tag-distribution.md`](../../docs/eval/04-frozen-tag-distribution.md):
  17,824 tagged chunks, 586 quarantined; every axis's value breakdown plus the top 20
  of 998 distinct polities. **Phase A closes here.**

---

## Stage 4 — live state (read this first)

**Step 0 preflight — PASS** (2026-07-22 03:1xZ). `pytest src` 1146 passed; tree cache
verified **30/30 by name**; 30 sources; `data/source_meta/` 0; `data/xref/` 0.

> The plan's tree check is `(Get-ChildItem data/trees/*.json).Count >= 30`, which is
> **not** a coverage check — tree files carry a content-hash suffix and there are 2 test
> fixtures in the directory, so the count passes even if a real source is missing. Diff
> source basenames against tree basenames instead.

### ⚠️ Plan bug found and corrected — `axial run extract` cannot do 4.0

`STAGE-4-EXECUTION.md` Step 1 says to run `uv run axial run extract`. **It writes nothing.**
The runner's `_tree_done_predicate` (`src/axial/run.py:266`) skips on
`tree_path(source_id).exists()`, and all 30 trees exist — so the pass reports
`ok=0 skipped=3` and never invokes anything. `source_meta` is written by `intake()`, which
`extract()` calls at `src/axial/extract.py:547` — *before* the tree-cache check at line 559.

**The working command is the per-source CLI**, which reaches `intake()` and still short-circuits
before docling on a cache hit (so it is cheap and OOM-safe):

```powershell
uv run axial extract <one-source.pdf> 1>$null     # ALWAYS redirect: ~600KB of tree per source to stdout
```

Applies to any future 4.0 re-run. `STAGE-4-EXECUTION.md` still needs this edit (docs-only,
straight to `main`) — deferred only because a run is live.

### 4.0 as actually launched

Detached, serial, all 30, skipping any source already carrying `holdings_checked: true`:

```powershell
Start-Process cmd.exe -ArgumentList "/c pwsh -NoProfile -ExecutionPolicy Bypass -File <script> -RunDir data/logs/2026-07-22-stage4-0 >> data\logs\2026-07-22-stage4-0\console.log 2>&1" -WindowStyle Hidden
```

Progress: `Get-Content data/logs/2026-07-22-stage4-0/console.log -Tail 15`.
`run.jsonl` carries `source_id`, `status`, `seconds`, `title`, `title_provenance` per source.

> **The dashboard does NOT see 4.0.** `run-monitor.py` matches the `axial`→`run` token pair;
> 4.0 runs `axial extract`, so it reports `0 live worker(s)` / `STATUS IDLE - nothing running`
> **while the run is healthy**. Do not read IDLE as finished — tail `console.log` instead.
> Its checkpoint/last-write counters *are* accurate. The monitor is fully authoritative for
> steps 2 and 3, which do use `axial run`.

### Step 1a probe gate — FAILED; Step 1b now complete — the real number is worse than 28/30

**4.0 finished 2026-07-22 03:50Z. 30/30 records, 0 FAIL.** Full 30-title diff run against
`docs/academic/corpus-bibliography.md`. Both #322 numbers posted:
https://github.com/Muhanad-husn/axial/pull/322#issuecomment-5040949722

| §7.11 (false-positive half) | `holdings_flag` null in **30/30** |
|---|---|
| §7.13 (title read, strict full-title match) | **17/30 exact** (18/30 counting one trivial "The"-drop), **11/30 partial** (main title correct, subtitle dropped), **2/30 missing** (`unavailable`) |

**The plan's "no worse than 29/30" bar assumed tilly was the sole predictable miss. It is
not even that:**

- **tilly is NOT the predicted exception.** #320 measured `RevolaliOD` off the *title-page*
  path. This run resolved tilly's title from **embedded metadata** instead (clean: "From
  Mobilization to Revolution") — `intake.py`'s precedence kept the embedded value because
  the cross-check didn't veto it. #320 stays won't-fix; its predicted defect just didn't
  fire here. **tilly reads correctly in this run.**
- **The real failure mode is scale, not tilly.** All 11 partial misses share one root
  cause: `intake.py`'s documented precedence (lines 297–299) keeps the embedded-metadata
  title whenever the title-page cross-check doesn't affirmatively contradict it — and PDF
  embedded-metadata title fields routinely carry only the main title, never the subtitle.
  This is **the same mechanism that produced the Chouliaraki miss the probe already
  flagged** (see below), now measured at full scale for the first time: bayat, beshara,
  caspersen, chouliaraki, heydemann-networks-of-privilege, mann-v1, mann-v3, **mann-v4**
  (the only one of the four Mann volumes that also drops "Volume 4" — v1/v2/v3 keep their
  volume number), vignal, white, wimmer.
- **None of the 11 partials are wrong or hallucinated.** Every one is a real,
  correctly-truncated title of the actual book — this is a *completeness* gap, not a
  *correctness* defect, unlike #316's original bug (a title deleted from the page the
  model could see at all).
- **The 2 missing:** `ayubi-over-stating-the-arab-state` (title `unavailable`, author
  present but with a stray trailing `;` — a junk-filter leak, not yet filed) and
  `heydemann-war-institutions-social-change` (title **and** author `unavailable` — per the
  bibliography's own notes this file's embedded metadata is contaminated, attributing it to
  a different book entirely; `unavailable` here is very likely the cross-check correctly
  vetoing a wrong value, i.e. #285's safe behavior working as intended, not a failure).

**Original probe table (superseded by the full diff above, kept for the Chouliaraki
diagnosis):**

| Probe | Title recorded | Provenance | Verdict |
|---|---|---|---|
| `ugur-paramilitarism` | Paramilitarism: Mass Violence in the Shadow of the State | title page | ✅ #316's sharpest case — the fix is live |
| `batatu-syrias-peasantry` | Syria's Peasantry, the Descendants of Its Lesser Rural Notables… | title page | ✅ full multi-line title |
| `chouliaraki-wronged…` | **Wronged** | embedded metadata | ❌ subtitle dropped — first instance of the pattern found in all 11 partials |

**Any record with `title_provenance: "embedded metadata"` is a suspect** for a dropped
subtitle — every one of the 11 partials carries that provenance. `title_page` provenance
never dropped a subtitle in this run (batatu, ugur, jackson, do-civil-wars, elcheroth,
malesevic-haugaard-gellner, state-legitimacy — all exact).

**DECIDED 2026-07-22 (founder): accept as-is, proceed to Step 2.** None of the 11 partials
are wrong or hallucinated; fixing the precedence rule now risks re-litigating #285's
anti-recycled-metadata guarantee for a completeness polish, not a correctness defect.
Filed as fast-follow **[#324](https://github.com/Muhanad-husn/axial/issues/324)** — narrow
candidate fix (prefer title-page when it strictly *extends* the embedded value) plus the
author junk-filter's trailing-separator leak (`"Ayubi, Nazih N.;"`,
`"Lilie Chouliaraki;"`). Not scheduled; re-measure all 30 if ever picked up.

**Step 2 is now cleared to run.**

### Operational gotchas earned this session

- **Re-deriving a record requires DELETING it first.** `holdings_judged` short-circuits the
  model call once `holdings_checked: true`, so a bare re-run will not re-judge. Cost is low
  (22–237 s/source).
- **A client-less call is safe** — `_resolve_recorded_field` (`intake.py:378`) preserves the
  on-disk value, so re-touching a judged source cannot regress it.
- `axial extract` prints the whole tree to stdout. Always `1>$null`.
- #312's re-read is visible and dominates cost: 15–237 s per source, zero model calls.

### Next actions, in order

1. ~~Wait for 4.0~~ — **done**, 2026-07-22 03:50Z, 30/30, 0 FAIL.
2. ~~Diff all 30 titles against the bibliography~~ — **done**. 17/30 exact, 11/30 partial
   (subtitle dropped), 2/30 missing. See the table above.
3. ~~Report both #322 numbers on the issue~~ — **done**:
   https://github.com/Muhanad-husn/axial/pull/322#issuecomment-5040949722
4. **STOP HERE. Decide fix-vs-accept on the embedded-metadata precedence before Step 2.**
   This is a founder call, not one to make mechanically — get it before running Step 2, which
   bakes all 30 records into 18,410 notes. The question: is "main title correct, subtitle
   dropped" (11 sources) acceptable for the frozen corpus, or does `intake.py`'s
   embedded-vs-title-page precedence need a fix first? A fix means re-deriving affected
   records (delete then re-run `axial extract <source>` — cheap, 15–237 s/source) and
   re-measuring all 30 before Step 2.
5. Only once that's decided: steps 2 → 3 → 4 per `STAGE-4-EXECUTION.md`, using the
   worker/dashboard pattern below.

### Steps 2 & 3 must follow the plan's topology

Both use `axial run`, so the launch pattern and the dashboard both apply as written.

```powershell
# 3 detached workers, EACH WITH ITS OWN --ledger (never share one append-mode TSV)
1..3 | ForEach-Object {
  Start-Process cmd.exe -ArgumentList "/c uv run axial run <PASS> --worklist data/logs/$RUN/worklist.w$_.txt --ledger data/run/ledger.$RUN.w$_.tsv >> data/logs/$RUN/console.w$_.log 2>&1" -WindowStyle Hidden
}

# dashboard - leave --watch open in its own window; --once is the per-session peek
uv run python .claude/tools/run-monitor.py --watch --pass tag --run-dir data/logs/$RUN
uv run python .claude/tools/run-monitor.py --once  --pass tag --run-dir data/logs/$RUN
```

Poll on a **20–30 min** interval, not minutes. Act only when `STATUS` is not `HEALTHY`;
on `SUSPECT` take one more peek before doing anything. Escalate on `*** STALLED ***`.

- **Step 2** (vault-write, ~2.6 h at 3 workers) — gate: five notes across five sources carry a
  real author/title/date, then `data/xref/` is populated (30 files). **Never clear `data/xref/`.**
- **Step 3** (re-tag) — **archive `data/tags/*.jsonl` first** (`data/_archive/tags.pre-retag-2026-07-22/`),
  including the candidates log, or every source skips and the run reports OK having done nothing.
  Probe one source and extrapolate (×67 ÷ workers) before committing to the full re-tag.
- **While any run is live: no `pytest`, no commits, from any session** — `tests/conftest.py`
  snapshots and restores `data/trees/`, and the commit gate runs pytest.

### Step 2 findings — two corrections to the plan, no data loss

**1. `data/xref/` is never left populated after a clean run — the plan's rule 5 and
Step 2's "makes the second vault-write nearly free" rationale are wrong about this
codebase.** `src/axial/vault.py:565-568`, deliberate, by design:

```python
# completed (xref detected AND every note materialized), clear it so an
# independent later run recomputes xref fresh. A run that failed before
# reaching here leaves the checkpoint in place, so its resume is cheap.
xref_checkpoint_path(source_id, xref_dir).unlink(missing_ok=True)
```

Every source's xref checkpoint is deleted the moment `run_vault_write` finishes for it —
intentionally, so a later independent run never trusts a possibly-stale cross-reference.
`data/xref/` only ever holds checkpoints for sources still mid-pass or that failed; a
fully clean run always ends with it empty. **This is not data loss and not a bug** — it's
the code's real behavior, just not what the plan assumed. **Consequence: Step 3's
post-re-tag vault-write will NOT be fast.** It will recompute xref for all ~17k chunks
from scratch, same order of cost as the run that just finished (~6h wall clock, not
"nearly free"). Budget accordingly — this is a material correction to the plan's time
estimate for the remainder of stage 4, not a blocker.

**2. `data/vault/apparatus/` (897 files) is a stale, orphaned directory — not a live
defect.** A first pass at the gate sampled it and found the exact pre-#278 defect (slug
titles, null author/date). Investigation: every file in it is last-modified **2026-07-17**
(five days before this session), and `run_vault_write`'s own docstring confirms it only
ever writes to `<vault_dir>/prose/` and `<vault_dir>/artifacts/` — it never touches
`apparatus/` at all. The real, current corpus is `prose/` (**18,410 files**, matching the
plan's own expected total exactly) plus `artifacts/` (874). All 5 gate-sampled `prose/`
notes (agamben, batatu, mann-v2, tilly, zaum) carry correct metadata. `apparatus/` is
leftover from a pre-router-refactor pipeline version and should eventually be cleaned up
via #291's `reconcile.py` (dry-run first, per that tool's own default) — not urgent, not
part of the frozen corpus, filed here for visibility only. **If a future session samples
notes for anything, sample `data/vault/prose/`, not `apparatus/`.**

### Step 3 findings — one source excluded, one near-miss on touching locked code

**The founder went remote (`/remote-control`) partway through Step 2; everything from
here is operating under standing delegation ("solve it according to your best
recommendations") — decisions below were made autonomously, not confirmed live.**

**Probe (per the runbook's own "measure one source before launching thirty"):**
`ugur-paramilitarism` (277 chunks) was the chosen probe. **It failed 8 consecutive full
attempts, 0 chunks ever checkpointed** — not transient noise, a hard reproducible block.
Two distinct error classes, both on what looks like its first processed chunk (title
page + OUP publisher boilerplate — no real argumentative content):

```
expected 'field' value to be an object with a 'primary' key, got str: 'state'/'violence'  (3x)
claim_type.secondary[0] tag value is empty/whitespace-only: ''                            (4x)
```

**I almost made an unauthorized code change here — caught it by reading tests first.**
The `field` bare-string error looks like a gap in issue #105's bare-string coercion
(scoped only to `primary_plus_optional_secondary` axes, not `field`'s
`primary_plus_secondary`). It is not a gap — `test_tag.py` has a named test,
`test_parse_multi_value_tag_response_still_rejects_a_bare_scalar_for_primary_plus_secondary_axis`,
explicitly locking this as deliberate: a bare string for `field` is a genuine ambiguity the
design fails loud on, on purpose. **Do not touch this without founder review of that
design decision** — I was one edit away from breaking a considered, tested contract.

The *other* error class (`claim_type` blank secondary) is murkier: `test_tag.py` has a
section literally titled `# --- run_tag: degenerate (empty-string) tag values re-ask, not
fatal (#80) --`, so what I observed (a hard, unrecovered crash) contradicts the
documented intent. Whether that's the re-ask budget genuinely exhausted on a
persistently-terse chunk, or a real gap in `run_tag`'s votes loop (which has **no**
`except TagParseError` at all around `apply_correction_reask` — unlike
`ContentRefusedError`/`ModelJsonError`, both of which quarantine gracefully) is unresolved.
Neither was touched. Full diagnostic detail, and the suggested next step if picked up
(read `complete_json`'s retry semantics in `llm.py`), is on **#325**.

**Control probe proved this is NOT corpus-wide.** `agamben-state-of-exception` — whose own
first chunk is even sparser (34 characters of garbled OCR spacing) — succeeded cleanly on
the **first** attempt, zero retries. The tag pass itself is sound; this is a narrow
content-pathology specific to ugur's chunk 0.

**Decision: exclude `ugur-paramilitarism` from the 4.1 re-tag, proceed with the other 29.**
Filed as **[#325](https://github.com/Muhanad-husn/axial/issues/325)**, not scheduled, not
blocking. It affects only #298's teacher-label set and one of 30 sources in #288's rates —
small and bounded. Re-tag ugur separately once #325 is resolved.

**Mitigation used for the 29-source run: a per-worker shell-level retry wrapper, zero code
changes.** `_load_done_source_ids` (`run.py:323`) only tracks **OK** rows — a FAILED
source's ledger row does not mark it done — so a bare re-invocation of the same
`axial run tag --worklist ... --ledger ...` command naturally retries only what failed,
skips what succeeded (via the ledger) and skips already-checkpointed chunks within a
still-failing source (via `tag.py`'s own per-chunk checkpoint). The wrapper
(`tag-worker-with-retry.ps1`, scratchpad) just loops that same command up to 5 times per
worker and logs which attempt converged. This is pure operational shell scripting, not a
`src/` change — no builder dispatch needed.

**Timing correction: ~19–20h wall clock at 3 workers, not the plan's ~8–15h.** Measured
on `agamben` (153 chunks, succeeded clean): ~29 min → ~11.35 s/chunk. Extrapolated over
18,468 chunks ÷ 3 workers ≈ **19–20h**, meaningfully more than xref's rate implied (tag is
3 model calls + reconciliation per chunk vs xref's 1). Per the runbook's own decision
rule ("recommend full re-tag unless the probe comes back far slower than the xref rate
implies"), this is slower but not "far slower" — still far cheaper than the stratified
sample's overhead (mixed-provenance vault, estimated not exact 4.3 rates). **Full re-tag
stands; expect this to still be running past one overnight, likely into a second day.**

**Two log-hygiene notes for whoever reads `data/logs/2026-07-22-stage4-tag-probe/`:**
timestamps in the retry wrapper's `=== attempt N | ... ===` lines are mislabeled — the
script used bare `Get-Date -Format 'u'`, which is LOCAL time with an incorrect trailing
`Z`, not real UTC. Harmless (cosmetic only, retries worked correctly), just don't do
timezone math against them. The wrapper script itself hit a real PowerShell parser bug on
first write (`$attempt:` parsed as a drive reference) — fixed to `${attempt}:` before the
first real launch.

### ⚠️ Step 3 escalation — 4.1 is STOPPED, do not restart until the fix lands

**Read this first if you're picking up cold.** The 3-worker corpus re-tag launched
~12:41 local 2026-07-22 was **killed manually** (both the Monitor and the actual
detached `cmd`/`uv`/`python` processes) after ~1h, once its own ledgers proved the
problem below was NOT limited to ugur (which is [#325](https://github.com/Muhanad-husn/axial/issues/325),
already excluded). **Do not relaunch the 3-worker retag until the fix below is confirmed
merged or you've made your own informed call** — relaunching as-is will very likely
reproduce the same near-100% first-attempt failure rate.

**What was found:** every one of 17 sources checked (the full first pass across 3
workers, before I stopped it) failed on its own first few chunks, always one of:

```
expected 'field' value to be an object with a 'primary' key, got str: '<state|violence|ideology>'
claim_type.secondary[0] tag value is empty/whitespace-only: ''
```

This is **not** ugur-specific, **not** a concurrency/rate-limit artifact (verified:
`batatu-syrias-peasantry` failed identically running fully standalone, no other process
active), and **not** limited to sparse front-matter content (`mann-sources-of-social-
power-v1`'s first chunk is a clean, substantive one-sentence thesis summary and still
hit it). **This is a genuine, high-frequency structural gap**, not rare model noise.

**Root cause:** `run_tag`'s votes loop (`src/axial/tag.py`, the `for _ in range(votes):`
block) already quarantines two failure classes gracefully — `ContentRefusedError` and a
`ModelJsonError` that survives `complete_json`'s bounded retry. A **third class**,
`TagParseError` (raised by `_parse_and_validate_tags`/`apply_correction_reask` — either
from the `field`-type bare-string shape check or from `_reject_blank_tag`'s degenerate-
value check), **has no catch clause at all** and crashes the entire source. `test_tag.py`
even has a section header — `# --- run_tag: degenerate (empty-string) tag values re-ask,
not fatal (#80) --` — documenting this should NOT be fatal, but in practice, once
`complete_json`'s own 3-attempt re-ask budget is exhausted, the resulting exception has
nowhere graceful to land.

**What was explicitly NOT touched, and must not be:** `test_tag.py`'s
`test_parse_multi_value_tag_response_still_rejects_a_bare_scalar_for_primary_plus_secondary_axis`
locks in that a bare string for a `primary_plus_secondary` axis (`field`) is a genuine
shape error the low-level parser must keep raising — this is deliberate design (#105),
not a bug, and I nearly made an unauthorized fix here before checking tests first. **The
fix belongs one level up**: catching the otherwise-uncaught `TagParseError` in `run_tag`'s
votes loop and quarantining that one chunk (skip + log + continue), exactly mirroring the
two already-accepted patterns — never silently coercing/guessing a value, which fully
preserves #105's actual principle.

**Dispatched to the builder** (2026-07-22, mid-session, founder unreachable — proceeding
under standing delegation "solve according to your best recommendation"). Full brief
given: exact file/line pointers, both real error signatures, the concurrency-ruled-out
evidence, the #105 locked-test boundary, and instructions to branch off `main` (never
commit code to `main` directly), write a regression test, run the fast suite, and
**stop short of merging** — merge waits for founder approval, per Rule 1, no exception.

**Update — first fix landed but did NOT resolve the real failures. Second, deeper bug
found and a follow-up fix dispatched.** The builder's quarantine fix
(`fix/tag/quarantine-parse-errors`, commit `f1799d3`) is correct and independently
verified (1149 passed, ruff clean, locked #105 test untouched and green, 3 new tests
reproduce both real error strings) — **but re-running the actual tag pass against the 3
previously-failing sources from that branch reproduced the EXACT SAME crashes, zero
quarantine activity, zero checkpoint rows.**

**Why: `_invoke_tag` in `src/axial/run.py` (~line 248-249) never passes `tags_dir` to
`run_tag`.** `run_tag`'s `tags_dir` parameter defaults to `None`, so `checkpoint_path`
stays `None` for every `axial run tag ...` invocation — meaning the runner's own `tag`
pass has **never** checkpointed per chunk, for any source, success or failure. The
quarantine fix is correctly gated on `checkpoint_path is not None` (matching the
existing `ContentRefusedError`/`ModelJsonError` pattern exactly) — it's working as
designed, it just never receives an active checkpoint through this call path to
quarantine into.

**This explains two things at once:**
1. Why ugur's checkpoint was "still zero" across all 8 earlier attempts — not a
   content-specific mystery, just that checkpointing was never active for this
   invocation, full stop. Every retry was a complete cold restart from chunk 1.
2. Why the runbook's own claim ("Tag checkpoints: 18,410 records... a checkpointed chunk
   is reused verbatim and never re-sent to the model") was never true of a standalone
   `axial run tag` pass — only `vault.py`'s **internal** call to `run_tag` passes
   `tags_dir` (resolved via `_default_tags_dir`). The original 18,410 checkpoints almost
   certainly came from a prior `vault-write` run, not a `run tag` pre-pass. **Trap 1's
   whole strategy ("run tag separately first, vault-write reuses it") was never actually
   wired to work as the plan assumed.**

**Follow-up dispatched to the same builder** (same session, resumed via message, not a
fresh dispatch): wire `tags_dir=_default_tags_dir(config_path)` into `_invoke_tag`,
mirroring `vault.py`'s existing pattern exactly, plus judgment on whether `cli.py`'s
standalone `axial tag <source>` command (same gap) should get the same treatment. In
progress as of this update.

**Next steps once this second fix lands:**
1. Verify independently again (don't just trust the report) — re-run the fast suite,
   confirm the locked tests, AND re-run the real tag pass on the 3 proven-failing
   sources again from the updated branch. Unit-test-green was not sufficient last time;
   demand real-model evidence before trusting it this time too.
2. Prepare (but do not merge) a PR covering both commits.
3. **Re-run the tag pass FROM THAT BRANCH's checkout** (same `D:/axial` working directory
   — `data/` is gitignored, so switching branches doesn't touch it) rather than waiting
   for merge approval to unblock stage 4's timeline.
4. Re-derive the ~19-20h timing estimate once BOTH checkpointing and quarantine are
   actually active — likely cheaper now (a quarantined chunk costs one skipped record,
   and a genuinely-resumed retry no longer restarts a whole source from chunk 1).
5. `ugur-paramilitarism` ([#325](https://github.com/Muhanad-husn/axial/issues/325)) may
   also now succeed — worth a quick standalone check, but stays tracked separately.

**Update 2026-07-23 — PR opened, a fifth worker added, a silent worker death, and a real
CI regression found:**

- The branch grew a fifth commit, `c7cc868` (best-of-N votes now run concurrently, ~3x
  latency win, zero quarantines across ~4,000+ live chunks). The corpus re-tag relaunched
  as **5 workers** (was 3), run dir `data/logs/2026-07-23-stage4-tag-retag-5w/`.
- **[PR #327](https://github.com/Muhanad-husn/axial/pull/327)** opened, covering all four
  code commits (the two quarantine fixes, the `tags_dir` threading fix, and the
  concurrency perf fix). Not merged — CI was red (see below).
- **Live verification held**: the 5-worker run carried previously-crashing sources
  (batatu, mann-v1–v4, beshara) well past their old failure points with checkpointing
  active, satisfying step 1 of the "next steps" list above via real-model evidence.
- **The 5 workers silently died around 00:38 UTC** (no crash trace found in console
  logs, Application event log, or ledgers — root cause not established) and sat idle for
  ~13 minutes before being noticed and relaunched from the same branch at 00:50 UTC,
  resuming cleanly via the ledger + per-chunk checkpoint (no lost work). **A stale
  duplicate `per-chunk-monitor.py` from the earlier-killed 3-worker run was also found
  still running**, writing into the old `2026-07-22-stage4-tag-retag-v2` log path — killed
  as cleanup. **Lesson: a snapshot progress table looks identical whether a run is healthy
  or dead — always confirm two consecutive checks show forward movement (or a live
  per-chunk.log timestamp close to wall-clock) before trusting a "healthy" read.**
- **CI on PR #327 failed for real, not a flake**: `tests/ingestion/test_tag_shape_coercion.py`
  — issue #105's clause-4 acceptance tests (`test_genuinely_malformed_axis_shapes_still_raise`
  ×2, `test_claim_type_multi_element_list_secondary_still_raises`) — expect `axial vault
  write` to **exit non-zero** when a tag-pass response is genuinely malformed. The
  quarantine fixes now catch exactly these shapes and quarantine the chunk instead of
  crashing the whole source; in the test's tiny 3-chunk fixture every chunk gets the same
  malformed payload, all 3 quarantine, and the command exits 0 with an empty tag list —
  the opposite of what #105 requires. Invisible locally because the commit-gate only runs
  `pytest src`, not `tests/ingestion/`.
- **Real design tension, not a simple bug**: "one bad chunk shouldn't crash a 900-chunk
  source" (this branch, live-proven) vs. "a genuinely malformed shape must fail loud,
  never silently degrade" (#105 clause 4, locked). Recommended reconciliation: a source
  where **every** attempted chunk ends up quarantined (zero tags survive) is functionally
  the same as the old uncaught crash and should still fail loud; a source with a handful
  of quarantined chunks out of many should keep exiting 0. **Dispatched to the builder**
  in an isolated detached worktree (`.claude/worktrees/fix-tag-quarantine-105`, never the
  live `D:/axial` checkout) so the fix doesn't touch the running corpus pass. Not landed
  as of this update — see the PR for current status.

**Lesson for whoever reads this cold:** this is the THIRD time this session that a plan
document described a function's capability without verifying which CLI/runner entry
point actually wires the relevant parameter through (`axial run extract` vs `axial
extract` for source_meta; `data/xref/`'s "never clear" assumption; now `tags_dir` never
reaching `run_tag` via the runner). Read the actual call site, not just the function's
own docstring, before trusting a plan's claim about corpus-scale behavior.

### Stage 5 — hybrid distillation eval (gated behind stage 4, now CLOSED; mechanism pivoted DEC-37)

**Scoping done 2026-07-23 (DEC-35).** Vector store = LanceDB, embeddings = local
sentence-transformer, staleness = corpus_pin (#248) extended, notebook tooling =
new `distill` dependency group. #298 decomposed into 7 sub-issues so 5d's five
axes can run as concurrent worktrees. **Mechanism pivoted 2026-07-24 (DEC-37,
after real-corpus validation of #297):** HDBSCAN density clustering doesn't
recover any tag axis (ARI≈0); a direct supervised classifier on the corpus's
existing tags wins outright; but that classifier loses to the LLM teacher on
both blind axes once checked against gold. See *Stage 5 — live state* below.

- ✅ 5a #296 — embedding pass + vector store (LanceDB) + corpus-pin manifest convention — PR #357 merged
- ✅ 5b #297 — HDBSCAN readiness map (PCA) + cluster-(-1) router — PR #358 merged, real-corpus-validated. **Role demoted (DEC-37): kept as a correctly-implemented diagnostic (ARI≈0 against every tag axis is itself the finding), not a gate for 5c**
- ◐ 5c #347 — stratified teacher labels — **original scope superseded (DEC-37): existing corpus tags ARE the training set, zero new LLM spend needed.** Redirect pending: extend sim-gold coverage to the 3 head axes before any 5d graduation call. Not picked up as scoped — needs a rewritten issue body first
- ☐ 5d #348 — head classifier: `role_in_argument` — **technique revised (DEC-37): global classifier + confidence threshold on existing tags, not a cluster-stratified sample.** Gated on 5c's redirected gold-coverage work
- ☐ 5d #349 — head classifier: `empirical_scope` — same revision and gate as #348
- ☐ 5d #350 — head classifier: `field` — same revision and gate as #348
- ⛔ 5d #351 — head classifier: `claim_type` (blind axis) — **recommend stay LLM-only (DEC-37): gold-checked, classifier loses to the teacher (39.7% vs. 56.0%).** Do not build as scoped without a materially different approach
- ⛔ 5d #352 — head classifier: `theory_school` (blind axis) — **recommend stay LLM-only (DEC-37): gold-checked, classifier loses to the teacher (41.4% vs. 54.3%).** Do not build as scoped without a materially different approach
- ☐ 5e #353 — quality-per-dollar verdict — depends on #348–#350 now (effectively 3 axes, not 5)
- Tracking issue: #298 (no longer taken as a PR directly; see its body) — needs a comment reflecting DEC-37

## Next action

> **Superseded — see *Stage 4 — live state* above.** Stage 4 is running; 4.0 is live.
> #316 is settled (its fix is confirmed working on the corpus's hardest case). The
> section below is wave-4 history, kept for the lessons, not for the next action.

**Wave 4 is complete, and with it every planned Phase A slice.** Three module-disjoint
lanes ran as three concurrent worktrees; all three merged on CI green — #313 (`6ef14d9`),
#314 (`ffabada`), #315 (`635bf8c`). `main` is green at **1141 passed** on the src tier.
Every worktree and branch is torn down; the repo is `main` only, local and remote,
working tree clean.

**What remains is stage 4 — the freeze — and it opens with 4.0, a founder-run operation.**
There is no next build wave. Before 4.0 runs, settle
[#316](https://github.com/Muhanad-husn/axial/issues/316).

Three things a cold start should know about wave 4:

- **The "green suite is not evidence" rule paid again, in the other direction.** All
  three lanes ran real-corpus checks. #289's verify-first was *confirmed* (no code fix
  needed — the founder's measurement was right, reproduced independently). #278's found
  a real defect the suite could never see: 2 of 6 title-page reads returned the subtitle
  and dropped the main title (**[#316](https://github.com/Muhanad-husn/axial/issues/316)**,
  decide before 4.0). #288's found that 28 of 30 sources report 0.0% only because they
  predate the sentinels.
- **An issue's GitHub state is not evidence either.** #278 was closed as completed while
  its code was entirely unimplemented. Check the code, not the checkbox.
- **The plan missed a call site.** `_fallback_title` had a second caller — `_fallback_toc`'s
  deepest fallback labelled a single-entry TOC from the filename. Deleting the slug path
  for the bibliographic fields would have left the slug alive in the TOC.

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

### What the next session does — there is no wave 5

Wave 4 merged the last planned slice. **Nothing in stages 0–3 is left to build.** The
next session runs **stage 4, the freeze**, in checklist order, and it is operations, not
slices. Order matters and 4.0 is load-bearing — see the ⚠️ above.

**Decide [#316](https://github.com/Muhanad-husn/axial/issues/316) first.** The title-page
read returns the subtitle and drops the main title on some sources (2 of 6 measured). 4.0
writes all 30 records at one model call each; fixing the prompt after that pass means
redoing it. This is a small fix-lane change against `holdings.probe`'s prompt, and it is
the only build-shaped work standing between here and the freeze.

Then 4.0 → 4.1 → 4.2 → 4.3 → 4.4, then **stage 5**.

**Deferred, filed, not scheduled:** [#312](https://github.com/Muhanad-husn/axial/issues/312)
— `extract()` re-reads the full pypdf text layer and re-hashes the file on every call, even
on a tree-cache hit. Measured at gate 4: a no-op corpus pass costs 10–410 s per source with
**zero** model calls (~50 min per pass). Pre-existing; #303 made it dominant. Deliberately
**not** scheduled before stage 4 — it touches `extract.py`/`intake.py`, the path the freeze
depends on.

See [`README.md`](README.md) → *Execution — parallel feature lanes & worktrees* for
the full conflict rationale.

## Stage 5 — live state (read this first if picking up 5c/5d)

**Full record: DEC-37.** This section is the working detail; DEC-37 is authoritative.

### What happened

#297 (5b) was built, merged real-corpus checks per this repo's own "green suite is
not evidence" rule (see Stage 4's lessons above — the same rule paid again here), and
that check surfaced a near-degenerate result on the real 18,410-chunk corpus:
`cluster_count=1`, `noise_fraction=0.722`, almost every tag axis reading 0 "tight"
values. The fix (PR #358: Kaiser-criterion PCA=93, `leaf` selection, `min_samples=5`,
"tight" redefined over non-noise chunks) landed and is correct — but re-measuring after
the fix, plus a founder-directed deeper data-science pass, found the improved numbers
were still not meaningfully informative, and traced the real cause one level down.

### The measurements, in order

1. **Cluster-validity vs. real tags (sklearn `adjusted_rand_score` etc.).** HDBSCAN's
   clusters (even the fixed config) score **ARI ≈ 0** (one axis slightly negative)
   against every one of the five tag axes. Not a tuning artifact — swept PCA dims
   50/93/100/150, `min_cluster_size` 15/30/50/100/200, `cluster_selection_method`
   eom/leaf, `allow_single_cluster` true/false. `eom` (the implicit default) always
   collapsed to 1–2 clusters; `leaf` found 17–42 real clusters but still ARI≈0 against
   tags — real density structure exists in this embedding space, it just doesn't align
   with these tag categories.
2. **Direct supervised probe** (kNN/logistic regression/LDA, trained on the *existing*
   corpus tags, zero new LLM calls): every axis clears its majority-class baseline by a
   wide margin, including the two axes HDBSCAN found zero structure for
   (`field_primary` 84.5%, `empirical_scope_value` 77.6%). Confirms density clustering
   and classifier-learnability are different questions here, pointing in opposite
   directions.
3. **Cluster-then-classify vs. global-classifier-with-threshold** (a real, previously
   successful technique from the founder's own experience, tested directly on this
   data): per-cluster local classifiers never covered more than ~4% of the corpus at
   any `min_cluster_size` (15–200), at accuracy no better than the global classifier.
   A global logistic regression with a predicted-probability threshold strictly
   dominated — e.g. `field_primary` 92.2% accuracy at 72.7% coverage (threshold=0.8),
   vs. the best per-cluster result of 90.8% accuracy at 2.3% coverage.
4. **Secondary explorations, folded into the recommendation:** `e5-base-v2` embeddings
   give a small, consistent lift over `all-MiniLM-L6-v2` on a fair 4,000-chunk subset
   (kNN +2–3 points on most axes); MiniLM truncates 56% of real chunks at its 256-token
   window, but truncation turned out *not* to be the dominant accuracy driver
   (untruncated `bge-small-en-v1.5` performed about the same). Cross-axis association
   (Cramér's V) found `field_primary`↔`claim_type_primary` at 0.850 — but a
   leakage-free hierarchical classifier (predict field, feed the *predicted* value into
   claim_type's classifier) gave **zero** improvement over the flat baseline; the
   embedding already carries the shared signal. Region-grouping high-cardinality sparse
   categoricals (tested on `polity`, not a current 5d axis) raised accuracy 80.8%→88.9%,
   mostly by rescuing individually-too-rare classes rather than revealing new signal.
5. **Gold check — the decisive, corrective measurement.** Steps 2–4 all measured
   accuracy against the *tagger's own* labels, which is not the same as accuracy
   against truth. Retrained the classifiers with the 120 gold chunks fully excluded
   from training, scored against the real (DEC-29/30 simulated) academic gold labels
   for the two axes that gold set actually covers (`claim_type`, `theory_school` — the
   two blind axes, the only ones DEC-29/30 independently re-judged; `field`/
   `empirical_scope`'s "1.0 agreement" in the existing gold report is trivial, those
   columns were copied from the tagger, never independently checked):

   | axis | classifier vs. gold | tagger's own reported agreement vs. gold |
   |---|---|---|
   | `claim_type_primary` | 39.7% (46/116) | 56.0% |
   | `theory_school_primary` | 41.4% (48/116) | 54.3% |

   Confidence-threshold abstention (≥0.6) narrows but doesn't close the gap: 46.4%/48.1%
   accuracy at ~70% coverage, still below the teacher. **The classifier loses to the
   teacher on both axes it can be checked against**, reversing what the internal-only
   probe suggested. This matches `docs/eval/02`'s own original expectation ("the blind
   axes likely stay LLM + best-of-N") — the internal numbers were the misleading signal,
   not the original plan.
6. **TF-IDF baseline, same gold check (DEC-38).** Prompted by an external "standard
   solution for wiki-style tagging" writeup — most of it re-confirmed decisions already
   made here (confidence-thresholded shortlist + human/LLM-in-the-loop = the same
   design as step 3's threshold; hierarchical/ontology tagging = the field→claim_type
   idea step 4 already found gave zero lift). Its one genuinely untested idea was a
   TF-IDF + linear baseline, never tried alongside dense embeddings. Measured, same
   leakage-free gold check as step 5:

   | axis | TF-IDF full-coverage | embedding full-coverage | TF-IDF @conf≥0.6 | tagger vs. gold |
   |---|---|---|---|---|
   | `claim_type_primary` | 45.7% | 39.7% | 75.0% @ 27.6% cov. (90% boot CI 62.2–87.5%) | 56.0% |
   | `theory_school_primary` | 47.4% | 41.4% | 70.0% @ 34.5% cov. (90% boot CI 57.1–81.6%) | 54.3% |

   TF-IDF beats the dense-embedding classifier outright on both blind axes, and its
   confident subset **beats the teacher's own gold agreement** — robustly for
   `claim_type` (CI floor 62.2% > teacher's 56.0%), more marginally for `theory_school`
   (CI floor 57.1% barely clears teacher's 54.3%). Concatenating TF-IDF+embedding
   features was tried and is **worse than TF-IDF alone** (40.5%/43.1% full-coverage,
   48.1%/51.9% @conf≥0.6 — the huge sparse TF-IDF space dilutes the embedding's
   contribution in a single linear head) — a negative result, don't retry without a
   different combination mechanism (e.g. a proper ensemble, not feature concatenation).
   **Caveat:** the confident subset is only ~32–40 gold chunks; real, but thin.

### What is still unknown

`role_in_argument`/`empirical_scope_value`/`field_primary` have **no independent gold
coverage at all** — the current 120-chunk sim-gold set only re-judged the two blind
axes. Their strong internal numbers are exactly as unvalidated as the blind axes' were
before step 5. **Do not treat them as distillation-ready without the same gold check.**

### Next actions

1. **Extend sim-gold coverage to the three head axes** (mirrors the DEC-29/30
   in-harness Sonnet-5 dispatch already used for the two blind axes) — this is the one
   real prerequisite before #348–#350 can make a trustworthy graduation call. Likely
   lands as a rewritten #347, not a new issue — see the status board above.
2. **#351/#352 (`claim_type`/`theory_school`): do not build a full-coverage classifier
   as scoped, but not a flat "stay LLM-only" either.** A TF-IDF (not embedding) model
   at a conservative confidence threshold automates a real, gold-checked slice
   (~28–35% of chunks) at accuracy that clears the teacher's own gold agreement —
   see step 6. Re-scope to a narrow automate-if-confident-else-defer proposal rather
   than closing outright; flag the thin evidence base (32–40 gold chunks) plainly so
   the founder can weigh whether that's enough to act on.
3. **#348–#350: revise the issue bodies** before dispatch — global classifier +
   confidence threshold on existing tags (not a cluster-stratified fresh sample), gated
   on next action 1's gold coverage.
4. **#297/PR #358: still worth merging** — correctly implemented, real-corpus-validated,
   and the ARI≈0 finding is itself a useful documented negative result / future
   OOD-triage candidate, even though it no longer gates 5c.
5. Drafts for the revised #347/#348–#352 issue bodies (and a #298 tracking comment)
   should go to a local file for founder review before filing, per this repo's own
   "draft before filing" practice for backlog changes.

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

**Stage 4 is done; Phase A is closed.** The `Stage 4 — live state` section above is
kept as incident history, not something a fresh session needs to act on. **Stage 5's
mechanism pivoted 2026-07-24 (DEC-37) — read `Stage 5 — live state` above before
touching #347 or any #348–#352 issue; the original DEC-35 design (HDBSCAN-gated
cluster-stratified sampling) is superseded, not just "not yet built."**

For a stage-5 (or any future build-lane) session:

1. Read this file first (**especially `Stage 5 — live state`**), then `README.md`'s
   stage-5 section, then DEC-37 (the pivot, authoritative) and DEC-35 (original
   scoping, now partly superseded — still correct on vector store/embedding
   model/staleness tracking, superseded on dimensionality reduction and issue
   #347/#348–#352's build technique), then the relevant issue.
2. `git checkout main && git pull` (the plans live on `main`; cut each slice's
   `feat/<feature>/NN-slug` branch from there).
3. Check the status board above and each issue's open PRs for anything ◐ in flight.
4. **Do not dispatch #347 or #348–#352 as currently written** — their issue bodies
   describe the superseded design. `Stage 5 — live state`'s *Next actions* lists what
   actually needs doing: extend sim-gold coverage to the three head axes first, then
   revise #348–#350's bodies to the global-classifier-plus-threshold technique;
   #351/#352 (`claim_type`/`theory_school`) are a recommended stay-LLM-only call, not a
   dispatch candidate, pending a materially different approach. Draft the revised issue
   bodies to a local file for review before filing/editing on GitHub.
5. Once redirected, resume the normal lane pattern: `gh issue list` (or the GitHub
   plugin equivalent) scoped to #298's sub-issues to see what's unblocked and has no
   open PR; when more than one axis issue qualifies, spin one worktree per issue and
   dispatch concurrently, same as stage 0–3's parallel feature lanes. Pick the next ☐
   slice per its lane order; run it through the harness; open a PR; update its checkbox
   to ◐ (PR #), then ✅ on merge.
