"""Offline canonical polity normalization map (issue #205, slice 01;
plans/polity-normalization/01-canonical-map.md; specs/PRODUCT.md Appendix C,
Sec 11 step 7).

A **deterministic, offline, model-free** downstream reconciliation layer: it
folds alias and historical polity verbatims (the free-text `polity`/
`polities_touched` values the tagging pass already emitted, Appendix C) to a
canonical referent, without ever gating or rewriting the tagger's own output.
It is a *living* map -- growable by hand-editing
`<domain_dir>/polity_canonical.yaml` -- and *never a closed gate*: an unmapped
verbatim is accepted, logged as a candidate, and passed through unchanged.

Three pieces:

  - `load_polity_canonical` reads the canonical tree and flattens it into a
    normalized `alias|canonical -> node` index. The same normalized string
    naming two different nodes (via alias or canonical name) is an
    unresolvable ambiguity -- `AmbiguousAliasError` -- because it would
    silently blanket-merge two distinct referents (the "distinguish, don't
    blanket-merge" guarantee: `Scotland`/`England` as children of `United
    Kingdom`, `North Korea`/`South Korea` as unrelated siblings).
  - `canonicalize` resolves one verbatim against a loaded map: `mapped` (an
    exact, normalized alias/canonical match -- a CHILD node's own alias names
    the child, never its parent), `leak` (the verbatim splits on a
    multi-polity separator into >= 2 parts that EACH independently
    canonicalize to a known node -- e.g. "Syria and Lebanon" -- surfaced as a
    flag, never folded to either part; "Bosnia and Herzegovina" is NOT a leak
    because its parts are not standalone nodes), or `candidate` (no match,
    passthrough unchanged, non-fatal).
  - `harvest_vault_polities` / `run_polity_build` / `run_polity_report` are the
    vault-facing operations backing `axial polity build` (a deterministic seed
    tree scanned from vault prose, reusing `axial.gold`'s frontmatter-scan
    pattern) and `axial polity report` (the post-run notification: mapped/
    candidate/leak lists plus a candidate count, non-fatal at any scale).

Matching is explicit-alias/exact only (casefold + collapse/trim whitespace) --
NEVER substring/prefix/fuzzy -- so siblings never collapse under a naive rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH
from axial.tag import DEFAULT_DOMAIN_DIR
from axial.vault import _default_vault_dir

CANONICAL_MAP_FILENAME = "polity_canonical.yaml"


class PolityCanonicalError(Exception):
    """Base class for all canonical polity-map loading errors."""


class MissingPolityCanonicalFileError(PolityCanonicalError):
    """Raised when `<domain_dir>/polity_canonical.yaml` does not exist."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"missing polity canonical map: {path}")


class MalformedPolityCanonicalError(PolityCanonicalError):
    """Raised when `polity_canonical.yaml` is not valid YAML, or its
    top-level/node shape does not match the documented contract."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"polity canonical map at {path} is malformed: {reason}")


class MissingVersionError(PolityCanonicalError):
    """Raised when `polity_canonical.yaml` carries no top-level `version` key."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"polity canonical map at {path} is missing a top-level 'version' key")


class AmbiguousAliasError(PolityCanonicalError):
    """Raised when the same normalized alias/canonical name maps to two
    DIFFERENT nodes -- this is what enforces "distinguish, don't
    blanket-merge": folding two distinct referents under one shared alias
    would silently collapse them."""

    def __init__(self, verbatim: str, first_canonical: str, second_canonical: str):
        self.verbatim = verbatim
        self.first_canonical = first_canonical
        self.second_canonical = second_canonical
        super().__init__(
            f"ambiguous polity alias {verbatim!r}: maps to both "
            f"{first_canonical!r} and {second_canonical!r} -- an alias/"
            f"canonical name must resolve to exactly one node"
        )


@dataclass
class PolityNode:
    canonical: str
    kind: str = "modern"
    aliases: list[str] = field(default_factory=list)
    children: list["PolityNode"] = field(default_factory=list)


@dataclass
class PolityCanonical:
    version: int
    nodes: list[PolityNode]
    index: dict[str, PolityNode]


@dataclass
class CanonResult:
    verbatim: str
    status: str  # "mapped" | "candidate" | "leak"
    canonical: str | None = None
    parts: list[str] | None = None


def _normalize(text: str) -> str:
    """Casefold + collapse/trim whitespace -- the exact-match normalization
    key. Never substring/prefix/fuzzy."""
    return re.sub(r"\s+", " ", text.strip()).casefold()


def _register(index: dict[str, PolityNode], key: str, node: PolityNode, path: Path) -> None:
    normalized = _normalize(key)
    existing = index.get(normalized)
    if existing is not None and existing is not node:
        raise AmbiguousAliasError(key, existing.canonical, node.canonical)
    index[normalized] = node


def _build_node(raw_node: Any, index: dict[str, PolityNode], path: Path) -> PolityNode:
    if not isinstance(raw_node, dict) or not raw_node.get("canonical"):
        raise MalformedPolityCanonicalError(
            path, f"every node must be a mapping with a non-empty 'canonical' key, got {raw_node!r}"
        )

    canonical = str(raw_node["canonical"])
    kind = raw_node.get("kind") or "modern"
    aliases_raw = raw_node.get("aliases") or []
    if not isinstance(aliases_raw, list):
        raise MalformedPolityCanonicalError(
            path, f"node {canonical!r}'s 'aliases' must be a list, got {aliases_raw!r}"
        )
    aliases = [str(alias) for alias in aliases_raw]

    node = PolityNode(canonical=canonical, kind=str(kind), aliases=aliases, children=[])
    _register(index, canonical, node, path)
    for alias in aliases:
        _register(index, alias, node, path)

    children_raw = raw_node.get("children") or []
    if not isinstance(children_raw, list):
        raise MalformedPolityCanonicalError(
            path, f"node {canonical!r}'s 'children' must be a list, got {children_raw!r}"
        )
    for child_raw in children_raw:
        node.children.append(_build_node(child_raw, index, path))

    return node


def load_polity_canonical(domain_dir: str | Path) -> PolityCanonical:
    """Load and validate `<domain_dir>/polity_canonical.yaml`: a `version` +
    a list of `nodes` (each with `canonical`, `kind`, `aliases`, optional
    nested `children`), flattened into a normalized `alias|canonical -> node`
    index. Raises `MissingPolityCanonicalFileError`, `MalformedPolityCanonicalError`,
    `MissingVersionError`, or `AmbiguousAliasError` (a duplicate alias across
    two different nodes)."""
    path = Path(domain_dir) / CANONICAL_MAP_FILENAME
    if not path.is_file():
        raise MissingPolityCanonicalFileError(path)

    with path.open("r", encoding="utf-8") as handle:
        try:
            raw = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise MalformedPolityCanonicalError(path, str(exc)) from exc

    if not isinstance(raw, dict):
        raise MalformedPolityCanonicalError(path, f"top level must be a mapping, got {raw!r}")
    if "version" not in raw:
        raise MissingVersionError(path)

    nodes_raw = raw.get("nodes") or []
    if not isinstance(nodes_raw, list):
        raise MalformedPolityCanonicalError(path, f"'nodes' must be a list, got {nodes_raw!r}")

    index: dict[str, PolityNode] = {}
    nodes = [_build_node(node_raw, index, path) for node_raw in nodes_raw]

    return PolityCanonical(version=raw["version"], nodes=nodes, index=index)


# Multi-polity separators (the plan's exact list): " and ", ", ", "/", " & ".
_LEAK_SEPARATOR_PATTERN = re.compile(r"\s+and\s+|\s*,\s*|\s*/\s*|\s+&\s+")


def _split_multi_polity(verbatim: str) -> list[str]:
    parts = [part.strip() for part in _LEAK_SEPARATOR_PATTERN.split(verbatim)]
    return [part for part in parts if part]


def canonicalize(verbatim: str, cmap: PolityCanonical) -> CanonResult:
    """Resolve one verbatim against `cmap`. `mapped` on an exact normalized
    alias/canonical match (a child node's own alias resolves to the child,
    never the parent); `leak` when the verbatim splits into >= 2 parts that
    EACH independently match a node (surfaced, never folded); otherwise
    `candidate` (passthrough unchanged, non-fatal)."""
    node = cmap.index.get(_normalize(verbatim))
    if node is not None:
        return CanonResult(verbatim=verbatim, status="mapped", canonical=node.canonical)

    parts = _split_multi_polity(verbatim)
    if len(parts) >= 2:
        part_nodes = [cmap.index.get(_normalize(part)) for part in parts]
        if all(part_node is not None for part_node in part_nodes):
            return CanonResult(verbatim=verbatim, status="leak", parts=parts)

    return CanonResult(verbatim=verbatim, status="candidate")


def _split_frontmatter(text: str) -> dict[str, Any] | None:
    """Parse a note's `---`-delimited YAML frontmatter block into a mapping,
    or None if the text is not a well-formed note. Duplicated (rather than
    imported) from `axial.gold` to avoid a private cross-module import; kept
    byte-identical to that scan."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            block = "\n".join(lines[1:index])
            parsed = yaml.safe_load(block)
            return parsed if isinstance(parsed, dict) else None
    return None


def harvest_vault_polities(prose_dir: Path) -> dict[str, dict[str, Any]]:
    """Scan every prose note under `prose_dir` (sorted, model-free) and
    collect distinct `polity` (`empirical_scope.polity`) and
    `polities_touched[]` verbatims, each with its occurrence count (number of
    notes mentioning it) and the source note ids (`chunk_id`) it came from.
    A verbatim mentioned twice within the SAME note (e.g. both as `polity`
    and inside `polities_touched`) counts once for that note."""
    harvest: dict[str, dict[str, Any]] = {}
    for path in sorted(prose_dir.glob("*.md")):
        frontmatter = _split_frontmatter(path.read_text(encoding="utf-8"))
        if frontmatter is None:
            continue
        chunk_id = frontmatter.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            continue

        verbatims: set[str] = set()
        empirical_scope = frontmatter.get("empirical_scope")
        if isinstance(empirical_scope, dict):
            polity = empirical_scope.get("polity")
            if isinstance(polity, str) and polity.strip():
                verbatims.add(polity.strip())

        polities_touched = frontmatter.get("polities_touched")
        if isinstance(polities_touched, list):
            for item in polities_touched:
                if isinstance(item, str) and item.strip():
                    verbatims.add(item.strip())

        for verbatim in verbatims:
            entry = harvest.setdefault(verbatim, {"count": 0, "notes": []})
            entry["count"] += 1
            entry["notes"].append(chunk_id)

    return harvest


def run_polity_build(
    vault_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> str:
    """Scan the vault prose notes (model-free) and emit a deterministic seed
    canonical tree as YAML text: one root node per distinct polity verbatim,
    sorted, for the operator to curate by hand. Same vault -> identical
    output (a pure function of the vault's own note contents)."""
    if vault_dir is None:
        vault_dir = _default_vault_dir(config_path)

    prose_dir = vault_dir / "prose"
    harvest = harvest_vault_polities(prose_dir) if prose_dir.is_dir() else {}

    nodes = [
        {"canonical": verbatim, "kind": "modern", "aliases": []} for verbatim in sorted(harvest)
    ]
    document = {"version": 1, "nodes": nodes}
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def run_polity_report(
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
    vault_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> dict[str, Any]:
    """Read the vault's collected polity verbatims, canonicalize each against
    `<domain_dir>/polity_canonical.yaml`, and return the report structure:
    `mapped` (verbatim -> canonical node), `candidates` (unmapped verbatim +
    occurrence count + source note ids), `leaks` (multi-polity flags + split
    parts), and `candidate_count` (== len(candidates)). Raises
    `PolityCanonicalError` (missing/malformed map, ambiguous alias) -- never
    silently swallowed; the CLI renders it as a clean `error: ...` line.
    Non-fatal by design otherwise: an unmapped verbatim is always a
    candidate, never an error."""
    cmap = load_polity_canonical(domain_dir)

    if vault_dir is None:
        vault_dir = _default_vault_dir(config_path)
    prose_dir = vault_dir / "prose"
    harvest = harvest_vault_polities(prose_dir) if prose_dir.is_dir() else {}

    mapped: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    leaks: list[dict[str, Any]] = []

    for verbatim in sorted(harvest):
        entry = harvest[verbatim]
        result = canonicalize(verbatim, cmap)
        if result.status == "mapped":
            mapped.append({"verbatim": verbatim, "canonical": result.canonical})
        elif result.status == "leak":
            leaks.append({"verbatim": verbatim, "parts": result.parts})
        else:
            candidates.append(
                {
                    "verbatim": verbatim,
                    "count": entry["count"],
                    "notes": sorted(entry["notes"]),
                }
            )

    return {
        "mapped": mapped,
        "candidates": candidates,
        "leaks": leaks,
        "candidate_count": len(candidates),
    }
