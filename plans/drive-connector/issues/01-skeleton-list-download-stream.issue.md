# feat(drive-connector): list, download & stream a Drive source into ingestion [slice 01]

**Spec:** specs/PRODUCT.md#7.10 · §8 P0-11 · **Plan:** plans/drive-connector/01-skeleton-list-download-stream.md
**Depends on:** none
**Labels:** sub:ingestion-v0, enhancement

## Deliverable
`axial drive ingest <folder_id>` authenticates a Google service account from a
`[drive]` secrets section, lists the shared Books folder through an **injectable**
Drive client (`parentId` + `pageToken`, paginated to exhaustion), filters listed
files to `.pdf`/`.docx` candidates by name and mime type, downloads each
candidate's bytes to a local cache under `data/drive/`, and hands each downloaded
source to the existing ingestion path via an injected callable. Missing or
incomplete `[drive]` secrets halt the command with a clear logged error before
any network call. This is the thinnest end-to-end thread through the new
connector; incrementality and the language gate are separate slices.

## Acceptance criterion
```gherkin
Given a fake Drive client seeded for folder "BOOKS" with two files —
      "alpha.pdf" (a candidate) and "notes.txt" (not a candidate) —
  And a valid [drive] secrets section pointing at a service-account key
When  `axial drive ingest BOOKS` runs with the fake client and a spy ingest
      callable injected
Then  only "alpha.pdf" is downloaded and handed to the ingest callable,
      "notes.txt" is filtered out and never downloaded, and the command exits 0

Given a [drive] secrets section that is absent or missing books_folder_id
When  `axial drive ingest BOOKS` runs
Then  the command exits non-zero with a logged reason naming the missing secret,
      and no Drive client call and no download is attempted
```
The outer test injects the fake client + a spy ingest callable — hermetic, no
network, no LLM.

## Out of scope
- Incremental fetch-state / skip-on-unchanged (slice 02).
- English-only language gate (slice 03).
- Live network calls against Google Drive; retry/backoff on the real client.
- Any operator-managed staging surface (`--dest`, worklist emission).

## Notes
- Reconcile the stale `[google_drive]` stub in `secrets/secrets.example.toml` to
  `[drive]` (`service_account_json` + `books_folder_id`).
- Adds `google-api-python-client` + `google-auth` (additive; off the chunk
  critical path, §12).
