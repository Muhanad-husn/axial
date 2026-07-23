---
chunk_id: vqf2-src-north_1_causes-of-conflict_001
section: "Synthetic Section — Causes of Conflict"
chunk_text: "SENTINEL_CHUNK_TEXT_VQF2_A: a synthetic sentence about cross-border patronage networks linking two invented polities."
source_meta:
  author: "B. Synthetic Author"
  title: "A Synthetic Fixture Source on Cross-Case Conflict"
  date: 2021
  thesis: "Synthetic thesis: cross-border patronage structures conflict onset."
  scope: "Synthetic scope: a comparative two-country study."
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
  value: scope:comparative
  polity: Syria
polities_touched: [Syria, Iraq]
artifact_refs: [vqf2-art-001]
---
# Synthetic Section — Causes of Conflict

SENTINEL_CHUNK_TEXT_VQF2_A: a synthetic sentence about cross-border
patronage networks linking two invented polities.

Fixture for tests/analysis/test_vault_query_facets.py (issue #251). This is
"chunk A": `polities_touched` deliberately differs from `empirical_scope.polity`
(Syria only) to prove `query_by_polity("Iraq")` is a distinct facet from the
single-valued scope axis. Its `artifact_refs` points at the one fixture
artifact note, whose `cited_by` in turn points back at this chunk and chunk B
(`follow_backlinks` bidirectional scenario).
