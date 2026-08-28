# Vocabulary build, real-corpus validation for #806

**Run:** 2026-08-28, `D:/axial` at detached `236e339`, branch
`feat/derived-vocabulary/02-a-derived-vocabulary-is-persisted`.
`AXIAL_SECRETS_PATH=secrets/secrets.toml` on every command — the ambient value
points at the container path and every model call dies without the override.

## The three acceptance clauses, each measured

### 1. A first build assigns every answered value

```
uv run axial vocabulary build --columns mechanism
```

5,871 answered values, 971 excluded as abstention or empty. **5,315 assigned,
556 refused, 0 unanswered.** 59 calls, **$0.0633**, **1 minute 51 seconds** of
wall clock. Scheme `2026-08-28-mechanism-v1`, answers pin `417777fd2373b7e6`.

**Effective concurrency 10.0 on 12 workers** — 1,110.2s of summed per-call
elapsed over 111s of wall clock, per-call 7.7s to 79.8s. Measured, not read off
`--workers`. The issue budgeted "roughly $0.08 and twenty minutes"; the twenty
minutes was a budget, and an earlier draft of this log restated it as if it had
been measured.

All 20 categories reach 5 members and 2 sources. The largest,
`ideological-persuasion-and-legitimation`, holds **11.7%** of assigned values
across 30 sources.

Against slice 01's held-out estimate: assignment 88.5% predicted, **90.5%**
actual. Largest category 8.0% predicted, **11.7%** actual — bigger than the
400-value sample suggested, still far under the share that failed four other
columns.

### 2. A second build on unchanged input reuses

```
REUSED: the scheme version and the answers pin are both unchanged
-- 0 model call(s), nothing re-assigned
```

**3.9 seconds, zero calls.** `assignments.jsonl` is byte-identical by hash and
its mtime never moved — the file was not rewritten, not even with the same
content.

### 3. A further source's answers assign only themselves

Run at small scale so the clause is measured rather than argued: build against
3 sources' answers, then add a 4th (`agamben-2005`) and build again into the
same artifact.

```
built: 48 newly assigned, 142 reused from the previous build
model: deepseek/deepseek-v4-flash (1 call(s), cost $0.0008)
```

All 142 lines from the first build are present verbatim in the second, and
every one of the 48 new lines belongs to `agamben-2005`. Adding a source costs
that source and nothing else — the failure mode #623 measured on merge, where
93% of the spend went on books already ingested, does not recur here.

Artifacts: `answers-3/`, `answers-4/`, `vocab-incr/`,
`assignments-before-incr.jsonl` in this directory.

## What is on disk

`data/vocabulary/mechanism/assignments.jsonl` — 5,871 lines, one per answered
value, sorted, keys sorted. `data/vocabulary/mechanism/manifest.json` —
written last, so a directory without one was never a completed build.

## Not measured here

A scheme version change. The build refuses it, naming both versions, rather
than re-assigning; that choice is flagged in the pull request because the
issue's Mechanism section reads the other way.
