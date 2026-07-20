# Slice 01: Vault reader and tag query — parse notes, fetch by id, filter by tag axes

- **Feature:** vault-query
- **Slice slug:** vault-reader-and-tag-query
- **GitHub issue:** #249
- **Branch:** `feat/vault-query/01-vault-reader-and-tag-query`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** yes (a new `src/axial/query/` module per §6; the thinnest
  end-to-end thread — parse a note off disk, filter it by tags, return sorted ids)
- **Depends on:** none

## Goal — the minimum testable behaviour

A reader parses a vault note — YAML frontmatter plus markdown body — from
`data/vault/prose/<chunk_id>.md` and `data/vault/artifacts/<artifact_id>.md`
into a result object carrying the note's id, its frontmatter fields, and its
text. On top of it, three of the §7.5 tools:

- **`get_chunk(chunk_id)`** — one prose note by id, with frontmatter and text.
- **`get_artifact(artifact_id)`** — one artifact note by id, with frontmatter.
- **`query_by_tag(**filters)`** — every chunk matching a **conjunction** of
  tag-axis filters over `field`, `claim_type` (incl. `subtags`),
  `empirical_scope` (incl. `polity`), `role_in_argument`, and `theory_school`.

The determinism contract lands here and binds everything after it: **the same
query over the same pinned vault returns the same ids in the same order**.
Results are explicitly sorted by `chunk_id`, never left in filesystem
enumeration order. A missing id raises a clear not-found error rather than
returning `None` into a caller that will not check it.

Zero model calls and zero embedding calls on any path — the acceptance test
asserts the whole surface runs with no LLM client present (P0-2).

## INVEST check

- **Independent:** it reads files and returns objects. Nothing upstream; the
  agentic loop that will call it is a later sprint. `src/axial/vault.py` is
  write-only, so nothing existing is disturbed.
- **Valuable:** P0-2, the foundation slice of the whole phase (§11 step 2).
  Until the vault can be read, no Phase-B stage above it can be built or tested.
  `query_by_tag` alone is the single most-used retrieval move the agent has.
- **Small:** one frontmatter parser, one result shape, one filter predicate, one
  directory scan. The nested frontmatter shapes are known and fixed.
- **Testable:** build a fixture vault of a handful of notes on disk with known
  tags, then assert exactly which ids come back and in what order. Fully
  hermetic — no network, no LLM, no embedding model.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture vault under data/vault/prose/ with four prose notes whose
      frontmatter carries known values for field, claim_type (with subtags),
      empirical_scope (value + polity), role_in_argument, and theory_school
  And one artifact note under data/vault/artifacts/
  And no LLM client configured or constructible in the test process
When  query_by_tag(field="field:political-sociology", role_in_argument="role:claim")
      is called
Then  exactly the chunk_ids of the notes matching BOTH filters are returned
  And the ids are returned in ascending chunk_id order
  And calling the identical query a second time returns the identical id list in
      the identical order
  And zero model calls and zero embedding calls were made

Given the same fixture vault
When  get_chunk(<a known chunk_id>) is called
Then  the result carries that chunk_id, its chunk_text, its section, its
      source_meta, its polities_touched list, and its artifact_refs list

Given the same fixture vault
When  get_chunk("does-not-exist") is called
Then  a clear not-found error naming the id is raised, not a None result
```

- **Boundary / endpoint:** library entries `axial.query.get_chunk(chunk_id)`,
  `axial.query.get_artifact(artifact_id)`, and
  `axial.query.query_by_tag(**filters)`; the on-disk vault at
  `data/vault/prose/` and `data/vault/artifacts/`.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_vault_query.py` — authored by the
  test-author, committed red, then locked (DEC-1).

## Inner loop — initial unit test list

Co-located under `src/axial/query/` (e.g. `src/axial/query/test_reader.py`).

- [ ] The note parser splits YAML frontmatter from the markdown body and returns
      both; a note with no frontmatter, unterminated frontmatter, or invalid
      YAML raises a clear error naming the file.
- [ ] A parsed prose note exposes `chunk_id`, `section`, `chunk_text`,
      `source_meta`, `schema_version`, `role_in_argument`, `field`,
      `claim_type`, `theory_school`, `empirical_scope`, `polities_touched`, and
      `artifact_refs` in their real nested shapes.
- [ ] A parsed artifact note exposes `artifact_id`, `artifact_role`, `field`,
      `source_id`, `section`, `retrievable`, and `cited_by`; an absent `caption`
      reads as `None` rather than raising.
- [ ] `field` filtering matches `primary` and `secondary`.
- [ ] `claim_type` filtering matches `primary`, `secondary`, and `subtags[]` —
      the "incl. subtags" rule of §7.5, pinned here as a stated tunable.
- [ ] `theory_school` filtering matches `primary` and `secondary`; the `status`
      sub-field is carried on the result but is not a filter key.
- [ ] `empirical_scope` filtering matches on `value`, and separately on
      `polity`; a note whose `empirical_scope.polity` is `null` never matches a
      polity filter.
- [ ] `role_in_argument` filtering matches the plain string exactly (e.g.
      `"role:claim"`).
- [ ] Multiple filters compose as a **conjunction**: a note must satisfy every
      supplied filter to be returned; a filter set no note satisfies returns an
      empty list, not an error.
- [ ] An unknown filter key raises rather than silently matching everything — a
      typo'd axis must not quietly widen a query.
- [ ] Results are sorted by `chunk_id`; a fixture directory whose files are
      created in a scrambled order still returns ascending ids.
- [ ] `get_chunk` / `get_artifact` raise a clear not-found error on an unknown id.
- [ ] The whole module imports and runs with no LLM client configured — no
      import of, or construction of, any provider client on any path.

## Out of scope for this slice (deferred)

- `query_by_polity`, `query_by_source` / `get_envelope`, `follow_backlinks`, and
  `coverage_count` — slice 02.
- Any ranking, scoring, or relevance order. Sorting is for determinism only
  (§7.5).
- Embedding or vector similarity of any kind (§3 non-goal 4, P2-1).
- The agentic loop that calls these tools and the trajectory log (P0-3, §7.6).
- Caching or indexing for speed. A full scan is correct; making it fast is a
  measured follow-up if the agentic loop proves it necessary.
- Any write path into the vault. This layer is read-only by construction.
- Free-text search over `chunk_text`. v0 retrieval is structured tag query
  (§7.5).

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
