# feat(positions-not-names): positions carry profiles; relations are asked where profiles point [slice 07]

**Spec:** docs/approach-positions-not-names.md#6-the-change · **Plan:** plans/positions-not-names/07-profiles-and-ranked-relations.md
**Depends on:** #831 — **gated on the founder's go from its comparison**
**Labels:** enhancement, sub:analysis-v0

## Deliverable

Every re-formed position inherits the category values its passages hold on
every built axis (its **profile**, a free join), and the relate pass proposes
its neighbourhoods from profile rank — same region, opposed or differing
stance, different books — instead of argument-sentence similarity. The model
still decides every relation; a shared category asserts nothing and no
relation record is written without a model answer (approach §10, pinned by
test). The run reports the cross-author relation rate next to the default
build's.

## Mechanism

A profile join over `positions.jsonl` × `data/vocabulary/`, a deterministic
pair-ranking function, and a wiring change in neighbourhood construction.
The relate call itself — prompt, blindness, fault isolation, ledger — is
untouched.

## Acceptance criterion

```gherkin
Given a variant build with positions and built vocabulary columns
When  `uv run axial map build --grouping category` runs its relate stage
Then  positions.jsonl carries each position's profile (category values per
      axis, with per-axis coverage from its passages)
And   relation neighbourhoods are composed from profile-ranked candidate
      pairs, capped at the existing neighbourhood sizes
And   map.json's relations block records the cross-author relation rate, so
      it can be read next to the default build's
And   a position with no profile on any constitutive axis still reaches at
      least one neighbourhood
```

## Files

```aeo-independence
slice: 07-profiles-and-ranked-relations
creates: src/axial/argmap/profile.py
creates: src/axial/argmap/test_profile.py
edits: src/axial/argmap/build.py
edits: src/axial/argmap/test_positions_on.py
creates: data/logs/2026-08-29-profile-relations/summary.md
depends-on: 06-structural-comparison
```

## Out of scope

- Retrieval (slice 08); a relation-type taxonomy (labels stay the model's
  own words); exhaustive pair coverage (profiles rank, caps still bound the
  spend).
