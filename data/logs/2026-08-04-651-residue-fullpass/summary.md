# #651 full pass: the semantic residue resolved against the argument map

2026-08-04. Founder-approved full pass, both arms, union. Run from `D:\axial`,
main at `f171d02` (PR #664). Model `deepseek/deepseek-v4-flash`, 20 workers.
Raw output: `console.log`; the fold-in: `materialize.log`; the decisions
themselves: `data/map/297bcfa93d6974b0/residue_decisions.jsonl`.

Commands:

    uv run axial map residue --workers 20
    uv run axial names materialize --residue-decisions-path data/map/297bcfa93d6974b0/residue_decisions.jsonl

## The pass

| Arm | Resolved | Calls | Reused | Wall | Cost |
|---|---|---|---|---|---|
| blocked (section-bucketed) | 610 / 5,846 (10.4%) | 5,846 | 0 | 560.9s | $0.2988 |
| unblocked (full map) | 1,115 / 5,846 (19.1%) | 5,736 | 110 | 547.0s | $0.7824 |
| **union** | **1,516 / 5,846 (25.9%)** | | | ~18.5 min | **$1.08** |

**The 100-target sample was a real estimator.** It predicted 11.0 / 19.0 /
27.0; the full corpus came in at 10.4 / 19.1 / 25.9, at 58x the scale. The
110 reused calls are the sample's own decisions, replayed from the
content-keyed log rather than re-asked.

## Coverage

Over the 10,897 distinct `(note, target)` pairs:

| Route | Pairs | Share |
|---|---|---|
| Joined to a NAME (the relational join, pre-existing) | 5,051 | 46.4% |
| Joined to a POSITION (new, this pass) | 1,504 | 13.8% |
| **Either** | **6,555** | **60.2%** |

The two routes are near-complementary: the position join adds 13.8 points on
a 46.4-point base, so almost every position match is a target the name index
never reached.

## What the edges actually are

1,881 rows in `note_opposed_position`, over **852 distinct positions**.

| | rows | share |
|---|---|---|
| Position drawn only from the opposing note's OWN book | 1,119 | 59.5% |
| Position spans other books, own book among them | 297 | 15.8% |
| Position carries none of the opposing note's own book | 465 | 24.7% |
| **Reaching at least one other book** | **762** | **40.5%** |

`self_referential` (1,416 rows, 75.3%) is a `source_id` membership test
against the matched position's own sources — deliberately conservative. It
is not the same as "useless": 297 of those 1,416 sit on positions that also
span other books, so the edge still crosses. **The honest cross-book figure
is 762 of 1,881 (40.5%)**, and the honest "this only points back at the book
it came from" figure is 1,119 (59.5%).

That share is much higher than the 100-target sample's hand-check suggested
(2 of 30 looked self-referential there, but that check was at PASSAGE level
and this flag is at SOURCE level — a stricter-sounding name for a looser
test). Anyone reading the two numbers together should not treat them as the
same measurement.

## Which arm earned its place

| mode | rows |
|---|---|
| unblocked only | 1,233 |
| blocked only | 500 |
| both | 148 |

Blocking contributed 648 rows, **500 of them found by nothing else** — the
sample's "mostly disjoint, not a nested subset" result reproduces at full
scale. Running both arms was the right call; dropping blocking would have
cost 500 edges for a saving of $0.30.

## Store state after the fold-in

    store_notes 6,148 | back_matter 497 | note_names 140,596
    note_arguing_against 12,743 | note_citations 32,796
    note_opposed_position 1,881
    name_pages 49,555 (0 written, 0 deleted)

## What this does not settle

- **No retrieval tool reads `note_opposed_position` yet.** The edges are in
  the store; nothing queries them. That is the next slice, not this one.
- **A map rebuild orphans every row here.** Position IDs are per-pin; adding
  books means re-running the pass (noted on #623 as a sequence).
- 73.9% of the residue (4,330 targets) still joins to nothing. At 31 uneven
  sources that is an accepted trade-off, not an open defect.
