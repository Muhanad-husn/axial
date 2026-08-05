# feat(vault-query): facet and traversal queries — polity, source/envelope, backlinks, coverage [slice 02]

**Spec:** specs/PHASE-B.md#7.5 · §8 P0-2 · **Plan:** plans/vault-query/02-facet-and-traversal-queries.md
**Depends on:** #249
**Labels:** sub:analysis-v0, enhancement

## Deliverable
The remaining four §7.5 tools on slice 01's reader, completing P0-2.
`query_by_polity(polity)` returns chunks whose many-valued `polities_touched`
list includes the polity — the cross-case retrieval the single-valued
`empirical_scope.polity` axis cannot serve, and what makes
case-as-anchor-not-fence (charter §3) mechanically possible.
`query_by_source(source_id)` returns a source's chunks and
`get_envelope(source_id)` reads `data/envelopes/<source_id>.json` with its
`thesis`, `scope`, `stated_argument`, and the post-#235 **nested** `toc`
(`[{title, children[]}, ...]`, preserved, not flattened). `follow_backlinks(id)`
traverses both directions: chunk → `artifact_refs`, artifact → `cited_by`.
`coverage_count()` counts substantive chunks per polity across the vault from
`polities_touched` — the raw material of the coverage map (§7.7). Same
guarantees as slice 01: explicitly sorted results, so the same query over the
same pinned vault returns the same ids in the same order. LLM-free by
construction: zero model and zero embedding calls on any path.

## Acceptance criterion
```gherkin
Given a fixture vault where chunk A has polities_touched ["Syria", "Iraq"],
      chunk B has ["Iraq"], and chunk C has ["Lebanon"]
  And no LLM client configured or constructible in the test process
When  query_by_polity("Iraq") is called
Then  exactly chunk A and chunk B are returned, in ascending chunk_id order
  And an identical second call returns the identical id list in the identical order
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

## Out of scope
- The coverage **map** of §7.7 — `evidence_chunk_count`, `coverage_band`, and
  the tunable band threshold belong with P0-7. This slice ships the raw counts.
- Re-litigating what counts as "substantive" beyond what Phase A encoded
  (§3 non-goal 5).
- Multi-hop or transitive backlink traversal; one hop each direction is the
  §7.5 contract.
- Any ranking, scoring, or relevance order; embedding or vector similarity
  (§3 non-goal 4, P2-1).
- The agentic loop that calls these tools and the trajectory log (P0-3, §7.6).
- Caching or indexing for speed.
