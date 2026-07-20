# feat(analysis-record): the analysis record and `axial brief run` [slice 01]

**Spec:** specs/PHASE-B.md#7.3 · specs/PHASE-B.md#7.12 · §8 P0-8, P0-9 · **Plan:** plans/analysis-record/01-analysis-record-and-brief-run.md
**Depends on:** #256, #248
**Labels:** sub:analysis-v0, enhancement

## Deliverable
`axial brief run <brief_file>` drives stages 1–6 and writes one analysis-record
JSON per brief run at `data/analyses/<brief_id>.json`, carrying the full §7.3
shape: `brief_id`, `brief` (verbatim), `corpus_pin`, `schema_version`, `lens`,
`interrogation`, `claims`, `counter_position`, `coverage_map`, `confidence`,
`trajectory`, `model_by_pass`. No field is nullable except as stated in
§7.3–§7.8. Each record records the `corpus_pin` and `schema_version` it was
produced against, so two records are comparable only if their pins match
(§7.12, P0-10). On disposition `refuse` the record is **still written**,
`claims` is empty, no synthesis call is made, and the command exits 0 — a
refusal is a completed run, not an error (§7.2). This issue scopes the record
spine and the run command; the validator-computed content of
`counter_position` / `coverage_map` / `confidence` lands with the
`analysis-validators` feature.

## Acceptance criterion
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

## Out of scope
- The markdown answer (§7.10) — slice 02.
- **Computing** `counter_position`, `coverage_map`, and `confidence` (P0-6,
  P0-7, §7.8, §7.7). This slice carries the fields and writes whatever the
  validators supply; the validator-computed content lands with
  `analysis-validators`.
- The validators' release-blocking behaviour on a failed mechanical check
  (§7.9).
- Writing the corpus-pin manifest — `analysis-foundation` slice 02. This slice
  reads a pin id.
- Detecting a pin mismatch between two records (§7.12) — eval work.
- Any change to stages 1–4; multi-brief batching or sweeps (§3 non-goal 6).
