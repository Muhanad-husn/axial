# Slice 03: Artifact pass consumes the router; captions attach to their figure/table

- **Feature:** source-router
- **Slice slug:** artifact-caption-routing
- **GitHub issue:** #168
- **Branch:** feat/source-router/03-artifact-caption-routing
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

The artifact pass (`run_artifacts`) collects artifact-routed blocks **via the router**:
`table` and `picture` become vault artifact notes as today, and each `caption` block
**attaches to its figure/table** (its text rides on that artifact note rather than being
lost or chunked). Apparatus-routed blocks (`document_index`, `footnote`, page heads/feet)
are **never** picked up as artifacts. This completes the caption's journey: slice 02 took it
out of the prose path; this slice delivers it to the artifact note.

## INVEST check

- **Independent:** consumes slice 02's router; changes only `artifacts.py`'s node collection
  (which blocks it treats as artifacts, and caption attachment). The chunk stage is untouched.
- **Valuable:** caption text is preserved on the artifact it describes (not silently dropped
  between 02 and now), and the acceptance clause "the figure becomes a vault artifact note"
  holds with its caption intact. Apparatus is provably absent from artifact notes.
- **Small-ish (M):** swap `_artifact_nodes_with_section`'s raw `type=="artifact"` scan for the
  router's artifact route, plus a caption-to-figure/table attachment step (adjacency in reading
  order / shared enclosing section).
- **Testable:** run `axial artifacts` on a tree with a captioned figure, a table, a TOC, and an
  endnotes section; assert one artifact note per figure/table, the figure's note carries the
  caption text, and no artifact note is produced for the TOC or endnotes.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a persisted tree with a captioned figure, a table, a table-of-contents (document_index),
      and an endnotes (footnote) section
When   the operator runs `axial artifacts` on the source
Then   the figure and the table each become one vault artifact note (artifact_role / provenance)
And    the figure's artifact note carries its caption text (the caption attached, not lost)
And    no artifact note is produced for the document_index or the footnote blocks
And    the caption is absent from data/chunks/<source_id>.jsonl (established in slice 02, still true)
```

- **Boundary / endpoint:** the `axial artifacts` CLI pass
- **Outer test type:** pytest integration test (fabricated persisted tree; stub LLM; no network)
- **Outer test file (planned):** tests/test_source_router.py (extend) or tests/test_artifacts.py — test-author, red, locked

## Inner loop — initial unit test list

- `run_artifacts` collects blocks whose router route is `artifact` (was: raw `type=="artifact"`);
  `table`/`picture` still collected, apparatus never collected.
- A `caption` block is associated with its figure/table (adjacency in reading order, or shared
  enclosing section) and its text is carried onto that artifact's note/record.
- A `caption` with no resolvable figure/table nearby: defined fallback (attach to nearest prior
  artifact, else emit as a standalone artifact note — never chunk it, never crash).
- An apparatus block that happens to sit among artifacts is not routed to the artifact pass.
- Existing artifact classification (role, provenance, `cited_by`) is unchanged for table/picture.

## Out of scope (this slice)

- **Retiring the per-pass gate + examine reading router drops** — slice 04.
- **Re-scoring / re-classifying artifacts** — role taxonomy and `cited_by` logic unchanged.
- **The chunk stage** — unchanged from slice 02.

## Notes

- Today `artifacts._artifact_nodes_with_section` scans raw `type=="artifact"` nodes; captions
  (`type=prose`) are invisible to it, which is exactly why caption text is lost without this
  slice. Routing captions to `artifact` (slice 02) plus attaching them here closes that gap.
- Caption→figure attachment is the one genuinely new mechanism; keep it simple (reading-order
  adjacency within a section) per the 80/20 principle. If robust attachment proves fiddly, the
  fallback (standalone caption artifact note) still preserves the text — the invariant is
  "caption text is never lost and never chunked."
- Land close behind slice 02 so no shipped state drops caption text.
