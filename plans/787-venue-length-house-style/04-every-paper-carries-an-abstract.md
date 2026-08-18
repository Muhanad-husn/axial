# Slice 04: Every paper carries an abstract

- **Feature:** 787-venue-length-house-style
- **Slice slug:** every-paper-carries-an-abstract
- **Branch:** feat/787-venue-length-house-style/04-every-paper-carries-an-abstract
- **Project directory:** .
- **Status:** ◐ built, awaiting measurement
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

## Why its own pass, and not one more field on the shape check

The obvious cheaper route was rejected deliberately, so do not re-propose it.
The shape check (`src/axial/paper/shape.py`) already reads the whole drafted
paper, already runs on a model guaranteed different from the drafter, and
already returns structured JSON -- and issue #717 already added the paper's
*title* to it on exactly that "one more field on a call already being made"
argument.

An abstract is not that. A title is eight words; an abstract is ~200 words of
generation that would dominate the completion of a call whose response
*ordering* was measured and calibrated -- issue #600 moved defect detection
from 8.3% to 50% purely by requiring per-section reviews before the band, and
that instrument is fragile enough that two of three defect classes still vary
across replicates. Re-calibrating it costs a measured run. Also the roles
differ: the shape check grades, and this writes.

So: a separate pass, `paper_abstract`, with its own name in `axial.llm`, its
own tier in `config/pipeline.yaml`, and its own entries in the record's `cost`
and `model_by_pass` -- the same shape `paper_shape` has.

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
creates: tests/paper/test_abstract_unit.py
creates: tests/paper/test_abstract.py
depends-on: 03-apa-citations-and-bibliography
```

## Inner loop — initial unit test list

- [x] `compose_abstract_prompt` is given the thesis statement and the drafted section prose, and asks for one paragraph of about 200 words.
- [x] The prompt forbids claim markers and citations in the abstract.
- [x] `parse_abstract_response` rejects an empty or non-string abstract with a typed error, in the same shape the other parse errors use.
- [x] The abstract lands on the persisted record and survives a round trip through `record.py`.
- [x] `render_reader_paper` places the abstract after the title and before the first section.
- [x] `render_paper` (the audit render) also carries it, since it renders the same record.
- [x] A record with no abstract renders exactly as it does today — the field is additive, never a new way for an existing record to fail to render.

## Measurement (reviewed 2026-08-18, before the slice was built)

The feature README records that the nine dev briefs are the wrong substrate
for judging writing quality -- `shape.band` came back `strong` on 35 of 35
drafts across both arms of slice 01. That finding binds this slice, and the
plan's original bar ("drafted against at least three real dev briefs") walked
straight into it.

**It does not cost a re-draft to avoid.** The abstract call reads only the
thesis statement and the drafted section prose, both of which are already
persisted on every record under `data/papers/`. So the measurement is a
harness script over the records already on disk -- **no drafting call, no
retrieval, no re-key** -- one abstract call per record.

- **Substrate: all 10 records in `data/papers/`**, which includes papers
  drafted from real analyst questions through `axial ask`, not only the dev
  briefs. That is what makes it a real substrate rather than the easy one.
- **Cost:** 10 calls of ~200 completion tokens. Pennies, minutes.
- **The bar is read by eye, and it is a yes/no per abstract:** does it state
  the paper's own thesis and what it concluded, or does it describe what the
  sources say? A summary of the sources is the failure this looks for. There
  is no judged band to invent here and none should be added -- the plan already
  rules an abstract-quality gate out of scope.
- **Report the count plainly** (e.g. "8 of 10 state the argument"), name the
  failures, and quote at least one abstract in full in the PR body so the
  founder can judge the instrument as well as the result.
- **Do not read a clean 10 of 10 as proof the prompt is good.** It is the
  first draw of a judged property; say so.

The 10 records must be copied into the run log before the harness runs
anyway -- the README's re-drafting hazard is about `paper draft`, and this
harness writes no record, but the copies are what the eye-read is quoted from.

## Out of scope for this slice (deferred)

- A keyword list. No venue asks for one that this product serves.
- A configurable abstract length. 200 words, one number, no option.
- Structured abstracts (background / methods / results). Wrong genre.
- Making the abstract's quality a gate. Like the shape check, it is written and
  reported, never blocking.

## Definition of done

- [x] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [x] All seeded unit behaviours covered; `uv run pytest` and `uv run ruff check` green locally.
- [x] Refactor pass complete with the bar green.
- [x] Measured per the section below, and the abstracts read by eye. Logged under
      `data/logs/2026-08-18-787-abstract/` — 10 of 10 state the argument, 0 markers,
      0 citations, $0.0257, 35s.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Evidence collected and PR opened into `main` (`safe-pr`).

## Status / progress log

- 2026-08-18 planned.
- 2026-08-18 measurement section reviewed before building (`1ca3e15`); the pass
  sited on its own rather than on the shape check.
- 2026-08-18 built green at `fd37703`; 2,525 tests, ruff clean.
- 2026-08-18 measured over all 10 records in `data/papers/`: 10 of 10 state the
  paper's own argument, none describes the sources. Every one opens with the
  identical five words, which is slice 05's business.
- 2026-08-18 built on `feat/787-venue-length-house-style/04-every-paper-carries-an-abstract`.
  `uv run pytest` 2,525 passed; `uv run ruff check` clean; `tests/paper`,
  `tests/analysis`, `tests/service/test_ask_ends_in_an_essay.py` green.
  Remaining: the founder's measurement over the 10 records in `data/papers/`,
  then the PR.

  The harness entry point, over one record already on disk (no drafting call,
  no re-key):

  ```python
  from axial.paper.abstract import run_abstract
  from axial.paper.render import plan_sections, prose_by_section

  prose = prose_by_section(record)
  sections = [
      {"heading": s["heading"], "prose": prose.get(str(s["section_id"]), "")}
      for s in plan_sections(record)
  ]
  result = run_abstract(client, record["plan"]["thesis_statement"], sections)
  # result.text, result.model, result.cost
  ```

  Needs `production_paper_abstract` in `secrets/secrets.toml`; it is set
  locally to `openai/gpt-5.6-luna`, matching the drafter.
