# Slice 07: Positions carry profiles; relations are asked where profiles point

- **Feature:** positions-not-names
- **Slice slug:** profiles-and-ranked-relations
- **Branch:** feat/positions-not-names/07-profiles-and-ranked-relations
- **Project directory:** .
- **Status:** ✗ RETIRED UNBUILT (2026-08-30) — slice 06's structural
  comparison returned **no-go** and the founder shelved the direction. This
  plan was gated on a go that never came. Kept as the record of what the
  direction would have built; nothing here was started, and nothing it names
  for deletion was deleted.
- **Walking skeleton?** no
- **Gated on:** founder go from slice 06.

## Goal — the minimum testable behaviour

Every re-formed position inherits the category values its passages hold on
every built axis (its **profile**, a free join), and the relate pass proposes
its neighbourhoods from profile rank — same region, opposed or differing
stance, different books — instead of argument-sentence similarity. The model
still decides every relation; profiles only choose what it is asked about.

## INVEST check

- **Independent:** reads the variant positions and `data/vocabulary/`; the
  relate call itself (prompt, blindness, fault isolation, ledger) is
  untouched.
- **Valuable:** attacks the measured thinness of relations — most asserted
  relations today never cross authors, and the neighbourhoods they were
  asked in were built by the same wording trap as the bagging.
- **Small:** one profile join, one ranking function, one wiring change in
  neighbourhood construction.
- **Testable:** profile inheritance and pair ranking are pure functions;
  neighbourhood construction is deterministic given fixtures.

## Acceptance criterion (outer loop — the failing e2e/integration test)

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
      least one neighbourhood (it is never silently unrelatable)
```

- **Boundary / endpoint:** CLI — the relate stage of `uv run axial map build --grouping category`
- **e2e test type:** API/integration test (pytest, CLI-level, injected fake LLM client)
- **e2e test file (planned):** src/axial/argmap/test_profile.py

## Files (parallel-safety declaration)

```aeo-independence
slice: 07-profiles-and-ranked-relations
creates: src/axial/argmap/profile.py
creates: src/axial/argmap/test_profile.py
edits: src/axial/argmap/build.py
edits: src/axial/argmap/test_positions_on.py
creates: data/logs/2026-08-29-profile-relations/summary.md
depends-on: 06-structural-comparison
```

## Inner loop — initial unit test list

- [ ] Profile inheritance: a position's profile is the distribution of its
      passages' category values per axis; a passage refused on an axis
      contributes nothing to that axis.
- [ ] Pair ranking: same claim region + differing position category +
      disjoint sources ranks above same-everything; the ordering is total
      and deterministic.
- [ ] A shared category alone asserts nothing: ranking produces candidates
      for the relate call, and no relation record is ever written without a
      model answer (approach §10, pinned by test).
- [ ] Neighbourhood caps respected; the resume key stays membership-derived
      exactly as today.
- [ ] Profile-less positions fall back into a neighbourhood rather than out
      of the pass.

## Operational steps inside the slice

1. Run the relate stage over the real variant, detached; write
   `data/logs/2026-08-29-profile-relations/`.
2. Summary records: relations asserted, cross-author rate versus the default
   build's, distinct labels, cost.

## Out of scope for this slice (deferred)

- Retrieval (slice 08).
- Relation-type taxonomy — labels stay the model's own words, named
  afterwards, as today.
- Exhaustive pair coverage — profiles rank, caps still bound the spend.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Real-corpus relate run done, cross-author rate recorded beside the default build's.
- [ ] Evidence collected and PR opened into main (`safe-pr`).

## Status / progress log

- 2026-08-28 planned.
