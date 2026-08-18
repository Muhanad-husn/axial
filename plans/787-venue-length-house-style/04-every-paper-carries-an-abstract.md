# Slice 04: Every paper carries an abstract

- **Feature:** 787-venue-length-house-style
- **Slice slug:** every-paper-carries-an-abstract
- **Branch:** feat/787-venue-length-house-style/04-every-paper-carries-an-abstract
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

A finished paper opens with an abstract of roughly 200 words that summarises
the argument the paper actually made, written after the sections are drafted
and persisted on the record.

## Why unconditionally, and not per venue

Every venue surveyed requires one and the lengths converge — IJMES asks for
150 words, Nature for a ~200-word summary paragraph. It is the one thing the
formatting survey turned up that is real writing rather than typesetting, and
it is the piece a reader who was sent the essay actually uses. So it is not
venue-conditional: every paper gets one.

## Why after drafting, not in the plan

An abstract summarises the paper that exists, not the paper that was planned.
Composing it from the plan would describe an argument the drafter may not have
made. This is one cheap call over the drafted sections, after stage 3.

## INVEST check

- **Independent:** depends on slice 03 (both edit `reader.py`); nothing depends
  on it.
- **Valuable:** the reader gets the argument in a paragraph before deciding to
  read the essay.
- **Small:** one prompt, one model call, one record field, one render block.
- **Testable:** the record carries it, both renders show it, the word count is
  observable.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a paper brief with two analysis records
When  an operator runs `uv run axial paper draft <that brief>`
Then  the persisted record under data/papers/ carries an abstract of roughly 200 words
And   the reader-facing markdown opens with that abstract, under the title and before the first section
And   the abstract states the paper's own thesis and what it concluded, not a description of the sources
And   the abstract carries no claim markers and no citations
```

- **Boundary / endpoint:** CLI — `uv run axial paper draft <paper_brief_file>`
- **e2e test type:** API/integration test
- **e2e test file (planned):** `tests/paper/test_abstract.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 04-every-paper-carries-an-abstract
edits: src/axial/paper/draft.py
edits: src/axial/paper/record.py
edits: src/axial/paper/reader.py
edits: src/axial/paper/render.py
creates: src/axial/paper/abstract.py
creates: src/axial/paper/test_abstract.py
creates: tests/paper/test_abstract.py
depends-on: 03-apa-citations-and-bibliography
```

## Inner loop — initial unit test list

- [ ] `compose_abstract_prompt` is given the thesis statement and the drafted section prose, and asks for one paragraph of about 200 words.
- [ ] The prompt forbids claim markers and citations in the abstract.
- [ ] `parse_abstract_response` rejects an empty or non-string abstract with a typed error, in the same shape the other parse errors use.
- [ ] The abstract lands on the persisted record and survives a round trip through `record.py`.
- [ ] `render_reader_paper` places the abstract after the title and before the first section.
- [ ] `render_paper` (the audit render) also carries it, since it renders the same record.
- [ ] A record with no abstract renders exactly as it does today — the field is additive, never a new way for an existing record to fail to render.

## Out of scope for this slice (deferred)

- A keyword list. No venue asks for one that this product serves.
- A configurable abstract length. 200 words, one number, no option.
- Structured abstracts (background / methods / results). Wrong genre.
- Making the abstract's quality a gate. Like the shape check, it is written and
  reported, never blocking.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; `uv run pytest` and `uv run ruff check` green locally.
- [ ] Refactor pass complete with the bar green.
- [ ] Drafted against at least three real dev briefs and the abstracts read by eye — a summary that describes the sources rather than the argument is the failure to look for. Logged under `data/logs/<date>-787-abstract/`.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Evidence collected and PR opened into `main` (`safe-pr`).

## Status / progress log

- 2026-08-18 planned.
