# feat(analysis-foundation): land the 26 parked research questions as versioned dev briefs [slice 03]

**Spec:** specs/PHASE-B.md#9 · §8 P0-11 · **Plan:** plans/analysis-foundation/03-dev-brief-backlog.md
**Depends on:** #247
**Labels:** sub:analysis-v0, enhancement, blocked

## Deliverable
The founder's 26 parked Academic research questions land under
`config/briefs/dev/` as versioned dev briefs in the §7.1 shape
`{case, request, lens?}`, one file per question. A conformance test walks the
whole directory and asserts every dev brief loads and validates under slice 01's
`axial.brief.load_brief`, computes a `brief_id`, and that no two dev briefs
collide on `brief_id`. This is the seam that keeps the build off the Academic's
critical path (§9): the dev briefs drive every dry-run from the repo, while the
Academic's hard cases swap in later as referee data, never as a code change.
LLM-free by construction: zero model and zero embedding calls on any path.

**BLOCKED.** The 26 question files live with the founder and are **not yet in
the repo** (§8 P0-11 states this explicitly). This issue cannot start until the
founder supplies them. Do not substitute invented questions: slice 01's fixture
briefs already cover the need for something to build against, and fabricating
research questions would put invented content where the real backlog belongs.

## Acceptance criterion
```gherkin
Given the founder's 26 research questions landed as files under
      config/briefs/dev/
When  the conformance test walks every *.yaml under config/briefs/dev/
Then  at least 26 dev briefs are found, every one loads under
      axial.brief.load_brief without error, every one has a non-empty `case` and
      a non-empty `request`, every one computes a brief_id, and no two dev
      briefs share the same brief_id

Given a dev brief file with an empty `request`
When  the conformance test runs
Then  the test fails naming that file and the `request` field
```

## Out of scope
- **Running** any dev brief through the engine — nothing downstream of intake
  exists yet.
- Academic hard cases under `evals/cases/` — a different seam (§9).
- Curating, rewriting, or editorially improving the founder's questions; they
  land as given.
- Assigning a `lens` to any dev brief (`lens` is optional, §7.1).
- Grouping or prioritizing the backlog — that is sprint sequencing.
