# #661 rollout: materialize writes the back-matter flag into the live store

2026-08-04. `uv run axial names materialize` from `D:\axial`, main at
`f9ad417` (PR #662 merged). No model calls. Console: `console.log`.

## Command and counts

| Counter | Value |
|---|---|
| sources | 31 |
| notes_written | 6,148 |
| notes_skipped_no_answer | 18 |
| artifact_notes_written | 910 |
| name_pages | 49,555 |
| name_pages_written / unchanged / deleted | 0 / 49,555 / 0 |
| store_notes | 6,148 |
| **store_notes_back_matter** | **497** |
| store_note_names | 140,596 |
| store_note_arguing_against | 12,743 |
| store_note_citations | 32,796 |

497 flagged, exactly the census figure — the classifier fires identically in
the pipeline and in the offline census
(`data/logs/2026-08-04-661-backmatter-census/`). No name page changed: the
flag is an evidence-set fact, not a rendering one.

## Before / after, live anchors

Raw membership vs what now counts as evidence:

| Anchor | Before (notes / sources) | After | Delta |
|---|---|---|---|
| Syria | 962 / 22 | 867 / 22 | -95 notes (-9.9%) |
| Michael Mann | 377 / 15 | 359 / 15 | -18 |
| Charles Tilly | 154 / 20 | 140 / 20 | -14 |
| nationalism | 158 / 18 | 154 / **17** | -4 notes, -1 source |
| French Mandate | 55 / 8 | 49 / 8 | -6 |

Two things worth keeping:

- **The hub loses the most, in absolute and relative terms.** Syria drops
  9.9% against the corpus-wide 8.1%, because endnote pages are dense in
  exactly the names a hub carries.
- **A source can disappear from a concept entirely** (`nationalism`, 18 -> 17):
  its only notes carrying that name sat on back matter. That is the intended
  reading — a book whose sole contribution to a concept is an endnote was
  never covering it — but it means a source count is not comparable across
  the #661 boundary.

## Integrity check

`note_names` rows with no matching `notes` row: **0**. So `doors()`'s
`LEFT JOIN notes` cannot silently drop a member through a missing note row —
the conditional-aggregate form and a plain join agree on this corpus.

## Consequence for older numbers

Every door/member count measured before today is a raw count. Anything
compared across this boundary must be re-measured, not carried over.
