# Run: 855 relation examine (runs checkout)

#855 step 1: `axial vocabulary examine --column relation` over the argument
map's relations, exactly as #805 ran over the answer columns. Run in
`D:/axial-runs` at main `7d7b314`.

## Command

```
AEO_DATA_ROOT=D:/axial-runs/data  AXIAL_SECRETS_PATH=D:/axial-runs/secrets/secrets.toml
(cwd D:/axial-runs, detached with Start-Process, memory sampled by watch_run.py)
axial vocabulary examine --column relation
```

Exit 0 in 238.6s, peak private memory 545 MB. **$0.0059** over 6 calls
(deepseek-v4-flash proposes and assigns, $0.0037; gpt-5.6-luna checks,
$0.0022).

## Result

1,472 relations, 1,472 distinct label+says strings, 0 excluded. Propose
sample 400, held-out assign sample 400.

| | |
|---|---|
| categories proposed | 17 (3 drew no members) |
| assignment rate, held-out | **97.8%** (391 of 400) |
| unanswered / refused | 0 / 9 |
| categories with 5+ members | 11, all spanning 2+ sources |
| largest category share | 18.5% |
| two-model agreement (n=100) | **76.0%**; 78.4% where the first model assigned (n=97) |

For scale against #805's table: agreement sits with `claim` (77.0%) and
`about` (81.9%), above every column that failed its bar on c2 (59-66%).

| proposed kind | members | sources |
|---|---:|---:|
| illustration/exemplification | 74 | 48 |
| support | 73 | 47 |
| qualification | 55 | 38 |
| mechanism explanation | 40 | 37 |
| contradiction | 38 | 35 |
| causal supplementation | 36 | 28 |
| specification | 29 | 25 |
| basis provision | 16 | 14 |
| contextualization | 8 | 8 |
| scope extension | 6 | 6 |
| undermining via counterexample | 6 | 5 |
| critique of limitation | 4 | 4 |
| competing explanation | 4 | 4 |
| precedence or antecedent | 2 | 2 |
| reduction to single cause, evaluative judgment, identification of target | 0 | 0 |

## What went into `config/vocabulary.yaml`

A flat, nine-kind scheme, version `2026-09-29-relation-v1`, proposed for the
founder's edit: the 14 non-empty kinds folded into nine, `conflict` kept as an
id because the corridor reads it by name.

- **conflict** = contradiction + counterexample + competing explanation:
  48 of 391, **12.3%** of assigned.
- **qualification** kept apart from conflict (59, 15.1%): it keeps the other
  claim and narrows it, so it does not belong first in a contested corridor.
- AIF's `preference` genus drew nothing and is dropped. The genus of each kind
  is named in its gloss instead of as a level, because `vocabulary build`
  assigns depth 1 only (#806).

A flat scheme offers the relate prompt no example labels
(`relation_kind_examples` offers only kinds below the top level), so the map
build's prompt stays byte-identical.

`test_vocabulary_relation.py`'s pin on the draft seed is updated to the
committed shape: flat, dated, holding `conflict`.

## Next

Founder edits and commits the scheme; then `axial vocabulary build --column
relation` (priced at about $0.02 from this run's rate), the five smoke briefs
with `corridor: order=kind`, and the structural read against the 629
cross-author relations.
