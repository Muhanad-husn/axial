"""Inner unit tests for evidence assembly (issue #255,
specs/PHASE-B.md §7.5/§7.7). Co-located under src/axial/analyze/ per the
repo's existing test layout (mirrors src/axial/brief/test_interrogate.py).

Covers plans/analysis-synthesis/01-evidence-assembly-and-examine.md's
inner-loop checklist: dedup + first-seen order, per-chunk frontmatter
carried through, raw per-polity coverage counts (evidence vs. corpus,
never a recount), a touched-by-nobody polity excluded, and an empty
evidence set assembling cleanly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.analyze.assembly import EvidenceChunk, EvidenceSet, assemble_evidence


def _chunk_frontmatter(
    *, chunk_id: str, polities_touched: list[str], role_in_argument: str = "role:claim"
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": "A. Synthetic Author",
            "title": "A Synthetic Fixture Source",
            "date": 2021,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "schema_version": "0.1",
        "role_in_argument": role_in_argument,
        "field": {"primary": "field:political-sociology", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {
            "value": "scope:country-case",
            "polity": polities_touched[0] if polities_touched else None,
        },
        "polities_touched": polities_touched,
        "artifact_refs": [],
    }


def _write_vault(root: Path, notes: list[dict[str, Any]]) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for frontmatter in notes:
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")
    return prose_dir.parent


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    notes = [
        _chunk_frontmatter(chunk_id="asfix_001_syria_a", polities_touched=["Syria"]),
        _chunk_frontmatter(chunk_id="asfix_002_syria_b", polities_touched=["Syria"]),
        _chunk_frontmatter(chunk_id="asfix_003_syria_c", polities_touched=["Syria"]),
        _chunk_frontmatter(chunk_id="asfix_004_lebanon", polities_touched=["Lebanon"]),
        _chunk_frontmatter(chunk_id="asfix_005_two_polities", polities_touched=["Syria", "Iraq"]),
    ]
    return _write_vault(tmp_path, notes)


def test_dedupes_and_preserves_first_seen_retrieval_order(vault_dir: Path):
    ids = [
        "asfix_002_syria_b",
        "asfix_001_syria_a",
        "asfix_002_syria_b",  # duplicate -- returned again by a later tool call
    ]

    evidence = assemble_evidence(ids, vault_dir=vault_dir)

    assert evidence.chunk_ids == ["asfix_002_syria_b", "asfix_001_syria_a"]


def test_evidence_chunks_carry_synthesis_relevant_frontmatter(vault_dir: Path):
    evidence = assemble_evidence(["asfix_001_syria_a"], vault_dir=vault_dir)

    assert len(evidence.chunks) == 1
    chunk = evidence.chunks[0]
    assert isinstance(chunk, EvidenceChunk)
    assert chunk.chunk_id == "asfix_001_syria_a"
    assert chunk.polities_touched == ["Syria"]
    assert chunk.role_in_argument == "role:claim"
    assert chunk.theory_school["primary"] == "school:synthetic-institutionalist"
    assert chunk.claim_type["primary"] == "claim:causal"
    assert chunk.empirical_scope["value"] == "scope:country-case"


def test_per_polity_counts_evidence_vs_corpus(vault_dir: Path):
    # Only two of the vault's three Syria-touching chunks are retrieved --
    # corpus_chunk_count must still reflect the whole vault (coverage_count),
    # never a recount over just this evidence set.
    ids = ["asfix_001_syria_a", "asfix_002_syria_b"]

    evidence = assemble_evidence(ids, vault_dir=vault_dir)

    syria = evidence.polity_coverage["Syria"]
    assert syria.corpus_chunk_count == 4  # 3 Syria-only notes + the dual-polity one
    assert syria.evidence_chunk_count == 2


def test_polity_touched_by_a_single_evidence_chunk_reports_count_one(vault_dir: Path):
    evidence = assemble_evidence(["asfix_005_two_polities"], vault_dir=vault_dir)

    assert evidence.polity_coverage["Iraq"].evidence_chunk_count == 1
    assert evidence.polity_coverage["Iraq"].corpus_chunk_count == 1


def test_polity_absent_from_evidence_is_absent_from_the_report(vault_dir: Path):
    # "Lebanon" has real corpus coverage (asfix_004_lebanon) but no chunk in
    # this evidence set touches it -- it must not appear at all.
    evidence = assemble_evidence(["asfix_001_syria_a"], vault_dir=vault_dir)

    assert "Lebanon" not in evidence.polity_coverage


def test_empty_evidence_set_assembles_cleanly(vault_dir: Path):
    evidence = assemble_evidence([], vault_dir=vault_dir)

    assert evidence == EvidenceSet(chunk_ids=[], chunks=[], polity_coverage={})


def test_an_id_that_does_not_resolve_to_a_chunk_is_dropped_not_raised(vault_dir: Path):
    # The retrieval loop's evidence_ids channel pools ids from every tool a
    # model called, including non-chunk ids (e.g. coverage_count's own
    # polity names) -- assembly must not crash on one.
    ids = ["asfix_001_syria_a", "Syria"]

    evidence = assemble_evidence(ids, vault_dir=vault_dir)

    assert evidence.chunk_ids == ["asfix_001_syria_a"]
    assert len(evidence.chunks) == 1
