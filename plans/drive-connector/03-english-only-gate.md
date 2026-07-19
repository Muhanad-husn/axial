# Slice 03: English-only language gate — reject-and-log non-English sources

- **Feature:** drive-connector
- **Slice slug:** english-only-gate
- **GitHub issue:** #239
- **Branch:** feat/drive-connector/03-english-only-gate
- **Project directory:** `.`
- **Status:** ◐ PR #244 (awaiting founder approval)
- **Walking skeleton?** no
- **Depends on:** slice 01 (#237); independent of slice 02

## Goal — the minimum testable behaviour

Before a downloaded source is handed to ingestion, the connector detects its
language deterministically from a bounded text probe (`language_probe_chars`
leading characters) using a `langdetect`/`lingua`-style detector. A source whose
dominant detected language is English at or above `language_accept_threshold`
passes to ingestion; any other source is **rejected before extraction** and
logged with a reason naming the detected language and confidence — never a silent
pass-through. The gate runs only on sources that carry a text layer (scanned /
no-text-layer sources are already rejected at intake, P0-1).

## INVEST check

- **Independent:** a filter inserted between download and handoff in slice 01's
  loop; touches neither listing nor incrementality.
- **Valuable:** the v0 tool is English-only by contract; this keeps non-English
  sources out of the corpus and the eval, with an auditable logged reason.
- **Small:** one bounded probe + one detector call + a threshold compare +
  reject-and-log; deterministic.
- **Testable:** feed the connector a fake source whose probe text is non-English
  and assert it is rejected+logged and never handed off; an English one passes.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fake Drive client for folder "BOOKS" with two candidates —
      "english.pdf" whose text probe is English prose and
      "french.pdf" whose text probe is French prose
When  `axial drive ingest BOOKS` runs with the fake client and spy ingest
      injected
Then  "english.pdf" is handed to the ingest callable
  And "french.pdf" is NOT handed to the ingest callable
  And a rejection is logged for "french.pdf" naming the detected language and
      confidence
  And the command exits 0 (a non-English source is a recorded skip, not a crash)
```

- **Boundary / endpoint:** CLI — `axial drive ingest <folder_id>`; the logged
  rejection line and the set of sources reaching the ingest callable.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_drive_language_gate.py` — authored by
  the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] The probe draws at most `language_probe_chars` leading characters from the
      source's text layer, deterministically.
- [ ] The detector classifies an English probe as English above threshold and a
      French/other probe as non-English; the call is deterministic (fixed seed or
      deterministic library).
- [ ] `language_accept_threshold` is honoured: an English detection just below
      the threshold is rejected; at/above passes.
- [ ] A rejected source produces a log line naming the detected language and
      confidence and is excluded from the handoff set.
- [ ] The tunables `language_probe_chars` + `language_accept_threshold` are read
      from config, not hardcoded (§7.10).
- [ ] The gate runs only on text-layer sources; the intake text-layer check
      precedes it (interaction with P0-1).

## Out of scope for this slice (deferred)

- Multi-language corpora / per-language routing (English-only is a hard gate).
- Language detection on scanned sources (rejected upstream at intake).
- Tuning the probe size / threshold on the real corpus — starting values are
  stated tunables proven via inspection, not re-derived here.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED, seen to
      fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] A deterministic language-detection dependency added to project deps.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` (`safe-pr`) — merge awaits
      founder approval.

## Status / progress log

- 2026-07-19 planned.
