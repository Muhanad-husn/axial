# Slice 03: The reader-facing paper cites in APA

- **Feature:** 787-venue-length-house-style
- **Slice slug:** apa-citations-and-bibliography
- **Branch:** feat/787-venue-length-house-style/03-apa-citations-and-bibliography
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

In-text citations and the bibliography in the reader-facing render follow APA:
`(Bayat, 2017)` in the text, `Bayat, A. (2017). *Revolution without
revolutionaries*. Stanford University Press.` in the list.

## Current state and the exact delta

- **In-text is nearly there.** `render_reader_paper`
  (`src/axial/paper/reader.py`) already emits an author-date parenthetical:
  `(Vignal 2021; Bayat 2017)`. APA wants a comma before the year.
- **The bibliography is Chicago-shaped.** `format_bibliography_entry`
  (`src/axial/cite.py:161`) emits `Author. Title. Publisher, Year.` APA wants
  `Surname, F. M. (Year). *Title*. Publisher.` — author inverted, year
  parenthesised and moved forward, title italicised, place dropped.
- **The audit render does not change.** `src/axial/paper/render.py`'s
  field-tagged, provenance-carrying bibliography is an operator artifact.
  APA is a reader convention. Leave it alone.

## The one real hazard, and the primitive that closes it

Inverting a full name to surname-plus-initials is the whole risk in this slice.
`author_surname` is documented as deliberately crude — the last whitespace-
separated token — which was correct while it only ever fed a deterministic sort
order (§7.6 asks for a stable order, not an onomastically correct one). A sort
key that is stable and wrong costs nothing. A **printed** name that is wrong is
a reader-visible error.

The corpus makes this concrete. Measured across all 35 records in
`data/source_meta/`: **19 carry the author in natural order, 13 already
inverted, 3 put two people in one string** (`John A. Hall and Ralph
Schroeder`). Michael Mann has four records — two say `Michael Mann`, two say
`Mann, Michael`. The same author already renders two ways in one bibliography,
today, before APA touches anything.

This is not a metadata defect. §7.13 is deliberate: `author` is read from the
title page **as the document prints it**, and the filename is explicitly never
a source for it. Thirty-five books print their authors thirty-five ways and the
record is faithful to that. Nothing in the pipeline ever needed to know which
token was the surname, so nothing ever decided.

**The primitive already exists.** `src/axial/intake.py:_name_tokens` folds
diacritics away (`Siniša` → `sinisa`) and normalizes commas so `"Last, First"`
and `"First Last"` yield the same token set — written and tested for the §7.13
same-work identity guard, which §7.13 describes as treating *"diacritics and
'Last, First' vs 'First Last' order ... as the same person"*. Reuse it. Do not
add a name-parsing library and do not hand-edit the metadata records.

**Where a name cannot be confidently resolved, print the author string as
given.** That is `biblio.py`'s own never-guess rule, and it is the fallback for
the three two-person strings and anything else ambiguous. APA also already
supplies `(n.d.)` for a source with no resolved date, which fits §7.13's
three-state value / `unavailable` / `not_attempted` contract without weakening
it — an absent field still renders as a stated absence, never a blank and never
a guess.

## INVEST check

- **Independent:** shares no file with slices 01 or 02, so it may be built in
  parallel with 01.
- **Valuable:** the reader gets a bibliography that reads as a bibliography and
  names each author one consistent way.
- **Small:** two formatting functions and a name-order resolution reusing an
  existing primitive.
- **Testable:** pure functions over the record; no model call anywhere in this
  slice.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a persisted paper record citing sources whose author metadata is a mix of "First Last" and "Last, First"
When  the reader-facing paper is rendered
Then  every in-text citation reads "(Surname, Year)" with sources separated by semicolons
And   every bibliography entry reads "Surname, F. M. (Year). Title. Publisher." with the title italicised
And   the same author appearing in both metadata orders renders identically in both places
And   a source with no resolved date renders "(n.d.)" rather than a blank or an omission
And   the audit render from render_paper is byte-identical to what it produces today
```

- **Boundary / endpoint:** CLI — the reader-facing markdown written by
  `uv run axial paper draft <paper_brief_file>`
- **e2e test type:** API/integration test
- **e2e test file (planned):** `tests/paper/test_apa_reader_render.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 03-apa-citations-and-bibliography
edits: src/axial/cite.py
edits: src/axial/paper/reader.py
creates: tests/paper/test_apa_reader_render.py
creates: src/axial/test_cite_apa.py
```

## Inner loop — initial unit test list

- [ ] An in-text citation renders `(Bayat, 2017)`; a multi-source run renders `(Vignal, 2021; Bayat, 2017)`.
- [ ] `Michael Mann` and `Mann, Michael` resolve to the same surname and render identically.
- [ ] A bibliography entry renders `Surname, F. M. (Year). *Title*. Publisher.` from a fully resolved record.
- [ ] `Siniša Malešević` resolves through the diacritic fold without mangling the printed name — the *printed* form keeps its diacritics; only the matching is folded.
- [ ] `John A. Hall and Ralph Schroeder` is printed as given, not inverted — the never-guess fallback.
- [ ] A record with `date` absent renders `(n.d.)`; a record with `author` absent falls back without inventing one.
- [ ] `render_paper`'s audit output is unchanged — pinned byte-for-byte against a fixture.
- [ ] Entry ordering stays deterministic, on the resolved surname.

## Out of scope for this slice (deferred)

- Any second citation style, or a style selector. APA is the house style.
- Contributor roles (author vs editor) — #481.
- Editing `data/source_meta/` records. The metadata is faithful to the title
  pages by design; this slice reads it, it does not correct it.
- The audit render, the citation table, the coverage table and the shape block.
- The ask path's own render, beyond whatever it inherits from `cite.py` — which
  it should, and that is correct, but it is not this slice's acceptance.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; `uv run pytest` and `uv run ruff check` green locally.
- [ ] Refactor pass complete with the bar green.
- [ ] **Rendered against all 35 real `data/source_meta/` records** and the output read by eye — this is a corpus-facing formatter and a green suite is not the evidence. Zero model calls, so this costs nothing but the reading.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Evidence collected and PR opened into `main` (`safe-pr`).

## Status / progress log

- 2026-08-18 planned.
