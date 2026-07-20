# feat(vault-query): vault reader and tag query — parse notes, fetch by id, filter by tag axes [slice 01]

**Spec:** specs/PHASE-B.md#7.5 · §8 P0-2 · **Plan:** plans/vault-query/01-vault-reader-and-tag-query.md
**Depends on:** none
**Labels:** sub:analysis-v0, enhancement

## Deliverable
A reader parses a vault note — YAML frontmatter plus markdown body — from
`data/vault/prose/<chunk_id>.md` and `data/vault/artifacts/<artifact_id>.md`
into a result object carrying the note's id, its frontmatter in its real nested
shapes, and its text. `src/axial/vault.py` is write-only today, so this builds
the read layer from scratch. On top of it, three §7.5 tools: `get_chunk`,
`get_artifact`, and `query_by_tag`, the last filtering on a **conjunction** of
tag-axis filters over `field`, `claim_type` (incl. `subtags`), `empirical_scope`
(incl. `polity`), `role_in_argument`, and `theory_school`. The determinism
contract lands here and binds every tool after it: the same query over the same
pinned vault returns the same ids **in the same order**, so results are
explicitly sorted by `chunk_id` and never left in filesystem enumeration order.
A missing id raises a clear not-found error rather than returning `None`.
LLM-free by construction: zero model and zero embedding calls on any path, and
the acceptance test asserts the surface is exercisable with no LLM client
present (P0-2).

## Acceptance criterion
```gherkin
Given a fixture vault under data/vault/prose/ with four prose notes whose
      frontmatter carries known values for field, claim_type (with subtags),
      empirical_scope (value + polity), role_in_argument, and theory_school
  And one artifact note under data/vault/artifacts/
  And no LLM client configured or constructible in the test process
When  query_by_tag(field="field:political-sociology", role_in_argument="role:claim")
      is called
Then  exactly the chunk_ids of the notes matching BOTH filters are returned, in
      ascending chunk_id order
  And an identical second call returns the identical id list in the identical order
  And zero model calls and zero embedding calls were made

Given the same fixture vault
When  get_chunk(<a known chunk_id>) is called
Then  the result carries that chunk_id, its chunk_text, its section, its
      source_meta, its polities_touched list, and its artifact_refs list

Given the same fixture vault
When  get_chunk("does-not-exist") is called
Then  a clear not-found error naming the id is raised, not a None result
```

## Out of scope
- `query_by_polity`, `query_by_source` / `get_envelope`, `follow_backlinks`,
  `coverage_count` — slice 02.
- Any ranking, scoring, or relevance order; sorting is for determinism only (§7.5).
- Embedding or vector similarity of any kind (§3 non-goal 4, P2-1).
- The agentic loop that calls these tools and the trajectory log (P0-3, §7.6).
- Caching or indexing for speed; any write path into the vault (read-only by
  construction, §3 non-goal 5).
- Free-text search over `chunk_text` — v0 retrieval is structured tag query.
