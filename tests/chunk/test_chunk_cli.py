"""Thin CLI-dispatch coverage for the plain `axial chunk <source>` subcommand
(issue #191 follow-up: reviewer-found coverage regression).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fixture source with a persisted tree
When  the user runs the plain `axial chunk <source_path>` CLI subcommand
      (no `examine`)
Then  it exits 0 and writes data/chunks/<source_id>.jsonl with at least one
      chunk record

Why this test exists
-----------------------------------------------------------------------
tests/chunk/test_chunk.py and test_chunk_recursive.py both call
`axial.chunk.run_chunk_recursive` directly (necessary at the time they were
written, to sidestep the CLI's now-retired embedding-default dispatch and
its network-touching real model -- see those files' own "Seam decision 1"
docstrings). That migration left `src/axial/cli.py`'s `_chunk()` --  the
actual `chunk_parser`/`args.command == "chunk"` dispatch a real operator
invocation goes through -- with zero test coverage: nothing but `chunk
examine` exercised the `chunk` subcommand at all. Recursive/structural is
now the sole chunk mechanism (issue #191), so `_chunk()` has no embedder
seam and no network dependency of its own; this test proves the CLI
actually reaches `run_chunk_recursive` and writes the real artifact,
end-to-end, without duplicating the deep band/provenance/skip assertions
tests/chunk/test_chunk.py and test_chunk_recursive.py already cover.

Seam decisions -- mirrors tests/chunk/test_chunk_recursive.py exactly
-----------------------------------------------------------------------
In-process (`axial.cli.main`), not a subprocess, for speed: no `uv run`
subprocess startup cost, and no embedder/LLM seam needs poisoning here (this
test isn't proving zero-cost, just that the wiring reaches the artifact), so
there is nothing a subprocess-only monkeypatch limitation would force. An
isolated, freshly created `tmp_path` cwd (`monkeypatch.chdir`) keeps
`data/trees/`/`data/chunks/` (both plain, cwd-relative paths) away from the
real repo's `data/` tree. The fixture tree is pre-placed at
`data/trees/<source_id>.json` for the committed
`tests/fixtures/envelope/thesis_paper.pdf` (reused purely as a byte source
for a real, deterministic `source_id` -- never for its own tree shape),
exactly as the sibling outer tests already do -- `axial.extract.extract`'s
persisted-tree cache is checked before docling ever runs, so this makes
`axial chunk` consume the fabricated tree verbatim, offline.
"""

from __future__ import annotations

import json
from pathlib import Path

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_PDF = REPO_ROOT / "tests" / "fixtures" / "envelope" / "thesis_paper.pdf"


def _build_fixture_tree() -> dict:
    """A minimal one-section tree -- this test only needs enough real prose
    to produce at least one chunk record; the band/provenance/skip
    guarantees are already locked elsewhere (see module docstring)."""
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Overview",
                "label": "section_header",
                "children": [
                    {
                        "type": "prose",
                        "order": "1.1",
                        "text": (
                            "Field teams conducted a short survey of provincial "
                            "administration following the ceasefire, focused on "
                            "service delivery and local governance capacity."
                        ),
                    }
                ],
            }
        ]
    }


def _place_fixture_tree(root: Path, source_id: str) -> None:
    tree_path = root / "data" / "trees" / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(json.dumps(_build_fixture_tree()), encoding="utf-8")


def test_plain_chunk_subcommand_dispatches_to_recursive_and_writes_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    source_id = compute_source_id(FIXTURE_PDF)
    _place_fixture_tree(tmp_path, source_id)

    from axial.cli import main

    exit_code = main(["chunk", str(FIXTURE_PDF)])

    assert exit_code == 0, (
        f"expected exit code 0 for the plain `axial chunk <source>` "
        f"subcommand against a fixture tree, got {exit_code}"
    )

    chunk_path = tmp_path / "data" / "chunks" / f"{source_id}.jsonl"
    assert chunk_path.exists(), (
        f"expected the plain `chunk` subcommand's CLI dispatch to reach "
        f"`run_chunk_recursive` and write {chunk_path} (PRD §7.7), but it "
        f"does not exist"
    )

    lines = [line for line in chunk_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines, f"expected at least one chunk record written to {chunk_path}, got none"
    for line in lines:
        record = json.loads(line)
        assert isinstance(record, dict) and record.get("chunk_id"), (
            f"expected a well-formed chunk record with a non-empty chunk_id, got {record!r}"
        )
