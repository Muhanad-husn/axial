"""The bibliography, generated from source metadata (specs/PHASE-C.md §7.6,
§8 P0-6).

**Zero model calls**, for exactly the sources cited: the `source_id`s
reachable from the grounds of the record's claims. A source that appears in a
named analysis record but is never cited in this paper does not appear.

Three rules carry forward from PRODUCT.md §7.13 and are load-bearing here.

- **An absent field renders as a stated absence, never a blank and never a
  guess.** The source-metadata record distinguishes a value, `unavailable` (a
  read was attempted and found nothing), and `not_attempted` (no read has
  run). Those are three different facts about the world and the bibliography
  keeps them apart. A wrong value that looks right is more dangerous than an
  honest gap.
- **The filename is never a source** for any field. Not title, not author, not
  date, not publisher.
- **Provenance travels with the value.** Where a field came from embedded
  metadata, the title page or an identifier lookup, the entry says so.

Ordering is deterministic -- author surname where known, then title, then
`source_id` -- so the same record always renders the same bibliography.

The entry carries **no source text** and no verbatim excerpts (DEC-23). It is
metadata only.

Imports reach the vault through `axial.query.reader` rather than
`axial.answer.source_usage`, which has the same `source_ids_for_grounds`
helper: importing that module executes `axial/answer/__init__.py`, which pulls
`run_brief` and the whole Phase-B orchestrator into Phase C's import graph and
would break §3 non-goal 1's structural guarantee. The query layer is what §12
permits, and it is verified clean of the run path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from axial.intake import NOT_ATTEMPTED, SOURCE_META_DIR, UNAVAILABLE, source_meta_path
from axial.query.reader import get_artifact, source_id_from_chunk_id

# The four §7.6 bibliographic fields, in render order.
BIB_FIELDS: tuple[str, ...] = ("author", "title", "date", "publisher")


class BibliographyError(Exception):
    """Base class for bibliography failures."""


def source_ids_for_claims(
    claims: Iterable[dict[str, Any]], *, vault_dir: Path | None = None
) -> set[str]:
    """Every distinct `source_id` the claims' grounds reach.

    A `chunk` pointer's source is a parse of its id; an `artifact` pointer's
    is read off the artifact. Same derivation Phase B already uses for source
    usage, reached through the query layer rather than through Phase B's own
    answer package."""
    source_ids: set[str] = set()
    for claim in claims:
        for ground in claim.get("grounds") or []:
            if not isinstance(ground, dict):
                continue
            ref_type, ref_id = ground.get("ref_type"), ground.get("ref_id")
            if not isinstance(ref_id, str):
                continue
            if ref_type == "chunk":
                source_ids.add(source_id_from_chunk_id(ref_id))
            elif ref_type == "artifact":
                source_ids.add(get_artifact(ref_id, vault_dir=vault_dir).source_id)
    return source_ids


def _field(source_meta: dict[str, Any], field: str) -> dict[str, Any]:
    """One §7.6 field as `{value, provenance}` or a stated absence.

    A key the record does not carry at all is `not_attempted` -- no read has
    run for it -- never a blank that reads like an empty answer. This mirrors
    `axial.vault.bibliographic_value`'s own three-state contract; it is
    restated rather than reused because that helper returns only the value and
    drops the provenance §7.6 requires travel with it."""
    raw = source_meta.get(field, NOT_ATTEMPTED)
    if isinstance(raw, dict):
        value = raw.get("value")
        if value:
            return {"value": value, "provenance": raw.get("provenance")}
        return {"absent": UNAVAILABLE}
    if raw in (UNAVAILABLE, NOT_ATTEMPTED):
        return {"absent": raw}
    return {"value": raw, "provenance": None}


def _read_source_meta(source_id: str, source_meta_dir: Path) -> dict[str, Any]:
    """The persisted metadata record, or an all-absent stand-in.

    A source with no record renders every field as `not_attempted` rather than
    failing the run (§12): a missing record is the honest statement that no
    read has happened, which is exactly what the sentinel means. Phase B's
    `read_source_meta` raises instead, which is right for a write path and
    wrong here -- a bibliography that refuses to render because one of thirty
    sources lacks metadata helps nobody."""
    path = source_meta_path(source_id, source_meta_dir)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def _surname(entry: dict[str, Any]) -> str:
    """The author surname an entry sorts under, or "" when unknown.

    Deliberately crude -- the last whitespace-separated token of the first
    listed author. §7.6 asks only for a deterministic order, not a correct
    onomastic one, and a real name parser here would be a mechanism nothing
    reads (`van der Berg` and `Jr.` both sort somewhere stable and wrong,
    which costs a reader nothing and costs the build nothing to leave)."""
    author = entry.get("author") or {}
    value = author.get("value")
    if not isinstance(value, str) or not value.strip():
        return ""
    first = value.split(",")[0].split(" and ")[0].strip()
    return first.split()[-1].casefold() if first else ""


def _title_key(entry: dict[str, Any]) -> str:
    title = (entry.get("title") or {}).get("value")
    return title.casefold() if isinstance(title, str) else ""


def build_bibliography(
    claims: Iterable[dict[str, Any]],
    *,
    source_meta_dir: Path | None = None,
    vault_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """The §7.6 bibliography for exactly the sources the claims cite.

    Deterministic and model-free: given the same claims and the same metadata
    records, this returns the same list in the same order, every time."""
    source_meta_dir = Path(source_meta_dir) if source_meta_dir is not None else SOURCE_META_DIR
    claims = list(claims)

    entries: list[dict[str, Any]] = []
    for source_id in sorted(source_ids_for_claims(claims, vault_dir=vault_dir)):
        source_meta = _read_source_meta(source_id, source_meta_dir)
        entry: dict[str, Any] = {"source_id": source_id}
        for field in BIB_FIELDS:
            entry[field] = _field(source_meta, field)
        entries.append(entry)

    entries.sort(key=lambda entry: (_surname(entry), _title_key(entry), entry["source_id"]))
    return entries


def format_field(field: dict[str, Any]) -> str:
    """One field rendered for the page: the value with its provenance, or the
    absence stated in words a reader can act on."""
    if "absent" in field:
        if field["absent"] == UNAVAILABLE:
            return "[unavailable - a read was attempted and found nothing]"
        return "[not attempted - no read has run for this field]"
    provenance = field.get("provenance")
    value = field.get("value")
    return f"{value} (from {provenance})" if provenance else str(value)
