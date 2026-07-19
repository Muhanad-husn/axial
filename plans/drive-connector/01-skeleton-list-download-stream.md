# Slice 01: List, download, and stream a Drive source into ingestion

- **Feature:** drive-connector
- **Slice slug:** skeleton-list-download-stream
- **GitHub issue:** #237
- **Branch:** feat/drive-connector/01-skeleton-list-download-stream
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** yes (thinnest end-to-end thread through the new connector)

## Goal — the minimum testable behaviour

`axial drive ingest <folder_id>` authenticates a service account from `[drive]`
secrets, lists the Books folder through an **injectable** Drive client
(`parentId` + `pageToken`, paginated to exhaustion), filters listed files to
`.pdf`/`.docx` candidates by name and mime type, downloads each candidate's bytes
to a local cache path, and hands each downloaded source to the existing
ingestion path. Missing or incomplete `[drive]` secrets halt the command with a
clear logged error before any network call.

## INVEST check

- **Independent:** it stands alone — a complete list→filter→download→handoff
  thread. Incrementality and the language gate are later, additive slices.
- **Valuable:** the operator can ingest the corpus straight from the shared Drive
  folder in one command, no manual staging — the core of P0-11.
- **Small:** one new module + one CLI subcommand + a thin service-account client;
  the ingestion pipeline itself is reused unchanged via an injected callable.
- **Testable:** the outer test injects a fake client (fixture records + fixture
  bytes) and a spy ingest callable and asserts what was downloaded and handed
  off — hermetic, no network, no LLM.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fake Drive client seeded for folder "BOOKS" with two files —
      "alpha.pdf" (a candidate) and "notes.txt" (not a candidate) —
  And a valid [drive] secrets section pointing at a service-account key
When  `axial drive ingest BOOKS` runs with the fake client and a spy ingest
      callable injected
Then  only "alpha.pdf" is downloaded to the cache and handed to the ingest
      callable, "notes.txt" is filtered out and never downloaded
  And the command exits 0

Given a [drive] secrets section that is absent or missing books_folder_id
When  `axial drive ingest BOOKS` runs
Then  the command exits non-zero with a logged reason naming the missing secret
  And no Drive client call and no download is attempted
```

- **Boundary / endpoint:** CLI — `axial drive ingest <folder_id>`; library entry
  `axial.drive.run_drive_ingest(folder_id, client=..., ingest_fn=..., ...)`.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_drive_ingest.py` — authored by the
  test-author, committed red, then locked (DEC-1).

## Inner loop — initial unit test list

Co-located under `src/axial/` (e.g. `src/axial/test_drive.py`).

- [ ] `[drive]` secrets loader returns `service_account_json` + `books_folder_id`;
      raises a clear error on an absent section, missing key, or unreadable key path.
- [ ] The list step paginates: given a fake client returning two pages with a
      `next_page_token` between them, the connector enumerates every record.
- [ ] `.pdf`/`.docx` candidate filter keeps candidates by name + mime type and
      drops others; the drop does not replace intake validation (§7.8 note).
- [ ] `download(file_id)` bytes are written to a deterministic cache path under
      `data/drive/` and the local path is what the ingest callable receives.
- [ ] The service-account real client constructs from the key path (google libs
      mocked) and satisfies the injectable protocol.
- [ ] Injected `ingest_fn` is called once per downloaded candidate with its local
      path; the default binds the real ingestion path.

## Out of scope for this slice (deferred)

- Incremental fetch-state / skip-on-unchanged — slice 02.
- English-only language gate — slice 03.
- Real network calls against live Google Drive (proven by the mocked client
  construction + the fake in tests; never in CI).
- Retry/backoff and rate-limit handling on the real client (thin wrapper only).

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (with the
      founder-approved `.claude/allow-red-commit` flag), seen to fail for the
      right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete (no duplication, clear names) with the bar green.
- [ ] `secrets/secrets.example.toml` reconciled: `[google_drive]` → `[drive]` with
      `service_account_json` + `books_folder_id`.
- [ ] `google-api-python-client` + `google-auth` added to project deps.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Reviewer's two-stage review passed (spec compliance, then quality).
- [ ] Evidence collected and PR prepared into `main` (`safe-pr`) — merge awaits
      founder approval.

## Status / progress log

- 2026-07-19 planned.
