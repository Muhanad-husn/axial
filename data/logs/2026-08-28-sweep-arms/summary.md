# Sweep arms, real-corpus validation for #808

**Run:** 2026-08-28, `D:/axial` at detached `29255b0`, then `dd278b8` after
the fix below. Branch `feat/derived-vocabulary/04-the-sweep-runs-the-map-arm`.

**Commands** (both detached, `AXIAL_SECRETS_PATH=secrets/secrets.toml`; the
ambient value points at the container path `/secrets/secrets.toml` and every
model call dies without the override):

```
uv run axial brief sweep data/logs/2026-08-28-sweep-arms/worklist.txt \
  --draws 1 --sweep-dir data/runs/808-arm-name --workers 1 --arm name
uv run axial brief sweep data/logs/2026-08-28-sweep-arms/worklist.txt \
  --draws 1 --sweep-dir data/runs/808-arm-map  --workers 1 --arm map
```

Worklist: one brief, `config/briefs/smoke/S-03.yaml`, the cheapest of the
smoke set in the last recorded sweep.

**Cost:** $0.1821, one draw. The map arm failed at 66.8s having spent three
calls; the refusal check and the resume both cost nothing.

## What the runs establish

| check | result |
|---|---|
| name arm runs the name-layer loop | 14-turn retrieval loop, OK in 690.4s, all four gates PASS |
| map arm takes a different path | went straight to "retrieving evidence through the argument map", no retrieval turns |
| each draw's record names its arm | `"arm": "name"` / `"arm": "map"` on the persisted draw |
| the summary names arm and commit | `"arm"`, `"commit": "dd278b8a…"` |
| resuming under a different arm is refused | refused, exit 1, naming the arm already there |
| a resume re-scores without re-spending | second run skipped the draw, zero model calls |

The refusal, verbatim:

```
error: data\runs\808-arm-name already holds draws for arm 'name'; refusing to
run arm 'map' in the same directory
```

## The map arm could not complete, for a reason that is not this change

```
no raw source file found for source_id 'beshara-2011-8410a9059300' under
data\sources (looked for .docx, .pdf)
```

`data/chunks/` holds 35 ingested sources; `data/sources/` holds 34. The map
arm computes the corpus pin, which hashes every ingested source's raw file;
the name arm never computes it. So one missing raw file takes down the map arm
alone. Filed as #816 with two remedies and no action taken — the choice moves
the corpus pin either way.

The failed draw is still evidence for this issue: it proves the two arms take
different paths, since the name arm on the same brief ran to completion.

## One defect the paid run caught that the green suite did not

`_distinct_sources_cited` type-checked `source_usage["sources"]` as a dict and
returned `None` for anything else. §7.13 writes it as a **list**, so the field
was `None` on every real draw — the one field #809 reads per arm. Two unit
fixtures asserted the invented dict shape, which is exactly why 2,464 passing
tests said nothing.

Found by reading the persisted summary of an OK draw that cited four sources
and recorded `"distinct_sources_cited": null`. Fixed in `dd278b8`, fixtures
corrected to the real shape, and verified against that same record, which now
reads 4. The resume regenerated `summary.json` at no cost.

## Next

- #816 decided before any map-arm draw is attempted again.
- #809 reads `summary.json` per arm; both fields it needs are present.
