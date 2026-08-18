# Slice 05: House style is domain data, not prompt text

- **Feature:** 787-venue-length-house-style
- **Slice slug:** house-style-is-domain-data
- **Branch:** feat/787-venue-length-house-style/05-house-style-is-domain-data
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

The prose conventions a paper is written to live in
`config/domains/<domain>/`, load at runtime, and reach the drafting prompt as
context — never as a gate, and never as a branch in `src/`.

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
edits: config/domains/default/schema.yaml
creates: tests/paper/test_house_style.py
creates: src/axial/paper/test_draft_house_style.py
depends-on: 02-length-is-a-plan-target
```

Confirm the domain directory name against `config/domains/` before branching —
the tree carries `codebook.yaml`, `polity_canonical.yaml` and `schema.yaml`,
and which of those the style block belongs in is the builder's call, stated in
one line in the PR body.

## Inner loop — initial unit test list

- [ ] The domain loader reads a house-style block and exposes it without any country- or corpus-specific handling.
- [ ] `compose_draft_prompt` carries the block when the frame declares one.
- [ ] A frame with no house-style block composes a prompt byte-identical to slice 02's.
- [ ] A malformed house-style block fails loudly at load with a typed error, rather than being silently dropped into the prompt.
- [ ] The block is context only — nothing in the draft path validates, scores or rejects prose against it.

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
- [ ] Drafted against at least two real dev briefs with the block present and absent, and the difference read by eye. Logged under `data/logs/<date>-787-house-style/`.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Evidence collected and PR opened into `main` (`safe-pr`).

## Status / progress log

- 2026-08-18 planned.
