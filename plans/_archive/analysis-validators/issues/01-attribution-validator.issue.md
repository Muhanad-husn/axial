# feat(analysis-validators): attribution validator — every claim marked, every (a)/(b) ground resolvable [slice 01]

**Spec:** specs/PHASE-B.md#7.9 · §8 P0-5 · **Plan:** plans/analysis-validators/01-attribution-validator.md
**Depends on:** #257, #249
**Labels:** sub:analysis-v0, enhancement

## Deliverable
A **deterministic** validator reads the analysis record at
`data/analyses/<brief_id>.json` and fails it when any claim's `kind` is absent or
outside `{a,b,c}`, or when any claim of kind `a` or `b` has empty `grounds` or a
`{ref_type, ref_id}` pointer that does not **resolve** through the vault query
API — `chunk` via `get_chunk`, `artifact` via `get_artifact`. Resolution is
checked against the vault, not against pointer shape: a well-formed pointer to a
chunk_id the vault does not contain is a failure. A `c` claim may carry partial or
empty grounds. A failure **blocks release** — the run emits no answer and the CLI
exits non-zero naming the offending `claim_id`s and reasons. Riding on the same
validator, a **bounded independent model check** flags a claim marked `b` that is
phrased as a source assertion (§7.9's (b)-seam honesty check); it runs under its
own `pass_name` so `model_by_pass` points it at a different model from the
synthesis pass. The generating model never checks its own attribution. All tests
are hermetic: fake vault, `stub`/`record`/`explode` providers, scripted judge.

## Acceptance criterion
```gherkin
Given a vault containing chunk "syr-0001" and artifact "art-0007"
  And an analysis record at data/analyses/DEV01.json whose claims all carry a
      kind in {a,b,c} and whose every (a)/(b) grounds pointer resolves
When  `axial brief validate DEV01` runs
Then  the command exits 0 and the attribution validator reports pass

Given an analysis record at data/analyses/DEV02.json carrying one claim "c-003"
      with no `kind` field
When  `axial brief validate DEV02` runs
Then  the command exits non-zero, the report names "c-003" with reason
      "missing_kind", and no answer is released for DEV02

Given an analysis record at data/analyses/DEV03.json carrying one claim "c-005"
      of kind "a" whose grounds is
      [{"ref_type": "chunk", "ref_id": "syr-9999"}]
  And the vault contains no chunk "syr-9999"
When  `axial brief validate DEV03` runs
Then  the command exits non-zero, the report names "c-005" with reason
      "unresolvable_grounds", and no answer is released for DEV03

Given an analysis record at data/analyses/DEV04.json carrying one claim "c-002"
      of kind "b" whose text reads as a source assertion
  And the LLM provider is the `record` provider scripted to flag "c-002"
When  `axial brief validate DEV04` runs
Then  the report names "c-002" with reason "b_seam_voiced_as_source"
  And the check ran under a pass_name distinct from the synthesis pass
```

## Out of scope
- The **grounding check** (does the cited chunk substantively support the claim
  text, §7.9) — a bounded model judgment scored as a rung-3 gate, not a per-run
  mechanical blocker.
- Counter-position and coverage/confidence validation (slices 02 and 03).
- Any repair behaviour: no claim dropping, no re-prompting, no retry. The
  validator reports and blocks.
- Aggregate cross-run metrics (attribution-completeness rate, (b) mislabel rate).
  Those belong to `rung3-gates` slice 01 (§10).
- Choosing the judge model or its family (§7.11, Open Questions). This slice lands
  the seam and the distinct `pass_name`.
</content>
