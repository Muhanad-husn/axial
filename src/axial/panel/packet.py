"""Sealed-packet assembly for the reviewer panel (issue #385,
specs/PHASE-B.md §9.4 properties 1, 2 and 7).

A packet is exactly what a journal referee gets: the rendered analysis
(§7.10) plus the resolved text of every chunk and artifact the analysis's
claims cite. Nothing else -- no spec, no prompts, no seeds, no repository
paths, and explicitly **not** the sim case's `expected_answer`, which would
anchor the reviewer to one pre-written opinion of a good answer (§9.3).

**The seal is enforced by tooling, not by prompt instruction** (property 2).
Two halves, and only the first lives here:

1. *Content*: this module builds the packet from the record and the vault
   reader alone, and `assert_sealed` refuses a packet carrying a repository
   path. An assembled packet is data, so it can be checked.
2. *Tools*: the reviewer is dispatched through `complete_json`, the plain
   completion seam, which has no `tools` parameter to pass -- it is
   structurally incapable of handing a reviewer a tool registry. See
   `axial.panel.review`. An agent holding file tools reads the repo whatever
   its prompt says, so "we told it not to" is not a seal.

**Packets are never committed** (property 7, DEC-23). They carry resolved
chunk text from copyrighted books. This module returns them in memory; no
function here writes one to disk, and nothing downstream may.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axial.answer.render import render_markdown
from axial.paper.render import render_paper
from axial.query.reader import (
    ArtifactNotFoundError,
    ChunkNotFoundError,
    get_artifact,
    get_chunk,
)


class PacketError(Exception):
    """Base class for packet-assembly failures."""


class UnresolvableGroundsError(PacketError):
    """Raised when a claim's grounds pointer does not resolve against the
    vault. A packet missing the evidence its claims cite would have the
    reviewer judge grounding against nothing, so this is an assembly error,
    never a silently thinner packet -- mirrors the grounding gate's own
    treatment of a broken pointer."""

    def __init__(self, claim_id: str, detail: str):
        self.claim_id = claim_id
        self.detail = detail
        super().__init__(f"claim {claim_id!r}: unresolvable grounds -- {detail}")


class SealBreachError(PacketError):
    """Raised when an assembled packet carries something that could lead a
    reviewer back to the repository. Raised before any reviewer call."""


# A packet is prose and quoted source text. Anything shaped like a path into
# this repository is a seal breach: it tells a reviewer where to look, and a
# reviewer that has read the prompt which generated the analysis is not a
# referee. Matched on the repo's own top-level directories rather than on
# "any slash", since ordinary prose and source ids contain slashes.
_REPO_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'(\[])(?:\./|/)?(?:src|tests|specs|docs|config|evals|plans|\.claude)/",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReviewPacket:
    """One self-contained submission. `brief_id` and `corpus_pin` key the
    verdict so a benchmark sweep can join a quality column (§9.4's benchmark
    seam); they are metadata for the caller and are never shown to a
    reviewer -- `prompt_body` is the whole of what one sees."""

    brief_id: str
    corpus_pin: str | None
    analysis_markdown: str
    evidence: dict[str, str]

    @property
    def prompt_body(self) -> str:
        """Everything the reviewer sees, in a fixed order so the same record
        always builds the same packet, byte for byte."""
        lines = ["# Submission", "", self.analysis_markdown.rstrip(), "", "# Cited evidence", ""]
        if not self.evidence:
            lines.append("(the submission cites no evidence)")
        for ref_id, text in self.evidence.items():
            lines += [f"## {ref_id}", "", text.strip(), ""]
        return "\n".join(lines).rstrip() + "\n"


def _resolve_reference(ref_type: str | None, ref_id: Any, claim_id: str, vault_dir: Path | None):
    if ref_type == "chunk":
        try:
            return get_chunk(ref_id, vault_dir=vault_dir).chunk_text
        except ChunkNotFoundError as exc:
            raise UnresolvableGroundsError(claim_id, str(exc)) from exc
    if ref_type == "artifact":
        try:
            artifact = get_artifact(ref_id, vault_dir=vault_dir)
        except ArtifactNotFoundError as exc:
            raise UnresolvableGroundsError(claim_id, str(exc)) from exc
        # `artifact_role` is retired (issue #429): the artifacts pass makes
        # no LLM call, so most artifacts carry no role at all. Fall back to
        # the artifact's own id -- always present, never None -- rather than
        # a field that is usually absent now.
        return artifact.caption or artifact.artifact_id
    raise UnresolvableGroundsError(claim_id, f"grounds entry has unknown ref_type {ref_type!r}")


def _iter_grounds(record: dict[str, Any]):
    """Every grounds pointer the record cites, from claims and from the
    counter-position alike. The counter-position's own grounds are included
    deliberately: a reviewer judging whether the opposition is steelmanned
    or strawmanned needs the material it rests on."""
    index = 0
    for claim in record.get("claims") or []:
        index += 1
        claim_id = claim.get("claim_id") or f"<claim #{index}>"
        for entry in claim.get("grounds") or []:
            if isinstance(entry, dict):
                yield claim_id, entry
    counter = record.get("counter_position") or {}
    for entry in counter.get("grounds") or []:
        if isinstance(entry, dict):
            yield "<counter_position>", entry


def assert_sealed(packet: "ReviewPacket | PaperReviewPacket") -> None:
    """Raise `SealBreachError` if `packet` carries a path into this repo.
    The content half of the seal (module docstring). Works identically for
    an analysis packet or a paper packet (issue #611): both expose
    `prompt_body`, and each carries its own record-id field for the
    message."""
    match = _REPO_PATH_PATTERN.search(packet.prompt_body)
    if match:
        record_id = getattr(packet, "brief_id", None) or getattr(packet, "paper_brief_id", None)
        raise SealBreachError(
            f"packet for {record_id!r} carries what looks like a "
            f"repository path ({match.group(0).strip()!r}) -- a reviewer must "
            "have no route back to how the analysis was made (§9.4 property 2)"
        )


def build_packet(
    record: dict[str, Any],
    *,
    corpus_pin: str | None,
    vault_dir: Path | None = None,
) -> ReviewPacket:
    """Assemble `record`'s sealed packet. Raises `UnresolvableGroundsError`
    on a broken grounds pointer and `SealBreachError` if the assembled
    packet carries a repository path. Never writes to disk (property 7)."""
    evidence: dict[str, str] = {}
    for claim_id, entry in _iter_grounds(record):
        ref_id = entry.get("ref_id")
        if ref_id in evidence:
            continue
        evidence[ref_id] = _resolve_reference(entry.get("ref_type"), ref_id, claim_id, vault_dir)

    packet = ReviewPacket(
        brief_id=record.get("brief_id") or "<unknown brief>",
        corpus_pin=corpus_pin,
        analysis_markdown=render_markdown(record),
        evidence=evidence,
    )
    assert_sealed(packet)
    return packet


@dataclass(frozen=True)
class PaperReviewPacket:
    """The §7.7 sealed packet, assembled from a Phase-C paper record
    (specs/PHASE-C.md §7.7, issue #611). `paper_brief_id` and `corpus_pin`
    are metadata for the caller, exactly as `ReviewPacket.brief_id` and
    `.corpus_pin` are -- never shown to a reviewer. `to_packet_dict` is
    exactly and only what §7.7 lists: `packet_id`, `paper_markdown`,
    `cited_evidence`, `bibliography`. Nothing else."""

    paper_brief_id: str
    corpus_pin: str | None
    packet_id: str
    paper_markdown: str
    cited_evidence: tuple[dict[str, Any], ...]
    bibliography: tuple[dict[str, Any], ...]

    def to_packet_dict(self) -> dict[str, Any]:
        """§7.7's contract, exactly. A test asserts these four keys and no
        others, so an accidental addition to the packet is caught rather
        than silently shipped to a reviewer."""
        return {
            "packet_id": self.packet_id,
            "paper_markdown": self.paper_markdown,
            "cited_evidence": [dict(entry) for entry in self.cited_evidence],
            "bibliography": [dict(entry) for entry in self.bibliography],
        }

    @property
    def prompt_body(self) -> str:
        """Everything the reviewer sees, in a fixed order so the same
        record always builds the same packet, byte for byte."""
        lines = ["# Submission", "", self.paper_markdown.rstrip(), "", "# Cited evidence", ""]
        if not self.cited_evidence:
            lines.append("(the submission cites no evidence)")
        for entry in self.cited_evidence:
            lines.append(
                f"## {entry.get('paper_claim_id')} "
                f"(kind {entry.get('kind')}, confidence {entry.get('confidence')})"
            )
            lines.append("")
            for ground in entry.get("grounds") or []:
                lines.append(f"- {ground.get('ref_id')}: {ground.get('text')}")
            lines.append("")
        lines.append("# Bibliography")
        lines.append("")
        if not self.bibliography:
            lines.append("(no cited sources)")
        for entry in self.bibliography:
            lines.append(f"- {_paper_bib_line(entry)}")
        return "\n".join(lines).rstrip() + "\n"


def _paper_bib_line(entry: dict[str, Any]) -> str:
    author = (entry.get("author") or {}).get("value")
    date = (entry.get("date") or {}).get("value")
    title = (entry.get("title") or {}).get("value")
    label = ", ".join(str(part) for part in (author, date, title) if part)
    return f"{entry.get('source_id')} -- {label}" if label else str(entry.get("source_id"))


def build_paper_packet(
    record: dict[str, Any],
    *,
    corpus_pin: str | None,
    vault_dir: Path | None = None,
) -> PaperReviewPacket:
    """Assemble a paper record's §7.7 sealed packet. The paper analogue of
    `build_packet` above (issue #611): one entry per cited claim, carrying
    the resolved text of every grounds pointer it cites, plus the paper's
    own bibliography. Raises `UnresolvableGroundsError` on a broken grounds
    pointer and `SealBreachError` if the assembled packet carries a
    repository path. Never writes to disk (property 7)."""
    cited_evidence: list[dict[str, Any]] = []
    for index, claim in enumerate(record.get("claims") or [], start=1):
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("paper_claim_id") or f"<claim #{index}>"
        grounds: list[dict[str, Any]] = []
        for entry in claim.get("grounds") or []:
            if not isinstance(entry, dict):
                continue
            ref_id = entry.get("ref_id")
            text = _resolve_reference(entry.get("ref_type"), ref_id, claim_id, vault_dir)
            grounds.append({"ref_id": ref_id, "text": text})
        cited_evidence.append(
            {
                "paper_claim_id": claim_id,
                "kind": claim.get("kind"),
                "confidence": claim.get("confidence"),
                "grounds": grounds,
            }
        )

    paper_brief_id = record.get("paper_brief_id") or "<unknown paper>"
    packet = PaperReviewPacket(
        paper_brief_id=paper_brief_id,
        corpus_pin=corpus_pin,
        packet_id=f"paper-packet:{paper_brief_id}",
        paper_markdown=render_paper(record),
        cited_evidence=tuple(cited_evidence),
        bibliography=tuple(dict(entry) for entry in (record.get("bibliography") or [])),
    )
    assert_sealed(packet)
    return packet
