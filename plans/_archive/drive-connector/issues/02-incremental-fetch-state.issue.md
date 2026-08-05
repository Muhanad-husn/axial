# feat(drive-connector): incremental fetch-state — re-runs pull only new or changed files [slice 02]

**Spec:** specs/PRODUCT.md#7.10 · §8 P0-11b · **Plan:** plans/drive-connector/02-incremental-fetch-state.md
**Depends on:** #<slice 01 issue>
**Labels:** sub:ingestion-v0, enhancement

## Deliverable
The connector persists a fetch-state manifest at `data/drive/fetch_state.json`
(`id` → `{modifiedTime, md5Checksum, fetched_at}`) and, on re-run, skips **before
download** any listed file whose `modifiedTime` and `md5Checksum` both match the
manifest. A file absent from the manifest, or whose change token differs, is
fetched. The manifest entry is written only after a file is successfully fetched
and ingested, so an interrupted run re-fetches next pass. This pre-download skip
composes with — does not replace — the ingest-level `vault_status=OK` skip.

## Acceptance criterion
```gherkin
Given a fake Drive client for folder "BOOKS" with one file "alpha.pdf"
  And a first `axial drive ingest BOOKS` run has completed and written
      data/drive/fetch_state.json
When  `axial drive ingest BOOKS` runs a second time over the unchanged folder
Then  zero bytes are downloaded (the fake client's download is never called),
      zero sources are handed to the ingest callable, and the command exits 0

Given the same manifest but the fake client now reports a different
      md5Checksum for "alpha.pdf"
When  `axial drive ingest BOOKS` runs again
Then  "alpha.pdf" is re-downloaded and handed to the ingest callable
```

## Out of scope
- Manifest compaction / pruning entries for files removed from the folder.
- Concurrent-run locking (single-operator, serial).
- Change detection beyond `modifiedTime` + `md5Checksum`.
