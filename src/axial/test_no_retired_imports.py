"""Pinning test for issue #853 (DEC-75): Gather, its grounding eval, and the
name retrieval arm's eight walk tools are DELETED, not disabled. A module
that still imports one of them is a sign the deletion was only partial --
this walks every `.py` file under `src/axial` and fails loudly on the first
one that does.

`axial.names` (Reconcile's own inventory/similarity module, slice 04) is
untouched by this issue and is not one of the retired modules: only
`axial.gather`/`axial.gather_eval` (the disagreement pass and its eval) are
retired. The eight walk tools were never their own module -- they were
functions in `axial.query.names` (`find_names`, `get_name`, `name_neighbors`,
`who_cites`, `who_argues_against`, `where_names_meet`) and `axial.query.
relations` (`names_arguing_against`, `opposition_pairs`) -- so this checks
for imports of the SIX names that no longer exist in `axial.query.names` at
all (the other two survive in `axial.query.relations` as plain functions,
just no longer registered as loop tools; see `axial.retrieve.tools`)."""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent

RETIRED_MODULES = frozenset({"axial.gather", "axial.gather_eval"})

# The six `axial.query.names` symbols retired outright (issue #853): a page
# reader, a page-walking traversal, or the embedding-fallback resolver.
# `find_names`/`get_name`/`coverage_count`/`canonical_for_surface` survive.
RETIRED_QUERY_NAMES_SYMBOLS = frozenset(
    {
        "name_neighbors",
        "who_cites",
        "who_argues_against",
        "where_names_meet",
        "resolve_encoder_model_name",
        "DISAGREEMENT_HEADING",
    }
)


def _iter_source_files():
    for path in sorted(SRC_ROOT.rglob("*.py")):
        # Never read this file's own literal strings as a violation of
        # itself -- the names above have to appear here as plain strings.
        if path == Path(__file__).resolve():
            continue
        yield path


def _imported_module_names(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _imported_from_query_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "axial.query.names":
            names.update(alias.name for alias in node.names)
    return names


def test_no_module_imports_gather_or_gather_eval():
    violations: list[str] = []
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hit = _imported_module_names(tree) & RETIRED_MODULES
        if hit:
            violations.append(f"{path.relative_to(SRC_ROOT.parent.parent)}: imports {sorted(hit)}")
    assert not violations, "retired module still imported:\n" + "\n".join(violations)


def test_no_module_imports_the_retired_name_layer_walk_tools():
    violations: list[str] = []
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hit = _imported_from_query_names(tree) & RETIRED_QUERY_NAMES_SYMBOLS
        if hit:
            violations.append(f"{path.relative_to(SRC_ROOT.parent.parent)}: imports {sorted(hit)}")
    assert not violations, "retired query.names symbol still imported:\n" + "\n".join(violations)


def test_gather_and_gather_eval_modules_do_not_exist_on_disk():
    assert not (SRC_ROOT / "gather.py").is_file()
    assert not (SRC_ROOT / "gather_eval.py").is_file()
