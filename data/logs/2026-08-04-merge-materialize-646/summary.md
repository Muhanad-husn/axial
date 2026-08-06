# Rolling #646 into the corpus of record: merge + materialize

2026-08-04. Main checkout `D:/axial` (never a worktree — `data/` is gitignored).
HEAD `99eba49`, which carries #652's `parse_merge_response` fix. No paid model
calls: merge reused every decision it already had.

## Commands

    uv run axial names merge          # merge-console.log
    uv run axial names materialize    # materialize-console.log (failed at the last step)
    uv run axial names materialize    # materialize-console-2.log (clean)

## Merge

| Field | Value |
|---|---|
| batches_total | 15,265 |
| batches_decided | 0 |
| batches_reused | 15,265 |
| batches_failed | 0 |
| complete | true |
| surface_forms | 61,612 |
| canonical_names | 49,555 |
| merged_surface_forms | 12,057 |
| escalated_surfaces | 7,608 |
| model calls | 0 |

Zero decided because the batch #646 stranded was already re-asked and recorded by
the 01:48 run on the same fixed parser; this pass confirms the log is complete and
nothing else in the 15,265 is outstanding. `merge_failures.jsonl` is untouched
since 2026-08-03 06:15 — no new failures.

### The #646 cluster, resolved

Cluster 14076's five surfaces now partition into three nodes in
`data/names/alias_map.json`, which is exactly the answer the old parser threw
away for echoing a different `kind`:

    {"canonical": "Renaissance", "kind": "period",
     "aliases": ["Renaissance period", "the Renaissance", "the Renaissance movement"]}
    {"canonical": "cultural renaissance", "kind": "concept", "aliases": []}
    {"canonical": "post-Renaissance", "kind": "period", "aliases": []}

In the vault this is one `Renaissance` door at **24 member notes over 12
sources**, where before the fix the same passages sat behind five separate
pages, three of them singletons.

## Materialize

| Field | Value |
|---|---|
| sources | 31 |
| notes_written | 6,148 |
| notes_skipped_no_answer | 18 |
| artifact_notes_written | 910 |
| name_pages | 49,555 |
| name_pages_written | 0 (second run; the first wrote them) |
| name_pages_unchanged | 49,555 |
| name_pages_deleted | 0 |

`data/vault/names.jsonl` carries 49,555 rows, matching the alias map's canonical
count exactly. No `the Renaissance` or `the Renaissance movement` page survives.

## The one failure: the door index lost an atomic-write race

The first materialize wrote every page, then died on its last statement:

    File "D:\axial\src\axial\materialize.py", line 481, in _write_name_page_index
      atomic_write_text(path, text)
    File "D:\axial\src\axial\paths.py", line 219, in atomic_write_text
      os.replace(tmp_name, path)
    PermissionError: [WinError 5] Access is denied:
      'D:\axial\data\vault\.names.jsonl.zpw7f0ck.tmp' -> 'data\vault\names.jsonl'

Cause: a second process held `names.jsonl` open at that moment (a #648 builder
spot-check querying the live vault, which rebuilds the index when it looks
stale). On Windows `os.replace` fails outright if any handle is open on the
destination without `FILE_SHARE_DELETE` — POSIX would have swapped it silently.

#645 made this write atomic so a *reader* never sees a truncated index. It did
not make the *writer* survive a reader. The two halves are separate problems and
only the first is fixed. Filed as its own issue.

Impact here: none that survived. The index on disk was verified complete
(49,555 rows) before the re-run, and the re-run exited 0 with everything
unchanged. But the run reported failure while the vault was in fact correct,
which is the wrong signal to give an operator.

## Next

- #648 (relational store over the notes) is in flight on
  `feat/relational-store-648`; it re-expresses `find_names`/`get_name` as SQL
  over a store built at this same materialize step.
