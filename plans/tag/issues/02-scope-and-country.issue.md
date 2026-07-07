# feat(tag): empirical_scope + scope:country-case country extra field [slice 02]

**Spec:** specs/PRODUCT.md#5-6 (stage 6), Appendix C · **Plan:** plans/tag/02-scope-and-country.md
**Depends on:** tag slice 01 (this sprint)
**Labels:** sub:ingestion-v0

## Deliverable

`axial tag <file>` additionally assigns `empirical_scope` — a single, exactly-one-value
axis — and, when that value is `scope:country-case`, attaches a `country` drawn from the
schema's controlled `country_list`. A country-case record with no country, or a country
absent from `country_list`, is a hard error. This is the axis that lets retrieval separate
`scope:general` theory from `scope:country-case:Syria` evidence (Appendix C rationale),
and it exercises the extra-field / controlled-list machinery.

## Acceptance criterion

```gherkin
Given an extracted fixture source with a stored envelope and chunks, AXIAL_LLM_PROVIDER=stub returning empirical_scope=scope:country-case with country=Syria
When  the user runs `axial tag <fixture>`
Then  each record carries exactly one empirical_scope value drawn from the schema
And   a scope:country-case record carries a country drawn from the schema's country_list
And   a country-case with a missing or out-of-list country exits non-zero with a clear error
```

## Out of scope

- The primary+secondary axes — field/claim_type/theory_school (slice 03).
- Vault persistence (slice 04).
- Expanding the country_list (a schema edit, not code).
