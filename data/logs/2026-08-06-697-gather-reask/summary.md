# Run: 697 Gather re-ask (forced)

A deliberate full re-ask of every qualifying name page against the packets the
#697 backfill changed. **Not** something the backfill triggered on its own —
#678 keys the checkpoint on a name's source set, and the backfill moved no
page's source set, so an ordinary `gather` would have re-asked **zero** pages.
Founder chose the forced re-ask so the new stance sentences would actually
reach the disagreements.

## Command

```
mv data/names/disagreements.jsonl <this dir>/disagreements-before.jsonl
.venv/Scripts/axial names gather          # workers 48 (default)
```

Relaunched once by `gather-retry.sh` after a crash; see Outliers.

## Counts

| | |
|---|---:|
| names seen | 47,584 |
| skipped, single member | 32,447 |
| skipped, below `min_gather_members` (10) | 13,289 |
| **names gathered** | **1,848** |
| asked, attempt 1 (crashed) | 1,148 |
| asked, attempt 2 | 700 |
| failed | 0 |
| `units_asked_touching_new` | 0 |
| batch calls | 1,247 |
| merge calls | 48 |
| vault pages written | 634 |
| model calls, both attempts | 4,525 |
| prompt / completion tokens | 12,461,828 / 11,394,831 |
| model | `deepseek/deepseek-v4-flash` |
| **billed** | **$4.94** |

Every one of the 1,848 pages was re-asked. Attempt 2's `reused: 1148` counts
attempt 1's own completed work, not stale findings.

## Outliers

- **Attempt 1 died at 55 minutes** on `transient provider fault:
  finish_reason='error'`, after one `deadline_exceeded` at 600s that the retry
  logic did absorb. 1,148 records had already been written and resumed for
  free. `gather-retry.sh` was added to relaunch on failure; attempt 2 ran clean.
- **Cost was 4x the $1.25 quoted from a prior full pass.** Completion tokens
  ran nearly equal to prompt tokens (11.4M vs 12.5M), which the older figure
  didn't carry. Do not re-quote $1.25.
- **Workers are per-name, so hub pages serialise.** `Syria` took 2,280s for 46
  batches, `Iraq` 2,335s for 17, `United Kingdom` 1,548s for 33 — each sitting
  in one of the 48 slots while short names churned through the rest. The hubs,
  not the volume, set the wall clock.
- **`disagreements.jsonl` went from 5,552 records to 1,848.** Not a loss: the
  old file had accumulated records across earlier corpus states, and only
  1,848 names currently clear the 10-member floor (DEC-53). The extra 3,704
  were orphans for names that no longer qualify or no longer exist after
  merging. Original kept as `disagreements-before.jsonl`.

## Not measured

Whether the findings actually changed, and how much. #700 measured Gather at
**36.1% non-reproducible on byte-identical input** for recorded disagreements,
so any before/after comparison needs a margin wider than that to mean anything.
`disagreements-before.jsonl` is kept for whoever wants to try.
