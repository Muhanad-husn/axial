# Run: 697 materialize

Rewrote the vault so name pages and prose notes carry the stance sentences the
#697 backfill produced, instead of the holder names `stated_position()`'s
`position_of` fallback had been handing every consumer.

## Command

```
.venv/Scripts/axial names materialize
```

Zero model calls, zero cost.

## Counts

| | |
|---|---:|
| sources | 35 |
| notes written | 6,842 |
| notes skipped (no answer record) | 18 |
| artifact notes written | 986 |
| name pages seen | 47,584 |
| name pages written | 801 |
| name pages unchanged | 46,783 |
| store: notes | 6,842 |
| store: back matter | 523 |
| store: note_names | 137,276 |
| store: note_arguing_against | 13,998 |
| store: note_citations | 35,975 |
| store: note_opposed_position | 0 |

## Outliers

- **Only 801 of 47,584 name pages changed.** Name pages don't render
  `position`; Gather's member packet does (`gather.py:472`). So the backfill
  reaches the name layer through Gather, not through this pass.
- `note_opposed_position` is 0 because no `--residue-decisions-path` was
  passed, matching the previous materialize. The current map pin
  (`9b796b3a6312b329`) has no `residue_decisions.jsonl` to fold in anyway.

## Verification

Before: `position` read as a holder name on 6,747 notes — "Giorgio Agamben",
"the author's own". After: 6,841 of 6,842 carry a stance sentence. The
pre-run values are preserved in `positions-before.jsonl`.

## Files kept

- `positions-before.jsonl` — every note's `position` as the vault held it
  before this run.
- `disagreements-before.jsonl` — copy taken before the Gather re-ask.
