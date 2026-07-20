---
chunk_id: vqfix_001_causes
section: "Synthetic Section One — Causal Claims"
chunk_text: "SENTINEL_CHUNK_TEXT_VQFIX_001: a synthetic sentence stating that weak local patronage networks caused a shift in ruling-coalition composition."
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
  secondary: []
claim_type:
  primary: claim:causal
  secondary: null
  subtags: [claim:causal:mechanism]
theory_school:
  primary: school:synthetic-institutionalist
  secondary: null
  status: candidate
empirical_scope:
  value: scope:country-case
  polity: Freedonia
polities_touched: [Freedonia]
artifact_refs: [vqfix_art_001]
---
# Synthetic Section One — Causal Claims

SENTINEL_CHUNK_TEXT_VQFIX_001: a synthetic sentence stating that weak local
patronage networks caused a shift in ruling-coalition composition.

This note is a fixture for tests/analysis/test_vault_query.py (issue #249) --
MATCH: both `field` and `role_in_argument` satisfy the query filter. This is
the KNOWN chunk_id used by the `get_chunk` field-surface scenario, so its
`artifact_refs` deliberately points at the one fixture artifact note.
