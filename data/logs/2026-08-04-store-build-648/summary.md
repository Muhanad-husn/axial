# Building the relational store over the live corpus (#648)

2026-08-04. Main checkout `D:/axial`. HEAD `5dba321` — PR #654 (the store) and
PR #655 (#653's atomic-write retry) both merged. No model calls; materialize
reads only already-persisted artifacts.

    uv run axial names materialize   # console.log

## Counts

| Field | Value |
|---|---|
| sources | 31 |
| notes_written | 6,148 |
| artifact_notes_written | 910 |
| name_pages | 49,555 (0 written, 0 deleted — unchanged from the #646 rollout) |
| store_notes | 6,148 |
| store_note_names | 140,596 |
| store_note_citations | 32,796 |
| store_note_arguing_against | 12,743 |
| `data/vault/notes.db` | 54 MB |

## Spot checks against production

| Check | Store | Expected |
|---|---|---|
| `French Mandate` | 55 notes / 8 sources | 55 / 8 (#632's door slate) |
| `Renaissance` | 24 notes / 12 sources | 24 / 12 (the #646 rollout) |
| `section` non-null | 6,148 of 6,148 | every prose note carries one |
| `chapter` non-null | 3,785 of 6,148 (61.6%) | NULL on 2,363 — exactly the offline measurement on #648 |
| opposition rows resolving to a canonical | 6,897 of 12,743 (54.1%) | the honest join rate; NULL stays countable |

The `chapter` NULL count reproduces the founder's offline figure to the note,
which is the strongest available evidence that the store derives it with the
same `chapter_for_section` the note pages use rather than a second
implementation.

## Note on the opposition denominator

12,743 rows here against the 10,897 distinct (note, target) pairs in
`2026-08-04-relational-join-ceiling/`. The store keeps one row per target per
note including the unresolved ones and does not collapse a target that resolves
to more than one canonical; the earlier measurement counted distinct pairs. The
44.0% conservative join rate in that log is the figure to quote for *targets*,
not the 54.1% row rate above.

## Next

- #650 (retrieval walks the relations) and #651 (the 56% semantic residue) are
  the open consumers. Nothing reads `notes.db` yet.
