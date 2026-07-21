# Slice 02: Fan the seam out to `envelope`, `tag`, `eval` — the model-bearing passes

- **Feature:** run-logging
- **Slice slug:** wire-remaining-passes
- **GitHub issue:** #270
- **Branch:** feat/run-logging/02-wire-remaining-passes
- **Project directory:** .
- **Status:** ✅ merged — PR #310, `301e37a`
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

Wrap the remaining three long-running passes — `run_envelope`, `run_tag`, and
the `eval` command — in the `run_context` seam built in slice 01, reusing it
verbatim. Each opens a `run_context("<pass>")` and appends one per-source
`run.jsonl` record with the pass populated **and now the `model` field set** from
the LLM client each pass already holds. A per-source failure records
`status="error"` with a short `error` string and the pass continues; a healthy
source records `status="ok"` with `duration_sec` and `model`. No new seam
surface — `runlog.py` is imported, not extended (any change to it is a red flag
that slice 01 under-built the contract).

After this slice, every "run that matters" — the four passes named in #270 —
leaves a `data/logs/<name>-<ts>/` with `run.jsonl` + `console.log`, and the
stage-4 re-tag is reproducibly logged. Console output stays exactly as it is.

## INVEST check

- **Independent:** consumes the slice-01 seam; the only edits are three
  context-manager wraps. No CLI-surface change, no change to `runlog.py`.
- **Valuable:** completes the #270 mandate — all four passes logged, `model`
  captured — and gives #277 and #288 the full record set they read.
- **Small:** three wraps of an existing helper; the record shape and files are
  already pinned by slice 01.
- **Testable:** run each pass over a fixture with the stub provider, an injected
  run dir, and a fixed clock; assert one record per source with the right `pass`
  and a non-null `model` drawn from the stub client.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture source with a stored envelope and chunk records, AXIAL_LLM_PROVIDER=stub, an explicit run directory, and a fixed clock
When  each of the envelope, tag, and eval passes runs through its run_context
Then  each writes a data/logs/<pass>-<fixed-ts>/ containing run.jsonl and console.log
And   each run.jsonl holds one record per source with pass set to that pass name
And   each record carries a non-null model (the stub provider's id), a status, and a numeric duration_sec
And   a source that fails its pass records status="error" with a short error string, and the pass continues to the next source
And   no run.jsonl record contains source text — ids, values, and status only (DEC-23)
And   each pass's existing stdout is unchanged
```

- **Boundary / endpoint:** the three passes (`envelope`, `tag`, `eval`) driven
  through `run_context`; assertions read files under the injected run dir.
- **Outer test type:** pytest integration test (in-process or subprocess; stub
  provider; injected run dir + clock).
- **Outer test file (planned):** tests/test_runlog_passes.py — test-author, red, locked (DEC-1)

### How the outer test stays deterministic

Same injection as slice 01, applied to three passes: an **explicit run dir**
(`root=<tmp_path>`) so assertions read a known path, and a **fixed clock**
(`clock=lambda: FIXED_TS`) so the dir name and record times are fixed.
`model` is deterministic because the **stub provider** returns a fixed id, not a
live model. `duration_sec` is asserted as a number ≥ 0, never a wall-clock value.
No global `datetime` monkeypatch.

## Inner loop — initial unit test list

- [ ] `run_envelope` wrapped: one record per source, `pass="envelope"`,
      `model` = the client's id, `status`/`duration_sec` set
- [ ] `run_tag` wrapped: one record per source, `pass="tag"`, `model` set;
      per-source granularity (not per-chunk) so `run.jsonl` stays ~one row/source
- [ ] `eval` wrapped: one record per unit, `pass="eval"`, `model` set
- [ ] a source raising inside a pass records `status="error"` + short `error`,
      loop continues, the next source's record is `status="ok"`
- [ ] `model` is read from the client each pass already constructs — no new
      client, no new config option
- [ ] none of the three wraps import or add anything to `runlog.py` beyond the
      slice-01 surface (the seam is closed)
- [ ] each pass's existing `print()` output is unchanged (added-to, not rerouted)

## Out of scope for this slice (deferred)

- **Any pass beyond the four in #270** — `intake`, `chunk`, `artifacts`, `xref`,
  `ingest` are not "runs that matter" under this issue. `ingest` already has its
  own TSV; folding it into `run.jsonl` belongs with the #277 runner, not here.
- **The corpus runner (#277)** — it opens one `run_context` around a full loop;
  this slice logs each pass invoked directly.
- **Rate reporting (#288)** — reads these records; not built here.
- **Extending the record shape** — if a pass needs a field the slice-01 shape
  lacks, that is a seam change and a signal to revisit 01, not to widen the shape
  ad hoc here.
- **`summary.md` content** — operator-authored, as in slice 01.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Correction — `eval` is not a model-bearing pass

This plan called `envelope`, `tag` and `eval` "the model-bearing passes" and its
Gherkin demanded a non-null `model` on every record. That was wrong about `eval`:
`src/axial/eval/` imports only `DEFAULT_PIPELINE_CONFIG_PATH` from `axial.llm`
and holds no client — the pass scores predictions against gold labels and makes
no completion call at all. So the landed slice records:

- `model: null` for `eval` — writing the stub's id would name a model that never
  ran, which is a false run record. Matches slice 01's `extract` precedent.
- one record per **invocation**, `source_id: ""` — `eval` takes no `source_path`;
  it scores the whole gold set atomically, so there is no per-source granularity
  to record.

Founder accepted both on 2026-07-21. The plan was corrected rather than the code:
the acceptance criterion above still reads as originally written, and its
"non-null `model`" clause applies to `envelope` and `tag` only.

## Status / progress log

- 2026-07-21 planned.
- 2026-07-21 merged as PR #310 (`301e37a`). Two deviations accepted (above);
  `llm.py` gained `model_for_pass()` on the protocol and all four clients, which
  de-duplicates the resolution `_post_with_deadline` already performed.
