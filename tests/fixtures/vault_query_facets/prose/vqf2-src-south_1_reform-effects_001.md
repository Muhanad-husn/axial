---
chunk_id: vqf2-src-south_1_reform-effects_001
section: "Synthetic Section — Reform Effects"
chunk_text: "SENTINEL_CHUNK_TEXT_VQF2_C: a synthetic sentence about a reform program in a third invented polity."
source_meta:
  author: "C. Synthetic Author"
  title: "A Synthetic Fixture Source on Reform Effects"
  date: 2019
  thesis: "Synthetic thesis: reform sequencing determines institutional durability."
  scope: "Synthetic scope: a single-country case study."
schema_version: "0.1"
role_in_argument: role:claim
field:
  primary: field:political-sociology
  secondary: []
claim_type:
  primary: claim:causal
  secondary: null
  subtags: []
theory_school:
  primary: school:synthetic-institutionalist
  secondary: null
  status: candidate
empirical_scope:
  value: scope:country-case
  polity: Lebanon
polities_touched: [Lebanon]
artifact_refs: []
---
# Synthetic Section — Reform Effects

SENTINEL_CHUNK_TEXT_VQF2_C: a synthetic sentence about a reform program in a
third invented polity.

Fixture for tests/analysis/test_vault_query_facets.py (issue #251). This is
"chunk C": a different `source_id` (`vqf2-src-south`) from chunks A and B, so
`query_by_source("vqf2-src-north")` must exclude it, and its own
`polities_touched` (Lebanon only) is the third `coverage_count` bucket.
