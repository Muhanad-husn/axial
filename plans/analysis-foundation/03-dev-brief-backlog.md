# Slice 03: Dev-brief backlog — land the 26 parked questions as versioned data

- **Feature:** analysis-foundation
- **Slice slug:** dev-brief-backlog
- **GitHub issue:** #250
- **Branch:** `feat/analysis-foundation/03-dev-brief-backlog`
- **Project directory:** `.`
- **Status:** ☐ todo — **BLOCKED on the founder**
- **Walking skeleton?** no
- **Depends on:** slice 01 (the loader every dev brief must parse under), and
  **the founder supplying the 26 question files**

## Blocked

This slice cannot start until the founder supplies the 26 parked Academic
research questions. They live with the founder and are **not yet in the repo**
(§8 P0-11 says so explicitly). Everything else in the slice — the conformance
test, the directory convention, the versioning — is ready to be built the day
the questions arrive. Do not substitute invented questions for the founder's;
slice 01's fixture briefs already cover the "something to build against" need,
and inventing research questions would put fabricated content in the place the
real backlog belongs.

## Goal — the minimum testable behaviour

The 26 parked Academic research questions land under `config/briefs/dev/` as
versioned dev briefs in the §7.1 shape `{case, request, lens?}`, one file per
question, each with a stable name. A conformance test walks the whole directory
and asserts every dev brief loads and validates under slice 01's
`load_brief`, computes a `brief_id`, and that no two dev briefs collide on
`brief_id`. The engine's later dry-runs read this directory, so the backlog is
readable from the repo with no Academic dependency (§9).

No model call and no embedding call on any path.

## INVEST check

- **Independent:** pure data landing plus a conformance test over it. It changes
  no behaviour; it populates the directory slice 01 established.
- **Valuable:** P0-11. It is the seam that keeps the build off the Academic's
  critical path (§9): the dev briefs drive every dry-run, while the Academic's
  hard cases swap in later as referee data, never as a code change.
- **Small:** 26 small files plus one directory-walking test.
- **Testable:** the conformance test is the whole behaviour — every brief in the
  directory parses, validates, and has a unique id. Hermetic — no network, no
  LLM.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given the founder's 26 research questions landed as files under
      config/briefs/dev/
When  the conformance test walks every *.yaml under config/briefs/dev/
Then  at least 26 dev briefs are found
  And every one loads under axial.brief.load_brief without error
  And every one has a non-empty `case` and a non-empty `request`
  And every one computes a brief_id
  And no two dev briefs share the same brief_id

Given a dev brief file with an empty `request`
When  the conformance test runs
Then  the test fails naming that file and the `request` field
```

- **Boundary / endpoint:** the directory `config/briefs/dev/`, read through
  `axial.brief.load_brief`.
- **Outer test type:** pytest integration/acceptance test (a data-conformance
  test over the committed directory).
- **Outer test file (planned):** `tests/test_dev_briefs.py` — authored by the
  test-author, committed red, then locked (DEC-1).

## Inner loop — initial unit test list

- [ ] The directory walker finds every dev brief and ignores non-brief files
      (e.g. a `README.md` sitting in the directory).
- [ ] An empty `config/briefs/dev/` fails the conformance test rather than
      passing vacuously.
- [ ] `brief_id` collision detection fires when two files carry identical
      `{case, request, lens}` content — duplicates in the backlog are caught at
      landing time, not at run time.
- [ ] Each dev brief's `case` follows the faithful-naming rule for polities
      (§7.1, PRODUCT.md Appendix C) — checked as a shape constraint, not a
      controlled-vocabulary lookup.
- [ ] Slice 01's fixture briefs continue to pass the same conformance test, so
      the fixtures and the real backlog live under one rule.

## Out of scope for this slice (deferred)

- **Running** any dev brief through the engine. Nothing downstream of intake
  exists yet; this slice lands data and proves it parses.
- Academic hard cases under `evals/cases/` — a different seam entirely (§9),
  authored by the Academic on the frozen corpus.
- Curating, rewriting, or editorially improving the founder's questions. They
  land as given; drift in their wording is the founder's call.
- Assigning a `lens` to any dev brief. `lens` is optional; when absent the
  analysis stage selects and records one (§7.1).
- Grouping or prioritizing the backlog (which briefs run first). That is sprint
  sequencing, not data landing.

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

- 2026-07-20 planned. BLOCKED: awaiting the founder's 26 question files.
