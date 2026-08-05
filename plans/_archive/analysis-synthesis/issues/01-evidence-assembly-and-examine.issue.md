# feat(analysis-synthesis): evidence assembly and `axial brief examine` — inspect before spend [slice 01]

**Spec:** specs/PHASE-B.md#7.5 · specs/PHASE-B.md#5 stage 4 · §8 P0-4, P0-9 · **Plan:** plans/analysis-synthesis/01-evidence-assembly-and-examine.md
**Depends on:** #254
**Labels:** sub:analysis-v0, enhancement

## Deliverable
The evidence set retrieved by stage 3 is assembled into one inspectable object
and reported before the expensive synthesis call. `axial brief examine
<brief_file>` runs interrogation and retrieval and prints the retrieved
`chunk_id`s in retrieval order, the raw per-polity coverage counts
(`corpus_chunk_count` from the query API's `coverage_count`, plus this run's
`evidence_chunk_count`), and the §7.2 interrogation result. It makes **zero
stage-4 synthesis calls**, writes nothing under `data/analyses/`, and exits 0 —
including on a `refuse` disposition, which is a completed run and not an error.
The bounded cost is the lockable property, asserted mechanically rather than
asserted in a comment.

## Acceptance criterion
```gherkin
Given a fixture vault and a brief file config/briefs/dev/fixture-syria-displacement.yaml
  And AXIAL_LLM_PROVIDER=record so the interrogation and retrieval passes are
      scripted and every prompt is written to AXIAL_LLM_RECORD_PATH
  And the scripted retrieval loop returns a known evidence set of chunk ids
When  `axial brief examine config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command exits 0
  And stdout lists exactly the retrieved chunk_ids, in retrieval order
  And stdout reports, for every polity the evidence set touches, both a
      corpus_chunk_count and an evidence_chunk_count
  And stdout reports the interrogation result's disposition, premises_found,
      and bounds_applied
  And no file is written under data/analyses/

Given the same brief and vault
  And the synthesis pass is poisoned so that any stage-4 model call raises
      (AXIAL_LLM_PROVIDER=explode on the synthesis pass_name, or the
      equivalent call-counting seam asserting a synthesis call count of 0)
When  `axial brief examine config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command still exits 0
  And the synthesis call count is 0

Given a brief whose scripted interrogation yields disposition "refuse" with a
      reason
When  `axial brief examine` runs on it
Then  the command exits 0
  And stdout states the refusal and its reason
  And the synthesis call count is 0
```

## Out of scope
- The synthesis call and the claim graph (§7.4, P0-4 bullets 2–4) — slice 02.
- Coverage **bands** (§7.7 `coverage_band`) and the threshold deriving them.
  This slice reports raw counts only; banding is `analysis-validators`.
- The confidence disclosure, the counter-position section (§7.8), and the
  analysis record (§7.3).
- `axial brief run` (P0-9 bullet 1) — `analysis-record` slice 01.
- Any change to the retrieval loop's planning or step budget (P0-3).
