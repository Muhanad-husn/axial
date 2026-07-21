# Stage 4 — execution plan for an operator session

**You are the operator session.** This file tells you *what to run, when, and how*.
[`STAGE-4-RUNBOOK.md`](STAGE-4-RUNBOOK.md) has the *why* — costs, traps, measurements.
Read this file top to bottom before launching anything; the order is load-bearing.

**Status when this was written (2026-07-22):** every planned Phase A slice is merged.
Lane A (#316) and lane B (#317 `--ledger`, PR #318) are closed. Nothing is left to build.
`data/source_meta/` is empty; the corpus is fully tagged under the *old* single-draw regime.

---

## Rules that hold for every step

1. **Run in the main checkout, `D:/axial`. Never in a worktree.** `data/` is gitignored, so
   it does not exist in a worktree — a corpus pass there would silently operate on nothing.
   Worktrees are for *code*; stage 4 is *operations*.
2. **While a corpus run is live: no `pytest`, no commits, from any session.**
   `tests/conftest.py` snapshots and restores `data/trees/`, so a test run clobbers a live
   pass's tree cache. The commit gate runs pytest, so this bans commits too. Fix code
   *between* runs, never during one.
3. **Launch long runs detached**, via `Start-Process cmd.exe /c` with `cmd`'s `>>`
   redirection — **not** PowerShell `*>>`, which writes UTF-16 and breaks log monitors.
4. **Every run writes `data/logs/<YYYY-MM-DD>-<run-name>/`** with `run.jsonl`,
   `console.log`, and `summary.md`. No loose log files.
5. **Never clear `data/xref/` once populated.** It is the difference between a 2.6-hour
   vault-write and a 20-minute one.
6. **Decisions go in the GitHub issue.** Logs are evidence, not the record.

---

## How to run, monitor, and report — the honest topology

The founder asked about agents and worktrees for this. Straight answer:

| Job | Use | Why not the alternative |
|---|---|---|
| **Running** a pass | A **detached OS process** per worker | An agent adds nothing to `axial run` and cannot reliably babysit a multi-hour job. Agents are for judgment, not for waiting |
| **Monitoring** | Cheap polling from this session (`tail` the log, count ledger rows) | Delegating a wait loop burns tokens to do nothing |
| **Analysing a finished run** | A **subagent** | Genuinely good delegation: `run.jsonl` is thousands of lines in, a paragraph out. Keeps the log out of your context |
| **Writing `summary.md`** | A **subagent**, from `run.jsonl` + `console.log` | Same shape — large input, small output |
| **Fixing code mid-run** | **Don't.** Queue it | Rule 2 — you cannot commit while a run is live |

So: **processes run, this session polls, subagents summarise.** No worktrees in stage 4.

### Launch pattern (3 workers)

```powershell
# split the corpus into 3 disjoint worklists
$src = Get-ChildItem data/sources -Include *.pdf,*.docx -Recurse | Sort-Object Name
0..2 | ForEach-Object {
  $i = $_
  $src | Where-Object { [array]::IndexOf($src, $_) % 3 -eq $i } |
    ForEach-Object { $_.FullName } |
    Set-Content -Encoding utf8 "data/logs/$RUN/worklist.w$($i+1).txt"
}

# launch each worker detached, with ITS OWN ledger (lane B, #317)
1..3 | ForEach-Object {
  Start-Process cmd.exe -ArgumentList "/c uv run axial run <PASS> " +
    "--worklist data/logs/$RUN/worklist.w$_.txt " +
    "--ledger data/run/ledger.$RUN.w$_.tsv " +
    ">> data/logs/$RUN/console.w$_.log 2>&1" -WindowStyle Hidden
}
```

Each worker gets its own `--ledger` so three processes never share one append-mode TSV.
Concatenate the per-worker ledgers when all three finish.

### Monitoring

```powershell
# progress: rows across all worker ledgers vs. 30
(Get-ChildItem data/run/ledger.$RUN.w*.tsv | Get-Content | Measure-Object -Line).Lines
# liveness
Get-Content data/logs/$RUN/console.w1.log -Tail 5
```

Poll on a **long** interval (15–30 min). These are multi-hour jobs; polling every minute
buys nothing.

### One shared-file caveat that `--ledger` does not cover

`data/tags/theory_school_candidates.jsonl` is appended by every tag worker. Volume is low
(1 row today), but it feeds #288's rates and therefore the 4.3 freeze. After a parallel tag
run, check it parses as clean JSONL before trusting the rates.

---

## Step 0 — preflight (5 minutes, do not skip)

```powershell
uv run pytest src -q -m "not slow" -n auto     # must be green BEFORE the ban starts
git status --short                             # must be clean
(Get-ChildItem data/trees/*.json).Count        # expect >= 30 — see below
(Get-ChildItem data/sources -Include *.pdf,*.docx -Recurse).Count   # expect 30
(Get-ChildItem data/source_meta).Count         # expect 0 before 4.0
```

**The tree count is a real gate, not a formality.** All 30 sources must hit the tree cache.
`extract()` returns before docling loads on a cache hit, which is the only reason stage 4
can run parallel workers at all. A cache *miss* means docling runs — and two concurrent
docling processes OOM-crash the machine. If any source misses, run that one alone, serially,
before launching any parallel step.

---

## Step 1 — 4.0: write `data/source_meta/` (~1 hour, serial)

**Serial on purpose.** It is short, it is the load-bearing correctness step, and serial
means zero shared-file risk.

### 1a. Probe first — 3 sources, then stop and read

```powershell
$RUN = "2026-07-22-stage4-0-probe"
mkdir data/logs/$RUN
@("data/sources/ugur-paramilitarism.pdf",
  "data/sources/batatu-syrias-peasantry.pdf",
  "data/sources/hall-schroeder-anatomy-of-power.pdf") |
  Set-Content -Encoding utf8 data/logs/$RUN/worklist.txt

uv run axial run extract --worklist data/logs/$RUN/worklist.txt `
  --ledger data/run/ledger.$RUN.tsv 2>&1 | Tee-Object data/logs/$RUN/console.log
```

Then **read the three records** in `data/source_meta/` and check `author`, `title`, `date`
against the actual books. Do not proceed on "the files exist."

This is the first real exercise of the wired holdings + title-page path after lane A. The
known failure mode is a **partial title** — the subtitle captured, the main title dropped
(#316). `ugur` and `batatu` are in the probe precisely because both failed that way before.

**Gate:** all three titles complete and correct → continue. Any partial title → stop, and
raise it on #316 rather than running 27 more.

### 1b. The remaining 27

```powershell
$RUN = "2026-07-22-stage4-0"
uv run axial run extract --corpus --ledger data/run/ledger.$RUN.tsv `
  2>&1 | Tee-Object data/logs/$RUN/console.log
```

`--corpus` is safe here: the three probed sources are already done and their records exist,
so they are skipped. Expect ~50–70 min; most of it is #312's re-read, not model time.

**Gate:** 30 records exist **and carry real author/title/date**. Spot-check at least five
against the real books. A human reading it is the only control this step has.

---

## Step 2 — the metadata rewrite (~2.6 h, 3 workers)

This lands #278's fix across all 18,410 notes. **It does not need a re-tag** — tag and
artifacts are already checkpointed and are reused without a single model call. The cost is
xref, which recomputes because `data/xref/` is empty.

```powershell
$RUN = "2026-07-22-stage4-vault-metadata"
# split into 3 worklists, then launch 3 detached workers on pass: vault-write
# (see the launch pattern above)
```

Measured on the identical 2026-07-20 operation: median 945 s/source, **~2.6 h wall clock at
3 workers**.

**Gate:** pick five notes across five sources and confirm the `source_meta` block carries a
real author/title/date — not a slug title, not a null. Then confirm `data/xref/` is now
populated (30 files); every later vault-write depends on it.

**Why this runs before the re-tag:** it validates #278's composition end-to-end on the real
corpus, cheaply, before committing to the overnight run — and it populates the xref cache,
which makes the *second* vault-write (after re-tagging) nearly free. The extra ~2.6 h buys
the project's own rule: verify on real data before the expensive pass.

---

## Step 3 — the re-tag decision

Read [`STAGE-4-RUNBOOK.md`](STAGE-4-RUNBOOK.md) → *Can a stratified sample replace the full
re-tag?* The recommendation is the **full re-tag** (~one overnight at 3–4 workers), because
unattended machine time is cheaper than an estimated freeze and a mixed-provenance vault.

**Probe before committing.** The ~8–15 h estimate is derived from the xref rate, not
measured for tag:

```powershell
# one source, timed — ugur-paramilitarism is 277 chunks
Measure-Command { uv run axial run tag --worklist <one-source.txt> --ledger <probe.tsv> }
```

Multiply by 18,468/277 ≈ 67, divide by workers. If that lands far above ~15 h, switch to
the stratified design in the runbook.

### Executing the full re-tag

The corpus is already fully tagged, and **a checkpointed chunk is never re-sent to the
model** — so without clearing the checkpoints the re-tag will skip every source and
**report OK**. This is the trap most likely to waste a night.

```powershell
# archive, do not delete
mkdir data/_archive/tags.pre-retag-2026-07-22
Move-Item data/tags/*.jsonl data/_archive/tags.pre-retag-2026-07-22/
```

Archive the candidates log with them, so #288's rates describe the new run only. Then
launch 3–4 workers on pass `tag`, each with its own `--ledger`.

**Verify the re-tag is actually happening:** within the first minutes, confirm worker
consoles show model activity and `data/tags/` is refilling. A silent, instant "OK" on every
source means the checkpoints were not cleared.

**Then run `vault-write` again** to push the new tags into the notes. With `data/xref/`
populated from step 2, this is fast.

---

## Step 4 — 4.2 eval, 4.3 freeze, 4.4 distribution (cheap, serial)

```powershell
uv run axial eval          # scores against the gold labels; makes no model calls
```

- **4.2** scores the tagger against the sim gold set (120 chunks). Per DEC-32 every number
  here is a **provisional dev signal** — the sim path is torn down and re-run on real
  labels later (#295). Never promote a simulated number.
- **4.3** freezes the schema, ratifying `theory_school` KEEP (DEC-31) against #288's
  not-applicable/unlisted rates. **These are only meaningful after the re-tag.** Before it,
  28 of 30 sources read 0.0% purely because they predate the sentinels — a clean-looking
  zero that means "not measured", not "none found". Do not ratify on pre-re-tag rates.
- **4.4** records the frozen tag distribution — the input to stage 5.

**Phase A closes at 4.4.**

---

## When something goes wrong

| Symptom | What it means | Do |
|---|---|---|
| A source reports FAIL | Per-source isolation worked; the run continued | Read its `run.jsonl` row. Re-run that source alone after the pass finishes |
| A worker stalls with no output | Usually a slow source, not a hang — max measured is 2168 s | Wait one full max-interval before acting. Check the ledger row count is still climbing overall |
| Re-tag finishes suspiciously fast | Checkpoints were not cleared | Stop. Archive `data/tags/*.jsonl`. Relaunch |
| A run dies partway | Every pass is resumable | Relaunch the same command. The ledger + per-source checkpoints skip completed work with zero model calls |
| Machine OOM / segfault during extract | Two docling processes ran concurrently | A source missed the tree cache. Run it alone, serially |
| `pytest` was run mid-pass | `data/trees/` may be clobbered | Stop the run, verify the tree count, re-run affected sources |

**Resumability is the safety net for all of it.** Nothing in stage 4 needs to be restarted
from zero, so when in doubt, stop and relaunch rather than improvising.

---

## Reporting

After each step, dispatch **one subagent** to read that run's `run.jsonl` + `console.log`
and write `data/logs/<RUN>/summary.md`: the command, counts (OK/FAIL/SKIP), per-source
timings, outliers, and anything that looks wrong. Large input, small output — exactly what
delegation is for. Then post the material findings to the relevant GitHub issue, and update
[`TRACKER.md`](TRACKER.md)'s stage-4 checkboxes.

Keep `TRACKER.md` current as you go. The next cold start reads it first.
