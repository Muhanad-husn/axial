"""Citation rendering mode (issue #690): a `locator` (book + chapter/
section, no book text) or a full quoted `passage`, picked once by the
deployer through `AXIAL_CITATION_MODE` and applied at the API boundary
(`axial.service.api`) -- no request field lets a client choose it, and no
"third mode for later" (#690's own tripwire).

**Two premise corrections shaped this module.** First, there is no page
number anywhere in this system: neither `axial.chunk` nor the extract path
persists one, and the finest per-note location the corpus carries is
`axial.query.store`'s `notes.section`/`notes.chapter` (chapter is derived
from a source's own table of contents at materialize time). A locator is
built from those two fields plus the source's own `author`/`title`/`date`
(`sources`), never a fabricated page (`axial.query.store.note_locator`).
Second, the §7.3 analysis record already carries no passage text -- a
claim's `grounds` and a `counter_position`'s own `grounds` are both
`{ref_type, ref_id}` pointers (`axial.answer.record`, `axial.analyze.
synthesis`), never a quote. `GET /asks/{id}/paper` already meets `locator`
mode's "no book text" bar with the record untouched.

**So this module is additive, not subtractive.** `render_record_for_serving`
attaches a `citation` block beside every `chunk` ground it can resolve --
`{source_id, author, title, date, chapter, section}` in both modes, plus
`quote` (the passage itself, `axial.query.reader.get_chunk(...).chunk_text`)
only in `passage` mode. A ground that does not resolve (`vault_dir` has no
store, or the chunk is missing from it -- a test fixture, or a corpus
predating the store) is left exactly as the record already had it: no
`citation` key, never a placeholder full of nulls.

**Every other served surface was checked and carries no book text either**
(#690's own instruction): `interrogation.premises_found`/`bounds_applied`
are the model's own summarizing prose, never a verbatim quote; `trajectory`
entries carry tool names, args and chunk ids, never note text
(`axial.retrieve.loop`); and `GET /asks/{id}/events`' SSE frames narrate
tool actions and counts (`axial.llm.emit_event`'s callers), also never note
text. Nothing on that surface needed a change."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from axial.query import store
from axial.query.reader import ChunkNotFoundError, get_chunk

LOCATOR = "locator"
PASSAGE = "passage"
CITATION_MODES = (LOCATOR, PASSAGE)

# Mirrors the `AXIAL_ROLE`/`AXIAL_QUOTA_ASKS_PER_DAY` seam
# (`axial.ask.role`, `axial.service.quotas`): one env var, one documented
# default, read at the edge, no config file.
CITATION_MODE_ENV_VAR = "AXIAL_CITATION_MODE"


class InvalidCitationModeError(ValueError):
    """Raised when `AXIAL_CITATION_MODE` (or an explicit override) names
    anything outside `CITATION_MODES` -- a startup error, not a silent
    fallback to the default (#690's own "done when")."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__(
            f"{CITATION_MODE_ENV_VAR}={value!r} is not a valid citation mode -- "
            f"use one of {LOCATOR!r} or {PASSAGE!r}"
        )


def resolve_citation_mode(
    explicit: str | None = None, *, env: Mapping[str, str] | None = None
) -> str:
    """The active citation mode: `explicit` when given (a caller's own
    override, e.g. a test), otherwise `AXIAL_CITATION_MODE` from `env`
    (defaulting to `os.environ`), defaulting to `locator` when that is
    unset or blank -- a fresh install is safe unconfigured (#690's first
    "done when")."""
    source = env if env is not None else os.environ
    raw = explicit if explicit is not None else source.get(CITATION_MODE_ENV_VAR)
    value = (raw or LOCATOR).strip().lower()
    if value not in CITATION_MODES:
        raise InvalidCitationModeError(value)
    return value


def _resolve_chunk_citation(
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
    return citation


def _resolve_grounds(grounds: Any, *, citation_mode: str, vault_dir: Path | None) -> None:
    """Attach `citation` to every resolvable `chunk` entry of `grounds`, in
    place. An `artifact` ground (or any other `ref_type`) is left
    untouched -- `axial.query.reader.ArtifactNote` carries no chunk text to
    leak, so there is nothing for either mode to add or withhold."""
    if not isinstance(grounds, list):
        return
    for ground in grounds:
        if not isinstance(ground, dict) or ground.get("ref_type") != "chunk":
            continue
        citation = _resolve_chunk_citation(
            ground.get("ref_id"), citation_mode=citation_mode, vault_dir=vault_dir
        )
        if citation is not None:
            ground["citation"] = citation


def render_record_for_serving(
    record: dict[str, Any], *, citation_mode: str, vault_dir: Path | None
) -> dict[str, Any]:
    """`record` (the §7.3 analysis record `GET /asks/{id}/paper` serves),
    with every `chunk` ground's citation resolved for the caller's own
    `citation_mode`. Mutates and returns `record` in place -- it was just
    freshly parsed from JSON by the caller (`axial.service.api.get_paper`),
    never the on-disk file, so there is nothing else holding a reference to
    mutate out from under."""
    claims = record.get("claims")
    if isinstance(claims, list):
        for claim in claims:
            if isinstance(claim, dict):
                _resolve_grounds(
                    claim.get("grounds"), citation_mode=citation_mode, vault_dir=vault_dir
                )
    counter_position = record.get("counter_position")
    if isinstance(counter_position, dict):
        _resolve_grounds(
            counter_position.get("grounds"), citation_mode=citation_mode, vault_dir=vault_dir
        )
    return record
