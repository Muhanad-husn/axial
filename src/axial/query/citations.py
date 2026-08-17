"""Resolving a record's `chunk` grounds into citations (issue #690, moved
into the query layer by #783).

`axial.service.citation` owned this until the reader-facing markdown renders
needed the same resolution: a citation that reads `Vignal (2021), ch. 30`
instead of a chunk id needs the store lookup, and `axial.service` is a layer
in FRONT of core -- nothing under `src/axial` core may import it
(`axial/service/__init__.py`). So the resolution lives here, beside the
store it reads, and the service keeps what is genuinely its own: the
deployer's citation mode, read from the environment once at the API
boundary.

Two modes, unchanged. `locator` attaches `{source_id, author, title, date,
chapter, section}` -- where a claim rests, no book text. `passage` attaches
the same plus `quote`, the note's own text. A ground that does not resolve
(no store, or a chunk id absent from it) is left exactly as the record had
it: no `citation` key, never a placeholder full of nulls.

Both modes also attach `display`, the citation as it reads on a page
(`axial.cite.format_citation`), so the web client prints what it is sent
rather than composing a second version of the same string (#786).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from axial.cite import format_citation
from axial.query import store
from axial.query.reader import ChunkNotFoundError, get_chunk

LOCATOR = "locator"
PASSAGE = "passage"
CITATION_MODES = (LOCATOR, PASSAGE)


def resolve_chunk_citation(
    ref_id: Any, *, citation_mode: str, vault_dir: Path | None
) -> dict[str, Any] | None:
    """One `chunk` ground's citation block, or `None` when it cannot be
    resolved -- no `vault_dir`, no store at it, or `ref_id` not in it."""
    if vault_dir is None or not isinstance(ref_id, str) or not ref_id.strip():
        return None
    connection = store.connect(Path(vault_dir))
    if connection is None:
        return None
    try:
        locator = store.note_locator(connection, ref_id)
    finally:
        connection.close()
    if locator is None:
        return None
    citation = dict(locator)
    if citation_mode == PASSAGE:
        try:
            note = get_chunk(ref_id, vault_dir=vault_dir)
        except ChunkNotFoundError:
            pass
        else:
            citation["quote"] = note.chunk_text
    display = format_citation(citation)
    if display is not None:
        citation["display"] = display
    return citation


def resolve_grounds(grounds: Any, *, citation_mode: str, vault_dir: Path | None) -> None:
    """Attach `citation` to every resolvable `chunk` entry of `grounds`, in
    place. An `artifact` ground (or any other `ref_type`) is left
    untouched -- `axial.query.reader.ArtifactNote` carries no chunk text to
    leak, so there is nothing for either mode to add or withhold."""
    if not isinstance(grounds, list):
        return
    for ground in grounds:
        if not isinstance(ground, dict) or ground.get("ref_type") != "chunk":
            continue
        citation = resolve_chunk_citation(
            ground.get("ref_id"), citation_mode=citation_mode, vault_dir=vault_dir
        )
        if citation is not None:
            ground["citation"] = citation


def resolve_record_citations(
    record: dict[str, Any], *, citation_mode: str, vault_dir: Path | None
) -> dict[str, Any]:
    """`record` -- a §7.3 analysis record or a Phase-C paper record, which
    carry claims and a counter-position in the same two shapes -- with every
    `chunk` ground's citation resolved for `citation_mode`. Mutates and
    returns `record` in place; callers hand it a dict they just parsed from
    JSON, never one another object still holds."""
    claims = record.get("claims")
    if isinstance(claims, list):
        for claim in claims:
            if isinstance(claim, dict):
                resolve_grounds(claim.get("grounds"), citation_mode=citation_mode, vault_dir=vault_dir)
    counter_position = record.get("counter_position")
    if isinstance(counter_position, dict):
        resolve_grounds(
            counter_position.get("grounds"), citation_mode=citation_mode, vault_dir=vault_dir
        )
    return record
