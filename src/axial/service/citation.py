"""Citation rendering mode (issue #690): a `locator` (book + chapter/
section, no book text) or a full quoted `passage`, picked once by the
deployer through `AXIAL_CITATION_MODE` and applied at the API boundary
(`axial.service.api`) -- no request field lets a client choose it, and no
"third mode for later" (#690's own tripwire). Issue #732 reuses
`render_record_for_serving` for the persisted `.md` `axial ask`/`axial
brief run` writes at the end of a run (`axial.answer.record.
persist_markdown`, imported lazily there) -- the same function, the same
env var, so a local run's citation mode matches an unconfigured API
deployment's.

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
text. Nothing on that surface needed a change.

**Where the resolution itself lives, since #783.** The reader-facing
markdown renders need the same store lookup, and core may not import
`axial.service` (`axial/service/__init__.py`), so `resolve_record_citations`
and its two helpers moved to `axial.query.citations` and are re-exported
here under their old names. What stays here is what is genuinely the
deployer's: the mode, read from the environment once, at the edge."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from axial.query.citations import (  # noqa: F401 -- re-exported; the API and tests import them from here
    CITATION_MODES,
    LOCATOR,
    PASSAGE,
    resolve_chunk_citation,
    resolve_grounds,
    resolve_record_citations,
)

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


def render_record_for_serving(
    record: dict[str, Any], *, citation_mode: str, vault_dir: Path | None
) -> dict[str, Any]:
    """`record` (the §7.3 analysis record `GET /asks/{id}/paper` serves),
    with every `chunk` ground's citation resolved for the caller's own
    `citation_mode` (`axial.query.citations.resolve_record_citations`, where
    the resolution itself now lives -- issue #783 needed it in core, which
    may not import this layer). Mutates and returns `record` in place -- it
    was just freshly parsed from JSON by the caller
    (`axial.service.api.get_paper`), never the on-disk file, so there is
    nothing else holding a reference to mutate out from under."""
    return resolve_record_citations(record, citation_mode=citation_mode, vault_dir=vault_dir)
