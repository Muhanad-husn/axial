# Slice 02: Incremental fetch-state — re-runs pull only new or changed files

- **Feature:** drive-connector
- **Slice slug:** incremental-fetch-state
- **GitHub issue:** #238
- **Branch:** feat/drive-connector/02-incremental-fetch-state
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** slice 01 (#237)

## Goal — the minimum testable behaviour

The connector persists a fetch-state manifest at `data/drive/fetch_state.json`
(`id` → `{modifiedTime, md5Checksum, fetched_at}`) and, on re-run, skips **before
download** any listed file whose `modifiedTime` and `md5Checksum` both match the
manifest. A file absent from the manifest, or whose change token differs, is
fetched. The manifest is written only after a file is successfully fetched and
ingested, so an interrupted run re-fetches on the next pass.

## INVEST check

- **Independent:** pure add-on to slice 01's list→download loop; changes when a
  download happens, not how listing or handoff work.
- **Valuable:** re-running the corpus ingest becomes cheap and idempotent — the
  operator can re-point at the folder anytime without re-pulling gigabytes or
  re-ingesting; the observable "zero bytes, zero new sources" is the payoff.
- **Small:** one manifest read/write + a pre-download skip predicate.
- **Testable:** drive the CLI twice against the same fake client and assert the
  second run downloads nothing and hands off nothing.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fake Drive client for folder "BOOKS" with one file "alpha.pdf"
  And a first `axial drive ingest BOOKS` run has completed and written
      data/drive/fetch_state.json
When  `axial drive ingest BOOKS` runs a second time over the unchanged folder
Then  zero bytes are downloaded (the fake client's download is never called)
  And zero sources are handed to the ingest callable
  And the command exits 0

Given the same manifest but the fake client now reports a different
      md5Checksum for "alpha.pdf"
When  `axial drive ingest BOOKS` runs again
Then  "alpha.pdf" is re-downloaded and handed to the ingest callable
```

- **Boundary / endpoint:** CLI — `axial drive ingest <folder_id>` (re-run); the
  manifest file `data/drive/fetch_state.json`.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_drive_incremental.py` — authored by
  the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] Manifest round-trips: write `{id: {modifiedTime, md5Checksum, fetched_at}}`,
      read it back; an absent manifest reads as empty.
- [ ] Skip predicate: a file whose listed `modifiedTime` **and** `md5Checksum`
      match the manifest is skipped; a mismatch on either is fetched; an unlisted
      file is fetched.
- [ ] The manifest entry is written only **after** a successful fetch+ingest, not
      before (an ingest failure leaves no manifest entry → re-fetch next run).
- [ ] The pre-download skip composes with the ingest-level `vault_status=OK` skip
      — both can fire; neither masks the other.

## Out of scope for this slice (deferred)

- Manifest compaction / pruning of entries for files removed from the folder.
- Concurrent-run locking on the manifest (single-operator, serial).
- Change detection beyond `modifiedTime` + `md5Checksum` (no content diffing).

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

- 2026-07-19 planned.
