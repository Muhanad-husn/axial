# Axial

Axial is a single-operator pipeline that turns a corpus of born-digital academic sources
(PDF/DOCX) into a tagged Obsidian knowledge graph, validated against a human-labeled gold
corpus. The full build specification lives in [`specs/PRODUCT.md`](specs/PRODUCT.md).

This repository is also a working **agentic engineering org**: tool-locked role subagents
(triage, spec author, test author, implementer, reviewer) do the building; deterministic
hook gates guarantee that subagents never merge and no one commits a red test suite; a
single human founder holds architecture and approval authority. GitHub issues and PRs are
the system of record. See `CLAUDE.md` for the handbook and `docs/DECISIONS.md` /
`docs/PROGRESS.md` for the build audit trail.

## Quick start

```bash
uv sync
uv run pytest
```
