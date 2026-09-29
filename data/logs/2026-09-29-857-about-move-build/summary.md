# #857: about and move built on the current pin, the schemes exported to SKOS

**Run:** 2026-09-29, `D:/axial-runs` on `feat/857-about-move-skos` at `937b935`.

```
axial vocabulary build --columns about,move      # wrapped in watch_run.py
python agreement.py   (AGREEMENT_SEED = 857, 1, 2)
axial vocabulary export --out vocabulary.ttl
```

Build: 369 s wall clock, peak 692 MB private, exit 0. 274 calls on
deepseek/deepseek-v4.1-flash, **$0.586**. Agreement checks: 6 calls on
gpt-5.6-luna, $0.013.

## Coverage and agreement against #805

#805's numbers are from its corrected examine run
(`../2026-08-27-vocabulary-categorise-v2/summary.md`, lines 38-39): a held-out
400 assigned by deepseek-v4-flash, 100 of them checked by gpt-5.6-luna.
Here the whole column is assigned by v4.1-flash, and three random 100s of the
build's own assignments (seeds 857, 1, 2) are re-assigned by gpt-5.6-luna
against the committed scheme in one batch each, the way examine checks.

| column | values | assigned | refused | out of scheme | coverage | #805 coverage | agreement where assigned | #805 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| about | 20,334 | 19,068 | 1,261 | 5 | 93.8% | 98.0% | 74.6% (212/284) | 81.9% (n=94) |
| move | 6,784 | 6,551 | 219 | 14 | 96.6% | 97.5% | 67.6% (194/287) | 72.0% (n=100) |

Per draw, where assigned: about 72.9%, 72.9%, 78.3%; move 64.6%, 67.7%, 70.5%.
Overall (a refusal both models agree on counts): about 72.7%, move 66.0%, n=300 each.

Read: `move` is inside noise of #805 (the draws span 6 points). `about` is
about 7 points below #805 on both coverage and agreement, more than one draw's
spread. Two differences from #805 could carry it and are not separated here:
the whole column is harder than a held-out 400 (6.2% refused here against 2%),
and the assigning model moved from v4-flash to v4.1-flash. Neither number was
a gate; both are disclosed.

Out-of-scheme values are the build's own named defect: 5 in `about` came back
under invented topic names (all statebuilding and BiH power-sharing), 14 in
`move` under truncated or reworded category names. They stay unfiled.

## Categories

about (members, sources): power, authority, and governance 2,985/34; political
economy and development 2,958/32; theory and methodology 2,618/35; state
formation and transformation 2,149/32; violence, war, and conflict 2,107/32;
nationalism and national identity 1,681/27; social categories and identities
1,397/33; bibliographic and source references 1,314/34; social movements and
collective action 1,271/27; colonialism and decolonization 588/23.

move: causal process tracing 1,014/34; bibliographic or evidentiary apparatus
851/34; concede-and-narrow argument 751/34; comparative case analysis 719/35;
theory synthesis or rebuttal 554/33; refutation 513/33; context-setting 481/34;
structural or typological framework 448/34; interpretation 361/34; synthesis
of findings 303/33; exposé of hidden mechanisms 244/30; methodological
justification 242/30; role annotation 70/28.

Every category in both columns spans 23+ sources.

## SKOS export and the ELSST cross-map

`vocabulary.ttl`: 6 schemes (mechanism, claim, position, relation, about,
move), 70 concepts, 7 closeMatch. Parses with rdflib; the round trip is
checked by `src/axial/test_vocabulary_skos.py` against the committed file.

`about` against ELSST version 7 (thesauri.cessda.eu, elsst-7), looked up by
its REST search:

| about category | ELSST closeMatch |
|---|---|
| nationalism and national identity | NATIONALISM |
| violence, war, and conflict | WAR |
| political economy and development | ECONOMICS (alt. label POLITICAL ECONOMY) |
| colonialism and decolonization | COLONIALISM |
| power, authority, and governance | POLITICAL POWER |
| social movements and collective action | POLITICAL MOVEMENTS |
| theory and methodology | RESEARCH METHODOLOGY |
| state formation and transformation | none: ELSST has no STATE or STATE FORMATION concept |
| social categories and identities | none: split across ETHNIC GROUPS, SOCIAL STRATIFICATION, IDENTITY |
| bibliographic and source references | none: not a subject |

No pipeline code reads `close_match`; only the export writes it.

## Next

The founder copies `data/vocabulary/about/`, `data/vocabulary/move/` and this
log back to `D:/axial`. #859/#860 next per the agreed order.
