"""Outer acceptance test for issue #14, slice 02 (structural extraction).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a born-digital fixture PDF containing prose sections and at least one
      table or figure
When  the user runs `axial extract <fixture>`
Then  it exits 0 and emits a hierarchical structural tree
And   the tree marks prose sections and non-text artifacts as distinct node
      types
And   each node preserves its source ordering / section provenance

See specs/PRODUCT.md §5 stage 2 (structural extraction: run docling to
produce a hierarchical tree that separates prose sections from non-text
artifacts; output: structural tree) and §8 P0-2 (docling produces a
hierarchical tree separating prose from non-text artifacts; on
docling failure/degenerate output for a source, Unstructured runs as
fallback -- out of scope for this slice, see slice 03) for the source of
truth.

Output-contract decision (this test's locked contract; the implementer
builds to this shape):

- `axial extract <file>` prints a single JSON document to stdout.
- The JSON is a hierarchical tree: a root object with a `children` list,
  where each child may itself carry a `children` list (nesting), giving the
  tree depth > 1 -- NOT a flat list of nodes.
- Every node is an object carrying at minimum:
    - `type`: one of `"prose"` (a prose section/paragraph run) or
      `"artifact"` (a non-text element: table, figure, etc.) -- prose and
      artifact nodes must be distinguishable by this field alone.
    - `order`: an integer or string giving the node's stable source
      position (e.g. a running index or a dotted section path) so
      downstream provenance/ordering is reconstructible.
- The root node itself is not required to carry `type`/`order` (it is the
  tree container), but every node in `children` (recursively) must.
"""

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "extract"

PROSE_AND_TABLE_PDF = FIXTURES_DIR / "prose_and_table.pdf"

# argparse's fallback error for an as-yet-nonexistent `extract` subcommand,
# e.g. "axial: error: argument command: invalid choice: 'extract' (choose
# from 'schema', 'intake')". Any of these substrings appearing in the
# combined output means extract logic was never actually exercised -- the
# process failed before real extract code ran, not because of a genuine
# structural-extraction decision. Reject that generic failure mode
# explicitly so this test can only pass once real `extract` behavior
# exists.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
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
            f"fallback (found {marker!r}) -- this means the `extract` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _iter_nodes(node: dict) -> list:
    """Depth-first flatten of a tree node's descendants (not including node itself)."""
    collected = []
    for child in node.get("children", []):
        collected.append(child)
        collected.extend(_iter_nodes(child))
    return collected


def _max_depth(node: dict, depth: int = 0) -> int:
    children = node.get("children", [])
    if not children:
        return depth
    return max(_max_depth(child, depth + 1) for child in children)


def test_extract_emits_hierarchical_tree_distinguishing_prose_and_artifacts():
    result = _run_extract(str(PROSE_AND_TABLE_PDF))

    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 for a born-digital PDF with prose + a table, "
        f"got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    stdout = result.stdout.strip()
    try:
        tree = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"expected `axial extract` to print a single JSON document to "
            f"stdout, but it did not parse as JSON ({exc}):\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        ) from None

    assert isinstance(tree, dict), (
        f"expected the top-level JSON output to be an object (the tree "
        f"root), got {type(tree).__name__}: {tree!r}"
    )

    # Hierarchical, not flat: depth > 1 means at least one child has its
    # own children (i.e. the tree nests, it isn't a one-level list of
    # sibling nodes hanging off the root).
    depth = _max_depth(tree)
    assert depth > 1, (
        f"expected a hierarchical tree with nesting depth > 1 (nodes "
        f"containing children, not a flat list under the root), got "
        f"max depth {depth}. Full tree: {json.dumps(tree, indent=2)}"
    )

    all_nodes = _iter_nodes(tree)
    assert all_nodes, (
        f"expected the tree to contain at least one node under the root, "
        f"got none. Full tree: {json.dumps(tree, indent=2)}"
    )

    for node in all_nodes:
        assert "type" in node, (
            f"expected every tree node to carry a `type` field distinguishing "
            f"prose from artifact nodes, missing on node: {node!r}"
        )
        assert "order" in node, (
            f"expected every tree node to carry an `order` field (stable "
            f"source position / provenance), missing on node: {node!r}"
        )

    node_types = {node["type"] for node in all_nodes}
    assert "prose" in node_types, (
        f"expected at least one node of type 'prose' among the tree's "
        f"nodes, got types: {sorted(node_types)}. "
        f"Full tree: {json.dumps(tree, indent=2)}"
    )
    assert "artifact" in node_types, (
        f"expected at least one node of type 'artifact' (the fixture's "
        f"table) among the tree's nodes, got types: {sorted(node_types)}. "
        f"Full tree: {json.dumps(tree, indent=2)}"
    )


def test_extract_nonexistent_file_does_not_crash_uninformatively():
    missing = FIXTURES_DIR / "does_not_exist.pdf"
    result = _run_extract(str(missing))

    _assert_not_argparse_fallback(result)

    assert result.returncode != 0, (
        f"expected nonzero exit code for a nonexistent source file, got 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    combined = result.stdout + result.stderr
    assert missing.name in combined, (
        f"expected the error message to name the missing file "
        f"{missing.name!r}, got:\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
