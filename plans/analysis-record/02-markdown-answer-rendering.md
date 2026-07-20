# Slice 02: Deterministic markdown answer rendering

- **Feature:** analysis-record
- **Slice slug:** markdown-answer-rendering
- **GitHub issue:** #261
- **Branch:** `feat/analysis-record/02-markdown-answer-rendering`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** `analysis-validators` slice 03 (the coverage map and the
  confidence disclosure the renderer presents), and slice 01 (the record)

## Goal — the minimum testable behaviour

A human-readable markdown answer is rendered from the analysis record and
written alongside the JSON (§7.10, P0-8 bullet 2). The renderer reads the record
and nothing else: no model call, no vault read, no clock.

The answer presents:

1. **the claims with their kind visible to the reader** — (a), (b), and (c) are
   legible on the page, since they carry different weight (§7.4, charter
   Principle II). A (b) claim is visibly the tool's cross-source inference, not
   something a source said,
2. the **counter-position section** (§7.8): the opposing stance from corpus
   grounds, or the explicit corpus-one-sided disclosure with its reason,
3. the **coverage map** (§7.7): per polity, the corpus and evidence chunk counts
   and the disclosed coverage band,
4. the **confidence disclosure** with its rationale.

On a `refuse` disposition the answer states the refusal and its reason and
presents no claims.

**Rendering is deterministic.** The same record renders **byte-identical**
markdown, every time, on any machine. That is the lockable property of this
slice.

## INVEST check

- **Independent:** a pure function from record to string. It reads no vault, no
  config beyond the record, and calls no model.
- **Valuable:** the record is an audit artifact; this is the thing a human
  actually reads. Making the (a)/(b)/(c) kinds legible on the page is what stops
  a cross-source inference from being read as a source's finding — the charter's
  Principle II at the point of consumption rather than only in the JSON.
- **Small:** one renderer plus a write step wired into `axial brief run`.
- **Testable:** ideally testable. Fixture record in, string out; assert content
  and assert byte-identity across two renders. Fully hermetic — no LLM, no
  network, no vault.

## Acceptance criterion (outer loop — the failing e2e/integration test)

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

- **Boundary / endpoint:** library entry
  `axial.answer.render_markdown(record) -> str`; CLI — the markdown written
  alongside the JSON by `axial brief run <brief_file>`.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_answer_rendering.py` — authored by
  the test-author, committed red, then locked (DEC-1).

## Inner loop — initial unit test list

Co-located under `src/axial/answer/` (e.g. `src/axial/answer/test_render.py`).

- [ ] Claim kinds render distinctly: an (a), a (b), and a (c) claim are
      distinguishable in the output by a stable, documented marker.
- [ ] Claim order in the output follows the record's `claims` order; no
      re-sorting, no set iteration.
- [ ] Grounds ids appear against their claims, so a reader can trace a claim to
      the vault without opening the JSON.
- [ ] A (c) claim with empty grounds renders without a grounds list and without
      raising.
- [ ] Counter-position: the `present: true` path renders stance and grounds; the
      `corpus_one_sided: true` path renders the disclosure and
      `one_sided_reason` instead.
- [ ] Coverage map rows are emitted in a deterministic polity order.
- [ ] The confidence section renders `overall_band` and `rationale`.
- [ ] The refusal path renders the reason and omits the claims section.
- [ ] Determinism: two renders of the same record are byte-identical, including
      trailing newline; no timestamp, no path, and no dict/set iteration order
      leaks into the output.
- [ ] An empty coverage map or an absent counter-position renders a stated
      "none" line rather than a blank hole, so a missing section is visible
      rather than silent.

## Out of scope for this slice (deferred)

- **Venue, length, and style adaptation.** §7.10 is explicit that this is plain
  rendering only; adapting to a venue or house style is **Phase D** (§3 non-goal
  2). Do not add formatting options here.
- Computing the coverage map, the counter-position, or the confidence
  disclosure. This slice presents what `analysis-validators` computed.
- Any output format other than markdown (no HTML, no PDF, no notebook).
- Narrative arc, apparatus, or paper structure — that is **Phase C** (§3
  non-goal 1).
- Re-rendering historical records in bulk, or diffing two runs' answers.

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
