---
artifact_id: vqf2-art-001
artifact_role: case-study
field:
  primary: field:political-sociology
  secondary: []
source_id: vqf2-src-north
section: "Synthetic Section — Causes of Conflict"
retrievable: true
cited_by: [vqf2-src-north_1_causes-of-conflict_001, vqf2-src-north_1_causes-of-conflict_002]
---
# Synthetic Artifact

Fixture for tests/analysis/test_vault_query_facets.py (issue #251):
`follow_backlinks("vqf2-src-north_1_causes-of-conflict_001")` resolves to
`["vqf2-art-001"]` (this note's id) via `artifact_refs`; the reverse call
`follow_backlinks("vqf2-art-001")` resolves to this note's `cited_by`, sorted
ascending.
