"""Evidence assembly (Phase-B stage 4 pre-pass, specs/PHASE-B.md §7.4/§7.5,
issues #255 and #489): the retrieval loop's output (a list of chunk ids)
turned into one inspectable object -- the assembled evidence set the operator
can look at, and the synthesis call will read, before any expensive model call
is made (P0-9, `axial brief examine`).

**What a note carries changed completely** (Phase B v1 slice 04). A note used
to arrive as text plus five closed-vocabulary tag axes, every one of which
Phase A v1 deleted. It now arrives as text plus the interrogation's own
answers (`specs/PRODUCT.md` §7.15): what it claims, what it is doing in the
argument, whose position it is and what that position is, who it argues
against, who it cites and with what stance, the mechanism, the evidence, the
comparison, what it defines versus uses, what it concedes, what it assumes,
and every name it names.

**An abstention is not an answer and never reaches the model as one.** Every
one of those fields can instead be §7.15's explicit abstention, and 23.6% of the
live corpus abstains on `position_of` alone. `assemble_evidence` applies
`axial.query.reader.is_abstention` once, here, and an abstained field is simply
absent from the assembled `EvidenceChunk.answers` -- so nothing downstream can
mistake "the passage does not support an answer" for one. `[]` is an ANSWER
("the passage names none of that kind of thing") and is kept as one, never
normalised onto an abstention.

`assemble_evidence` fetches each id's full `ChunkNote`, dropping any id the
retrieval loop returned that does not resolve to a prose chunk -- the loop's
own `RetrievalResult.evidence_ids` pools ids from every tool a model called,
and the evidence SET this module assembles is chunks specifically.

The per-name roll-up here is a plain **inspection count**: how many assembled
notes named each surface form. No bands, no corpus denominator, no confidence.
The §7.7 banded coverage map is a different computation over a different
substrate -- canonical names from `names_touched` over the just-produced claim
graph, post-synthesis, in `axial.validators.coverage` -- and this feature
deliberately ships one of each rather than two per-name numbers with different
denominators. The pre-synthesis per-polity roll-up that used to live here
(`polity_coverage`/`PolityCoverage`) read `polities_touched`, which no note
carries, and is deleted with it (issue #489).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from axial.query.reader import ChunkNotFoundError, ChunkNote, get_chunk, is_abstention

# The §7.15 answer fields an evidence chunk carries into synthesis, in the
# order the prompt reads them: what the passage claims and is doing first,
# whose position and against whom next, then the analytic detail, with the
# name and citation lists last. Read off `ChunkNote` by name -- every one of
# these is an attribute there (issue #489), and each is exposed raw so the
# abstention filter below can tell an answer from a refusal.
#
# `position_of` (whose position) and `position` (what that position is) are
# two different questions and both are carried when both are answered: the
# corpus is a permanent mix of the two frames (§7.15, issue #496), a note
# written before frame 0.2 carries only the former, and nothing here fills one
# from the other. The `*_nearest` fields are deliberately absent: a nearest
# example is a marked example, never the answer (§7.15 rule 3).
EVIDENCE_ANSWER_FIELDS = (
    "claim",
    "move",
    "position_of",
    "position",
    "arguing_against",
    "about",
    "ranges_over",
    "stops_holding",
    "mechanism",
    "evidence",
    "comparison",
    "defines",
    "uses",
    "concedes",
    "assumes",
    "names",
    "citations",
)


@dataclass(frozen=True)
class EvidenceChunk:
    """One evidence chunk as synthesis reads it: its id, its source's own
    bibliographic metadata, and every substantive interrogation answer it
    carries (`answers`, keyed by the §7.15 field name, in
    `EVIDENCE_ANSWER_FIELDS` order).

    `answers` holds answers only: a field the passage abstained on, or one the
    record does not carry at all, is absent from the mapping rather than
    present with a sentinel. `[]` is an answer and is kept.

    Not the full `ChunkNote` -- `chunk_text` stays reachable via
    `axial.query.reader.get_chunk`, which is where `compose_prompt` fetches the
    real prose from."""

    chunk_id: str
    source_meta: dict[str, Any]
    answers: dict[str, Any]


@dataclass(frozen=True)
class EvidenceSet:
    """The assembled evidence set: deduplicated `chunk_ids` in first-seen
    retrieval order, each surviving chunk's answers (`chunks`, index-aligned
    with `chunk_ids`), and `name_counts` -- how many of those notes named each
    surface form. Empty cleanly (`chunk_ids=[]`, `chunks=[]`,
    `name_counts={}`) when the evidence set itself is empty; never raises on
    that case."""

    chunk_ids: list[str]
    chunks: list[EvidenceChunk]
    name_counts: dict[str, int]


def _dedupe_preserving_order(ids: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for chunk_id in ids:
        if chunk_id not in seen:
            seen.add(chunk_id)
            ordered.append(chunk_id)
    return ordered


def substantive_answers(note: ChunkNote) -> dict[str, Any]:
    """The note's §7.15 answers that are actually answers, in
    `EVIDENCE_ANSWER_FIELDS` order: an abstention (all three of its forms) and
    an absent field are both dropped, `[]` is kept because it is an answer,
    and a blank string is dropped because it is neither."""
    answers: dict[str, Any] = {}
    for field_name in EVIDENCE_ANSWER_FIELDS:
        value = getattr(note, field_name, None)
        if value is None or is_abstention(value):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        answers[field_name] = value
    return answers


def name_surfaces(names_answer: Any) -> list[str]:
    """The surface forms one note's raw `names` answer gave, in the note's own
    order, deduplicated. Each entry is `{name, kind}` on a real note (§7.15);
    a bare string is accepted as its own surface, mirroring
    `axial.query.names._read_note_answers`' own tolerance for a free-text
    answer, and an abstention or a non-list value yields nothing rather than
    being iterated character by character.

    The one place a `names` answer is turned into surface forms: the
    inspection count below and §7.4's `names_touched`
    (`axial.analyze.synthesis`) both read it, so "what did this note name" has
    one answer. Surface forms as the corpus said them -- resolving them to
    canonical names needs the alias map, which is `names_touched`'s job."""
    if is_abstention(names_answer):
        return []
    entries = names_answer if isinstance(names_answer, list) else [names_answer]
    surfaces: list[str] = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            surface = entry["name"]
        elif isinstance(entry, str):
            surface = entry
        else:
            continue
        if surface.strip():
            surfaces.append(surface)
    return _dedupe_preserving_order(surfaces)


def _count_names(chunks: list[EvidenceChunk]) -> dict[str, int]:
    """Each surface form counted once per assembled note that names it, in
    ascending surface order. An inspection count, not the §7.7 map: no band,
    no corpus denominator (see the module docstring)."""
    counts: dict[str, int] = {}
    for chunk in chunks:
        for surface in name_surfaces(chunk.answers.get("names")):
            counts[surface] = counts.get(surface, 0) + 1
    return {surface: counts[surface] for surface in sorted(counts)}


def assemble_evidence(chunk_ids: Iterable[str], *, vault_dir: Path | None = None) -> EvidenceSet:
    """Assemble the evidence set `chunk_ids` (typically
    `RetrievalResult.evidence_ids`) resolves to: dedupe preserving first-seen
    retrieval order, fetch each id's note via `axial.query.reader.get_chunk`,
    keep the substantive interrogation answers (`substantive_answers` -- an
    abstention is dropped, never rendered as an answer), and count how many
    assembled notes named each surface form.

    An id that does not resolve to a real prose chunk (`ChunkNotFoundError`)
    is dropped rather than raised -- see the module docstring for why.

    Cleanly returns an empty `EvidenceSet` for an empty `chunk_ids`, never
    raising. Zero model calls, zero writes."""
    ordered_ids = _dedupe_preserving_order(chunk_ids)

    chunks: list[EvidenceChunk] = []
    resolved_ids: list[str] = []
    for chunk_id in ordered_ids:
        try:
            note = get_chunk(chunk_id, vault_dir=vault_dir)
        except ChunkNotFoundError:
            continue
        resolved_ids.append(chunk_id)
        chunks.append(
            EvidenceChunk(
                chunk_id=note.chunk_id,
                source_meta=dict(note.source_meta or {}),
                answers=substantive_answers(note),
            )
        )

    return EvidenceSet(chunk_ids=resolved_ids, chunks=chunks, name_counts=_count_names(chunks))
