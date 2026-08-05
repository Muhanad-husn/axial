# Slice 01: The analysis record and `axial brief run`

- **Feature:** analysis-record
- **Slice slug:** analysis-record-and-brief-run
- **GitHub issue:** #257
- **Branch:** `feat/analysis-record/01-analysis-record-and-brief-run`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no (new stage module `src/axial/answer/`, but it stands
  on stages 1–4 already built beneath it)
- **Depends on:** `analysis-synthesis` slice 02 (the claim graph) and
  `analysis-foundation` slice 02 (the corpus-pin manifest)

## Goal — the minimum testable behaviour

`axial brief run <brief_file>` drives stages 1 through 6 and writes **one
analysis-record JSON per brief run** at `data/analyses/<brief_id>.json`.

The record carries the full §7.3 shape, every key present:

```
brief_id, brief, corpus_pin, schema_version, lens, interrogation,
claims, counter_position, coverage_map, confidence, trajectory, model_by_pass
```

- `brief` is the §7.1 brief verbatim.
- `corpus_pin` is the pin id the run was produced against (§7.12), and
  `schema_version` is the domain schema version the vault was tagged under. Two
  records are comparable only if their pins match (P0-8 bullet 3, P0-10).
- `claims` is the §7.4 claim graph as `analysis-synthesis` emitted it.
- `trajectory` is the §7.6 retrieval trajectory log, one
  `{step, tool, args, result_ids[], result_count}` entry per tool call, in call
  order.
- `model_by_pass` records which model and reasoning setting each pass used.
- No field is nullable except as stated in §7.3–§7.8.

On disposition `refuse` the record is **still written**, `claims` is empty, no
synthesis call is made, and the command exits 0. A refusal is a completed run,
not an error (§7.2, P0-1 bullet 3).

`counter_position`, `coverage_map`, and `confidence` are written from whatever
the validators compute. This slice lands the record spine and the run command;
the validator-computed content lands with the `analysis-validators` feature.

## INVEST check

- **Independent:** it orchestrates stages that already exist and serializes what
  they returned. It reimplements none of them, and no earlier stage changes.
- **Valuable:** §7.3 calls the record "the load-bearing artifact" and "the audit
  surface". Without it a run leaves no trace: every downstream consumer — the
  markdown answer, eval #1, eval #3, the rung-3 gates — reads this file. `run`
  is also the command that makes the engine usable at all (P0-9 bullet 1).
- **Small:** one orchestration function over existing stages, one serializer,
  one CLI subcommand.
- **Testable:** hermetic. Every model pass is scripted through the
  `record`/`stub` providers; the refusal path's "no synthesis call" is asserted
  by poisoning the synthesis pass.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture vault, a written corpus pin under evals/corpus_pin/, and a
      brief file config/briefs/dev/fixture-syria-displacement.yaml
  And AXIAL_LLM_PROVIDER=record so interrogation, retrieval, and synthesis are
      all scripted, the interrogation yielding disposition "proceed"
When  `axial brief run config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command exits 0
  And data/analyses/<brief_id>.json exists, where <brief_id> is the id the
      brief loader computes for that brief
  And the record carries every §7.3 key: brief_id, brief, corpus_pin,
      schema_version, lens, interrogation, claims, counter_position,
      coverage_map, confidence, trajectory, model_by_pass
  And record["brief"] equals the loaded brief verbatim
  And record["corpus_pin"] equals the pin id under evals/corpus_pin/
  And record["claims"] equals the claim graph the synthesis pass emitted
  And record["trajectory"] is a list of {step, tool, args, result_ids,
      result_count} entries in tool-call order
  And record["model_by_pass"] names each pass that ran

Given the same brief run a second time over the same pinned vault
When  `axial brief run` runs again
Then  the record is written to the identical path data/analyses/<brief_id>.json

Given a brief whose scripted interrogation yields disposition "refuse" with a
      reason
  And the synthesis pass is poisoned so any stage-4 model call raises
      (AXIAL_LLM_PROVIDER=explode on the synthesis pass_name, or the
      equivalent call-counting seam)
When  `axial brief run` runs on it
Then  the command exits 0
  And data/analyses/<brief_id>.json is still written
  And record["claims"] is the empty list
  And record["interrogation"]["disposition"] is "refuse" with the reason present
  And the synthesis call count is 0
```

- **Boundary / endpoint:** CLI — `axial brief run <brief_file>`; the written
  file `data/analyses/<brief_id>.json`.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_analysis_record.py` — authored by
  the test-author, committed red, then locked (DEC-1).

## Inner loop — initial unit test list

Co-located under `src/axial/answer/` (e.g. `src/axial/answer/test_record.py`).

- [ ] The serializer emits every §7.3 key; a record missing any key fails to
      serialize rather than writing a partial file.
- [ ] `brief` round-trips verbatim: loading the written record back yields the
      same `case`, `request`, and `lens` the brief file carried.
- [ ] The record path is derived from `brief_id`, so the same brief content
      overwrites the same path rather than accumulating files.
- [ ] `data/analyses/` is created when absent.
- [ ] The record is written **atomically enough** that an interrupted run leaves
      either no file or a complete one, never a truncated JSON.
- [ ] `corpus_pin` is read from the written pin manifest, not recomputed.
- [ ] `schema_version` is read from the domain schema the vault was tagged
      under.
- [ ] Disposition routing: `proceed` and `proceed_bounded` invoke synthesis;
      `refuse` skips it and yields an empty `claims` list.
- [ ] The `trajectory` block preserves tool-call order and step numbering as
      stage 3 emitted it; no re-sorting.
- [ ] `model_by_pass` records the resolved model and reasoning setting per pass,
      not the config file's raw text.
- [ ] The `axial brief run` subparser is registered on the existing argparse
      tree and exits non-zero on a missing brief file path.
- [ ] JSON output is written with stable key ordering, so a record diffs
      cleanly across runs.

## Out of scope for this slice (deferred)

- The markdown answer (§7.10) — slice 02.
- **Computing** `counter_position`, `coverage_map`, and `confidence`. Those are
  the `analysis-validators` feature (P0-6, P0-7, §7.8, §7.7). This slice carries
  the fields on the record and writes whatever the validators supply; the
  validator-computed content lands with `analysis-validators`.
- The validators' release-blocking behaviour on a failed mechanical check
  (§7.9). This slice writes a record; blocking a release is the validators'.
- Writing the corpus-pin manifest — `analysis-foundation` slice 02. This slice
  reads a pin id.
- Detecting a pin mismatch between two records (§7.12). Eval work.
- Any change to stages 1–4.
- Multi-brief batching or sweeps (§3 non-goal 6).

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED, seen to
      fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` (`safe-pr`) — merge awaits
      founder approval.

## Status / progress log

- 2026-07-20 planned.
