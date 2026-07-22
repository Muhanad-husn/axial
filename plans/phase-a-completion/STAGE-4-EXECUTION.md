# Stage 4 — execution plan for an operator session

**You are the operator session.** This file tells you *what to run, when, and how*.
[`STAGE-4-RUNBOOK.md`](STAGE-4-RUNBOOK.md) has the *why* — costs, traps, measurements.
Read this file top to bottom before launching anything; the order is load-bearing.

**Status when this was written (2026-07-22):** every planned Phase A slice is merged.
Lane A (#316) and lane B (#317 `--ledger`, PR #318) are closed. Nothing is left to build.
`data/source_meta/` is empty; the corpus is fully tagged under the *old* single-draw regime.

**Updated 2026-07-22 (second revision).** #320 closed won't-fix (`tilly`'s garbled title
layer — 1 of 30, visibly corrupt, correct by hand in the record). #323 tracks the missing
live positive control for the holdings check.

**Correction: PR #322 is MERGED** (`ea753f7`, 02:41), four minutes after the commit that
named Step 1 as its merge gate. `data/source_meta/` is still empty, so neither number was
taken. **Step 1 is therefore no longer a merge gate — it is validation owed against `main`.**
Run it the same way and report the same two numbers; the difference is only what a bad
result triggers. A regression now means a fix or revert on `main`, not a withheld merge.

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
| **Monitoring** | `.claude/tools/run-monitor.py` — `--watch` for a human, `--once` per session peek | Delegating a wait loop burns tokens to do nothing |
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

### Monitoring — use the dashboard

`.claude/tools/run-monitor.py` reports every live worker, its CPU and memory, checkpoint
progress, and whether anything has silently hung.

```powershell
# human dashboard, refreshes in place - leave it open in its own window
uv run python .claude/tools/run-monitor.py --watch --pass tag --run-dir data/logs/$RUN

# one snapshot, ~15 lines - this is what a Claude session calls on each peek
uv run python .claude/tools/run-monitor.py --once --pass tag --run-dir data/logs/$RUN
```

Output:

```
axial run monitor | 2026-07-22 14:03:11 | pass=tag (per chunk)
3 live worker(s) | 291% CPU total

      PID  WORKER                   CPU%   RSS MB  ELAPSED
    12044  worklist.w1              98.2      412  1:24:03
    12061  worklist.w2              96.4      398  1:24:03
    12078  worklist.w3              96.8      405  1:24:02

  checkpoints 11,204 lines in 30 file(s)  (+37 since last peek)
  ledger      18 row(s) across 3 file(s)
  last write  3s ago

STATUS  HEALTHY
```

**Why hang detection is trustworthy here.** `tag` and `xref` append one checkpoint line
**per chunk**, so genuine progress ticks every few seconds even while a single source takes
36 minutes. The monitor calls a run stalled only when **three independent signals are flat
at once** — checkpoints not growing, logs not growing, and CPU idle. A merely slow book
trips none of them. `--stall-seconds` defaults to 2400 s, above the slowest single source
ever measured (2168 s).

**`extract` is the exception:** it checkpoints per *source*, not per chunk, so pass
`--pass extract --stall-seconds 3600` in Step 1 or you will get false alarms.

Two traps the monitor was fixed for, worth knowing because they would both have faked
health: the repo lives at `D:\axial`, so **substring-matching "axial" matches every process
in the repo** — including the monitor itself; and `uv run axial run …` produces a *chain* of
processes that all carry the same argv, so counting each link reports three workers per real
worker. It now matches the `axial`→`run` token pair and keeps only leaf processes.

### Scheduled peeks

For the Claude session, poll on a **long** interval — 20–30 min. These are multi-hour jobs
and a peek costs a tool call, so minute-by-minute polling buys nothing. `/loop 25m` with the
`--once` command is the cheapest way to keep an eye on it; the session only needs to act
when `STATUS` is not `HEALTHY`.

Escalate on `*** STALLED ***`. On `SUSPECT`, take one more peek before doing anything — that
status exists precisely so a single quiet sample does not trigger a restart.

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
  "data/sources/chouliaraki-wronged-weaponization-of-victimhood.pdf",
  "data/sources/batatu-syrias-peasantry.pdf") |
  Set-Content -Encoding utf8 data/logs/$RUN/worklist.txt

uv run axial run extract --worklist data/logs/$RUN/worklist.txt `
  --ledger data/run/ledger.$RUN.tsv 2>&1 | Tee-Object data/logs/$RUN/console.log
```

Then **read the three records** in `data/source_meta/` and check `author`, `title`, `date`
against the actual books. Do not proceed on "the files exist."

**Probe selection is deliberate.** #316's root cause was the running-furniture strip
deleting the book's main title from its own title page — it removed the printed main title
from 7 of 30 sources, and on **`ugur-paramilitarism` and `chouliaraki` the main title
reached the model on no page at all**. Those two are the hardest cases in the corpus and
the sharpest test that the fix is live; `batatu` is a multi-line-title source from the six
that went 6/30 → 30/30.

**Gate:** all three titles complete and correct → continue. A partial title on any of them
means the fix is not doing what it was measured to do — stop, and raise it on #322 rather
than running 27 more.

### 1b. The remaining 27

```powershell
$RUN = "2026-07-22-stage4-0"
uv run axial run extract --corpus --ledger data/run/ledger.$RUN.tsv `
  2>&1 | Tee-Object data/logs/$RUN/console.log
```

`--corpus` is safe here: the three probed sources are already done and their records exist,
so they are skipped. Expect ~50–70 min; most of it is #312's re-read, not model time.

**Gate:** 30 records exist **and carry real author/title/date**.

Do not spot-check five by hand. [`docs/academic/corpus-bibliography.md`](../../docs/academic/corpus-bibliography.md)
carries all 30 entries keyed by `source_id`, human-curated from the files themselves, so
every title can be diffed mechanically. Read the disagreements; the list is the control,
not a substitute for judgment about what a disagreement means.

**This run also takes the two numbers PR #322 owes** (#321, the prompt's framing sentence).
That PR cannot be measured by any test — it changes the text of a live prompt — and it
merged before they were taken. Both come out of these same 30 records, at no extra cost:

| §7.11 false-positive half | `holdings_flag` null in all 30 records |
| §7.13 title read | titles diffed against the bibliography, **no worse than 29/30** |

**Expect 29/30, not 30/30.** `tilly`'s title layer is garbled in the file itself — #320,
closed won't-fix. It is the known exception; correct it by hand in the record and do not
treat it as a regression. A *different* source failing is the signal that matters.

§7.11's **true-positive half is not owed here** and must not be manufactured. #267 replaced
both partial files with complete copies on purpose and the defective bytes are gone; PR #322
retires the "truncate them back" construction and re-gates that half on changes to the
check's *judgment*, which this run does not involve. **Do not truncate a book to test the
check.** The exposure that leaves — no live positive control — is #323.

Report both numbers on #322. If the title read comes back worse than 29/30, that is a fix
or revert decision on `main` — #322 is already merged, so there is no gate left to hold.

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
| A worker looks stuck | Usually a slow source, not a hang — max measured is 2168 s | Run the monitor. `HEALTHY` with a recent checkpoint write means it is working. Only `*** STALLED ***` (checkpoints flat + logs flat + CPU idle) is a real hang |
| Monitor says `*** STALLED ***` | Three signals flat at once | Kill that worker and relaunch its worklist. Resume skips completed work with zero model calls |
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
