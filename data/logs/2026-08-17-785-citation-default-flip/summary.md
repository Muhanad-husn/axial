# #785 — what the citation-default flip actually moves

**Date:** 2026-08-17. **Cost:** $0.00 — no model calls, no retrieval. Pure
resolution over records already on disk, per the founder's testing constraint
on this milestone.

**Command**

```
uv run python data/logs/2026-08-17-785-citation-default-flip/measure.py
```

Inputs: `data/analyses/*.json` (19 records), `data/vault/` (notes.db + prose).
Outputs: `run.jsonl` (one record per analysis), `console.log`.

## Result

| Measure | `locator` | `passage` | Move |
|---|---|---|---|
| Quotes resolved | 0 | 729 | +729 |
| Reader-render words, all 19 | 26,585 | 585,711 | **×22.03** |
| `rendered_word_count` (audit render, raw record) | 31,579 | 31,579 | **0** |

Records resolving no quote at all in `passage` mode: **0 of 19**. Every
answer in the corpus gains quoted evidence; none is left citing books it
cannot quote.

## The 22× is the finding, and it belongs to #784

38 quotes per answer on average, each a full chunk, is about **31,000 words
per answer**. Quoting under the claim is what #785 asked for and it is
correct. But a claim list with 38 full chunks bolted underneath it is not an
essay, and the size makes that unmistakable in a way the locator render hid.
#784 — "an ask must end in an essay, not a claim list" — is where the
selection happens: an essay quotes what it argues from, not everything it
cites.

Nothing here is a reason to hold #785. The material was always cited; it is
now visible.

## The hazard filed on #785 predicted three moves. None happens.

The issue's second comment warned the flip would silently change the sealed
reviewer packet, the instant-dismissal judge, and `rendered_word_count`,
because `answer/record.py:531` renders through `resolve_citation_mode()`. It
does not, and the reason is one line of call-graph:

- Citation resolution runs in exactly three places and **every one works on a
  copy**: `service/api.py:610` (a record freshly parsed from JSON for one
  response), `answer/record.py:526` and `paper/record.py:364` (both
  `copy.deepcopy(record)`). The record object every other consumer holds never
  gains a `citation` key.
- `panel/packet.py:173`, `answer/dismissal.py:141` and `run_report.py:681`
  all call `render_markdown(record)` on that unresolved record.
  `render_markdown` prints a quote only when `citation.quote` is already
  there. The 31,579 in the table above is the same number in both modes,
  measured, not argued.
- The packet was never starved either: `build_packet` resolves the full chunk
  text itself into `ReviewPacket.evidence` (`packet.py:104`), which is exactly
  what DEC-40 specifies. It does not read the citation mode, transitively or
  otherwise.

So the recommendation to pin the packet and the judge to their own explicit
mode would add a parameter nothing reads. Not done. A regression test pins the
property instead —
`src/axial/panel/test_packet.py::test_the_packet_does_not_move_with_the_deployment_citation_mode`.

## One behaviour change beyond the default

`AXIAL_CITATION_MODE=` (set but blank) used to raise
`InvalidCitationModeError` at startup, despite the docstring claiming blank
was treated as unset. It now resolves to the default, as documented. A blank
line in a `.env` file is a stated intent to configure nothing, not a typo
worth refusing to boot over.
