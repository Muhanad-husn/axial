# Run: the re-formed map build (slice 04, issue #829)

## Command

```
PYTHONPATH=D:/axial-wt/04-reformed-build-groups/src
AXIAL_SECRETS_PATH=secrets/secrets.toml
uv run axial map build --grouping category
```

Run in the main checkout `D:/axial` (the worktree has no `data/`), detached via
`Start-Process`, branch code at `9c1fcc1`. The console log's second line records
`CODE FROM: D:\axial-wt\04-reformed-build-groups\src\axial\__init__.py`, so the
run is pinned to the branch, not to `main`.

- Started 2026-08-29 04:51:53 +02:00, finished 05:33:02. Wall time 2,466s (41m).
- Run-context artifacts: `data/logs/map-build-20260829T025155Z/`.
- Console transcript copied here as `run-console.log`.

## What was built

`data/map/9b796b3a6312b329-category/` — reads.jsonl, positions.jsonl, map.json,
bag_state.json. No relations stage (out of scope, slice 07), so no
relations.jsonl and no `relations` block in the manifest.

**The manifest was regenerated after the review fixes, for $0.** The paid
pass wrote it under `9c1fcc1`, before review renamed the grouping-unit count
from `bags` to `groups` under category grouping and added
`passages_in_failed_reads`. Rather than leave slice 06 reading an artifact
whose keys no longer match the code that reads them, the same command was run
again on 2026-08-29 at 05:57: it resumed all 226 reads from the ledger, made
no model call, took 34s, and rewrote `map.json` under the current code.
`positions.jsonl`, `reads.jsonl` and `bag_state.json` came back byte-identical
to the paid run, which is also the strongest evidence available that the merge
is deterministic given the same ledger.

**The cost of the paid pass lives here, not in the manifest.** A resume records
`cost_usd: null` and its own 34s wall time, because it spent nothing — so the
regenerated manifest no longer carries the paid figures. They are $0.7052 and
2,466s, recorded in this log and in PR #844, and nowhere else. This is a
general trap, not a quirk of this run: **any** resume of **any** build
overwrites that build's recorded cost with `null`, including the default
build's. Worth its own issue.

The regenerated manifest's passage arithmetic closes to the residue this log
names below: 6,010 selected − 17 ungrouped − 5,497 placed − 457 declined −
31 in failed reads = 8 unaccounted.

## Counts

| | default build | variant (category) |
|---|---|---|
| grouping units | 660 wording bags | 176 category groups |
| reads | 679 | 226 |
| median passages shown per read | 3 | 20 |
| passages selected | 6,010 | 6,010 |
| passages ungrouped | n/a | 17 (0.28%) |
| raw positions | 2,206 | 2,036 |
| merged positions | 1,937 | 1,668 |
| singleton positions | 763 | 631 |
| median / max position size | 2 / 48 | 2 / 73 |
| distinct passages placed | 5,596 | 5,497 |
| declined by the model (`unassigned`) | 373 | 457 |
| failed reads | 3 | 2 |
| cost | $0.87 (pin 3c49f2e5) | **$0.7052** |

The 176 groups are 167 `claim x mechanism` cells plus 9 claim-only cells
holding 780 passages, exactly as the offline dry run projected before the pass
was paid for. `units_reused: 0` — no prior-pin seeding, confirmed both in the
manifest and by the console line `reads to make this run: 226 of 226`.

## The default build is untouched

Every file under `data/map/9b796b3a6312b329/` still carries its 2026-08-05 /
2026-08-06 mtime. Nothing in that directory was written today. Byte-identity
itself is asserted in the acceptance test, which hashes the directory either
side of a variant build.

## Outliers

- **Two failed reads, 31 passages, both retriable.** One model response came
  back as markdown headings instead of JSON
  (`critique-of-existing-theories-or-concepts::institutional-path-dependence-and-state-capacity`,
  17 passages shown); one exceeded the 600s wall-clock deadline on attempt 3/3
  (`characterization-of-regime-movement-or-system::territorial-control-and-conflict-dynamics`,
  14 passages shown). **Deliberately not retried.** The default build carries
  3 failed reads of its own into #831's D4 baseline; retrying only the
  variant's would hand it an advantage the comparison did not grant the other
  side.
- **Passages reaching no position: 513 of 6,010 = 8.54%**, against #831's D4
  bar of 6.9%. Composition: **457 declined by the extraction model + 17 never
  grouped + 31 shown in the two failed reads + 8 unaccounted** = 513. Those 8
  were shown to the model, appear in no position, and were not counted
  `unassigned`. The default build has the same residue: 414 missing (6,010
  selected − 5,596 placed) against 373 declined and ~9 passages in its 3
  failed reads (estimated at its median 3 shown per read), so roughly 32
  unaccounted there. The leak is pre-existing and is not this slice's to
  close; #831 should read both columns knowing it exists on both sides.
  The fallback did its job — only
  0.28% went ungrouped against the 13.3% that a no-fallback build would have
  lost — so the gap is not a coverage artifact of the grouping. It is the
  extraction model declining more passages when it is shown 20 at a time
  instead of 3 (`unassigned` 457 vs 373). Whether that fails the variant, or
  fails D4 as a guard, is slice 06's (#831) verdict, not this slice's.
- Largest group is 248 passages (`causal-argument-state-formation-or-power::war-and-state-formation`),
  five extraction slices. Fragmentation across those slices is expected here
  and is what slice 05's consolidation pass exists to reunite.

## Next steps

1. PR for #829 (`safe-pr`), founder approval, merge.
2. Slice 05 (#830): the consolidation pass over each category's groups.
3. Slice 06 (#831): `map compare` reads this directory against
   `data/map/9b796b3a6312b329/` and decides D1-D5. Note that a bare
   `axial map purity` / `map grouping-report` still resolves the **default**
   build; reading the variant needs `--pin 9b796b3a6312b329-category`.
4. **Slice 06: take `passages_selected` from `map.json`, never from
   `bag_state.json`.** The variant's bag state records what was *assigned to a
   group*, so its `assignments` key count is 5,993 — the 17 ungrouped passages
   never entered it — and `map grouping-report --pin
   9b796b3a6312b329-category` prints `passages (selected, this pin): 5993` for
   the same reason. D4 is counted against the honest 6,010 in `map.json`;
   deriving "selected" from the bag state understates the loss.
