# Run: map rebuild after the #697 backfill

Founder-requested rebuild, fastest path. It cost nothing and reproduced the
existing map exactly — which is the direct evidence that the `position`
backfill does not reach the argument map.

## Command

```
.venv/Scripts/axial map build --workers 40
```

No `--force`: the pin is computed over raw source content only
(`build.py:compute_corpus_pin`), and the backfill touched no sources, so the
pin was unchanged and every read ledger resumed.

## Counts

| | |
|---|---:|
| corpus pin | `9b796b3a6312b329` (unchanged) |
| passages selected | 6,010 |
| authors | 28 |
| bags | 660 |
| extraction reads | 679 |
| **`units_asked`** | **0** — all 679 reused |
| raw → merged positions | 2,206 → 1,937 |
| passages placed / unassigned | 6,070 / 373 |
| relation neighbourhoods | 340 |
| relations asserted / pairs possible | 1,472 / 5,707 |
| distinct relation labels | 504 |
| cross-author relations | 629 |
| dropped relations | 0 |
| **model calls** | **0** |
| **billed** | **$0** |
| wall clock | 157s |

## Why it was free, and why the output is identical

`argmap` selects on `claim` and `_SILENT_KEYS`, and `position` is deliberately
excluded from that list (`build.py:238-254`, #697's own reasoning). Bagging is
on claim text; extraction renders `[p7] <claim>` and nothing else. The backfill
patched `position`/`position_nearest` only and left `position_of` alone, so
every slice's `members_key` was unchanged and the whole ledger resumed.

`positions.jsonl` came out at 1,592,149 bytes and `relations.jsonl` at 366,204
— the same sizes as before the rebuild. `reads.jsonl` and
`relation_reads.jsonl` were not rewritten at all.

## Outliers

**3 failed extraction reads and 1 failed relation read** are baked into the
reused ledgers and carried over from the original 2026-08-05 build. A plain
resume will never retry them; clearing them needs `--force`, which re-reads
everything at full cost.

## Open, from `build.py`'s own comment

`_SILENT_KEYS` says to revisit adding `position` to the silence test now that
the backfill has run and `is_abstention(None)` can no longer fail open. That
change *would* move the map. It has not been made.
