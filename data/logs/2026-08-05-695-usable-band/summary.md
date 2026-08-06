# #695 — does the merge pass's self-disagreement move the material Axial writes from?

2026-08-05. Run from `D:/axial` against the live 34-book corpus.
**$0.055, 819s, 150 batches, 0 failures.**

```
uv run python scratchpad/probe_695_temp0.py --arms "1" --usable-only \
    --sample 150 --workers 12 --log-dir "data/logs/2026-08-05-695-usable-band"
uv run python scratchpad/impact_695_pages_moved.py
uv run python scratchpad/impact_695_band_exit.py
```

## The question

The founder's test: accept the instability unless it touches more than **5% of
the material Axial needs to produce better output**. A batch-level flip rate does
not answer that. Two things had to be fixed to make the number mean anything.

1. **The right population.** The earlier probe
   (`2026-08-05-695-merge-temp0/`) sampled all 3+-member batches and landed only
   37 notes on usable-band pages — 2.8% of its sample against 15.4% of the
   corpus. Its 0% impact there was a thin zero, not a finding. This run samples
   **only batches ruling on a surface that lands on a usable-band page**: 150 of
   the 237 that reproduce their key, 63% of the population.
2. **The right unit.** Counting every note of every surface that changed group
   overstates the impact enormously. A batch where `{'North Africa' (97 notes),
   'Northern African countries' (1)}` splits scores 98 notes "moved" that way —
   but the 97 stay on a North Africa page either way. **One** note moved. A note
   moves only when the heaviest surface of its group changes, which is the page
   a reader actually navigates to.

## Result

| | |
|---|---:|
| usable-band pages | 327 |
| their note assignments | 20,957 |
| batches sampled | 150 of 497 touching the band |
| **batch flip rate** | **19.3%** |
| flips that move any note to another page | 16 of 29 |
| **notes that change page — measured** | **90 — 0.43%** |
| scaled to reproducible batches only (×1.58) | 142 — 0.68% |
| scaled to all incl. stale-input (×3.31) | 298 — **1.42%** |

**Under 5% on every reading, by a factor of 3.5 at worst.**

## What the flips actually are

Every one. No exceptions:

```
'Berbers' -> 'Berber'                    'Catholic' -> 'Catholics' / 'Catholicism'
'North' -> 'the North'                   'South' -> 'the South'
'New York Times' -> 'The New York Times' 'Kuwaiti' -> 'Kuwait'
'Faysal' -> 'King Faysal'                'Circassians' -> 'Circassien'
'Denmark' -> 'Danish context'            'North America' -> 'North American'
'Decolonization' -> 'decolonization process'
'self-determination of peoples' -> 'Self-determination'
```

Singular/plural, definite article, adjectival form, capitalisation. **Not one is
a semantic error.** The pass is not confusing two different things; it is
re-electing which of two spellings of the same thing gets to name the page.

## The one mechanism that could have made this matter, checked

A small movement still matters if it pushes a page out of the productive band.
Three of the 15 affected pages do fall out of the descriptive 30–200 notes /
5-source band:

| page | before | after | |
|---|---|---|---|
| `Catholicism` | 48 notes / 15 sources | splits into 27 + 21 | both halves below 30 |
| `Berbers` | 37 / 9 | 24 / 6 | below 30 |
| `Faysal` | 81 / 5 | 77 / 4 | below 5 sources |

**None of them stops producing output.** The 30–200/5+ band is a measured
description of where good output has come from, not a gate in code. The only
hard gate is `gather.min_members: 10`, and every split half clears it — 27 and 21
both get gathered. `Catholicism` becoming two pages instead of one is a real if
minor quality loss, and it is one case in 150.

## Decision

**Accepted, not filed.** #695 closed. The 19.3% flip rate at 3+ members is real
and stands as the reproducibility floor for the name layer; what this run
establishes is that it does not reach the material. Do not re-open on the flip
rate alone — re-open only on evidence that a flip changed what a page *says*.

## Prior arms in this issue, for the record

| arm | result |
|---|---|
| temperature 0 vs 1, 150 batches, $0.13 | 14.7% vs 13.3% — temperature is **not** the cause |
| escalation as an ambiguity proxy, free | 18.5% vs 13.0%, z=1.06 — **not** significant |
| usable-band impact, $0.055 | **0.43%** of material — below the 5% bar |

Total spend on #695: **$0.19**.
