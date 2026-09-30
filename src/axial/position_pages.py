"""The argument map rendered as the vault (issue #854, DEC-75 step 1b): one
page per position under `<vault_dir>/positions/`, so Obsidian's Graph View
draws the argument structure instead of nothing.

A page is a pure function of `<map_dir>/positions.jsonl`,
`<map_dir>/relations.jsonl` and the committed vocabularies under
`<vocabulary_dir>`. No model call. Frontmatter carries the position's
sources, member count, and the `claim`/`mechanism`/`position` categories its
member passages were filed under. The body carries the argument sentence,
its variants, a link to each member passage's prose note, and one line per
relation on BOTH endpoints' pages, with the relation's committed kind and
the model's `says`.

The directory is owned by this writer: a page for a position no longer on
the map is deleted, so a rebuilt map never leaves stale nodes in the graph.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from axial.argmap.ask import load_map_relations, load_relation_kinds
from axial.paths import chunk_note_path
from axial.query.reader import source_id_from_chunk_id
from axial.vocabulary import ASSIGNMENTS_FILENAME, ROOT_LEVEL

POSITIONS_SUBDIR = "positions"

# The passage columns whose committed categories a page's frontmatter lists.
CATEGORY_COLUMNS = ("claim", "mechanism", "position")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _chunk_categories(vocabulary_dir: Path, column: str) -> dict[str, set[str]]:
    """`chunk_id -> {category_id}` for one column's level-1 assignments. A
    refused or out-of-scheme answer carries no category and files nothing."""
    by_chunk: dict[str, set[str]] = {}
    for record in _read_jsonl(vocabulary_dir / column / ASSIGNMENTS_FILENAME):
        category_id = record.get("category_id")
        if record.get("level", ROOT_LEVEL) == ROOT_LEVEL and isinstance(category_id, str):
            by_chunk.setdefault(record["chunk_id"], set()).add(category_id)
    return by_chunk


def _position_categories(chunk_ids: list[str], by_chunk: dict[str, set[str]]) -> list[str]:
    """The categories a position's passages were filed under, most passages
    first, ties by id."""
    counts = Counter(c for chunk_id in chunk_ids for c in by_chunk.get(chunk_id, ()))
    return [c for c, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _note_link(vault_dir: Path, chunk_id: str) -> str:
    stem = chunk_note_path(vault_dir, source_id_from_chunk_id(chunk_id), chunk_id).stem
    return f"[[{stem}]]" if stem == chunk_id else f"[[{stem}|{chunk_id}]]"


def _relation_line(relation: dict[str, Any], kind: str | None, outgoing: bool) -> str:
    label = relation.get("relation", "")
    kind_text = f" ({kind})" if kind else ""
    says = relation.get("says", "")
    if outgoing:
        head = f"{label} → [[{relation['to_position_id']}]]"
    else:
        head = f"[[{relation['from_position_id']}]] {label} this"
    return f"- {head}{kind_text}: {says}"


def _render_page(
    position: dict[str, Any],
    categories: dict[str, list[str]],
    relation_lines: list[str],
    vault_dir: Path,
) -> str:
    chunk_ids = list(position.get("chunk_ids", []))
    frontmatter = {
        "position_id": position["position_id"],
        "sources": list(position.get("sources", [])),
        "authors": list(position.get("authors", [])),
        "member_count": len(chunk_ids),
        **categories,
    }
    argument = position.get("argument", "")
    variants = [v for v in position.get("variants", []) if v != argument]

    parts = [f"# {position['position_id']}", argument]
    if variants:
        parts.append("## Variants\n\n" + "\n".join(f"- {v}" for v in variants))
    parts.append("## Passages\n\n" + "\n".join(f"- {_note_link(vault_dir, c)}" for c in chunk_ids))
    if relation_lines:
        parts.append("## Relations\n\n" + "\n".join(relation_lines))

    frontmatter_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    return f"---\n{frontmatter_yaml}---\n" + "\n\n".join(parts) + "\n"


def write_position_pages(*, map_dir: Path, vocabulary_dir: Path, vault_dir: Path) -> dict[str, int]:
    """(Re)write `<vault_dir>/positions/`, one page per position in
    `<map_dir>/positions.jsonl`. Returns the page count and how many
    positions no relation touches (the isolated nodes Graph View shows)."""
    map_dir, vocabulary_dir, vault_dir = Path(map_dir), Path(vocabulary_dir), Path(vault_dir)
    positions = _read_jsonl(map_dir / "positions.jsonl")
    relations = load_map_relations(map_dir)
    kinds = load_relation_kinds(vocabulary_dir)
    by_chunk = {column: _chunk_categories(vocabulary_dir, column) for column in CATEGORY_COLUMNS}

    lines: dict[str, list[tuple[tuple[str, ...], str]]] = {}
    for relation in relations:
        kind = kinds.kind_of(relation) if kinds is not None else None
        src, dst = relation["from_position_id"], relation["to_position_id"]
        key = (src, dst, relation.get("relation", ""))
        lines.setdefault(src, []).append(((0, *key), _relation_line(relation, kind, True)))
        lines.setdefault(dst, []).append(((1, *key), _relation_line(relation, kind, False)))

    out_dir = vault_dir / POSITIONS_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    written: set[str] = set()
    isolated = 0
    for position in sorted(positions, key=lambda p: p["position_id"]):
        position_id = position["position_id"]
        relation_lines = [line for _, line in sorted(lines.get(position_id, []))]
        isolated += not relation_lines
        categories = {
            column: _position_categories(position.get("chunk_ids", []), by_chunk[column])
            for column in CATEGORY_COLUMNS
        }
        page = _render_page(position, categories, relation_lines, vault_dir)
        path = out_dir / f"{position_id}.md"
        path.write_bytes(page.encode("utf-8"))
        written.add(path.name)

    for stale in out_dir.glob("*.md"):
        if stale.name not in written:
            stale.unlink()

    return {"position_pages_written": len(written), "position_pages_isolated": isolated}
