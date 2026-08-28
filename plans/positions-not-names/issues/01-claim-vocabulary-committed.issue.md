# feat(positions-not-names): the claim column has a committed, assigned scheme [slice 01]

**Spec:** docs/approach-positions-not-names.md#13-the-work-in-order · **Plan:** plans/positions-not-names/01-claim-vocabulary-committed.md
**Depends on:** none
**Labels:** enhancement, sub:analysis-v0

## Deliverable

`config/vocabulary.yaml` carries a founder-approved category scheme for the
`claim` column, and `axial vocabulary build --columns claim` files the corpus
against it into `data/vocabulary/claim/`, with coverage and refusals reported
and the scheme version pinned. This is the axis the re-formed map groups on;
nothing downstream starts without it. The founder edit of the drafted scheme
is a hard gate inside the slice.

## Mechanism

Existing column-generic commands (`vocabulary examine` to draft, `vocabulary
build` to assign) and the existing committed-scheme config shape. No new
machinery; the code delta is the config block plus loader/pin tests.

## Acceptance criterion

```gherkin
Given config/vocabulary.yaml carries a committed `claim` scheme with a version
      and every category bearing an id, name and gloss
When  `uv run axial vocabulary build --columns claim` runs against data/answers/
Then  data/vocabulary/claim/manifest.json exists, records that scheme version,
      and reports assigned, refused and unanswered counts per category
And   a second run under the same scheme version resumes rather than re-asking
```

## Files

```aeo-independence
slice: 01-claim-vocabulary-committed
edits: config/vocabulary.yaml
edits: src/axial/test_vocabulary.py
edits: src/axial/test_vocabulary_build.py
creates: data/logs/2026-08-28-claim-vocabulary/summary.md
```

## Out of scope

- Any change to `vocabulary examine`'s internals (its measurement apparatus
  dies in slice 09, not here).
- Categorising any other column; reading the assignments anywhere.
