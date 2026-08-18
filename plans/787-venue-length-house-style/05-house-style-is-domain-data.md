# Slice 05: House style is domain data, not prompt text

- **Feature:** 787-venue-length-house-style
- **Slice slug:** house-style-is-domain-data
- **Branch:** feat/787-venue-length-house-style/05-house-style-is-domain-data
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

The prose conventions a paper is written to live in
`config/domains/<domain>/`, load at runtime, and reach both prose-writing
prompts — the drafter and the abstract — as context, never as a gate, and
never as a branch in `src/`.

## Why this is the last slice and the thinnest

CLAUDE.md is explicit: the domain frame is data, it loads at runtime, and it
reaches the model as context and examples, never as a gate. House style is
exactly that shape. It is last because restyling has to happen over an essay
that already argues, and by this point slices 01–04 have made one.

What "house style" means here is what the format-free journals actually
enforce, which turned out not to be conformity but **consistency**: one
citation style throughout, uniform section headings, one spelling convention,
no mixed registers. That is a short block of prose conventions, not a
mechanism.

## Revised 2026-08-18, after slice 04 landed — read this before building

Three corrections to this plan, made when it came up for building. Each is a
decision already taken; do not re-litigate them, and do not silently do
something else.

### It reaches the abstract too, not only the drafter

This plan was written before slice 04 existed. The abstract is prose a reader
reads — the first prose, in fact, and the block a reader who was sent the essay
actually uses. A house style that governs the sections and not the abstract
would leave the one paragraph most likely to be read outside the style it
declares.

So `compose_abstract_prompt` (`src/axial/paper/abstract.py`) takes the block on
the same terms as `compose_draft_prompt`: present means context, absent means a
byte-identical prompt. That is one more seam, not a second mechanism.

This is also where the only *measured* style defect in this product lives — see
the measurement section below.

### It lives in its own file, not in `schema.yaml`

The Files declaration below originally said `config/domains/default/schema.yaml`.
Both halves were wrong:

- **There is no `default` domain.** `config/domains/` carries exactly one
  directory, `syria`, holding `codebook.yaml`, `polity_canonical.yaml` and
  `schema.yaml`.
- **`schema.yaml` is the tagging schema** — axes, cardinality, controlled
  values, a `version` — loaded by `src/axial/schema.py` and depended on by
  Phase A. Prose conventions are a different kind of thing entirely, and
  folding them into that loader would overload a file the ingestion path
  reads for a reason unrelated to writing.

House style is a new file, `config/domains/<domain>/house_style.yaml`, with its
own small loader following `schema.py`'s established shape: it takes a domain
*directory*, and no code path in `src/` branches on which domain it is.

### The paper path reads no domain frame at all today

Worth knowing before estimating: nothing under `src/axial/paper/` currently
loads anything from `config/domains/`. This slice opens that seam. Follow
`schema.py` for the loader's shape and `axial.paper.lens.resolve_lens` for how
the paper path already threads a runtime-resolved config object down to a
prompt — the lens is the precedent, and it is a close one.

## INVEST check

- **Independent:** depends on slice 02 (edits `draft.py` after 01 and 02 have
  settled that file); nothing depends on it.
- **Valuable:** the essays read as one product rather than as N model outputs,
  and the conventions become editable by the analyst who owns the domain.
- **Small:** one config block, one loader path already established, one prompt
  seam.
- **Testable:** the block is observable in the composed prompt, and its absence
  leaves the prompt unchanged.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a domain frame at config/domains/<domain>/ that declares house style conventions
When  an operator runs `uv run axial paper draft <a brief in that domain>`
Then  the drafting prompt for every section carries those conventions as context
And   a domain frame declaring no house style produces a prompt unchanged from slice 02's
And   no house-style value appears anywhere in src/ as a literal or a branch
```

- **Boundary / endpoint:** CLI — `uv run axial paper draft <paper_brief_file>`
- **e2e test type:** API/integration test
- **e2e test file (planned):** `tests/paper/test_house_style.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 05-house-style-is-domain-data
edits: src/axial/paper/draft.py
edits: src/axial/paper/abstract.py
edits: src/axial/paper/record.py
creates: config/domains/syria/house_style.yaml
creates: src/axial/paper/house_style.py
creates: tests/paper/test_house_style.py
creates: tests/paper/test_draft_house_style.py
depends-on: 02-length-is-a-plan-target
```

The domain is `syria` — the only directory under `config/domains/`. The style
block is its own file, not a section of `schema.yaml`; the revision section
above says why. `record.py` is on the list because it is where both prompts'
callers live, and the block has to reach them from somewhere.

## Inner loop — initial unit test list

- [ ] The loader reads `house_style.yaml` from a domain *directory* and exposes it without any country- or corpus-specific handling.
- [ ] `compose_draft_prompt` carries the block when the frame declares one.
- [ ] `compose_abstract_prompt` carries the same block, on the same terms.
- [ ] A domain with no `house_style.yaml` composes both prompts byte-identical to what they are on `main` at `5a34d45`. This is the regression that matters most: four slices' worth of measured prompt behaviour sits behind it.
- [ ] A malformed block fails loudly at load with a typed error, rather than being silently dropped into a prompt.
- [ ] The block is context only — nothing anywhere validates, scores or rejects prose against it.

## Measurement (reviewed 2026-08-18, before the slice was built)

The feature README's finding binds this slice: dev briefs cannot discriminate on
a judged property of the writing, and "two dev briefs, read by eye" — what this
plan's Definition of Done originally asked for — is exactly the shape that
finding rules out. Worse, it is a *before/after* on a judged property at n=2.

**But this slice has something the others did not: a countable signal at a 100%
base rate.**

Slice 04 measured all ten abstracts this product has produced and found that
**10 of 10 open with the identical five words, "This paper argues that."** The
prompt never asks for it; the model converges on it. That is a mechanical
count, not a judged band — and a before/after on a signal whose base rate is
100% is decisive at n=10 in a way slice 01's was never going to be. Slice 01
failed to measure because its defect ran at roughly 1 in 4, where n=3 cannot
separate any hypothesis from any other. Ten out of ten going to zero out of ten
cannot be a coin landing the same way twice.

**So the primary measurement is:**

1. Re-run slice 04's harness, `data/logs/2026-08-18-787-abstract/run_abstracts.py`,
   over the same 10 records in `data/papers/` with no house-style block. That is
   the control, and one already exists — `data/logs/2026-08-18-787-abstract/run.jsonl`
   — though re-running it on the day is cheap enough to prefer over trusting a
   week-old arm.
2. Run it again with the block present, where the block says something specific
   about opening formulas.
3. **Count how many of ten open with "This paper argues that."** Report both
   arms as counts. No re-draft is needed for either: the abstract call reads
   only the thesis and drafted prose, both already persisted.

**Cost: about $0.026 per arm, 35 seconds per arm.** That is the whole primary
measurement.

### The secondary measurement, and its honest limits

Whether house style changed the *sections* is a judged property, and the same
substrate finding applies. Draft two or three dev briefs with the block present,
read them, and report what you see — but **report it as an impression, not a
result**, and do not let a null there be read as "the block does nothing". The
sections have no countable signal comparable to the abstract's opening formula.

If the primary measurement moves and the secondary reads as unchanged, the
slice has still done its job: the block reaches both prompts, and one of them
demonstrably changed.

### What would make this measurement dishonest

Writing the house-style block to name the exact string being counted — "never
open with 'This paper argues that'" — and then reporting the count as evidence
the mechanism works. That measures the model's instruction-following on one
string, not whether house style reaches the prompt. **State the convention at
the level a style guide states one** (e.g. that abstracts should not open with a
formulaic self-reference), and let the count be a consequence rather than the
instruction restated.

## Out of scope for this slice (deferred)

- Enforcing house style. It reaches the model as context; there is no checker
  and no gate. A style gate is the mechanism CLAUDE.md forbids.
- Per-venue style. There are no venues.
- Restyling already-persisted papers. A re-draft is how a paper picks up a
  style change.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; `uv run pytest` and `uv run ruff check` green locally.
- [ ] Refactor pass complete with the bar green.
- [ ] Measured per the section below. Logged under `data/logs/<date>-787-house-style/`.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Evidence collected and PR opened into `main` (`safe-pr`).

## Status / progress log

- 2026-08-18 planned.
- 2026-08-18 revised before building: reaches the abstract as well as the
  drafter; lives in its own `house_style.yaml` rather than `schema.yaml`; the
  measurement rewritten around the one countable signal slice 04 turned up.
