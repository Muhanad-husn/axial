# Feature: Analysis validators — the deterministic post-passes

Put three gates behind the synthesis, outside the model's control. Stage 5 of the
engine (§5, §7.9) runs after the claim graph exists and before anything is
released: the **attribution validator** confirms every claim carries a kind and
every (a)/(b) claim's grounds resolve to a real vault id; the **counter-position
validator** confirms a contested brief carries a §7.8 counter-position section or
an explicit corpus-one-sided disclosure; the **coverage/confidence validator**
computes the per-polity coverage map deterministically from `polities_touched`
and confirms a confidence disclosure is present. Each is mechanical wherever the
property is mechanically checkable; where it genuinely is not — is a (b) claim
phrased as a source assertion, is a steelman actually a strawman — a bounded
model call runs, never the model that generated the answer. **A failed mechanical
check blocks release.** The operator (founder) benefits: an analysis that reaches
them has already failed to be quietly ungrounded, quietly one-sided, or quietly
overconfident. The checks are code, so they do not depend on the model behaving.

- **Slug:** analysis-validators
- **Created:** 2026-07-20
- **Status:** planned
- **New system?** no (new stage-5 module `src/axial/validate/` inside the
  existing `axial` CLI and LLM seams; slice 01 is the thinnest end-to-end thread
  through the new validator surface)
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [attribution-validator](01-attribution-validator.md) | [#258](https://github.com/Muhanad-husn/axial/issues/258) | A deterministic validator fails a record whose claim lacks a `kind` in `{a,b,c}` or whose (a)/(b) `grounds` pointer does not resolve to a real vault id via the query API, blocking release; a bounded independent model check flags a (b) claim phrased as a source assertion | ☐ todo | TBD |
| 02 | [counter-position-validator](02-counter-position-validator.md) | [#259](https://github.com/Muhanad-husn/axial/issues/259) | On a brief detected contested from corpus signal, the §7.8 section must be present with non-empty grounds or carry an explicit `corpus_one_sided` reason — absence of both fails as a red flag, not a clean pass | ☐ todo | TBD |
| 03 | [coverage-and-confidence](03-coverage-and-confidence.md) | [#260](https://github.com/Muhanad-husn/axial/issues/260) | A per-polity `coverage_map` is computed deterministically from `polities_touched` with `{corpus_chunk_count, evidence_chunk_count, coverage_band}`, and a missing map or missing `confidence` disclosure blocks release | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Dependencies

- All three slices depend on `analysis-record` slice 01: there must be a §7.3
  record with a §7.4 claim graph to validate. The validators read the record;
  they never produce claims.
- 01 additionally depends on `vault-query` for `get_chunk` / `get_artifact` —
  grounds resolution is checked **against the query API**, not against pointer
  shape. A syntactically valid pointer to a chunk_id that does not exist is a
  failure.
- 03 additionally depends on `vault-query` for `coverage_count` and
  `query_by_polity` — the corpus side of the coverage map.
- **02 and 03 are independent of each other** and can run in either order.
- Downstream: `rung3-gates` slice 01 depends on this feature's slice 01, and
  `rung3-gates` slice 02 depends on slices 02 and 03. The gates measure rates
  over runs; these validators are the per-run release gate. Different jobs, same
  underlying checks.

## Out of scope (whole feature)

- Producing or repairing claims. A validator reports pass/fail with reasons; it
  never edits the record, re-prompts the synthesis, or drops an offending claim.
  Retry policy is not a v0 concern.
- The **grounding check** (§7.9, does the cited chunk substantively support the
  claim text) as a release gate. It is a bounded model judgment and lands as a
  rung-3 *gate* in `rung3-gates` slice 01, not a per-run blocker here.
- The rung-3 gate metrics themselves (attribution-completeness rate, presence
  rate, calibration error). Those aggregate over many runs and belong to
  `rung3-gates` (P0-12, §10).
- Rendering the validator outcome into the markdown answer (§7.10). The record
  carries the result; `analysis-record` owns rendering.
- Any change to the claim-graph shape, the counter-position shape, or the
  coverage-map shape. All three are locked in §7.4, §7.8, and §7.7; this feature
  checks them, it does not define them. A shape that seems wrong is spec drift.
- Live LLM calls anywhere in the test path. Bounded model checks are exercised
  through the `stub` / `record` / `explode` providers with a scripted judge.

## Notes / open questions

- **The contested-detection rule is a stated tunable** (§7.8, P0-6), proven on
  the dev briefs. Slice 02 lands a starting rule — evidence spanning two or more
  distinct `theory_school` values, **or** any evidence chunk carrying
  `role:counter-position` — in config, not hardcoded, so tuning is a config
  change and not a code change. The starting rule is a hypothesis; the plan says
  so.
- **The coverage-band threshold is likewise a stated tunable**, in the spirit of
  the Phase-A chunk band (PRODUCT.md §7.7). Slice 03 lands starting cut points
  in config and an inspection affordance to prove them against the real vault.
  Both the rule and the band get revisited once the full ~30-source vault and the
  dev briefs are in hand.
- **Never the generating model.** Both bounded model checks (the (b)-seam honesty
  check in 01, the steelman-quality check in 02) must run under a distinct
  `pass_name` so `model_by_pass` can point them at a different model from the
  synthesis pass (§7.11, charter §2). The implementer wires the pass name; the
  founder picks the model. A check whose configured model equals the synthesis
  model is a config error worth surfacing loudly.
- **Judge-model protocol details are an open spec question** (§ Open Questions,
  deferred to eval #1). These slices need only *a* judge seam and a scripted
  judge in tests; they do not settle model family or agreement sampling.
- **Reuse from Phase A.** `src/axial/eval.py`'s report scaffolding and its
  per-polity folding are the closest existing shape and worth reading before
  writing new JSON-report plumbing. Its *data* shape is not reusable — it scores
  gold labels, these score analysis records.
</content>
</invoke>
