# Axial

Axial turns a corpus of born-digital academic sources into a tagged Obsidian
knowledge graph, and scores the tagging against a human-labeled gold corpus. The
full build specification is in [`specs/PRODUCT.md`](specs/PRODUCT.md); the
decision log is in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Working in this repo

- **Install and test:** `uv sync`, then `uv run pytest`. Drive the pipeline
  through the `axial` CLI (`uv run axial --help`).
- **Domain content is data, not code.** The axes, controlled vocabularies, and
  codebook definitions live in `config/domains/<domain>/` and load at runtime.
  No country- or corpus-specific logic belongs in `src/`.
- **A structural tree is extracted once per source**, persisted, and reused by
  every later stage. Prefer reading the cached tree to re-running extraction.
- GitHub issues and PRs are the system of record.

## Writing conventions

Plain, direct prose; no filler, no ceremony. Short sentences over long ones. At
most two em dashes per 500 words. Code comments only where the code cannot say
it itself.

## Developer principles

- **Practicality over perfectionism.** 80/20 rule. A working solution beats a
  theoretically optimal one.
- **Don't reinvent the wheel.** Check existing tools and libraries before
  building. If you know of something useful that isn't installed, suggest adding
  it.
- **Measure, don't speculate.** When in doubt, prototype and measure rather than
  analyze indefinitely.
