"""Inner unit tests for sealed-packet assembly (issue #385, §9.4
properties 1, 2, 7)."""

from __future__ import annotations

import pytest

import axial.panel.packet as packet_mod
from axial.panel.packet import (
    PaperReviewPacket,
    ReviewPacket,
    SealBreachError,
    UnresolvableGroundsError,
    assert_sealed,
    build_packet,
    build_paper_packet,
)


class _StubChunk:
    def __init__(self, text: str):
        self.chunk_text = text


class _StubArtifact:
    def __init__(self, caption: str | None, role: str = "table"):
        self.caption = caption
        self.artifact_role = role


def _record(**overrides):
    record = {
        "brief_id": "b-001",
        "claims": [
            {
                "claim_id": "c-1",
                "kind": "a",
                "text": "The state hollowed out its bureaucracy.",
                "confidence": "medium",
                "grounds": [{"ref_type": "chunk", "ref_id": "src_1_intro_001"}],
            }
        ],
        "counter_position": {"present": False},
        "coverage_map": {},
        "confidence": {"overall_band": "medium", "rationale": "thin on one polity"},
    }
    record.update(overrides)
    return record


@pytest.fixture
def stub_vault(monkeypatch):
    chunks = {"src_1_intro_001": "Tax receipts fell while militia payrolls grew."}
    artifacts = {"src_1_fig_1": _StubArtifact("Revenue by year")}

    def fake_get_chunk(ref_id, vault_dir=None):
        if ref_id not in chunks:
            raise packet_mod.ChunkNotFoundError(ref_id, packet_mod.Path("nowhere"))
        return _StubChunk(chunks[ref_id])

    def fake_get_artifact(ref_id, vault_dir=None):
        if ref_id not in artifacts:
            raise packet_mod.ArtifactNotFoundError(ref_id, packet_mod.Path("nowhere"))
        return artifacts[ref_id]

    monkeypatch.setattr(packet_mod, "get_chunk", fake_get_chunk)
    monkeypatch.setattr(packet_mod, "get_artifact", fake_get_artifact)
    return chunks


def test_packet_carries_the_analysis_and_its_cited_evidence(stub_vault):
    packet = build_packet(_record(), corpus_pin="pin-1")
    assert packet.brief_id == "b-001"
    assert packet.corpus_pin == "pin-1"
    assert "Tax receipts fell" in packet.prompt_body
    assert "hollowed out its bureaucracy" in packet.prompt_body


def test_packet_is_byte_for_byte_deterministic(stub_vault):
    first = build_packet(_record(), corpus_pin="pin-1")
    second = build_packet(_record(), corpus_pin="pin-1")
    assert first.prompt_body == second.prompt_body


def test_counter_position_grounds_are_included(stub_vault):
    """A reviewer judging steelman-vs-strawman needs the material the
    opposition rests on."""
    record = _record(
        counter_position={
            "present": True,
            "stance": "War made the state stronger.",
            "grounds": [{"ref_type": "artifact", "ref_id": "src_1_fig_1"}],
        }
    )
    packet = build_packet(record, corpus_pin=None)
    assert "Revenue by year" in packet.prompt_body


def test_evidence_is_deduplicated_across_claims(stub_vault):
    grounds = [{"ref_type": "chunk", "ref_id": "src_1_intro_001"}]
    record = _record(
        claims=[
            {"claim_id": "c-1", "kind": "a", "text": "One.", "grounds": grounds},
            {"claim_id": "c-2", "kind": "a", "text": "Two.", "grounds": grounds},
        ]
    )
    packet = build_packet(record, corpus_pin=None)
    assert packet.prompt_body.count("Tax receipts fell") == 1


def test_unresolvable_grounds_is_an_assembly_error(stub_vault):
    record = _record(
        claims=[
            {
                "claim_id": "c-1",
                "kind": "a",
                "text": "One.",
                "grounds": [{"ref_type": "chunk", "ref_id": "no_such_chunk"}],
            }
        ]
    )
    with pytest.raises(UnresolvableGroundsError):
        build_packet(record, corpus_pin=None)


def test_unknown_ref_type_is_an_assembly_error(stub_vault):
    record = _record(
        claims=[
            {
                "claim_id": "c-1",
                "kind": "a",
                "text": "One.",
                "grounds": [{"ref_type": "spreadsheet", "ref_id": "x"}],
            }
        ]
    )
    with pytest.raises(UnresolvableGroundsError):
        build_packet(record, corpus_pin=None)


def test_a_repo_path_in_the_packet_is_a_seal_breach():
    """The content half of the seal: a reviewer must have no route back to
    how the analysis was made."""
    packet = ReviewPacket(
        brief_id="b-001",
        corpus_pin=None,
        analysis_markdown="See specs/PHASE-B.md for the rubric this was written against.",
        evidence={},
    )
    with pytest.raises(SealBreachError):
        assert_sealed(packet)


def test_ordinary_prose_with_slashes_is_not_a_seal_breach():
    packet = ReviewPacket(
        brief_id="b-001",
        corpus_pin=None,
        analysis_markdown="The 2011/2012 period saw state/militia boundaries blur.",
        evidence={"src_1_intro_001": "Revenue and/or coercion."},
    )
    assert_sealed(packet)


def test_build_packet_never_writes_to_disk(stub_vault, tmp_path, monkeypatch):
    """Property 7, DEC-23: packets carry copyrighted book text and are
    assembled at runtime only."""
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.rglob("*"))
    build_packet(_record(), corpus_pin="pin-1")
    assert set(tmp_path.rglob("*")) == before


# -- the paper-shaped packet (issue #611, specs/PHASE-C.md §7.7) -------------


def _paper_record(**overrides):
    record = {
        "paper_brief_id": "pb-001",
        "paper_brief": {"title": "Did the state hold?", "thesis": "It did not."},
        "plan": {
            "thesis_statement": "It did not.",
            "sections": [{"section_id": "s1", "heading": "The claim", "role": "claim"}],
        },
        "drafts": [{"section_id": "s1", "prose": "The bureaucracy hollowed out [pc-001]."}],
        "claims": [
            {
                "paper_claim_id": "pc-001",
                "kind": "a",
                "confidence": "medium",
                "grounds": [{"ref_type": "chunk", "ref_id": "src_1_intro_001"}],
                "source_ids": ["src-1"],
            }
        ],
        "citations": [],
        "counter_position": {"present": False, "corpus_one_sided": True},
        "coverage_map": {},
        "confidence": {"overall_band": "medium", "rationale": "thin on one name"},
        "bibliography": [
            {
                "source_id": "src-1",
                "author": {"value": "Batatu", "provenance": "title page"},
                "date": {"value": "1999", "provenance": "title page"},
            }
        ],
    }
    record.update(overrides)
    return record


def test_paper_packet_carries_exactly_the_section_7_7_shape(stub_vault):
    packet = build_paper_packet(_paper_record(), corpus_pin="pin-1")
    assert isinstance(packet, PaperReviewPacket)
    assert set(packet.to_packet_dict()) == {
        "packet_id",
        "paper_markdown",
        "cited_evidence",
        "bibliography",
    }


def test_paper_packet_prompt_carries_the_rendered_paper_and_its_evidence(stub_vault):
    packet = build_paper_packet(_paper_record(), corpus_pin="pin-1")
    assert "bureaucracy hollowed out" in packet.prompt_body
    assert "Tax receipts fell" in packet.prompt_body


def test_paper_packet_cited_evidence_is_keyed_per_claim(stub_vault):
    packet = build_paper_packet(_paper_record(), corpus_pin="pin-1")
    entries = packet.to_packet_dict()["cited_evidence"]
    assert len(entries) == 1
    assert entries[0]["paper_claim_id"] == "pc-001"
    assert entries[0]["kind"] == "a"
    assert entries[0]["confidence"] == "medium"
    assert entries[0]["grounds"] == [
        {"ref_id": "src_1_intro_001", "text": "Tax receipts fell while militia payrolls grew."}
    ]


def test_paper_packet_is_byte_for_byte_deterministic(stub_vault):
    first = build_paper_packet(_paper_record(), corpus_pin="pin-1")
    second = build_paper_packet(_paper_record(), corpus_pin="pin-1")
    assert first.prompt_body == second.prompt_body


def test_paper_packet_unresolvable_grounds_is_an_assembly_error(stub_vault):
    record = _paper_record(
        claims=[
            {
                "paper_claim_id": "pc-001",
                "kind": "a",
                "confidence": "medium",
                "grounds": [{"ref_type": "chunk", "ref_id": "no_such_chunk"}],
            }
        ]
    )
    with pytest.raises(UnresolvableGroundsError):
        build_paper_packet(record, corpus_pin=None)


def test_a_paper_packet_carrying_a_repo_path_is_a_seal_breach(stub_vault):
    record = _paper_record(
        drafts=[{"section_id": "s1", "prose": "See specs/PHASE-C.md for the rubric."}]
    )
    with pytest.raises(SealBreachError):
        build_paper_packet(record, corpus_pin=None)


def test_paper_packet_never_writes_to_disk(stub_vault, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.rglob("*"))
    build_paper_packet(_paper_record(), corpus_pin="pin-1")
    assert set(tmp_path.rglob("*")) == before


def test_an_analysis_packet_is_unaffected_by_the_paper_packet_addition(stub_vault):
    """§8 P0-10 observable: an analysis packet still assembles from the
    original ReviewPacket shape, nothing added."""
    packet = build_packet(_record(), corpus_pin="pin-1")
    assert isinstance(packet, ReviewPacket)
    assert not hasattr(packet, "packet_id")
    assert not hasattr(packet, "cited_evidence")
