---
chunk_id: vqfix_004_uprising
section: "Synthetic Section Four — Mobilization"
chunk_text: "SENTINEL_CHUNK_TEXT_VQFIX_004: a synthetic sentence describing a fictional uprising that spread across two neighboring polities."
source_meta:
  author: "A. Synthetic Author"
  title: "A Synthetic Fixture Source on Political Sociology"
  date: 2020
  thesis: "Synthetic thesis: patronage networks structure coalition change."
  scope: "Synthetic scope: a single-country case study."
schema_version: "0.1"
role_in_argument: role:claim
field:
  primary: field:political-sociology
  secondary: [field:social-movements]
claim_type:
  primary: claim:descriptive
  secondary: null
  subtags: []
theory_school:
  primary: school:synthetic-conflict
  secondary: null
  status: candidate
empirical_scope:
  value: scope:country-case
  polity: Ruritania
polities_touched: [Ruritania, Freedonia]
artifact_refs: []
---
# Synthetic Section Four — Mobilization

SENTINEL_CHUNK_TEXT_VQFIX_004: a synthetic sentence describing a fictional
uprising that spread across two neighboring polities.

This note is a fixture for tests/analysis/test_vault_query.py (issue #249) --
MATCH: both `field` and `role_in_argument` satisfy the query filter. Its
chunk_id sorts last among the four fixtures, ascending, so the ordering
assertion cannot pass by coincidence of only two matching ids happening to
already be in file order.
