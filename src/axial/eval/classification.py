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

`SourceClassification.baseline_commentary_share` is **note-weighted, and read
directly off committed, measured data -- never derived from source counts in
this module.** The figure it is compared against (§7.15's `commentary_mix`)
is itself note-weighted (`source_usage.evidence_chunk_count`), so the
baseline must be too, or the comparison is apples to oranges. A source-COUNT
share (commentary sources over every classified source) was tried first and
retired: on `sim-2026-07-30` it reads 2/31 = 6.45%, a point off the real,
measured 7,812/141,268 = 5.53% -- close enough on THIS corpus to look right
while being the wrong quantity, which is exactly what makes it dangerous
rather than merely imprecise (issue #563 follow-up). The committed
`note_weighted_baseline` block carries its own `commentary_note_count`,
`total_note_count`, `share` and the `corpus_pin` it was measured at, so a
reader can see it is a measurement, not a derivation. Zero vault reads is
preserved because the number is already committed data by the time this
module reads it -- nothing here counts a note itself. A classification file
with no `note_weighted_baseline` block reads `baseline_commentary_share` as
`None`: a wrong baseline silently substituted for a right one is worse than
an absent one, so there is no source-count fallback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CLASSIFICATION_PATH = Path("evals/sources/classification.json")

_VALID_CLASSES = ("primary", "commentary")


@dataclass(frozen=True)
class SourceClassification:
    """One committed classification (§7.15): each source's `class`, plus the
    note-weighted corpus-wide commentary baseline it was measured alongside
    (see module docstring)."""

    corpus_pin: str | None
    classes: dict[str, str]
    baseline_commentary_share: float | None

    @property
    def commentary_source_ids(self) -> frozenset[str]:
        return frozenset(sid for sid, cls in self.classes.items() if cls == "commentary")


def default_classification_path() -> Path:
    """Where the committed classification lives. A plain constant, like
    `axial.eval.cases.default_cases_dir` -- `evals/` is repo content, not a
    `data/` pipeline directory, and no caller has ever needed to move it."""
    return CLASSIFICATION_PATH


def _baseline_share(payload: dict) -> float | None:
    """`note_weighted_baseline.share` off the committed payload -- a plain
    field read, never a recomputation from `commentary_note_count` /
    `total_note_count`, so a classification file that states an inconsistent
    trio is read exactly as authored rather than silently corrected. `None`
    when the block is absent or its `share` isn't a real number (never a
    fallback to a source-count share -- module docstring)."""
    block = payload.get("note_weighted_baseline")
    if not isinstance(block, dict):
        return None
    share = block.get("share")
    if isinstance(share, bool) or not isinstance(share, (int, float)):
        return None
    return float(share)


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
        baseline_commentary_share=_baseline_share(payload),
    )
