# Slice 03: Author/title/date ownership — record is sole origin, envelope drops them

- **Feature:** intake-metadata
- **Slice slug:** envelope-metadata-cleanup
- **GitHub issue:** #278
- **Branch:** feat/intake-metadata/03-envelope-metadata-cleanup
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Why this slice exists (the #278 bug, resolved per §7.13)

`author` and `date` are null in all 30 envelopes and propagate empty into ~17k
chunks' `source_meta`; `title` is worse than null — it is the filename slug
title-cased (`Mann Sources Of Social Power V2`), a wrong value that looks right.
§7.13/P0-1d resolve ownership: the source-metadata record (slice 02) is the
**sole origin** of author/title/date, and the envelope **no longer carries them**.
This slice makes that real. It is a third slice of this feature, not a fix-lane
cleanup, because it changes a *locked* envelope shape and rewrites the vault
writer's composition across two modules, and it depends on slice 02's record
existing to read from. See the feature README's "#278 coupling" section for the
full rationale.

## Goal — the minimum testable behaviour

Remove `author`, `title` and `date` from the envelope's locked shape, which
becomes `{source_id, thesis, toc[], scope, stated_argument}`: drop them from
`build_envelope`, drop `title`/`author`/`date` handling and the
`_fallback_title` slug path in `envelope.py`, and leave `validate_envelope_fields`
validating only the four remaining required fields. Rewrite the vault writer's
`source_meta` composition (today `{field: envelope.get(field) for field in
SOURCE_META_FIELDS}`) to compose the same **five-key** frontmatter block from two
places: `author`/`title`/`date` from `data/source_meta/<source_id>.json` (slice
02), `thesis`/`scope` from the envelope. An unavailable bibliographic field is
written as unavailable, never as an empty value indistinguishable from an
unattempted read. No note shape, no frontmatter key set, and no downstream reader
changes — only where three of the five values come from.

## INVEST check

- **Independent of new subsystems:** touches only `envelope.py` (shape) and
  `vault.py` (composition); adds no module. It is *sequenced* after slice 02 (it
  reads that record) but changes nothing slice 02 wrote.
- **Valuable:** closes #278 — the last step so that a re-tagged chunk carries real
  author/title/date instead of nulls and a fabricated title, with "one answer
  downstream, not two" (§7.13).
- **Small:** a field removal from one locked shape plus a two-source recomposition
  of one frontmatter block. It does **not** re-tag the corpus (that flush is the
  stage-4 operation).
- **Testable:** assert a freshly built envelope has no author/title/date keys and
  still validates; assert a written vault note's `source_meta` keeps its five keys
  with author/title/date sourced from the record (including an `unavailable`
  rendering) and thesis/scope from the envelope.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a source with a source-metadata record (slice 02) carrying author/title/date and an envelope carrying thesis/scope
When  the envelope is built and a chunk is written to the vault
Then  the envelope's locked shape is `{source_id, thesis, toc[], scope, stated_argument}` with no author, title, or date key, and it still validates
And   the vault note's `source_meta` block keeps its five keys `author`, `title`, `date`, `thesis`, `scope`
And   `author`, `title` and `date` are composed from the source-metadata record, and `thesis`, `scope` from the envelope
And   a source whose printed title differs from its filename slug yields the printed title, never the slug
And   a bibliographic field the record marks unavailable is written as unavailable, distinguishable from an empty value
```

- **Boundary / endpoint:** `axial.envelope.build_envelope` /
  `validate_envelope_fields` (shape) and `axial.vault`'s frontmatter composition
  (`source_meta` block).
- **Outer test type:** pytest integration test (stub LLM client for the envelope
  build; no network).
- **Outer test file (planned):** tests/ingestion/test_source_meta_ownership.py
  — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] `build_envelope` returns `{source_id, thesis, toc, scope, stated_argument}`
      and no `author`/`title`/`date` keys
- [ ] `validate_envelope_fields` accepts the four-field shape and no longer
      references author/title/date; the `_fallback_title` slug path is removed
- [ ] the envelope prompt/build reads source text only for thesis/scope/
      stated_argument/toc — no title handling remains (§7.3 grounding unaffected
      and strengthened)
- [ ] the vault `source_meta` block still has exactly the five keys `author`,
      `title`, `date`, `thesis`, `scope` (no note-shape change)
- [ ] `author`/`title`/`date` in that block come from the source-meta record;
      `thesis`/`scope` come from the envelope
- [ ] a record's `unavailable` field renders in `source_meta` as unavailable, not
      as an empty string that reads like an unattempted value
- [ ] a source whose filename slug differs from its printed title yields the
      printed title (from the record), never the slug
- [ ] a source with no record present fails loudly / is handled explicitly rather
      than silently re-emitting envelope nulls (the failure mode being retired)

## Out of scope for this slice (deferred)

- **Re-tagging the ~17k existing chunks.** This slice corrects the writer; the
  corpus flush that replaces in-vault nulls is the stage-4 re-tag operation in
  `plans/phase-a-completion/`. Deliberate 80/20 boundary — the slice does not run
  a full re-tag.
- **Producing author/title/date.** Slice 02 reads and records them; this slice
  only moves ownership and recomposes the frontmatter.
- **Any other envelope field change.** `thesis`, `toc`, `scope`,
  `stated_argument` are untouched.
- **Migrating already-written envelopes on disk.** Cached envelopes carrying the
  old keys are regenerated by normal operation; a one-off migration, if wanted, is
  a separate operational task, not this slice.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED
      (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test
      GREEN.
- [ ] Existing envelope/vault tests updated for the four-field shape and the
      two-source composition; no lingering assertion that the envelope carries
      author/title/date.
- [ ] The locked-shape change is recorded (spec already sanctions it, §7.3/§7.13);
      over-engineering tripwires checked (no field mirrored back into the
      envelope).
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder
      approval.

## Status / progress log

- 2026-07-21 planned. Depends on slice 02 (reads author/title/date from its
  record). Supersedes the phase-a-completion README's Wave-1 independent placement
  of 1a: #278 now depends on 1c (slice 02), not on nothing.
