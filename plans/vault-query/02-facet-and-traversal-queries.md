# Slice 02: Facet and traversal queries — polity, source/envelope, backlinks, coverage

- **Feature:** vault-query
- **Slice slug:** facet-and-traversal-queries
- **GitHub issue:** #251
- **Branch:** `feat/vault-query/02-facet-and-traversal-queries`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** slice 01 (the note parser, result shapes, sort contract, and
  vault-scan seam)

## Goal — the minimum testable behaviour

The remaining four §7.5 tools, on slice 01's reader:

- **`query_by_polity(polity)`** — chunks whose many-valued `polities_touched`
  list includes the given polity. This is the cross-case retrieval the
  single-valued `empirical_scope.polity` axis cannot serve, and it is what makes
  case-as-anchor-not-fence (charter §3) mechanically possible.
- **`query_by_source(source_id)` / `get_envelope(source_id)`** — the chunks of a
  given source, and that source's envelope read from
  `data/envelopes/<source_id>.json` with its `thesis`, nested `toc`, `scope`, and
  `stated_argument`. The `toc` is the post-#235 **nested** shape:
  `[{title: str, children: [str, ...]}, ...]`.
- **`follow_backlinks(id)`** — bidirectional traversal: from a chunk to its
  `artifact_refs`, and from an artifact to its `cited_by`. Both directions, the
  links Phase A already wrote.
- **`coverage_count()`** — the count of substantive chunks per polity across the
  whole vault, from `polities_touched`. This is the raw material of the coverage
  map (§7.7); the bands and thresholds are not built here.

Same guarantees as slice 01: results explicitly sorted so the same query over the
same pinned vault returns the same ids in the same order, and zero model calls
and zero embedding calls on any path.

## INVEST check

- **Independent:** four additive tools on slice 01's reader. Each is separately
  useful and none changes how `query_by_tag` behaves.
- **Valuable:** it completes P0-2, so the §7.5 tool set the agentic loop is
  specified against actually exists. `query_by_polity` and `coverage_count` are
  the two facets nothing else in the product can serve — they are the substrate
  for charter Principle V's per-polity disclosure.
- **Small:** three list-filter tools and one counter, plus a small JSON reader
  for the envelope.
- **Testable:** a fixture vault with known `polities_touched` lists, known
  `artifact_refs` / `cited_by` pairs, and one fixture envelope. Assert exact id
  sets, exact counts, and repeat-query order stability. Hermetic — no network,
  no LLM.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture vault where chunk A has polities_touched ["Syria", "Iraq"],
      chunk B has ["Iraq"], and chunk C has ["Lebanon"]
  And no LLM client configured or constructible in the test process
When  query_by_polity("Iraq") is called
Then  exactly chunk A and chunk B are returned, in ascending chunk_id order
  And a second identical call returns the identical id list in the identical order
  And zero model calls and zero embedding calls were made

Given the same fixture vault and an envelope at data/envelopes/<source_id>.json
When  get_envelope(<source_id>) is called
Then  the result carries thesis, scope, stated_argument, and a nested toc whose
      entries are {title, children} objects
  And query_by_source(<source_id>) returns exactly that source's chunk_ids,
      sorted ascending

Given chunk A whose artifact_refs is ["<artifact_id>"] and artifact
      <artifact_id> whose cited_by is ["<chunk A id>", "<chunk B id>"]
When  follow_backlinks(<chunk A id>) is called
Then  ["<artifact_id>"] is returned
When  follow_backlinks("<artifact_id>") is called
Then  ["<chunk A id>", "<chunk B id>"] is returned, sorted ascending

Given the same fixture vault
When  coverage_count() is called
Then  it returns {"Iraq": 2, "Syria": 1, "Lebanon": 1}
```

- **Boundary / endpoint:** library entries `axial.query.query_by_polity`,
  `axial.query.query_by_source`, `axial.query.get_envelope`,
  `axial.query.follow_backlinks`, `axial.query.coverage_count`; the on-disk vault
  and `data/envelopes/`.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_vault_query_facets.py` — authored by
  the test-author, committed red, then locked (DEC-1).

## Inner loop — initial unit test list

- [ ] `query_by_polity` matches any entry of the many-valued `polities_touched`
      list, not just the first; a chunk with an empty list never matches.
- [ ] `query_by_polity` is distinct from an `empirical_scope.polity` filter: a
      chunk scoped to Syria but touching Iraq is returned for `"Iraq"`, which is
      the cross-case behaviour the scope axis cannot serve (§7.5).
- [ ] Polity matching is exact-string against the faithful-naming values Phase A
      wrote; no normalization, aliasing, or fuzzy matching.
- [ ] `query_by_source` returns exactly one source's chunks; the `source_id`
      seam within `chunk_id`
      (`{source_id}_{page_start}_{page_end}-{section_label}_{seq}`) is pinned by
      a test so the parse rule cannot drift silently.
- [ ] `get_envelope` reads `data/envelopes/<source_id>.json` and exposes
      `source_id`, `author`, `title`, `date`, `thesis`, `toc`, `scope`, and
      `stated_argument`.
- [ ] `get_envelope` preserves the **nested** toc shape — a list of
      `{title, children[]}` — and does not flatten it.
- [ ] `get_envelope` on an unknown `source_id` raises a clear not-found error.
- [ ] `follow_backlinks` on a chunk returns its `artifact_refs`; on an artifact
      returns its `cited_by`; an empty list on either side returns `[]`, not an
      error.
- [ ] `follow_backlinks` dispatches on the id's kind and raises a clear error on
      an id that resolves to neither a chunk nor an artifact.
- [ ] `coverage_count` sums across the whole vault, counting each chunk once per
      distinct polity it touches, and returns a deterministically ordered mapping.
- [ ] `coverage_count` over a vault where no chunk carries `polities_touched`
      returns an empty mapping rather than raising.
- [ ] Every tool's results are explicitly sorted; a scrambled fixture creation
      order does not change any returned order.
- [ ] The whole module imports and runs with no LLM client configured.

## Out of scope for this slice (deferred)

- The coverage **map** of §7.7 — `evidence_chunk_count`, `coverage_band`, and
  the tunable band threshold. This slice ships `coverage_count`, the raw
  material; the map belongs with P0-7.
- What counts as "substantive" beyond what Phase A already encodes in the vault.
  This layer counts the chunks Phase A wrote; re-litigating substantiveness is a
  Phase-A concern (§3 non-goal 5).
- Multi-hop or transitive backlink traversal. One hop each direction is the
  §7.5 contract.
- Any ranking, scoring, or relevance order (§7.5); embedding or vector
  similarity (§3 non-goal 4, P2-1).
- The agentic loop that calls these tools and the trajectory log (P0-3, §7.6).
- Caching or indexing for speed; a measured follow-up if the loop proves it
  necessary.

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
