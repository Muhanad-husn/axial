# Slice 02: Persisted source-metadata record — written at intake, survives regen

- **Feature:** intake-metadata
- **Slice slug:** source-metadata-record
- **GitHub issue:** #285
- **Branch:** feat/intake-metadata/02-source-metadata-record
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

Intake writes one JSON per source at `data/source_meta/<source_id>.json`, keyed by
the same deterministic `source_id` the tree, envelope, and chunk use
(`{filename stem}-{first 12 hex of the sha256}`), **before extraction**. The
record carries: the **physical page count** where the format exposes one; the
**§7.11 holdings flag in full** (concluded kind, claimed extent, observed extent,
stated reason) or an explicit no-flag for a source judged complete; the **full
sha256** file hash (stored whole even though `source_id` embeds only its 12-char
prefix, so the record is self-describing); and **author, title, date** read at
intake from the PDF's embedded metadata and title page (§7.13/P0-1d), each in one
of three distinguishable states — a value with provenance, `unavailable`, or
`not_attempted`. The record survives envelope regeneration byte-unchanged, and
carries no source text (DEC-23).

## Boundary rule (§7.12) — the artifact vs. the work

The record holds facts about the **file as an artifact**, obtained without
interpreting its argument and unchanged when a model is re-run against the same
bytes: byte hash, page count, format, and what the file's own front matter states
about its identity and extent. The **envelope** holds what the model concludes
about the **work** — thesis, scope, stated argument, toc — which is expected to
change as prompts and models improve. A model may **read** an artifact fact off
the page (§7.11's holdings verdict and §7.13's author/title/date both do) without
that fact moving into the envelope: what puts a fact here is that it describes the
artifact and does not change on re-run, not whether a model was used to read it.
This is the rule that keeps the record from becoming a second envelope.

## INVEST check

- **Independent:** adds a writer inside `intake.py` and a small record module/
  shape; reads nothing from the tree or envelope (it runs before extraction). It
  reuses `envelope.content_digest()` and `envelope.compute_source_id()` as pure
  hashing primitives, adding no second hashing convention.
- **Valuable:** gives the holdings flag its first durable home and first
  downstream reader (P0-1c), and lands the author/title/date read at intake — the
  facts ~17k chunks currently lack. It is the artifact half of the §7.13 fix that
  slice 03 then wires into the vault.
- **Small:** one record shape, one writer, one intake call site; the read of
  author/title/date is bounded to embedded PDF metadata + title-page text already
  in hand from the P0-1 text layer.
- **Testable:** run intake on fixtures; assert the record exists at the right
  path with the right key, carries page count / full hash / holdings flag /
  three bibliographic fields in their three states, holds no source text, and is
  byte-identical before and after an envelope regen.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a source file processed through intake, with its holdings flag decided (slice 01)
When  intake runs before any extraction
Then  a JSON record exists at `data/source_meta/<source_id>.json`, keyed by the same source_id the tree/envelope/chunk use
And   it carries the physical page count (where the format exposes one), the full sha256 file hash, and the §7.11 holdings flag in full or an explicit no-flag
And   it carries author, title and date, each as a value-with-provenance, `unavailable`, or `not_attempted`, never the filename slug
And   it contains no source text and no verbatim title-page or contents transcription
And   regenerating (or deleting and regenerating) the source's envelope leaves the record byte-unchanged
And   the holdings flag is readable from the record after intake without re-running the holdings check
```

- **Boundary / endpoint:** the intake pass (`axial.intake.intake(...)`) and its
  new source-meta writer; the artifact is `data/source_meta/<source_id>.json`.
- **Outer test type:** pytest integration test (recorded/stub LLM client for the
  intake-side reads; no network).
- **Outer test file (planned):** tests/ingestion/test_source_metadata_record.py
  — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] the record path is `data/source_meta/<source_id>.json` and `source_id`
      equals `envelope.compute_source_id(path)` for the same bytes (same key
      across tree/envelope/chunk)
- [ ] the record is written before extraction — no tree file need exist for the
      record to be written
- [ ] `file_hash` is the full sha256 (`envelope.content_digest`), not the 12-char
      prefix, so the record is self-describing
- [ ] `physical_page_count` is present for a PDF; for a DOCX the field records
      that no page count is exposed (distinct from a numeric zero)
- [ ] the holdings flag is stored in full (kind, claimed extent + what stated it,
      observed extent, stated reason); a complete source stores an explicit
      no-flag, not an absent key
- [ ] author/title/date each carry one of three states, distinguishable on read:
      `{value, provenance}` (provenance = embedded metadata | title page),
      `unavailable`, or `not_attempted`
- [ ] the filename is never a source for author/title/date: a source whose slug
      differs from its printed title yields the printed title or `unavailable`,
      never the slug
- [ ] junk embedded metadata (a producer string as author, an empty author, a
      file-creation date) is recorded as `unavailable`, not passed through as a
      value
- [ ] no source text / no verbatim excerpt anywhere in the record (DEC-23)
- [ ] re-running intake on unchanged bytes overwrites with equivalent content and
      the same `source_id`; an edited source hashes to a new `source_id` and gets
      its own record, never inheriting a stale one
- [ ] the record is byte-unchanged across an envelope regen (the durability guard)

## Out of scope for this slice (deferred)

- **Removing author/title/date from the envelope and recomposing the vault's
  `source_meta`.** That is slice 03 (#278). This slice only *produces* the
  record; slice 03 makes the vault *read* from it.
- **Re-tagging the corpus.** The existing chunks are corrected by the stage-4
  re-tag, not here.
- **The holdings judgment itself.** Slice 01 decides the flag; this slice records
  whatever it concluded.
- **A general metadata-extraction pass.** The read is bounded to embedded PDF
  metadata and title-page text; no new heavy extractor.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED
      (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test
      GREEN.
- [ ] Byte-unchanged-across-regen guard passing; no source text in the record
      (reviewer-checked, DEC-23).
- [ ] Reuses `content_digest`/`compute_source_id` rather than a new hashing
      convention; over-engineering tripwires checked.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder
      approval.

## Status / progress log

- 2026-07-21 planned. Depends on slice 01 (carries its holdings flag shape).
