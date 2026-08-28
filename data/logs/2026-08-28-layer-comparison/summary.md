# Layer comparison — three retrieval arms, five briefs, three draws

**Issue:** [#809](https://github.com/Muhanad-husn/axial/issues/809), slice 05 of
derived-vocabulary. **Commit:** `b18f95b8a4d1e8298540687c054699ac682c5386`
(`main`, all three arms). **Run date:** 2026-08-28.

## What was run

| Arm | Sweep directory | Retrieval path |
|---|---|---|
| `name` | `data/runs/809-arm-name` | the name-layer loop |
| `map` | `data/runs/809-arm-map` | the argument map (#572) |
| `map+vocab` | `data/runs/809-arm-map-vocab` | the argument map plus the derived join (#807), `mechanism` column |

Worklist: `worklist.txt` in this directory — the five-brief smoke set,
`config/briefs/smoke/S-01..S-05.yaml`. Draws: 3 per brief per arm. Total 45
runs. Sweep workers: 3 per arm; the three arms ran concurrently.

A one-brief, one-draw preflight ran first on each arm (`worklist-preflight.txt`,
S-03 only) to prove all three arms reach a record before spending the hour. Its
draws resume into the full run rather than being thrown away, so it cost nothing
extra beyond a second gate scoring of S-03.

## Commands

```
# preflight, per arm
AXIAL_SECRETS_PATH=secrets/secrets.toml uv run axial brief sweep \
  data/logs/2026-08-28-layer-comparison/worklist-preflight.txt \
  --draws 1 --sweep-dir data/runs/809-arm-<slug> --arm <arm> --workers 1

# the full sweep, per arm
AXIAL_SECRETS_PATH=secrets/secrets.toml uv run axial brief sweep \
  data/logs/2026-08-28-layer-comparison/worklist.txt \
  --draws 3 --sweep-dir data/runs/809-arm-<slug> --arm <arm> --workers 3

# the comparison
uv run axial eval layers \
  --arm-dir data/runs/809-arm-name \
  --arm-dir data/runs/809-arm-map \
  --arm-dir data/runs/809-arm-map-vocab
```

`AXIAL_SECRETS_PATH` is overridden on every command: the ambient value in this
shell is the container path `/secrets/secrets.toml`, which makes every model
call die with "no API key was found".

## The two questions

- `name` against `map`: does the argument map beat the name layer?
- `map` against `map+vocab`: does the derived vocabulary add anything?

The second is what this feature exists to answer. The command prints both
comparisons and answers neither. The founder does.

## Two known misreadings

Both are on the record and both would be easy to repeat by eye.

- **A drop in sources cited is not a regression.** The argument map was
  validated at *strong* grounding against the name layer's *adequate*, on four
  sources against eight.
- **A margin narrower than the model's own variance is not a finding.** Gather
  does not reproduce 36.1% of its recorded disagreements on byte-identical
  input (#700); merge disagrees with itself at 13.3% on groups of three or more
  (#695). Every figure carries its draw spread so this cannot be missed.

One more, specific to this table: **`map+vocab` carries one column's worth of
join**, `mechanism`, per #806. A null result rules out a `mechanism` join, not
the idea.

## Results

45 draws attempted, 45 landed, 0 failures. The one `SKIP` per arm is that
arm's preflight draw, already on disk and resumed rather than re-asked.

```
layer comparison: 3 arms (name, map, map+vocab), 5 briefs, 3 draws per brief per arm, all at commit b18f95b8a4d1e8298540687c054699ac682c5386
comparisons, in the order the arms were given: name vs map; map vs map+vocab
figures are per brief; nothing here is pooled across briefs

brief  arm        grounding  rate   gate_draws  sources  range  src_draws
-----  ---------  ---------  -----  ----------  -------  -----  ---------
S-01   name       PASS       0.923  3           6.0      4-7    3
S-01   map        PASS       1.000  3           4.7      4-5    3
S-01   map+vocab  PASS       1.000  3           4.7      4-5    3
S-02   name       PASS       1.000  3           12.3     11-13  3
S-02   map        PASS       1.000  3           8.0      6-9    3
S-02   map+vocab  PASS       1.000  3           9.3      8-10   3
S-03   name       PASS       1.000  3           3.3      3-4    3
S-03   map        PASS       1.000  3           4.7      4-5    3
S-03   map+vocab  PASS       0.941  3           6.3      5-7    3
S-04   name       PASS       1.000  3           1.0      1-1    3
S-04   map        PASS       1.000  3           1.3      1-2    3
S-04   map+vocab  PASS       1.000  3           1.0      1-1    3
S-05   name       PASS       1.000  3           1.0      1-1    3
S-05   map        FAIL       0.800  3           1.7      1-2    3
S-05   map+vocab  PASS       1.000  3           1.3      1-2    3

grounding:   the gate's verdict for that (brief, arm). The sweep scores it
             ONCE over that brief's pooled draw records, so it is one figure,
             not a per-draw mean. NOT-SCOREABLE is neither a pass nor a fail.
rate:        grounding_support_rate, the gate's own metric (specs/PHASE-B.md
             section 10). '-' where the gate reported no value.
gate_draws:  how many of that brief's draws produced a record -- the pooled
             sample the grounding figure was scored over.
sources:     distinct sources cited, averaged across that brief's own draws.
range:       min-max of that same per-draw count; src_draws is how many draws
             reported one. This is the spread, and it is per brief.
not-scored:  that sweep ran without gate scoring, so no grounding figure
             exists to read.
missing:     that brief produced no usable draw in that arm. Reported, never
             averaged over and never dropped.
```

`comparison-table.txt` in this directory is the same output, captured raw.

## Cost and clock

| Arm | Cost | Tokens | Mean draw latency |
|---|---|---|---|
| `name` | $3.1845 | 5,924,648 | 13.2 min |
| `map` | $0.9919 | 1,870,111 | 3.4 min |
| `map+vocab` | $0.9454 | 1,835,691 | 3.2 min |
| **total** | **$5.1218** | 9,630,450 | |

The slice priced this at roughly $1.90, from the recorded $0.0417 for a single
web-client ask. The real figure is 2.7x that, and nearly all of the gap is one
arm: the name layer spent $3.18 of the $5.12 and ran 4x longer per draw than
either map arm. The estimate also left out the four rung-3 gates, which are
model calls of their own, scored once per brief per arm.

Cost and latency between arms is explicitly out of scope for the decision this
table informs (#809). It is recorded because it was measured, not because it
settles anything.

Wall clock: the three arms ran concurrently, 3 workers each. Summed draw time
was 277 minutes against roughly 40 minutes of wall clock -- an effective
concurrency near 7 on 9 workers.

## Outliers and failures

- No draw failed on any arm.
- `S-05`, arm `map`: the only grounding failure in the table, 0.800. Both other
  arms pass the same brief at 1.000. One brief, one arm, three draws.
- `S-04` and `S-05` cite one source on nearly every draw of every arm. They are
  narrow briefs; the source counts there carry almost no signal.
- `S-02`, arm `name`: 12.3 sources against `map`'s 8.0 and `map+vocab`'s 9.3 --
  the largest source-count gap in the table, and the one the first misreading
  above is about.
