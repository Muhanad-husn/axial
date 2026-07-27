# Axial

Axial turns a corpus of born-digital academic sources into an Obsidian wiki the
model wrote by reading. Each passage is interrogated once with open questions —
what it claims, whose position it is, who it argues against, who it cites, what
it names — and the passages meet each other at the names they share, on a page
per name that says what their authors disagree about. The full build
specification is in [`specs/PRODUCT.md`](specs/PRODUCT.md); the decision log is
in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Working in this repo

- **Install and test:** `uv sync`, then `uv run pytest`. Drive the pipeline
  through the `axial` CLI (`uv run axial --help`).
- **Domain content is data, not code.** The domain frame lives in
  `config/domains/<domain>/` and loads at runtime. It reaches the model as
  context and examples, never as a gate. No country- or corpus-specific logic
  belongs in `src/`.
- **A structural tree is extracted once per source**, persisted, and reused by
  every later stage. Prefer reading the cached tree to re-running extraction.
- GitHub issues and PRs are the system of record.

## Developer principles

- **Practicality over perfectionism.** 80/20 rule: build the smallest thing that
  meets the acceptance bar, and keep the bar strict, not the mechanism. Polishing
  past the bar is a process bug, not diligence.
- **Over-engineering tripwires** — stop and simplify, or justify in one line in
  the PR body: a hand-tuned constant or magic number in a heuristic; an
  abstraction with one implementation; a config option nobody sets; a fix larger
  than its bug.
- **Don't reinvent the wheel.** Check existing tools and libraries — or a single
  LLM call — before building. If you know of something useful that isn't
  installed, suggest adding it.
- **Measure, don't speculate.** When in doubt, prototype and measure rather than
  analyze indefinitely.

## Writing conventions

Plain, direct prose; no filler, no ceremony. Short sentences over long ones. At
most two em dashes per 500 words. Code comments only where the code cannot say
it itself.

### Answering the founder

Applies to every reply in a session, not just prose written into the repo.

- **Lead with the answer.** No preamble, no restating the question, no recap of
  what you just did.
- **Default to a few sentences.** Length is earned by content the founder asked
  for, never by thoroughness for its own sake. If the full answer is "yes, 10",
  that is the whole reply.
- **No jargon.** Plain words over insider terms. Name a file, symbol, or spec
  section only when the founder needs it to act. Never make a sentence carry
  three of them.
- **Structure only when it does work.** Tables for comparisons, lists for real
  lists. A heading over two sentences is noise.
- **Cut the hedging and the throat-clearing.** No "it's worth noting", no
  restating a finding you already stated, no closing summary of the reply.

Report findings completely — brevity never means dropping a caveat, a failure,
or a number that changes the decision. Say it in fewer words instead.
