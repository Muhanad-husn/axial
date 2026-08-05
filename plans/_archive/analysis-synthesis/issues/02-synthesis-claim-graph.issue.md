# feat(analysis-synthesis): synthesis pass emits the marked, grounded claim graph [slice 02]

**Spec:** specs/PHASE-B.md#7.4 · specs/PHASE-B.md#7.11 · §8 P0-4 · **Plan:** plans/analysis-synthesis/02-synthesis-claim-graph.md
**Depends on:** #255
**Labels:** sub:analysis-v0, enhancement

## Deliverable
The synthesis pass takes the assembled evidence set, applies the named lens from
`config/lenses/` (selecting and **recording** one when the brief omits `lens`,
§7.1), performs axial coding across the evidence, and emits the §7.4 claim
graph. Each claim is `{claim_id, text, kind, grounds[], confidence,
polities_touched[]}`: `kind` is exactly one of `a` / `b` / `c`; `grounds` is a
list of `{ref_type, ref_id}` with `ref_type` in `{chunk, artifact}` and `ref_id`
a real vault id, **required non-empty for every (a) and (b) claim**;
`polities_touched` is computed in code as the union of the grounds chunks'
facets, so the coverage map is computable from the claim graph; `claim_id` is
stable and deterministic within a run. Claims are **grounded by construction**:
the prompt forbids asserting from parametric memory or the open web and reasons
only over the supplied grounds — asserted deterministically against the recorded
prompt via the `record` provider. A (b) cross-source inference is emitted as a
(b) claim with real grounds, never voiced as a source assertion; unrequested
corpus-grounded analogues are permitted on the same terms. The pass runs on the
high tier with reasoning ON via a `model_by_pass` entry in
`config/pipeline.yaml`, never a hardcoded model name (§7.11).

## Acceptance criterion
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

## Out of scope
- The attribution validator (P0-5) and the bounded model check on whether a (b)
  claim is *phrased* as a source assertion (§7.9) — `analysis-validators`.
- The grounding check on whether a cited chunk supports the claim text (§7.9,
  §10). Independent-model work, never the generating model's.
- The counter-position section (§7.8) and the coverage map with bands (§7.7).
- The per-claim `confidence` **vocabulary** — bands vs numeric is an Open
  Question (§7.4) awaiting founder adjudication. The field is carried through;
  no scale is hardcoded here.
- Persisting the claim graph — `analysis-record` slice 01 owns
  `data/analyses/<brief_id>.json`.
- Choosing the concrete high-tier model string. The `model_by_pass` entry lands;
  the tier it names is a **[TENTATIVE]** operational decision (§7.11).
