"""The §7.15 source-classification read contract (issue #563): does a pinned
source state its own argument (`primary`), or is it a book *about* another
thinker's body of work (`commentary`)? Two of the 31 `sim-2026-07-30` sources
are the latter -- `hall-2006` (on Michael Mann) and `malesevic-2007` (on
Ernest Gellner) -- and nothing in the product could see that distinction
until this reader existed.

`evals/sources/classification.json` is **authored, not derived**: a human
read the 31 titles and classified each by hand (issue #563's builder brief),
and this module's only job is parsing that committed file -- mirroring
`axial.eval.cases`'s own discipline exactly: zero model calls, zero vault
reads, never raises on a missing or malformed file. An absent or unreadable
classification costs exactly one figure (§7.15's commentary-mix share, which
reports not-scored with a stated reason) and nothing else -- the same
contract `axial.eval.cases.load_case` already holds for a missing case file.

`SourceClassification.baseline_commentary_share` is the classification's OWN
corpus-wide baseline: commentary sources over every source it classifies. It
is a source-COUNT share, not a note-weighted one -- this reader makes zero
vault reads (by design, see above), so it cannot weight by how many notes
each source actually contributed to the index. The founder's own measurement
against the real vault (issue #563: the two commentary volumes are 5.5% of
the name index's notes) is a different, note-weighted number this module
does not reproduce; the source-count baseline here is the one a report can
compute without reading the corpus.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CLASSIFICATION_PATH = Path("evals/sources/classification.json")

_VALID_CLASSES = ("primary", "commentary")


@dataclass(frozen=True)
class SourceClassification:
    """One committed classification (§7.15), narrowed to what the run report
    reads: each source's `class`."""

    corpus_pin: str | None
    classes: dict[str, str]

    @property
    def commentary_source_ids(self) -> frozenset[str]:
        return frozenset(sid for sid, cls in self.classes.items() if cls == "commentary")

    @property
    def baseline_commentary_share(self) -> float | None:
        """The classification's own corpus-wide baseline: commentary sources
        over every classified source. `None` when the file classifies
        nothing, never a division by zero."""
        if not self.classes:
            return None
        return len(self.commentary_source_ids) / len(self.classes)


def default_classification_path() -> Path:
    """Where the committed classification lives. A plain constant, like
    `axial.eval.cases.default_cases_dir` -- `evals/` is repo content, not a
    `data/` pipeline directory, and no caller has ever needed to move it."""
    return CLASSIFICATION_PATH


def load_classification(*, path: Path | None = None) -> SourceClassification | None:
    """The classification at `path` (default
    `evals/sources/classification.json`), or `None` when no such file
    exists, isn't readable, or doesn't parse to the expected shape. Never
    raises: a classification is an oracle a report reads, not a
    precondition of a run, so an absent one costs the one figure that reads
    it (the caller discloses that as not-scored with a reason) and nothing
    else."""
    classification_path = Path(path) if path is not None else default_classification_path()
    if not classification_path.is_file():
        return None
    try:
        payload = json.loads(classification_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, dict):
        return None

    classes: dict[str, str] = {}
    for source_id, entry in raw_sources.items():
        if not isinstance(source_id, str) or not isinstance(entry, dict):
            continue
        cls = entry.get("class")
        if cls in _VALID_CLASSES:
            classes[source_id] = cls

    corpus_pin = payload.get("corpus_pin")
    return SourceClassification(
        corpus_pin=corpus_pin if isinstance(corpus_pin, str) else None,
        classes=classes,
    )
