# Run: corpus-shape-35

Re-measure the corpus distribution report at 35 sources, and diff it against 31.

## Command

```
uv run python scratchpad/coverage_counts.py --out shape-35.json
uv run python scratchpad/coverage_counts.py --exclude gelvin-1998 gould-2003 \
    hinnebusch-1990 wedeen-2019 --out shape-31.json
# both repeated with --back-matter exclude
```

No model calls. Counted from `data/vault/notes.db` (built 2026-08-05 23:17).

## Counts

| Arm | Sources | Passages | Pages | Mentions | Meet the bar |
|---|---:|---:|---:|---:|---:|
| 35 books | 35 | 6,842 | 47,584 | 137,276 | 329 |
| 31 books (recounted today) | 31 | 6,148 | 43,874 | 123,981 | 306 |
| 35 books, no back matter | 35 | 6,319 | 42,026 | 122,420 | 315 |
| 31 books, no back matter | 31 | 5,651 | 38,384 | 109,636 | 290 |

New sources: gelvin-1998, gould-2003, hinnebusch-1990, wedeen-2019.

## Outliers and gotchas

- **The published v1.0 baseline is not comparable.** v1.0 printed 49,674 pages
  for 31 books; recounting the same 31 books out of today's index gives 43,874,
  11.7% fewer. The index was rebuilt since (#642 fold, #677 merge changes) and
  Works alone dropped 29%. The diff therefore compares 31-recounted-today against
  35, not against the printed tables.
- **`note_names.kind` is per-mention and disagrees with the `names` table on a
  couple of hundred pages.** First-seen kind put *nationalism* and *capitalism*
  outside the concept table entirely. The `names` table is the page's kind of
  record and matches `names.jsonl` exactly (0 mismatches over 47,584 rows).
- Six pages left the research band by passing 200 passages, not by losing books.
  On the Syria material the ceiling now binds, not the floor.
- 34.5% of the pages the four books touch already existed; by mention it is 67.4%
  (Hinnebusch) down to 45.5% (Gould).

## Output

- `data/reports/axial-coverage-v2.md` — the 35-book report
- `data/reports/axial-coverage-v1-to-v2-diff.md` — the diff
- `data/reports/axial-coverage.md` — v1.0, left in place
- `scratchpad/coverage_counts.py` — the instrument, copied here

## Next steps

- The three concept-level gaps v1.0 named are untouched: sovereignty, a critic of
  Mann, an answer to Chouliaraki and Agamben. Next addition should not be Syria.
- Consider whether the 200-passage ceiling should be raised or replaced now that
  real pages are exiting through it.
