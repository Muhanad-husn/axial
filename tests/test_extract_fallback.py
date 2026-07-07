"""Outer acceptance test for issue #15, slice 03 (extraction fallback).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source on which docling fails or returns degenerate (empty/
      structureless) output
When  the user runs `axial extract <fixture>`
Then  it exits 0 having produced a structural tree via the Unstructured
      fallback
And   the run logs that docling failed and Unstructured was used for that
      source
And   the fallback tree uses the same prose/artifact node shape as the
      docling path

See specs/PRODUCT.md §5 stage 2 ("Structural extraction. Run docling to
produce a hierarchical tree that separates prose sections from non-text
artifacts. If docling fails or produces degenerate output on a source, fall
back to Unstructured for that source. Output: structural tree.") and §8 P0-2
second bullet ("On docling failure/degenerate output for a source,
Unstructured runs as fallback for that source; the fallback is logged.") for
the source of truth.

Failure-injection seam (design decision locked by this test)
--------------------------------------------------------------
docling cannot be made to genuinely fail or degenerate deterministically
through a subprocess invocation, so this slice introduces an environment
variable fault-injection seam that production code must honor:

    AXIAL_FORCE_DOCLING_FAILURE
        unset / ""    -> normal docling behavior (slice-02 path, unchanged)
        "exception"   -> the docling step is forced to raise; the exception
                         is caught and routed to the Unstructured fallback
        "degenerate"  -> the docling step is forced to return empty /
                         structureless output; the degeneracy detector flags
                         it and routes to the Unstructured fallback

Both modes must land in the fallback path and both must be logged.

Output-contract decision (reuses slice 02's locked contract; see
tests/test_extract.py)
-----------------------------------------------------------------------
- `axial extract <file>` still prints a single JSON document to stdout on
  the fallback path -- pure JSON, nothing else, so downstream tooling can
  pipe stdout straight into a JSON parser.
- The JSON is a hierarchical tree: a root object with a `children` list,
  where nodes may nest (tree depth > 1).
- Every node under the root (recursively) carries `type` (one of "prose" or
  "artifact") and `order` (a stable source-position marker).
- Unlike slice 02's happy-path test, this test does NOT require an
  "artifact" node in the fallback tree: Unstructured's fast (text-first)
  strategy may not re-detect the fixture's table as a distinct artifact.
  Requiring one here would over-constrain a text-first fallback and turn a
  legitimate shape difference into a spurious failure. What IS required:
  the tree is schema-conformant (valid `type`/`order` on every node),
  non-empty, hierarchical (depth > 1), and contains at least one "prose"
  node.
- The fallback event is logged to stderr (not stdout, so stdout stays pure
  JSON). The log must give evidence that (a) docling failed or degenerated,
  (b) Unstructured was used as a result, and (c) the source file is named --
  this is exactly the per-source judgment record P1-3 depends on later.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "extract"

PROSE_AND_TABLE_PDF = FIXTURES_DIR / "prose_and_table.pdf"

FORCE_FAILURE_ENV_VAR = "AXIAL_FORCE_DOCLING_FAILURE"

# Mirrors tests/test_extract.py's guard: reject the generic argparse-fallback
# failure mode so this test can only pass once real fallback behavior exists.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)

# Lowercased substrings that together unambiguously prove the fallback fired:
# the log must name the docling failure, name Unstructured as the mitigation,
# and explicitly call it a fallback. Exact wording beyond these substrings is
# left to the implementer.
FALLBACK_LOG_MARKERS = ("docling", "unstructured", "fallback")


def _run_extract_with_forced_failure(mode: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[FORCE_FAILURE_ENV_VAR] = mode
    return subprocess.run(
        ["uv", "run", "axial", "extract", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `extract` fallback behavior path, not an "
            f"argparse fallback (found {marker!r}) -- this means the "
            f"`extract` subcommand does not exist yet or was never reached:\n"
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


@pytest.mark.parametrize("mode", ["exception", "degenerate"])
def test_extract_falls_back_to_unstructured_on_forced_docling_failure(mode):
    """Both forced-failure modes must exit 0, log the fallback on stderr, and
    still emit a schema-conformant structural tree on stdout."""
    result = _run_extract_with_forced_failure(mode, str(PROSE_AND_TABLE_PDF))

    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 when docling is forced to {mode!r} and the "
        f"Unstructured fallback is used, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # --- stderr must prove the fallback actually fired for THIS source ---
    stderr_lower = result.stderr.lower()
    for marker in FALLBACK_LOG_MARKERS:
        assert marker in stderr_lower, (
            f"expected the fallback log (stderr) to contain {marker!r} as "
            f"evidence that docling failed/degenerated and Unstructured was "
            f"used as a result (forced mode: {mode!r}), got:\n"
            f"stderr: {result.stderr!r}"
        )
    assert PROSE_AND_TABLE_PDF.name in result.stderr, (
        f"expected the fallback log (stderr) to name the source file "
        f"{PROSE_AND_TABLE_PDF.name!r} (forced mode: {mode!r}), got:\n"
        f"stderr: {result.stderr!r}"
    )

    # --- stdout must still be pure, schema-conformant JSON tree ---
    stdout = result.stdout.strip()
    try:
        tree = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"expected `axial extract` to print a single JSON document to "
            f"stdout even on the fallback path (forced mode: {mode!r}), but "
            f"it did not parse as JSON ({exc}):\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        ) from None

    assert isinstance(tree, dict), (
        f"expected the top-level JSON output to be an object (the tree "
        f"root), got {type(tree).__name__}: {tree!r} (forced mode: {mode!r})"
    )

    depth = _max_depth(tree)
    assert depth > 1, (
        f"expected a hierarchical tree with nesting depth > 1 on the "
        f"fallback path (forced mode: {mode!r}), got max depth {depth}. "
        f"Full tree: {json.dumps(tree, indent=2)}"
    )

    all_nodes = _iter_nodes(tree)
    assert all_nodes, (
        f"expected the fallback tree to contain at least one node under "
        f"the root (forced mode: {mode!r}), got none. "
        f"Full tree: {json.dumps(tree, indent=2)}"
    )

    valid_types = {"prose", "artifact"}
    for node in all_nodes:
        assert "type" in node, (
            f"expected every fallback tree node to carry a `type` field "
            f"(forced mode: {mode!r}), missing on node: {node!r}"
        )
        assert node["type"] in valid_types, (
            f"expected every node's `type` to be one of {sorted(valid_types)} "
            f"(forced mode: {mode!r}), got {node['type']!r} on node: {node!r}"
        )
        assert "order" in node, (
            f"expected every fallback tree node to carry an `order` field "
            f"(forced mode: {mode!r}), missing on node: {node!r}"
        )

    # Deliberately NOT required here: an "artifact" node. Unstructured's
    # fast (text-first) strategy may not re-detect the fixture's table, and
    # requiring one would over-constrain a legitimately text-first fallback.
    node_types = {node["type"] for node in all_nodes}
    assert "prose" in node_types, (
        f"expected at least one node of type 'prose' among the fallback "
        f"tree's nodes (forced mode: {mode!r}), got types: "
        f"{sorted(node_types)}. Full tree: {json.dumps(tree, indent=2)}"
    )


def test_extract_does_not_fall_back_when_docling_succeeds_normally():
    """No-regression guard: with the seam unset, no fallback log should
    appear -- the seam must not leak into the normal (slice-02) path."""
    env = dict(os.environ)
    env.pop(FORCE_FAILURE_ENV_VAR, None)
    result = subprocess.run(
        ["uv", "run", "axial", "extract", str(PROSE_AND_TABLE_PDF)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )

    _assert_not_argparse_fallback(result)

    assert result.returncode == 0, (
        f"expected exit code 0 for the unmodified happy path, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    stderr_lower = result.stderr.lower()
    assert "fallback" not in stderr_lower, (
        f"expected no fallback to be logged when docling succeeds normally "
        f"(seam unset), got:\nstderr: {result.stderr!r}"
    )
