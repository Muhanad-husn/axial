# Feature: Vault query API — deterministic, model-free retrieval

Build the read layer Phase B stands on. Phase A's `src/axial/vault.py` is
**write-only**: it writes prose and artifact notes and has no reader, no parser,
and no query helper. This feature builds the read side from scratch — the §7.5
tool set over the tagged vault: query by tag axis, by the many-valued
`polities_touched` facet, by source and envelope; fetch a chunk or artifact by
id; traverse backlinks in both directions; count coverage per polity. Every tool
returns auditable vault ids plus the frontmatter and text needed to reason, and
**calls no model and no embedding model**, so the whole surface is testable with
no LLM client present (P0-2). Determinism is the contract: the same query over
the same pinned vault returns the same ids in the same order. The agentic query
loop (stage 3) and every stage above it benefit — they get a small fixed tool set
whose behaviour is pinned by tests rather than by a model's mood.

- **Slug:** vault-query
- **Created:** 2026-07-20
- **Status:** planned
- **New system?** yes (a new `src/axial/query/` module per §6; slice 01 is the
  thinnest end-to-end thread — parse a note, filter by tags, return sorted ids)
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [vault-reader-and-tag-query](01-vault-reader-and-tag-query.md) | [#249](https://github.com/Muhanad-husn/axial/issues/249) | Parse a vault note from disk, then `get_chunk`, `get_artifact`, and `query_by_tag` over a conjunction of tag-axis filters, returning deterministically sorted ids with zero LLM present | ☐ todo | TBD |
| 02 | [facet-and-traversal-queries](02-facet-and-traversal-queries.md) | [#251](https://github.com/Muhanad-husn/axial/issues/251) | `query_by_polity`, `query_by_source` + `get_envelope`, `follow_backlinks` both directions, and `coverage_count` — completing the §7.5 tool set under the same determinism and no-LLM guarantees | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Dependencies

- 01 is the foundation: the note parser, the `Chunk`/`Artifact` result shapes,
  the sort contract, and the vault-scan seam every other tool reuses. 02 depends
  on 01 and cannot start before it.
- Neither slice depends on the `analysis-foundation` feature. This feature and
  that one can run in parallel; they share no code.
- Both slices are LLM-free by construction: no model call, no embedding call, on
  any path. The acceptance tests assert the whole surface is exercisable with no
  LLM client present (P0-2).
- Phase-B build order puts this second, right after scaffolding (§11 step 2),
  because stages 3–6 all call these tools.

## Out of scope (whole feature)

- Ranking, scoring, or relevance ordering of any kind. Retrieval in v0 is exactly
  these structured queries: no ranking model, no vector similarity (§7.5, §3
  non-goal 4). The sort order exists for determinism, not for relevance.
- Any embedding or vector index. Deferred to P2-1 and reopened **only** on
  demonstrated recall failure on real briefs, never speculatively (§3, Open
  Questions).
- The agentic query loop that calls these tools (P0-3, stage 3) and the
  trajectory log (§7.6). This feature ships the tools; the agent is a later
  sprint.
- The coverage **map** (§7.7) with its bands and thresholds. Slice 02 ships
  `coverage_count`, the raw material; deriving `coverage_band` against a tunable
  threshold belongs with P0-7.
- Any write to the vault. Phase B reads the vault read-only; Phase A owns
  ingestion, tagging, and the schema (§3 non-goal 5). Nothing in this feature
  opens a vault file for writing.
- Caching or indexing for speed. Correctness and determinism first; if a
  full-vault scan over ~17k chunks proves too slow in the agentic loop, that is a
  measured follow-up, not a speculative one.

## Notes / open questions

- **No reader exists.** `src/axial/vault.py` is write-only, so slice 01 builds
  the frontmatter parser too. PyYAML is already a project dependency; the parser
  should split YAML frontmatter from the markdown body and validate the note
  carries the fields the query layer reads.
- **The frontmatter shapes are nested and must be honoured exactly.** Prose:
  `field` / `claim_type` / `theory_school` are dicts (`primary`, `secondary`,
  plus `subtags[]` on `claim_type` and `status` on `theory_school`),
  `empirical_scope` is `{value, polity|null}`, `polities_touched` is a flat
  `list[str]`, `role_in_argument` is a plain string like `"role:claim"`, and
  `artifact_refs` is always present. Artifacts carry `artifact_id`,
  `artifact_role`, `field`, `source_id`, `section`, `retrievable`, an optional
  `caption` (omitted when absent), and `cited_by`, always present.
- **`claim_type` subtag matching** needs a decision the implementer should make
  explicit in slice 01: a `claim_type` filter should match against `primary`,
  `secondary`, and `subtags[]` unless the caller narrows it. The spec says
  "incl. subtags" (§7.5); the exact matching rule is a stated tunable pinned by
  the unit tests.
- **`chunk_id` carries structure** — `{source_id}_{page_start}_{page_end}-{section_label}_{seq}`
  — which makes `query_by_source` cheap in slice 02. The implementer should
  decide whether to filter on the id prefix or on a parsed field, and pin the
  choice with a test; ids are the contract, parsing them is an implementation
  detail.
- **`empirical_scope.polity` vs `polities_touched`** is the distinction slice 02
  turns on. The scope axis is single-valued and says what a chunk is *about*;
  `polities_touched` is many-valued and says what it *engages*. Cross-case
  retrieval — the case-as-anchor-not-fence behaviour of charter §3 — is only
  servable from the many-valued facet (§7.5).
- **Determinism is a testable property, not a docstring.** Results must be
  explicitly sorted, never left in filesystem enumeration order, which varies by
  platform and by directory history. Both slices' acceptance tests assert
  repeat-query id-order stability.
