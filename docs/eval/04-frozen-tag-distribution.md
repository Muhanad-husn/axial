# Frozen tag distribution (stage 4.4)

**Recorded 2026-07-23**, immediately after the 2026-07-23 corpus retag (best-of-N,
issue #294/DEC-31) and its post-retag `vault-write` both finished with 0 unresolved
fails across all 30 sources. This is the input stage 5 (HDBSCAN distillation) reads for
stratified teacher-label sampling. Computed directly from `data/tags/*.jsonl` — real
corpus data, no model calls, no simulation.

Phase A closes at this step (DEC-32).

## Corpus totals

- **17,824** tagged chunks (non-quarantined)
- **586** quarantined chunks (parse_error/missing_polity/out_of_vocab classes — issues
  #120/#327/#329/#331)

## Per-axis distribution

Percentages are of the 17,824 tagged chunks. An axis's `abstained` count (best-of-N
draws held no strict plurality, DEC-31/33) is reported separately, not folded into the
value percentages.

### `role_in_argument`

| value | count | % |
|---|---|---|
| role:evidence | 6923 | 38.8% |
| role:claim | 6491 | 36.4% |
| role:setup | 3474 | 19.5% |
| role:counter-position | 517 | 2.9% |
| role:synthesis | 254 | 1.4% |
| role:methodological | 117 | 0.7% |
| role:digression | 48 | 0.3% |

### `empirical_scope`

| value | count | % |
|---|---|---|
| scope:general | 9058 | 50.8% |
| scope:country-case | 6386 | 35.8% |
| scope:comparative | 1311 | 7.4% |
| scope:regional | 739 | 4.1% |
| scope:sub-national | 330 | 1.9% |

### `field`

| value | count | % |
|---|---|---|
| state | 11821 | 66.3% |
| ideology | 3693 | 20.7% |
| violence | 2310 | 13.0% |

### `claim_type` (blind axis, best-of-N; abstained: 1452)

| value | count | % |
|---|---|---|
| state-formation | 4482 | 25.1% |
| state-society-relations | 2355 | 13.2% |
| state-capacity | 2343 | 13.1% |
| violence-logic | 1554 | 8.7% |
| ideology-as-system | 869 | 4.9% |
| nationalism-theory | 674 | 3.8% |
| sovereignty-and-recognition | 567 | 3.2% |
| legitimating-narratives | 473 | 2.7% |
| identity-and-group-formation | 392 | 2.2% |
| revolution-and-contention | 354 | 2.0% |
| war-and-state | 347 | 1.9% |
| legitimacy-and-legitimation | 344 | 1.9% |
| power-typology | 304 | 1.7% |
| comparative-method | 288 | 1.6% |
| ideology-as-practice | 226 | 1.3% |
| mobilization-and-recruitment | 198 | 1.1% |
| violence-actors | 192 | 1.1% |
| statehood-gradations | 140 | 0.8% |
| state-autonomy | 89 | 0.5% |
| civilian-targeting | 88 | 0.5% |
| normative-political-theory | 83 | 0.5% |
| religion-and-politics | 10 | 0.1% |

### `theory_school` (blind axis, best-of-N; abstained: 1898)

DEC-34 ratifies KEEP on these numbers: 48.8% not-applicable (a legitimate structural
category — most prose is descriptive/empirical, not theory-engaging), 0.6% unlisted
(the codebook's vocabulary covers the real corpus well).

| value | count | % |
|---|---|---|
| not-applicable | 8701 | 48.8% |
| bellicist | 1503 | 8.4% |
| colonial-postcolonial | 920 | 5.2% |
| institutionalist-state-centered | 611 | 3.4% |
| marxist-political-economy | 595 | 3.3% |
| state-in-society | 438 | 2.5% |
| micro-sociological | 431 | 2.4% |
| constructivist | 405 | 2.3% |
| discursive | 388 | 2.2% |
| historical-sociological | 308 | 1.7% |
| cultural-ideational | 305 | 1.7% |
| external-statebuilding | 260 | 1.5% |
| constructivist-anti-essentialist | 221 | 1.2% |
| neo-bellicist | 168 | 0.9% |
| state-centered-organizational | 137 | 0.8% |
| unlisted | 107 | 0.6% |
| materialist | 92 | 0.5% |
| modernization-developmental | 73 | 0.4% |
| neo-marxist | 62 | 0.3% |
| marxist-critical-pol-econ | 44 | 0.2% |
| interpretive-constructivist | 31 | 0.2% |
| biological-evolutionary | 31 | 0.2% |
| structuralist | 25 | 0.1% |
| systematic | 25 | 0.1% |
| postcolonial-decolonial | 13 | 0.1% |
| subject-centered | 9 | 0.1% |
| opportunity-feasibility | 8 | 0.0% |
| civilizing-decline | 7 | 0.0% |
| structural-violence | 4 | 0.0% |
| criminological | 4 | 0.0% |

### `polities_touched` (many-valued; top 20 of 998 distinct polities)

| polity | count |
|---|---|
| Syria | 2577 |
| United States | 1146 |
| France | 900 |
| Egypt | 894 |
| Lebanon | 857 |
| Iraq | 546 |
| Germany | 530 |
| Britain | 433 |
| Russia | 382 |
| United Kingdom | 380 |
| Ottoman Empire | 367 |
| Tunisia | 363 |
| China | 354 |
| Turkey | 324 |
| Japan | 272 |
| Israel | 258 |
| Morocco | 249 |
| Iran | 249 |
| Jordan | 247 |
| Soviet Union | 246 |

Note `Britain`/`United Kingdom` and `Russia`/`Soviet Union` are surface variants of
related but distinct referents here, not yet folded through the #205 canonical alias
map for this report — stage 5's own sampling should apply that map if per-polity
stratification needs the merged counts.

## Provenance

Computed via a one-off read over `data/tags/*.jsonl` (all 30 sources' post-retag
checkpoints), excluding `theory_school_candidates.jsonl` and `_quarantine_log.jsonl`.
No LLM calls. See issue #329 and `plans/phase-a-completion/TRACKER.md` for the retag's
full operational history.
