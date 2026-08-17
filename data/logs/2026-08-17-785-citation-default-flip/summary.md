# #785 — what the citation-default flip actually moves

**Date:** 2026-08-17. **Cost:** $0.00 — no model calls, no retrieval. Pure
resolution over records already on disk, per the founder's testing constraint
on this milestone.

**Command**

```
uv run python data/logs/2026-08-17-785-citation-default-flip/measure.py
```

Inputs: `data/analyses/*.json` (19 records), `data/vault/` (notes.db + prose).
Outputs: `run.jsonl` (one record per analysis), `placement-skeleton.txt`,
`console.log`.

## Result

| Measure | `locator` | `passage` | Move |
|---|---|---|---|
| Quotes resolved | 0 | 729 | +729 |
| Reader-render words, all 19 | 26,585 | 589,837 | **×22.19** |
| `rendered_word_count`, before both resolutions | 31,579 | | |
| `rendered_word_count`, after both resolutions | 31,579 | | **0** |
| Raw records that gained a `citation` key | 0 of 19 | | |

Records resolving no quote at all in `passage` mode: **0 of 19**.

The two `rendered_word_count` rows are two independent counts of the same
record object, taken before and after both resolutions run over it — not one
number printed twice. `render_markdown` takes no mode argument, so
mode-independence is true by construction; these rows confirm the production
path does not mutate the record out from under it.

## Placement, not just presence

A count of resolved quotes cannot show *where* a quote lands, and the issue's
third condition is about placement. `placement-skeleton.txt` is the reader
render of all 19 answers with every quoted passage replaced by
`[passage: N words, N lines]` — no book text, so it commits (DEC-23). Each
stand-in sits as a blockquote directly under the claim bullet it grounds.
No appendix, no trailing evidence block.

## The ×22 is the finding, and it belongs to #784

38 quotes per answer on average, each a full chunk at ~767 words, is about
**31,000 words per answer** — roughly 95% of the delivered text is block
quote. Quoting under the claim is what #785 asked for and it is correct. But
a claim list with 38 full chunks bolted underneath is not an essay, and the
size makes that unmistakable in a way the locator render hid. #784 — "an ask
must end in an essay, not a claim list" — is where the selection happens: an
essay quotes what it argues from, not everything it cites.

Nothing here is a reason to hold #785. The material was always cited; it is
now visible.

## A real defect the measurement surfaced

The first `placement-skeleton.txt` run leaked book text, and the reason was a
bug, not a bad script. `render_reader_answer` emitted a passage as a single
`  > {quote}` line. A resolved passage is a whole chunk with embedded
newlines, so **only its first paragraph was a blockquote** — every paragraph
after it rendered as ordinary body text, indistinguishable from the tool's
own prose. That is precisely the confusion the `stated` / `concluded` /
`runs past the books` markers exist to prevent, and it was invisible for as
long as the default resolved no quotes at all. Fixed: every line of a
passage now carries `>`. It is why the reader-word total is 589,837 rather
than the 585,711 measured before the fix.

## The hazard filed on #785 predicted three moves. None happens.

The issue's second comment warned the flip would silently change the sealed
reviewer packet, the instant-dismissal judge, and `rendered_word_count`,
because `answer/record.py:531` renders through `resolve_citation_mode()`. It
does not:

- Citation resolution runs in exactly three places and **every one works on a
  copy**: `service/api.py:610` (a record freshly parsed from JSON for one
  response), `answer/record.py:526` and `paper/record.py:364` (both
  `copy.deepcopy(record)`). The table's "0 of 19 gained a `citation` key"
  row is that property, checked on the real records.
- `panel/packet.py:173`, `answer/dismissal.py:141` and `run_report.py:681`
  all call `render_markdown(record)` on that unresolved record.
  `render_markdown` prints a quote only when `citation.quote` is already
  there.
- The packet was never starved either: `build_packet` resolves the full chunk
  text itself into `ReviewPacket.evidence` (`packet.py:104`), which is exactly
  what DEC-40 specifies. It does not read the citation mode, transitively or
  otherwise.

So the recommendation to pin the packet and the judge to their own explicit
mode would add a parameter nothing reads. Not done. Two regression tests pin
the property instead —
`src/axial/panel/test_packet.py::test_the_packet_does_not_move_with_the_deployment_citation_mode`
and the pre-existing
`test_passage_mode_never_mutates_the_persisted_json_record`.

## One behaviour change beyond the default

`AXIAL_CITATION_MODE="  "` (whitespace only) used to raise
`InvalidCitationModeError` at startup: the value survived the `or`, stripped
to `""`, and failed the membership check — despite the docstring promising
blank was treated as unset. It now resolves to the default. An empty value
(`AXIAL_CITATION_MODE=`) already resolved to the default before this change,
being falsy; it still does. An unrecognised value still refuses to start.
