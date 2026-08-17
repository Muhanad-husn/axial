# Slice 01 — `passage` becomes the default citation mode

Issue: #785. Feature slug: `785-passage-default`.

## Goal

A fresh install with no environment configuration resolves to `passage`, so
the reader-facing answer quotes the book it argues from. `locator` stays a
fully supported deployer choice through the same environment variable,
enforced at the same API boundary.

## Acceptance criterion

**Given** no `AXIAL_CITATION_MODE` in the environment and a vault holding the
cited chunks,
**When** an answer record is served through `GET /asks/{id}/paper` and
rendered for the reader,
**Then** each claim carries the quoted passage that grounds it, under that
claim; and setting `AXIAL_CITATION_MODE=locator` returns the same answer with
no quoted text at all.

## Scope

1. `resolve_citation_mode` returns `PASSAGE` when the variable is unset or
   blank (`src/axial/service/citation.py:83`).
2. Remove the "safe unconfigured" framing from `citation.py`,
   `service/api.py`, `answer/record.py:513`, `paper/record.py:355` and
   `docs/service-citation-mode.md`. The modes stay documented as a deployer
   choice with the exposure stated plainly.
3. Reader render already places a quote under the claim it grounds
   (`answer/reader.py:_quote_lines`, shipped in #783). Nothing to build — an
   acceptance test proves it now fires by default.
4. Report the `rendered_word_count` shift over `data/analyses/*.json`, before
   and after, into the run log.
5. `docs/DECISIONS.md` — DEC entry recording the ruling and superseding
   DEC-65's copyright half.

## Out of scope

- `data/` staying gitignored (DEC-23) and the reviewer-packet seal
  (PHASE-C.md §7.7). Neither costs output quality; #785 says so explicitly.
- The essay shape (#784), readable citations in markdown (#786), venue and
  house style (#787).

## The hazard comment, checked before any code

`#785`'s second comment says the flip moves three things beyond the reader
default: the sealed reviewer packet, the instant-dismissal judge, and
`rendered_word_count`. **All three are unaffected.** Read the call graph:

- Citation resolution happens in exactly three places, and every one of them
  works on a *copy*: `service/api.py:610` (a record freshly parsed from JSON
  for one response), `answer/record.py:526` and `paper/record.py:364` (both
  `copy.deepcopy(record)`). The record object every other consumer holds
  never gains a `citation` key.
- `panel/packet.py:173`, `answer/dismissal.py:141` and
  `run_report.py:681` all call `render_markdown(record)` on that unresolved
  record. `render_markdown` prints a quote only when `citation.quote` is
  already present, so all three render identically in either mode.
- The packet was never starved: `build_packet` resolves the full chunk text
  itself into `ReviewPacket.evidence` (`packet.py:104`,
  `get_chunk(...).chunk_text`), which is what DEC-40 asks for. It does not
  read the citation mode, transitively or otherwise.

So the recommendation to pin the packet and the judge to an explicit mode
would add a parameter nothing reads — an abstraction with one implementation.
Not done. Instead a regression test pins the *fact*: `render_markdown` of a
record is byte-identical under both modes, and the empirical run over the 19
records confirms `rendered_word_count` does not move.

## Unit test list

- [x] `resolve_citation_mode()` returns `passage` on an empty environment.
- [x] `resolve_citation_mode()` returns `passage` when the variable is blank.
- [x] `resolve_citation_mode()` still returns `locator` when set to it.
- [x] An explicit argument still wins over the environment.
- [x] An unrecognised value still raises `InvalidCitationModeError`.
- [x] `persist_markdown` with no environment set writes a quote.
- [x] `persist_markdown` under `locator` still writes no book text.
- [x] `build_packet` is byte-identical under both modes and unconfigured
      (the packet / judge / word-count regression pin).
- [x] `create_app` with no environment set serves `citation.quote`.

## Acceptance test

`tests/service/` — drive `GET /asks/{id}/paper` through the real app with a
vault fixture and no `AXIAL_CITATION_MODE`, assert `citation.quote` is
present, then render for the reader and assert the quote sits under its
claim. Same app with `AXIAL_CITATION_MODE=locator` asserts no quote.

## Definition of done

- [x] Acceptance test green (19 passed in `tests/service`, against a real
      Postgres container).
- [x] `uv run pytest` green (2,470 in ~40s); `uv run ruff check` clean.
- [x] Word-count before/after reported in
      `data/logs/2026-08-17-785-citation-default-flip/`.
- [x] DEC-72 landed.
- [x] Docs carry no safety-default framing.

## Status log

- Read the call graph before writing code: the hazard filed on #785 says the
  flip moves the reviewer packet, the dismissal judge and
  `rendered_word_count`. It moves none of them — all three render the raw
  record, and all three resolution call sites work on copies. Measured, not
  argued: `rendered_word_count` is 31,579 in both modes across the 19
  records. No packet/judge parameter added; a regression test pins it.
- Acceptance test watched red through `GET /asks/{id}/export` with the
  default flip stashed, then green with it restored.
- `AXIAL_CITATION_MODE=` (blank) used to raise at startup despite the
  docstring promising it behaved as unset. Now it resolves to the default.
- The reader-facing answer grows ×22 (26,585 → 585,711 words over 19
  records). That is correct per this issue and is the case for #784.
