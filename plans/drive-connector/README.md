# Feature: Google Drive source connector

Give `axial` a shared Google Drive "Books" folder as a first-class source. The
connector authenticates with a service account, enumerates the folder, and
streams eligible `.pdf`/`.docx` sources into the existing intake→extract→vault
pipeline with no operator-managed staging step. Two gates ride on top: an
incremental fetch-state manifest so re-runs pull only new or changed files, and
a deterministic English-only language gate that rejects-and-logs non-English
sources before the expensive pipeline. The operator (founder) benefits: corpus
ingestion becomes a single command against Drive instead of manual local
staging, and re-runs are cheap and idempotent.

- **Slug:** drive-connector
- **Created:** 2026-07-19
- **Status:** planning
- **New system?** no (extends the existing ingest path; no walking skeleton for
  build/CI, but slice 01 is the thinnest end-to-end thread through the new
  connector)
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [skeleton-list-download-stream](01-skeleton-list-download-stream.md) | [#237](https://github.com/Muhanad-husn/axial/issues/237) | `axial drive ingest <folder_id>` lists the Books folder via an injectable client, filters to `.pdf`/`.docx`, downloads each, and streams it into the existing ingestion path — all against a fake client, no network | ◐ PR | [#240](https://github.com/Muhanad-husn/axial/pull/240) |
| 02 | [incremental-fetch-state](02-incremental-fetch-state.md) | [#238](https://github.com/Muhanad-husn/axial/issues/238) | A `data/drive/fetch_state.json` manifest makes a re-run over an unchanged folder fetch zero bytes and ingest zero new sources; changed files are re-fetched | ◐ PR | [#242](https://github.com/Muhanad-husn/axial/pull/242) |
| 03 | [english-only-gate](03-english-only-gate.md) | [#239](https://github.com/Muhanad-husn/axial/issues/239) | A deterministic bounded-probe language gate rejects-and-logs non-English sources before extraction; English sources pass | ☐ todo | — |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Dependencies

- 01 is the foundation (client protocol, service-account impl, secrets, the
  list→filter→download→handoff thread). 02 and 03 both depend on 01.
- 02 and 03 are independent of each other and can run in either order.

## Out of scope (whole feature)

- OAuth desktop / user-credential auth (founder chose service-account; §7.10).
- An env-var credential fallback (founder's "incomplete secrets → hard error"
  reading; deliberately omitted from the spec).
- Any operator-managed local staging surface (`--dest`, worklist emission): the
  connector streams; the temp/cache dir is an implementation detail, not a
  contract (§7.10).
- Re-testing the full LLM pipeline: the connector hands off to the existing,
  already-tested ingestion path via an injectable callable; the outer tests
  assert the handoff, not the downstream tag/artifact/xref behaviour.
- Non-English support of any kind for this version (English-only is a hard gate).
- Multi-folder / recursive folder traversal (single Books folder, flat listing).

## Notes / open questions

- **secrets.example reconciliation:** `secrets/secrets.example.toml` carries a
  stale `[google_drive]` stub with `credentials_path`. Slice 01 reconciles it to
  `[drive]` with `service_account_json` + `books_folder_id` (spec §7.10). This is
  code-adjacent config, done by the implementer in slice 01.
- **New dependencies:** `google-api-python-client` + `google-auth` (slice 01, the
  real client behind the protocol); a `langdetect`/`lingua`-style deterministic
  detector (slice 03). All additive, all outside the chunk critical path (§12).
- **Language-probe source:** the English gate needs leading source text. The
  implementer wires the bounded probe to the source's text layer (reuse
  `intake`'s text-layer extraction where possible), deterministic and bounded by
  `language_probe_chars`. Slice 03 pins the exact seam.
- **Handoff shape:** slice 01 hands each selected source to the existing
  ingestion via an injected callable (default the real `run_vault_write` /
  ingest path). This keeps the connector's outer tests hermetic (no LLM, no
  network) while the production default drives the real pipeline.
