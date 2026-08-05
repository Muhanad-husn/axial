# feat(analysis-record): deterministic markdown answer rendered from the record [slice 02]

**Spec:** specs/PHASE-B.md#7.10 · §8 P0-8 · **Plan:** plans/analysis-record/02-markdown-answer-rendering.md
**Depends on:** #260, #257
**Labels:** sub:analysis-v0, enhancement

## Deliverable
A human-readable markdown answer is rendered from the analysis record and
written alongside the JSON (§7.10). It presents the claims with their **kind
visible to the reader** — (a), (b), and (c) legible on the page, since they
carry different weight (charter Principle II) — the counter-position section
(§7.8), the coverage map with per-polity counts and bands (§7.7), and the
confidence disclosure with its rationale. On a `refuse` disposition it states
the refusal and its reason and presents no claims. The renderer reads the record
and nothing else: no model call, no vault read, no clock. **Rendering is
deterministic: the same record renders byte-identical markdown**, which is this
issue's lockable property. Plain rendering only; venue, length, and style
adaptation is Phase D (§3 non-goal 2).

## Acceptance criterion
```gherkin
Given a fixture analysis record carrying one (a) claim, one (b) claim, one (c)
      claim, a counter-position section with non-empty grounds, a coverage_map
      with one dense polity and one thin polity, and a confidence disclosure
      with a rationale
When  the answer is rendered from that record
Then  each claim's text appears in the markdown
  And each claim's kind is legible on the page as (a), (b), or (c)
  And the counter-position section appears with its stance and grounds
  And every polity in the coverage_map appears with its corpus and evidence
      chunk counts and its coverage band
  And the confidence disclosure and its rationale appear

Given the same fixture record
When  the answer is rendered twice
Then  the two rendered strings are byte-identical

Given a record whose interrogation disposition is "refuse" with a reason and
      whose claims list is empty
When  the answer is rendered
Then  the markdown states the refusal and its reason
  And no claims section is rendered

Given a fixture vault, a corpus pin, and a brief file
  And AXIAL_LLM_PROVIDER=record so every pass is scripted
When  `axial brief run config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command exits 0
  And both data/analyses/<brief_id>.json and the rendered markdown answer are
      written
  And re-running the same brief rewrites byte-identical markdown
```

## Out of scope
- **Venue, length, and style adaptation** — Phase D (§3 non-goal 2). No
  formatting options land here.
- Computing the coverage map, the counter-position, or the confidence
  disclosure. This slice presents what `analysis-validators` computed.
- Any output format other than markdown (no HTML, no PDF, no notebook).
- Narrative arc, apparatus, or paper structure — Phase C (§3 non-goal 1).
- Re-rendering historical records in bulk, or diffing two runs' answers.
