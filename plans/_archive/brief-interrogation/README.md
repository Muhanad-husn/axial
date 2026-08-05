# Feature: Brief interrogation pre-pass

Give the analysis engine a gate in front of it. Before any retrieval or
synthesis happens, a bounded model pass reads the brief (§7.1) and interrogates
it against what the corpus actually covers, emitting the structured
interrogation result (§7.2): the smuggled premises it found and how the corpus
treats each, the bounds it would apply, and a refusal when the corpus does not
support the request as posed. A deterministic wrapper — not the model — reads
those fields and sets the `disposition` to exactly one of `proceed`,
`proceed_bounded`, or `refuse`. A refusal is a completed run, not an error: the
result is persisted and no synthesis call is made. The founder benefits: a brief
that smuggles a premise the corpus contradicts comes back with the premise named
and the request bounded, instead of a confident, expensive answer built on a
false floor.

- **Slug:** brief-interrogation
- **Created:** 2026-07-20
- **Status:** planned
- **New system?** no (new stage inside the existing `axial` CLI and LLM seams;
  slice 01 is the thinnest end-to-end thread through the new pre-pass)
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [interrogation-pass-and-disposition](01-interrogation-pass-and-disposition.md) | [#252](https://github.com/Muhanad-husn/axial/issues/252) | A bounded model pass emits `{premises_found[], bounds_applied[], refusal, disposition}` for a brief, with `disposition` set deterministically by a wrapper, and a contradicted premise is NAMED in a `refuse`/`proceed_bounded` result rather than passed through | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Dependencies

- Slice 01 depends on `analysis-foundation` slice 01 (the brief loader — the
  §7.1 `{brief_id, case, request, lens?}` record this pass reads).
- Slice 01 depends on `vault-query` slice 02 (`coverage_count` /
  `query_by_polity`, used to test a premise against corpus coverage: a premise
  naming a polity the corpus barely covers is a thin-coverage finding).
- Stage 3 (`retrieval-loop` slice 02) consumes this feature's output — the
  interrogation result is what retrieval planning is driven from (§5 stage 3).

## Out of scope (whole feature)

- Synthesis, claim graph, validators, rendering (P0-4 through P0-8): this
  feature ends at the persisted interrogation result and the disposition.
- The full analysis record (§7.3). Slice 01 emits the `interrogation` block; the
  record that carries it is `analysis-foundation`'s.
- The adversarial red-teaming gate (P0-12, §10 premise-catch rate). The gate
  harness scores this pass; it is built with the other gates, not here.
- Tuning which model tier interrogation runs at (§7.11 is [TENTATIVE], "proven
  by measurement on the dev briefs"). The slice wires the `pass_name` seam so
  the tier is configurable; picking it is an operational pass.
- Any live-LLM test. Every acceptance test drives the `stub`/`record` provider.

## Notes / open questions

- **Pass name and tiering.** The pass registers a `pass_name` constant (mirroring
  `ENVELOPE_PASS_NAME = "envelope"` in `src/axial/llm.py`) so `model_by_pass` /
  `reasoning_by_pass` in `config/pipeline.yaml` can route it (§7.11). An unnamed
  pass falls back to the default model, which is an acceptable v0 default here:
  §7.11 says interrogation "may run cheaper".
- **Where the coverage signal comes from.** Testing a premise against coverage
  needs real counts, not model opinion. The pass reads `coverage_count` (and
  `query_by_polity` where the premise names a polity) from the `vault-query`
  API and puts those counts in the prompt, so the model assesses a premise
  against numbers rather than recalling them. The counts stay deterministic and
  the model's job is the assessment, not the arithmetic.
- **Deterministic disposition rule (the load-bearing bit).** §7.2 and P0-1 both
  put the disposition in the wrapper's hands, not the model's. The v0 rule:
  `refusal` non-null → `refuse`; else any `premises_found` entry assessed
  `contradicts`, or any non-empty `bounds_applied` → `proceed_bounded`; else
  `proceed`. A model-emitted `disposition` field, if present, is ignored. The
  rule is a stated tunable, but the *wrapper owning it* is not.
- **Prompt-content assertions.** Locking "the premise is NAMED" needs the prompt
  and the parsed result, both deterministic. Use the `record` provider
  (`AXIAL_LLM_PROVIDER=record`, `AXIAL_LLM_RECORD_PATH`) as the existing tests
  do — canned response out, full prompt text on disk to assert against.
