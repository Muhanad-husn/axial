# Run: 697 position backfill

The one-question re-ask that put `position` on every note interrogated under
frame 0.1 (issue #697).

## Command

```
.venv/Scripts/axial position-backfill data/sources/<source>.pdf
```

Driven per source across all 35 sources by `backfill-retry.sh`; each source
also wrote its own `data/logs/position-backfill-<ts>/` run record.

## Counts

| | |
|---|---:|
| sources | 35 |
| model calls | 6,845 |
| prompt tokens | 17,182,706 |
| completion tokens | 410,081 |
| model | `openai/gpt-5.6-luna` |
| **billed** | **$1.96** |

## Acceptance (issue #697), measured 2026-08-06

| criterion | result |
|---|---|
| every answer record carries `position` | **pass** — 6,842 of 6,842, zero missing |
| abstention near the 585 notes' 6.2% | **finding** — see below |
| Gather re-asks after the backfill | **0**, as #678 predicted |

**The one-question prompt abstains 1.64x more than the same question asked
inside the full sixteen.**

| | notes | abstains |
|---|---:|---:|
| frame 0.2, never backfilled | 585 | 6.15% |
| backfilled by #697 | 6,257 | 10.07% |

#697 called this out in advance: a large gap "means the one-question prompt is
not asking the same question and is a finding, not a pass." Two caveats before
anyone acts on it — per-source rates run 0.3% (mann-v1/v3/v4) to 39.4%
(chouliaraki), so the corpus figure is sensitive to the book mix, and the
baseline is only three books.

## Outliers

- `mann-v2-1993` failed on attempt 1 and succeeded on attempt 2. No other
  source needed a retry.
- Cost came in at **$1.96 against the issue's ~$16 estimate**. The estimate
  assumed full-interrogation output volume; the real pass averaged 60
  completion tokens per call, and `gpt-5.6-luna` prices output at $0.0006/1k.

## Next steps

- The abstention gap is unowned. It needs a decision: accept it, or re-ask the
  666 abstaining notes with more context.
- `argmap/build.py`'s `_SILENT_KEYS` comment says to revisit adding `position`
  now that the backfill has run and the fail-open problem is gone. Still open.

## Downstream this run required

`data/logs/2026-08-06-697-materialize/` then
`data/logs/2026-08-06-697-gather-reask/`. The argument map did **not** need a
rebuild — see `data/logs/2026-08-06-map-rebuild/`.
