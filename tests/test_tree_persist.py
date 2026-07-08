"""Outer acceptance test for issue #45 (persist and reuse the structural
extraction tree).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a born-digital fixture source with no persisted tree yet
When  the user runs `axial extract <fixture>`
Then  it exits 0, emits the hierarchical tree on stdout (as already locked by
      tests/test_extract.py), AND persists that exact tree to
      data/trees/<source_id>.json, where source_id is
      `axial.envelope.compute_source_id` of the source

Given a source whose source_id already has a persisted tree on disk
When  the user runs `axial extract` again for that same source
Then  the persisted tree is read back VERBATIM and returned/printed as-is --
      docling is never re-run for that source

See specs/PRODUCT.md §5 stage 2 ("This tree is produced once per source,
persisted, and reused by every later stage for that source (not
re-extracted). Output: structural tree (persisted)."), §6 (repository
structure: `data/trees/ # one JSON per source (persisted structural tree)`),
§7.4 ("Structural tree" -- "One JSON per source in data/trees/, keyed by
source_id (the same deterministic id used for the envelope --
axial.envelope.compute_source_id) ... The shape is exactly the extraction
pass's output ... Produced once in stage 2 and reused by every later stage
for that source ... A source is re-extracted only when no persisted tree
exists for its source_id."), and §8 P0-2, third bullet ("The structural tree
is written once per source (keyed by source_id) and read by later stages
(not re-extracted); a source is re-extracted only when no persisted tree
exists for its source_id.") for the source of truth.

Seam decision 1 -- observing "read verbatim, not re-extracted" black-box,
deterministically (not timing-based)
-----------------------------------------------------------------------
A subprocess-based outer test cannot see whether docling's real conversion
pipeline ran in-process. Timing is not a reliable signal (docling's model
load time varies by machine/cache state) and would make this test flaky by
construction, so this test uses a content-based proof instead:

Before invoking `axial extract` for a source, this test pre-places a KNOWN,
clearly-distinguishable SENTINEL tree JSON directly at
`data/trees/<source_id>.json` -- a single prose node whose `order` and
`text` carry an unmistakable sentinel marker that could never appear in a
real docling/Unstructured extraction of the fixture PDF, and that (unlike a
real extraction of this fixture, which has a table) carries no `artifact`
node at all.

`axial extract` is then run for that exact same source. If reuse is
implemented (the persisted tree is read verbatim and docling is skipped),
the command's output is byte-for-byte the sentinel tree. If the source were
re-extracted instead, the output would necessarily reflect the real PDF: it
would contain the fixture's actual prose/artifact nodes (including at least
one real `type: "artifact"` node for its table) and would never contain the
sentinel marker text. These two outcomes are mutually exclusive by
construction, so asserting output-equals-sentinel is a hard behavioral proof
of reuse, not a scrape of an incidental log line or a race against a clock.

This is exactly the mechanism the downstream test-speedup (avoiding
redundant real docling calls in later-stage tests/fixtures) will rely on,
per the issue's own framing, so locking it here at the extract boundary is
the correct place to lock it.

Seam decision 2 -- the forward direction (fresh source persists a tree)
-----------------------------------------------------------------------
This test also asserts the complementary direction: extracting a source
with NO persisted tree yet must CREATE `data/trees/<source_id>.json`, and
that file's content must be exactly the tree printed to stdout (PRD §7.4,
"the shape is exactly the extraction pass's output... this subsection adds
persistence, not a new shape"). This exercises the real docling pipeline
once (same fixture and shape checks as tests/test_extract.py); it is left
unmarked (not `@pytest.mark.slow`), mirroring tests/test_extract.py's own
real-docling outer acceptance test, so this acceptance criterion stays
covered by CI's `pytest tests -m "not slow"` step. The reuse assertions
(seam decision 1) never touch docling at all and so stay fast regardless.

Fixture: tests/fixtures/extract/prose_and_table.pdf (already used by
tests/test_extract.py) -- born-digital, with both a prose section and at
least one table, so a real extraction is distinguishable from the sentinel
by the presence of an `artifact` node alone.

Test hygiene: data/trees/ isolation (both new files this test creates, and
the deliberate sentinel-content overwrite the reuse test below performs on a
pre-existing path) is handled by the shared, content-snapshot-based
`_isolate_persisted_tree_and_envelope_state` autouse fixture in
tests/conftest.py -- restoring original bytes for any pre-existing file this
test overwrites, and deleting any file it newly creates. This test does not
invoke `axial envelope` and so never touches data/envelopes/.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "extract"
TREES_DIR = REPO_ROOT / "data" / "trees"

PROSE_AND_TABLE_PDF = FIXTURES_DIR / "prose_and_table.pdf"

# argparse's fallback error for an as-yet-nonexistent option/behavior path.
# `extract` itself already exists (tests/test_extract.py), so this only
# guards against a wholesale CLI breakage, not a missing subcommand.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)

# A marker that can never appear in a real docling/Unstructured extraction
# of prose_and_table.pdf: it names the sentinel mechanism itself.
_SENTINEL_MARKER_TEXT = (
    "SENTINEL_TREE_7f3a1c9d: if you can read this in `axial extract`'s "
    "output, the persisted tree was reused verbatim; real docling output "
    "for this fixture never contains this string."
)


def _run_extract(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "axial", "extract", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `extract` behavior path, not an argparse "
            f"fallback (found {marker!r}):\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _tree_path_for(source_pdf: Path) -> Path:
    """The persisted-tree path this test locks: data/trees/<source_id>.json,
    where source_id is axial.envelope.compute_source_id(source_pdf) -- the
    same deterministic id used for envelopes (PRD §7.4)."""
    return TREES_DIR / f"{compute_source_id(source_pdf)}.json"


def _iter_nodes(node: dict) -> list:
    """Depth-first flatten of a tree node's descendants (not including the
    node itself). Mirrors tests/test_extract.py's helper of the same name."""
    collected = []
    for child in node.get("children", []):
        collected.append(child)
        collected.extend(_iter_nodes(child))
    return collected


def test_extract_persists_tree_for_a_fresh_source_matching_stdout():
    """Forward direction (PRD §7.4 / §8 P0-2): a source with no persisted
    tree yet gets one written at data/trees/<source_id>.json, with content
    identical to what `axial extract` printed to stdout."""
    tree_path = _tree_path_for(PROSE_AND_TABLE_PDF)
    if tree_path.exists():
        tree_path.unlink()  # guarantee a genuinely fresh source_id for this run

    result = _run_extract(str(PROSE_AND_TABLE_PDF))
    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 extracting a fresh fixture source with no "
        f"persisted tree yet, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    stdout_tree = json.loads(result.stdout.strip())

    assert tree_path.exists(), (
        f"expected `axial extract` to persist the structural tree to "
        f"{tree_path} (PRD §7.4: 'One JSON per source in data/trees/, keyed "
        f"by source_id ... produced once in stage 2'), but no such file "
        f"exists after a fresh extraction.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    persisted_tree = json.loads(tree_path.read_text(encoding="utf-8"))

    assert isinstance(persisted_tree, dict), (
        f"expected the persisted tree at {tree_path} to be a JSON object "
        f"(the tree root), got {type(persisted_tree).__name__}: {persisted_tree!r}"
    )

    all_nodes = _iter_nodes(persisted_tree)
    assert all_nodes, (
        f"expected the persisted tree to contain at least one node under "
        f"the root. Full tree: {json.dumps(persisted_tree, indent=2)}"
    )
    for node in all_nodes:
        assert "type" in node and "order" in node, (
            f"expected every persisted-tree node to carry `type` and "
            f"`order` (PRD §7.4, 'the shape is exactly the extraction "
            f"pass's output'), missing on node: {node!r}"
        )

    node_types = {node["type"] for node in all_nodes}
    assert "prose" in node_types and "artifact" in node_types, (
        f"expected the persisted tree for prose_and_table.pdf to contain "
        f"both 'prose' and 'artifact' nodes, got types: {sorted(node_types)}"
    )

    assert persisted_tree == stdout_tree, (
        f"expected the persisted tree at {tree_path} to be exactly the tree "
        f"`axial extract` printed to stdout (PRD §7.4: 'the shape is "
        f"exactly the extraction pass's output ... this subsection adds "
        f"persistence, not a new shape'), but they differ.\n"
        f"stdout tree: {json.dumps(stdout_tree, indent=2)}\n"
        f"persisted tree: {json.dumps(persisted_tree, indent=2)}"
    )


def test_extract_reuses_persisted_tree_verbatim_instead_of_re_extracting():
    """Reuse direction (PRD §5 stage 2, §8 P0-2, §7.4): when a persisted
    tree already exists for a source's source_id, `axial extract` must
    return/print it verbatim and must NOT re-run docling. Proven
    deterministically via a pre-placed sentinel tree the real fixture could
    never produce (see module docstring, seam decision 1) -- not via
    timing."""
    tree_path = _tree_path_for(PROSE_AND_TABLE_PDF)

    sentinel_tree = {
        "children": [
            {
                "type": "prose",
                "order": "sentinel-0",
                "text": _SENTINEL_MARKER_TEXT,
            }
        ]
    }
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel_bytes = json.dumps(sentinel_tree, sort_keys=True).encode("utf-8")
    tree_path.write_bytes(sentinel_bytes)

    result = _run_extract(str(PROSE_AND_TABLE_PDF))
    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 extracting a source whose source_id already "
        f"has a persisted (sentinel) tree on disk, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    stdout_tree = json.loads(result.stdout.strip())

    all_nodes = _iter_nodes(stdout_tree)
    node_types = {node.get("type") for node in all_nodes}
    assert "artifact" not in node_types, (
        f"expected NO 'artifact' node in the output -- the sentinel tree "
        f"has none, while a real extraction of prose_and_table.pdf always "
        f"produces at least one (its table). Finding an 'artifact' node "
        f"here means the source was RE-EXTRACTED instead of reusing the "
        f"persisted tree (PRD §7.4, 'a source is re-extracted only when no "
        f"persisted tree exists for its source_id').\n"
        f"Full output tree: {json.dumps(stdout_tree, indent=2)}"
    )

    all_text = json.dumps(stdout_tree)
    assert _SENTINEL_MARKER_TEXT in all_text, (
        f"expected `axial extract`'s output to contain the pre-placed "
        f"sentinel tree's marker text verbatim, proving the persisted tree "
        f"was read and reused rather than the source being re-extracted "
        f"with docling (PRD §5 stage 2 / §8 P0-2). Got output tree: "
        f"{json.dumps(stdout_tree, indent=2)}"
    )

    assert stdout_tree == sentinel_tree, (
        f"expected `axial extract`'s output to be exactly the pre-placed "
        f"sentinel tree (proving verbatim reuse, not re-extraction plus "
        f"incidental sentinel-text passthrough), got:\n"
        f"{json.dumps(stdout_tree, indent=2)}\n"
        f"expected sentinel:\n{json.dumps(sentinel_tree, indent=2)}"
    )

    assert tree_path.read_bytes() == sentinel_bytes, (
        f"expected {tree_path} to remain byte-for-byte unchanged after "
        f"`axial extract` reused it (reuse must not rewrite the persisted "
        f"tree), but its contents differ from what this test wrote."
    )
