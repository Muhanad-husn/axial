"""Citation markers and the citation index (specs/PHASE-C.md §7.5, §8 P0-5).

Stage 4, deterministic and model-free: parse the drafted prose for markers,
build the citation index in document order, and reduce the record's `claims`
to exactly the set the prose actually cited.

**One plain format.** A marker is the literal token `[<paper_claim_id>]` at the
end of the sentence it supports; multiple markers adjoin with no separator
(`[pc-004][pc-011]`). Nothing else in the rendered paper uses square-bracket
tokens, which is what makes the format unambiguously parseable rather than
merely conventional.

Two placements are both accepted, because both are what a writer produces and
neither is ambiguous: markers before the terminal punctuation
(`... its own terms [pc-004].`) and markers after it (`... its own terms. [pc-004]`).
A trailing fragment consisting only of markers is folded back onto the
sentence it follows rather than counted as a sentence of its own, so
`sentence_index` counts sentences and never marker runs.

A marker naming an unknown claim is a hard failure here (§7.5), not a warning
and not a silently dropped citation: an unresolvable marker in released prose
is a sentence whose grounds the reader cannot reach, which is the whole
property the apparatus exists to provide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

# A marker token. Deliberately greedy about what an id may contain (anything
# but a bracket) so a malformed id is caught by resolution against the claim
# set, naming the offending token, rather than by silently failing to match
# and vanishing from the index.
_MARKER = re.compile(r"\[([^\[\]]+)\]")

# Sentence boundary: terminal punctuation followed by whitespace. Kept simple
# on purpose -- this splits prose the drafter wrote to be split, and the index
# it feeds is a locator, not a linguistic claim. A fragment that is only
# markers is folded back (`_split_sentences`), which is the one case a naive
# split gets wrong in a way that would mis-key the index.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")

# A fragment carrying markers and nothing else -- the after-the-period
# placement, which a boundary split would otherwise strand as its own sentence.
_MARKERS_ONLY = re.compile(r"^(?:\s*\[[^\[\]]+\])+\s*$")


class CitationError(Exception):
    """Base class for citation-index failures."""


class UnresolvableMarkerError(CitationError):
    """Raised when a marker names a claim the record does not carry (§7.5)."""

    def __init__(self, marker: str, section_id: str, sentence_index: int):
        self.marker = marker
        self.section_id = section_id
        self.sentence_index = sentence_index
        super().__init__(
            f"citation marker [{marker}] in section {section_id!r} (sentence "
            f"{sentence_index}) names no claim in the record; every marker must resolve "
            f"to a paper_claim_id (§7.5)"
        )


class UnresolvableGroundsError(CitationError):
    """Raised when a cited claim's grounds pointer names an id the vault does
    not contain.

    A well-formed pointer to a missing id is a failure, not a shape check
    (§7.5): the citation chain claim -> grounds -> chunk -> source is only
    worth anything if its last link lands."""

    def __init__(self, paper_claim_id: str, ref_type: Any, ref_id: Any):
        self.paper_claim_id = paper_claim_id
        self.ref_type = ref_type
        self.ref_id = ref_id
        super().__init__(
            f"claim {paper_claim_id!r} cites {ref_type!r} ground {ref_id!r}, which does "
            f"not resolve in the vault"
        )


@dataclass(frozen=True)
class Citation:
    """One marker occurrence, in document order (§7.5)."""

    section_id: str
    sentence_index: int
    paper_claim_id: str

    def to_json(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "sentence_index": self.sentence_index,
            "paper_claim_id": self.paper_claim_id,
        }


def _split_sentences(prose: str) -> list[str]:
    """Split `prose` into sentences, folding a markers-only fragment back onto
    the sentence it follows."""
    fragments = [part for part in _SENTENCE_BOUNDARY.split(prose.strip()) if part.strip()]
    sentences: list[str] = []
    for fragment in fragments:
        if sentences and _MARKERS_ONLY.match(fragment):
            sentences[-1] = f"{sentences[-1]} {fragment.strip()}"
            continue
        sentences.append(fragment)
    return sentences


def markers_in(prose: str) -> list[str]:
    """Every marker id in `prose`, in order, duplicates included."""
    return [match.group(1).strip() for match in _MARKER.finditer(prose)]


def build_citation_index(
    sections: Iterable[dict[str, Any]], known_claim_ids: set[str]
) -> list[Citation]:
    """The §7.5 citation index: one entry per marker occurrence, in document
    order, over the drafted sections in plan order.

    `sections` are `{section_id, prose}` mappings -- the drafter's output, not
    the plan's sections, because the index is built by parsing what was
    actually written."""
    citations: list[Citation] = []
    for section in sections:
        section_id = section.get("section_id")
        prose = section.get("prose") or ""
        for sentence_index, sentence in enumerate(_split_sentences(prose)):
            for marker in markers_in(sentence):
                if marker not in known_claim_ids:
                    raise UnresolvableMarkerError(marker, str(section_id), sentence_index)
                citations.append(
                    Citation(
                        section_id=str(section_id),
                        sentence_index=sentence_index,
                        paper_claim_id=marker,
                    )
                )
    return citations


def cited_claim_ids(citations: Iterable[Citation]) -> list[str]:
    """The distinct claims the prose cited, in first-citation order."""
    seen: dict[str, None] = {}
    for citation in citations:
        seen.setdefault(citation.paper_claim_id, None)
    return list(seen)


def reduce_to_cited(
    claims: list[dict[str, Any]], citations: Iterable[Citation]
) -> list[dict[str, Any]]:
    """The record's `claims` list is EXACTLY the set of cited claims (§7.5).

    A claim assigned in the plan but never cited in the prose is dropped at
    persistence rather than carried as an orphan -- a record whose claim list
    overstates what the paper actually rests on is a record that cannot be
    audited by counting.

    Order follows `claims`, not citation order, so a record's claim list stays
    stable under a re-draft that reorders sentences."""
    cited = set(cited_claim_ids(citations))
    return [claim for claim in claims if claim.get("paper_claim_id") in cited]


def assert_grounds_resolve(
    claims: Iterable[dict[str, Any]], resolves: Callable[[str, str], bool]
) -> None:
    """Every cited claim's grounds resolve to a real vault id (§7.5, P0-5).

    `resolves(ref_type, ref_id)` is injected rather than imported so this is
    testable with no vault on disk; production passes a resolver over the
    Phase-B query API's `get_chunk` / `get_artifact`."""
    for claim in claims:
        paper_claim_id = str(claim.get("paper_claim_id"))
        for ground in claim.get("grounds") or []:
            if not isinstance(ground, dict):
                raise UnresolvableGroundsError(paper_claim_id, None, ground)
            ref_type = ground.get("ref_type")
            ref_id = ground.get("ref_id")
            if not isinstance(ref_type, str) or not isinstance(ref_id, str):
                raise UnresolvableGroundsError(paper_claim_id, ref_type, ref_id)
            if not resolves(ref_type, ref_id):
                raise UnresolvableGroundsError(paper_claim_id, ref_type, ref_id)
