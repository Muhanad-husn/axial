# Slice 02: Synthesis — lens, axial coding, and the marked claim graph

- **Feature:** analysis-synthesis
- **Slice slug:** synthesis-claim-graph
- **GitHub issue:** #256
- **Branch:** `feat/analysis-synthesis/02-synthesis-claim-graph`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** slice 01 (the assembled evidence set)

## Goal — the minimum testable behaviour

The synthesis pass takes slice 01's assembled evidence set, applies the named
lens, performs axial coding across the evidence, and emits the §7.4 claim graph.

Each claim is `{claim_id, text, kind, grounds[], confidence, polities_touched[]}`:

- `kind` is exactly one of `a` (source-says), `b` (tool-infers-across-sources),
  `c` (speculation). No claim is emitted unmarked.
- `grounds` is a list of `{ref_type, ref_id}` where `ref_type` is `chunk` or
  `artifact` and `ref_id` is a real vault id. **Non-empty is required for every
  (a) and (b) claim**; a (c) claim may carry partial or empty grounds.
- `polities_touched` is the union of the `polities_touched` facets of the
  claim's grounds chunks, computed deterministically in code, so the coverage
  map (§7.7) is computable from the claim graph rather than asked of a model.
- `claim_id` is stable and deterministic within a run.

The lens comes from `config/lenses/` when the brief names one. When the brief
omits `lens`, the stage selects one and **records which**, so the choice is
always disclosed (§7.1).

**Grounded by construction** (P0-4 bullet 3): the prompt forbids asserting from
parametric memory or the open web and instructs the model to reason only over
the supplied grounds. That is a prompt-content property and is asserted
deterministically against the recorded prompt, the same way the #228
anti-anecdote test does. A (b) cross-source inference is emitted as a (b) claim
with real grounds, never voiced as a source assertion; unrequested
corpus-grounded analogues are permitted on exactly the same terms (P0-4 bullet
4, charter §3).

The pass runs on the high tier with reasoning ON per §7.11, via a
`model_by_pass` entry in `config/pipeline.yaml`, never a hardcoded model name.

## INVEST check

- **Independent:** it consumes the evidence set slice 01 assembles and returns a
  claim graph object. It neither persists nor validates; those are separate
  features that read its output.
- **Valuable:** this is the phase's product. Everything else in Phase B feeds it
  or checks it. The (b) seam it emits is, per §7.4, the whole value of the tool.
- **Small:** one prompt, one parser, one deterministic post-step that computes
  `polities_touched` and `claim_id`, one config entry.
- **Testable:** the model is scripted (`record` provider), so both halves lock
  cleanly. The claim graph's shape is asserted against the canned response; the
  grounded-by-construction instruction is asserted against the recorded prompt.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture vault, a brief naming lens "political-economy", and an
      assembled evidence set of known chunk ids
  And AXIAL_LLM_PROVIDER=record with AXIAL_LLM_RECORD_PATH set, the canned
      synthesis response carrying one (a) claim, one (b) claim, and one (c)
      claim
When  the synthesis pass runs over that evidence set
Then  every emitted claim carries a `kind` in {a, b, c}
  And the (a) claim and the (b) claim each carry at least one `grounds` entry
  And every grounds entry is {ref_type, ref_id} with ref_type in
      {chunk, artifact} and ref_id resolving to a real id in the fixture vault
  And each claim's `polities_touched` equals the union of its grounds chunks'
      polities_touched facets
  And `lens` is recorded as "political-economy"

Given the recorded prompt at AXIAL_LLM_RECORD_PATH from that run
Then  the prompt instructs the model to reason only over the supplied grounds
  And the prompt forbids asserting from parametric memory or the open web
  And the prompt states that a cross-source inference is marked (b) and never
      voiced as a source assertion

Given the canned response carries an (a) claim with empty grounds
When  the synthesis pass runs
Then  the pass fails loudly with the offending claim named, and no claim graph
      with an ungrounded (a) claim is returned

Given a brief with no `lens` field
When  the synthesis pass runs
Then  a lens is selected from config/lenses/ and recorded on the result,
      never left null

Given the same evidence set and the same canned response
When  the synthesis pass runs twice
Then  the two claim graphs carry identical claim_ids
```

- **Boundary / endpoint:** library entry
  `axial.analyze.synthesize(evidence_set, brief, lens) -> ClaimGraph`; the LLM
  boundary is the synthesis `pass_name`.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_synthesis_claim_graph.py` —
  authored by the test-author, committed red, then locked (DEC-1).

## Inner loop — initial unit test list

Co-located under `src/axial/analyze/` (e.g. `src/axial/analyze/test_synthesis.py`).

- [ ] The response parser rejects a claim whose `kind` is absent, empty, or
      outside `{a, b, c}`, naming the claim.
- [ ] The parser rejects an (a) or (b) claim with absent or empty `grounds`; it
      accepts a (c) claim with empty grounds.
- [ ] A grounds entry whose `ref_id` does not resolve in the vault is rejected,
      naming the id — a hallucinated citation never reaches the claim graph.
- [ ] `ref_type` outside `{chunk, artifact}` is rejected.
- [ ] `polities_touched` is computed in code from the grounds chunks' facets and
      overrides whatever the model emitted for that field.
- [ ] `polities_touched` de-duplicates across grounds and is order-stable.
- [ ] `claim_id` is deterministic within a run and unique across the claim graph.
- [ ] Lens resolution: a named lens loads from `config/lenses/`; an unknown lens
      name fails with the name in the error; an absent lens yields a selected
      lens recorded on the result.
- [ ] The prompt embeds the evidence chunks' text and ids, so grounds pointers
      are drawn from what was supplied rather than invented.
- [ ] The pass sends its own `pass_name`, so `model_by_pass` /
      `reasoning_by_pass` can route it; `config/pipeline.yaml` carries the
      high-tier entry with reasoning ON (§7.11).
- [ ] An unparseable model response fails with a clear error rather than an
      empty claim graph — an empty `claims` list is valid only on refusal
      (§7.3).

## Out of scope for this slice (deferred)

- The attribution validator (P0-5). This slice *emits* a well-formed claim
  graph; the post-pass that independently re-checks it is `analysis-validators`.
  The two overlap deliberately: emitting correctly and verifying independently
  are different jobs (§4, "the code holds the line").
- The bounded model check on whether a (b) claim is *phrased* as a source
  assertion (§7.9). Mechanically un-checkable here; it belongs to the validator.
- The grounding check — whether a cited chunk actually supports the claim text
  (§7.9, §10). Independent-model work, not the generating model's.
- The counter-position section (§7.8) and the coverage map with bands (§7.7).
- Per-claim `confidence` **vocabulary**. The field is carried through; whether
  it is a band or a number is an Open Question (§7.4) awaiting founder
  adjudication. Carry whatever the confidence decision lands on without
  hardcoding a scale here.
- Persisting the claim graph. `analysis-record` slice 01 owns
  `data/analyses/<brief_id>.json`.
- Choosing the concrete high-tier model. The `model_by_pass` entry lands; which
  tier string it names is a **[TENTATIVE]** operational decision (§7.11).

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
