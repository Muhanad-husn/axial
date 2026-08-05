# Slice 01: Brief intake — load, validate, and deterministically id a brief

- **Feature:** analysis-foundation
- **Slice slug:** brief-intake-and-id
- **GitHub issue:** #247
- **Branch:** `feat/analysis-foundation/01-brief-intake-and-id`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** yes (Phase B opens a new module tree per §6; this is the
  thinnest end-to-end thread through `src/axial/brief/` and the `axial brief`
  CLI namespace)
- **Depends on:** none

## Goal — the minimum testable behaviour

A brief loader reads a versioned brief file from disk into the §7.1 shape
`{brief_id, case, request, lens?}`, validates it, and computes `brief_id` as a
stable deterministic hash over the brief's content. `case` and `request` are
required non-empty strings; `lens` is optional. A malformed brief — missing
`case`, missing `request`, empty either, unparseable file — fails with a clear
error naming the offending field, not a traceback. `brief_id` uses no
randomness, no timestamps, and no filename input: the same brief content yields
the same id on every machine and every run. `axial brief show <brief_file>`
prints the loaded brief and its computed id. The slice lands 2–3 hand-written
fixture briefs under `config/briefs/dev/` so every downstream Phase-B stage has
real input to build against before the founder's 26 questions arrive.

No model call and no embedding call on any path.

## INVEST check

- **Independent:** it stands alone — file in, validated brief object plus id out.
  Nothing upstream, and the interrogation pre-pass that consumes it is a later
  sprint.
- **Valuable:** it is the phase's input contract (§7.1). Every later stage takes
  a brief, and `brief_id` is what names the analysis record at
  `data/analyses/<brief_id>.json` (§7.3). Without a stable id, re-running a
  brief is untraceable.
- **Small:** one new module (`src/axial/brief/`), one loader, one hash function,
  one read-only CLI subcommand, and a handful of fixture files.
- **Testable:** entirely on-disk fixtures and pure functions. Assert the same
  content hashes to the same id twice; assert each malformed shape raises with
  the field named. Hermetic — no network, no LLM.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a brief file config/briefs/dev/fixture-syria-displacement.yaml carrying
      case: "Syria" and request: "How did displacement reshape local authority?"
When  `axial brief show config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command exits 0
  And it prints case "Syria", the request text, and a brief_id
  And running the same command a second time prints the identical brief_id

Given a second brief file whose content is byte-identical to the first but
      whose filename differs
When  `axial brief show` runs on it
Then  the printed brief_id is identical to the first file's brief_id

Given a brief file with a `case` key that is absent or an empty string
When  `axial brief show` runs on it
Then  the command exits non-zero with a logged reason naming `case`
  And no partially-constructed brief is emitted
```

- **Boundary / endpoint:** CLI — `axial brief show <brief_file>`; library entry
  `axial.brief.load_brief(path) -> Brief` and `axial.brief.compute_brief_id(brief)`.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_brief_intake.py` — authored by the
  test-author, committed red, then locked (DEC-1).

## Inner loop — initial unit test list

Co-located under `src/axial/brief/` (e.g. `src/axial/brief/test_intake.py`).

- [ ] `load_brief` on a well-formed file returns `case`, `request`, and `lens`
      (`None` when the key is absent), with surrounding whitespace stripped.
- [ ] Validation raises a clear, field-naming error for: absent `case`, empty
      `case`, absent `request`, empty `request`, a non-string `lens`, and an
      unparseable file.
- [ ] Unknown top-level keys are rejected rather than silently dropped, so a
      typo'd field is caught at intake instead of vanishing.
- [ ] `compute_brief_id` is deterministic: the same `{case, request, lens}`
      hashes to the same id across two calls in the same process and across a
      fresh load from a different path.
- [ ] `compute_brief_id` is content-sensitive: changing `request` by one
      character changes the id; adding a `lens` changes the id.
- [ ] `compute_brief_id` ignores presentation: key order in the source file and
      trailing whitespace do not change the id.
- [ ] `brief_id` is filesystem-safe (usable directly as the stem of
      `data/analyses/<brief_id>.json`) and of fixed length.
- [ ] The `axial brief show` subparser is registered on the existing argparse
      tree and exits non-zero on a missing file path.
- [ ] Every fixture brief shipped in `config/briefs/dev/` loads and validates.

## Out of scope for this slice (deferred)

- The interrogation pre-pass and the interrogation result (§7.2, P0-1) — the
  first model call in Phase B, a later sprint.
- `axial brief run` and `axial brief examine` (P0-9). Only the read-only `show`
  subcommand lands here.
- Resolving `lens` against `config/lenses/` data. `lens` is validated as an
  optional string; lens selection and recording is stage-4 (§7.1).
- The founder's 26 dev briefs — slice 03, and blocked on the founder.
- Any writing under `data/analyses/`.

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
