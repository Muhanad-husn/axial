# Fresh-session runbook — canary readiness run + #138 fallback probe

**Purpose.** Run all placed canary sources end-to-end in parallel workers, watch
for silent stalls, then score the #115 "pipeline ready" bar and decide the #138
`content_fallback_model`. This is one live, multi-hour, semi-autonomous session:
the agent launches the workers and self-schedules 10-minute liveness peeks; the
founder intervenes only on a genuine stall.

**Run this in a FRESH session** (`/clear` first). This session must be the
orchestrator (main), on `main`, cwd `D:\axial`. Everything below is already
prepared — sources renamed, worklists written, secrets set — so the session's job
is to execute, watch, and score, not to re-derive.

---

## Why workers, not `axial pipeline-ready`

`pipeline-ready` is a sequential, single-process scorer; over 6 sources it would
run ~50 h serial. The parallel path is the first-class worker loop `axial ingest`
(issue #119). But the two do **not** compose: `run_vault_write` resumes from
checkpoints, so running `pipeline-ready` *after* a worker run resumes fast and
reports a meaningless ~0 s duration (criterion 3 becomes a bogus PASS). So we run
the workers and **score the criteria from the run artifacts**, not from a second
`pipeline-ready` pass.

## Topology (established from the code, 2026-07-14)

- **Phase 1 (serial, docling-bound):** `axial envelope <src>` runs docling
  extraction once per source and caches the tree to `data/trees/<id>.json`
  (extract.py persisted-tree cache) plus the envelope to
  `data/envelopes/<id>.json`. Docling is heavy — run these **one at a time**.
- **Phase 2 (parallel, LLM-bound, docling-free):** one detached `axial ingest`
  worker per source. `ingest` → `run_vault_write` → chunk → tag → artifacts →
  xref → vault. Chunk re-reads the **cached** tree, so Phase 2 does no docling and
  needs no mutex. `xref` runs here and is the known silent-stall risk (big OCR'd
  back-matter); #110's xref checkpoint lets a resumed worker skip completed xref
  work but does not prevent the stall itself.
- Workers self-coordinate via `data/gold/ingest.results.tsv` (skip-guard on
  `vault_status=OK`), and one bad source never aborts the loop — it gets a `FAIL`
  row and the worker moves on. We give each worker its **own single-source
  worklist** so concurrent workers never grab the same source.

## Sources (6) — placed and renamed

| worklist | source_id stem | role |
|---|---|---|
| `data/gold/worklists/mann-v4.txt` | mann-sources-of-social-power-v4 | canary (seen) + #138 hazard |
| `data/gold/worklists/tilly.txt` | tilly-from-mobilization-to-revolution | canary (seen) |
| `data/gold/worklists/hall-schroeder.txt` | hall-schroeder-anatomy-of-power | canary (seen) + #138 hazard |
| `data/gold/worklists/vignal.txt` | vignal-war-torn | canary (held-out) + #138 bonus |
| `data/gold/worklists/batatu.txt` | batatu-syrias-peasantry | canary (held-out) + #138 bonus |
| `data/gold/worklists/kalyvas.txt` | kalyvas-logic-of-violence-in-civil-war | #138 densest hazard (not a canary) |

The **readiness gate** is the 5 canaries (all but kalyvas). Kalyvas is included
because it is the densest moderation hazard and sharpens the #138 verdict.

---

## Phase 0 — Preconditions (verify, don't assume)

```powershell
# a) six sources present with the stems above
ls data/sources

# b) live provider — MUST be empty, not "stub"
echo $env:AXIAL_LLM_PROVIDER

# c) fallback + tier set
Get-Content secrets/secrets.toml | Select-String "llm_tier|content_fallback_model"
#    expect: llm_tier = "production_low"  and  content_fallback_model = "deepseek/deepseek-v4-pro"

# d) cold start — clear ALL derived state so timings and quarantine counts are honest.
#    Keep data/sources and data/gold/{chunks,labels,worklists}.
Remove-Item -Recurse -Force data/envelopes,data/trees,data/vault,data/tags,data/artifacts,data/xref -ErrorAction SilentlyContinue
Remove-Item -Force data/gold/ingest.results.tsv -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force data/gold/logs | Out-Null
```

## Phase 1 — Build envelopes (SERIAL, docling)

Run one at a time; each caches the tree and writes the envelope. The giant OCR
scan (mann-v4, 129 MB) is the slow one — expect tens of minutes for it alone.

```powershell
$sources = @(
  "data/sources/mann-sources-of-social-power-v4.pdf",
  "data/sources/tilly-from-mobilization-to-revolution.pdf",
  "data/sources/hall-schroeder-anatomy-of-power.pdf",
  "data/sources/vignal-war-torn.pdf",
  "data/sources/batatu-syrias-peasantry.pdf",
  "data/sources/kalyvas-logic-of-violence-in-civil-war.pdf"
)
foreach ($s in $sources) {
  Write-Host "envelope: $s"
  uv run axial envelope "$s" 2>&1 | Tee-Object -FilePath ("data/gold/logs/envelope." + [IO.Path]::GetFileNameWithoutExtension($s) + ".log")
}
# Gate check: 6 envelope files must exist before Phase 2.
(Get-ChildItem data/envelopes/*.json).Count   # expect 6
```
If any envelope fails (e.g. empty-`toc`, the tilly failure mode), that source is a
**criterion-1 FAIL** — note it and drop its worker from Phase 2.

## Phase 2 — Launch workers (PARALLEL, detached)

One detached process per source, each with its own log. Reroute/retry events go to
**stderr** (`_log_retry` prints there), so the `content_filter` evidence lands in
the `.err.log`.

```powershell
$jobs = @(
  @{ wl="mann-v4";        },
  @{ wl="tilly";          },
  @{ wl="hall-schroeder"; },
  @{ wl="vignal";         },
  @{ wl="batatu";         },
  @{ wl="kalyvas";        }
)
foreach ($j in $jobs) {
  $wl = $j.wl
  Start-Process -FilePath "uv" `
    -ArgumentList "run","axial","ingest","data/gold/worklists/$wl.txt" `
    -RedirectStandardOutput "data/gold/logs/$wl.out.log" `
    -RedirectStandardError  "data/gold/logs/$wl.err.log" `
    -WindowStyle Hidden
  Write-Host "launched worker: $wl"
}
```
Detached (`Start-Process`) so the run survives session boundaries — a new session
can re-attach by reading `ingest.results.tsv` and the logs.

> Fast-path variant (only the #138 endpoint answer, not the full gate): launch a
> single worker on `kalyvas` — densest refusals, answer in hours not ~12 h. Score
> §"#138 verdict" from its two logs and stop.

## Phase 3 — Liveness peeks every 10 minutes

Immediately schedule the first peek, then re-schedule after each:

```
ScheduleWakeup(delaySeconds=600, reason="10-min liveness peek on ingest workers",
               prompt=<this same /loop or ops prompt>)
```

The harness notifies on process *completion*; it cannot detect a process that is
**alive but frozen**. That is exactly what these peeks catch. Each peek:

1. **Completion:** how many of the 6 sources have a row in
   `data/gold/ingest.results.tsv`? When all 6 are present (OK or FAIL), the run is
   done → go to Phase 4 and stop scheduling.
2. **Progress (the real liveness signal):** for each still-running worker, has its
   log grown **and/or** its checkpoint advanced since the last peek?
   ```powershell
   Get-ChildItem data/gold/logs/*.err.log,data/gold/logs/*.out.log | Select Name,Length,LastWriteTime
   Get-ChildItem data/tags/*.jsonl,data/xref/*.jsonl -ErrorAction SilentlyContinue | Select Name,Length,LastWriteTime
   ```
   Advancing size/mtime = healthy. CPU is only a secondary tell — a stalled xref
   can spin CPU while making zero progress, so do **not** trust CPU alone.
3. **Suspected stall:** a worker whose process is alive but whose log **and**
   checkpoint are frozen across a full 10-min interval — most likely an xref
   back-matter stall. **Report it to the founder; do not blind-restart** (it will
   re-hang on the same chunk). The founder decides: skip that source (kill the
   worker, accept a criterion-3 FAIL) or wait.
4. Log a one-line status (which workers done / running / suspected-stalled) and
   re-`ScheduleWakeup(600)`.

## Phase 4 — Score the readiness gate (5 canaries)

```powershell
# criterion 1 — single-attempt completion:
Get-Content data/gold/ingest.results.tsv    # every canary row should be vault_status=OK

# criterion 2 — quarantine fraction < 2% per source:
#   numerator  = quarantine_reason records in that source's tag checkpoint
#   denominator= total records in the same checkpoint
foreach ($f in Get-ChildItem data/tags/*.jsonl) {
  $total = (Get-Content $f).Count
  $q = (Select-String -Path $f -Pattern '"quarantine_reason"').Count
  "{0}: {1}/{2} = {3:P2}" -f $f.BaseName,$q,$total,($q/[math]::Max($total,1))
}

# criterion 3 — within time envelope (duration_sec column vs the manifest ceiling):
#   mann 66000  tilly 54000  hall-schroeder 72000  vignal 86400  batatu 86400
```
All 5 canaries: OK + <2% quarantine + under envelope → **pipeline-ready PASS**.

## Phase 5 — #138 verdict (content_fallback_model)

```powershell
# refusals that hit the reroute (primary refused → fell back to deepseek-v4-pro):
Select-String -Path data/gold/logs/*.err.log -Pattern "trigger=content_filter" | Measure-Object | % Count

# unrecovered (deepseek-v4-pro ALSO refused → quarantined):
Select-String -Path data/tags/*.jsonl -Pattern '"quarantine_reason":\s*"content_filter"' | Measure-Object | % Count
```
- **recovered by deepseek-v4-pro = refusals − content_filter quarantines.**
- **If it recovered ~all refusals and canary quarantine stays <2%** → deepseek-v4-pro
  is confirmed. Keep it in `secrets.toml`.
- **If many content_filter quarantines remain** → it moderates too; pick another
  endpoint, update `content_fallback_model` in `secrets/secrets.toml`, and re-run
  Phase 2 (kalyvas alone is enough to re-probe).

## Phase 6 — Close out

- Comment the #138 verdict on the issue: refusal count, recovered count, the
  chosen endpoint, and the evidence path (`data/gold/logs/`). Add the same to
  `docs/postmortem/gold-run-2026-07/model-tier-decision.md`. Close #138.
- Note the pipeline-ready result (per-canary PASS/FAIL + envelopes to calibrate
  the held-out 24 h ceilings) in the postmortem. If all 5 PASS, the pipeline-ready
  bar is met for the next corpus-scale run.
- If any source stalled/failed, that is a real finding, not a nuisance — record it
  (candidate follow-up: #109 xref input guard).

---

### Notes / gotchas

- The run touches only gitignored `data/`; nothing here is committed. This runbook
  and the worklists were prepared on `main` (direct commits to `main` are
  hook-blocked) and live in the working tree.
- `data/sources` files are copyright — never commit them or paste source text into
  issues; evidence is refusal *counts* and prompt *hashes*, not chunk text.
- Real OpenRouter spend: flash primary + pro on refusals, ~a quarter of the
  original gold run's compute. Expect a long babysitter session.
