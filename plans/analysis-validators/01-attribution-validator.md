# Slice 01: Attribution validator — every claim marked, every (a)/(b) ground resolvable

- **Feature:** analysis-validators
- **Slice slug:** attribution-validator
- **GitHub issue:** #258
- **Branch:** `feat/analysis-validators/01-attribution-validator`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** yes (thinnest end-to-end thread through the new
  `src/axial/validate/` module and the validator's pass/fail release seam)
- **Depends on:** `analysis-record` slice 01 (there must be a §7.3 record with a
  §7.4 claim graph to validate); `vault-query` (`get_chunk` / `get_artifact`, for
  real resolution)

## Goal — the minimum testable behaviour

A deterministic validator reads an analysis record at
`data/analyses/<brief_id>.json` and returns a pass/fail result. It fails when any
claim's `kind` is absent or outside `{a,b,c}`, and when any claim of kind `a` or
`b` has empty `grounds` or carries a `{ref_type, ref_id}` pointer that **does not
resolve** through the query API — `ref_type: chunk` resolved by `get_chunk`,
`ref_type: artifact` by `get_artifact`. Resolution is checked against the vault,
not against pointer shape: a well-formed pointer to a chunk_id the vault does not
contain is a failure. A `c` claim may carry partial or empty grounds. A failure
**blocks release**: the run does not emit an answer, and the CLI exits non-zero
with the offending `claim_id`s named.

Riding on the same validator, a **bounded independent model check** flags a claim
marked `b` that is phrased as a source assertion — the honesty half of the (b)
seam (§7.9, P0-5). It runs under its own `pass_name` so `model_by_pass` can point
it at a model from a different family than the synthesis pass. The generating
model never checks its own attribution.

## INVEST check

- **Independent:** reads a finished record and the vault; changes nothing
  upstream. It does not touch synthesis, retrieval, or the record's shape.
- **Valuable:** this is the mechanical floor under Principle II. Without it, the
  a/b/c marking is a convention the model may or may not honour; with it, an
  unmarked claim or a hallucinated chunk_id cannot reach the operator. It is also
  the *only* check that catches generate-then-cite mechanically.
- **Small:** one pass over `record["claims"]`, two query-API lookups, one bounded
  model call for the (b) phrasing check.
- **Testable:** hand-built records — one clean, one with an unmarked claim, one
  with a pointer to a non-existent chunk_id — against a fake vault and a scripted
  judge. No LLM, no network.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a vault containing chunk "syr-0001" and artifact "art-0007"
  And an analysis record at data/analyses/DEV01.json whose claims all carry a
      kind in {a,b,c} and whose every (a)/(b) grounds pointer resolves
When  `axial brief validate DEV01` runs
Then  the command exits 0
  And the attribution validator reports pass with zero failures

Given an analysis record at data/analyses/DEV02.json carrying one claim
      "c-003" with no `kind` field
When  `axial brief validate DEV02` runs
Then  the command exits non-zero
  And the report names "c-003" with reason "missing_kind"
  And no answer is released for DEV02

Given an analysis record at data/analyses/DEV03.json carrying one claim
      "c-005" of kind "a" whose grounds is
      [{"ref_type": "chunk", "ref_id": "syr-9999"}]
  And the vault contains no chunk "syr-9999"
When  `axial brief validate DEV03` runs
Then  the command exits non-zero
  And the report names "c-005" with reason "unresolvable_grounds"
  And no answer is released for DEV03

Given an analysis record at data/analyses/DEV04.json carrying one claim
      "c-002" of kind "b" whose text reads as a source assertion
  And the LLM provider is the `record` provider scripted to flag "c-002"
When  `axial brief validate DEV04` runs
Then  the report names "c-002" with reason "b_seam_voiced_as_source"
  And the check ran under a pass_name distinct from the synthesis pass
```

- **Boundary / endpoint:** CLI — `axial brief validate <brief_id>`; the record at
  `data/analyses/<brief_id>.json`; the validator report written into the record's
  validation section.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_attribution_validator.py` — authored
  by the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] Kind check: a claim with `kind` absent, `null`, `""`, or `"d"` fails with
      reason `missing_kind`; each of `a`, `b`, `c` passes.
- [ ] Grounds-presence check: kind `a` with `grounds: []` fails; kind `b` with
      `grounds: []` fails; kind `c` with `grounds: []` passes.
- [ ] Grounds-resolution check: `{ref_type: chunk, ref_id: <exists>}` resolves;
      `{ref_type: chunk, ref_id: <absent>}` fails `unresolvable_grounds`;
      `{ref_type: artifact, ref_id: <exists>}` resolves via `get_artifact`;
      an unknown `ref_type` fails.
- [ ] Resolution goes through the query API, not a string/shape check — a test
      with a fake query API asserts `get_chunk` was actually called per pointer.
- [ ] Partial failure: a record with one bad claim among five reports exactly one
      failure and names the right `claim_id`; the report lists all failures, not
      just the first.
- [ ] Release blocking: a failing validation makes the run exit non-zero and
      writes no answer file.
- [ ] The (b)-seam model check runs only over claims of kind `b` — zero model
      calls when the record has no (b) claims (`explode` provider proves it).
- [ ] The (b)-seam check uses a `pass_name` distinct from the synthesis pass, and
      a config in which the two resolve to the same model raises a clear error.
- [ ] A record with `disposition: refuse` and `claims: []` passes vacuously
      (§7.2 — a refusal is a completed, valid run).

## Out of scope for this slice (deferred)

- The **grounding check** — does the cited chunk substantively support the claim
  text (§7.9). That is a bounded model judgment scored as a rung-3 gate in
  `rung3-gates` slice 01, not a per-run mechanical blocker.
- Counter-position and coverage/confidence validation (slices 02 and 03).
- Any repair behaviour: no claim dropping, no re-prompting, no retry loop. The
  validator reports and blocks.
- Aggregate metrics across runs (attribution-completeness rate, (b) mislabel
  rate). Those are `rung3-gates` slice 01.
- Choosing the judge model or its family. The slice lands the seam and the
  distinct `pass_name`; the founder picks the model (§7.11, Open Questions).

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
</content>
