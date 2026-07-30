"""Inner unit tests for evidence assembly (issues #255 and #489,
specs/PHASE-B.md §7.4/§7.5, `specs/PRODUCT.md` §7.15). Co-located under
src/axial/analyze/ per the repo's existing test layout (mirrors
src/axial/brief/test_interrogate.py).

Covers: dedup + first-seen order, the interrogation's own answers carried
through, every form of the §7.15 abstention dropped, `[]` kept because it is
an answer, the plain per-name inspection count, and an empty evidence set
assembling cleanly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.analyze.assembly import EvidenceSet, assemble_evidence, name_surfaces


def _chunk_frontmatter(*, chunk_id: str, answers: dict[str, Any] | None = None) -> dict[str, Any]:
    """A prose note in the shape `axial.materialize` writes today: source
    metadata plus the nested interrogation `answers` block (§7.15, Appendix
    H), and none of the retired tag axes."""
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
        "frame_version": "0.1",
        "answers": answers if answers is not None else {},
    }


def _answers(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "claim": "Displacement reshaped local authority.",
        "move": "narrowing an earlier claim to the wartime period",
        "position_of": "the author",
        "arguing_against": ["the modernization account"],
        "names": [
            {"name": "Syria", "kind": "country/state/place"},
            {"name": "Charles Tilly", "kind": "person"},
        ],
        "citations": [{"cited": "Charles Tilly", "stance": "foil", "about": "war-making"}],
        "mechanism": "displacement severs the tax base from the notables who collected it",
    }
    base.update(overrides)
    return base


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
        _chunk_frontmatter(chunk_id="asfix_001_syria_a", answers=_answers()),
        _chunk_frontmatter(chunk_id="asfix_002_syria_b", answers=_answers()),
        _chunk_frontmatter(
            chunk_id="asfix_003_no_answers_block",  # a note written before #411
        ),
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


def test_evidence_chunks_carry_the_interrogation_answers_and_source_meta(vault_dir: Path):
    evidence = assemble_evidence(["asfix_001_syria_a"], vault_dir=vault_dir)

    chunk = evidence.chunks[0]
    assert chunk.chunk_id == "asfix_001_syria_a"
    assert chunk.source_meta["author"] == "A. Synthetic Author"
    assert chunk.answers["claim"] == "Displacement reshaped local authority."
    assert chunk.answers["move"] == "narrowing an earlier claim to the wartime period"
    assert chunk.answers["position_of"] == "the author"
    assert chunk.answers["arguing_against"] == ["the modernization account"]
    assert chunk.answers["citations"][0]["stance"] == "foil"
    # Answers appear in the prompt's own reading order, not YAML order.
    assert list(chunk.answers) == [
        "claim",
        "move",
        "position_of",
        "arguing_against",
        "mechanism",
        "names",
        "citations",
    ]


def test_a_field_the_note_does_not_carry_is_absent_not_none(vault_dir: Path):
    evidence = assemble_evidence(["asfix_001_syria_a"], vault_dir=vault_dir)

    # The fixture answers no `position`, `concedes` or `assumes`; an absent
    # key never arrives as a null the prompt would render.
    assert "position" not in evidence.chunks[0].answers
    assert "concedes" not in evidence.chunks[0].answers


def test_a_note_with_no_answers_block_at_all_assembles_with_no_answers(vault_dir: Path):
    evidence = assemble_evidence(["asfix_003_no_answers_block"], vault_dir=vault_dir)

    assert evidence.chunk_ids == ["asfix_003_no_answers_block"]
    assert evidence.chunks[0].answers == {}


@pytest.mark.parametrize(
    "abstained",
    [
        "not-in-passage",
        {"not-in-passage": "the passage bears on this but does not settle it"},
        ["not-in-passage"],
        [{"not-in-passage": "the passage names no opponent"}],
    ],
    ids=["bare-string", "object-with-reason", "one-element-list", "one-element-object-list"],
)
def test_every_form_of_abstention_is_dropped_never_carried_as_an_answer(
    tmp_path: Path, abstained: Any
):
    """§7.15's three abstention forms (the object form and the bare string,
    each also legal alone inside a one-element list). An abstention is not an
    answer and must never reach the model as one."""
    notes = [
        _chunk_frontmatter(
            chunk_id="asfix_010_abstained",
            answers=_answers(position_of=abstained, arguing_against=abstained),
        )
    ]
    vault_dir = _write_vault(tmp_path, notes)

    evidence = assemble_evidence(["asfix_010_abstained"], vault_dir=vault_dir)

    answers = evidence.chunks[0].answers
    assert "position_of" not in answers
    assert "arguing_against" not in answers
    # The fields the passage DID answer are untouched.
    assert answers["claim"] == "Displacement reshaped local authority."


def test_an_empty_list_is_an_answer_and_is_kept(tmp_path: Path):
    """`[]` on a multi-valued field says the passage names none of that kind
    of thing -- a read, not a refusal (§7.15). It is never normalised onto an
    abstention, so it stays in the assembled answers."""
    notes = [
        _chunk_frontmatter(
            chunk_id="asfix_011_empty_list", answers=_answers(arguing_against=[], names=[])
        )
    ]
    vault_dir = _write_vault(tmp_path, notes)

    evidence = assemble_evidence(["asfix_011_empty_list"], vault_dir=vault_dir)

    answers = evidence.chunks[0].answers
    assert answers["arguing_against"] == []
    assert answers["names"] == []


def test_name_counts_count_each_surface_once_per_assembled_note(vault_dir: Path):
    evidence = assemble_evidence(
        ["asfix_001_syria_a", "asfix_002_syria_b", "asfix_003_no_answers_block"],
        vault_dir=vault_dir,
    )

    # Both answer-carrying notes name Syria and Charles Tilly; the third
    # names nothing. No band, no corpus denominator -- a plain count.
    assert evidence.name_counts == {"Charles Tilly": 2, "Syria": 2}


def test_a_repeated_surface_on_one_note_counts_once(tmp_path: Path):
    notes = [
        _chunk_frontmatter(
            chunk_id="asfix_012_repeat",
            answers=_answers(
                names=[
                    {"name": "Syria", "kind": "country/state/place"},
                    {"name": "Syria", "kind": "country/state/place"},
                ]
            ),
        )
    ]
    vault_dir = _write_vault(tmp_path, notes)

    evidence = assemble_evidence(["asfix_012_repeat"], vault_dir=vault_dir)

    assert evidence.name_counts == {"Syria": 1}
    assert name_surfaces(evidence.chunks[0].answers["names"]) == ["Syria"]


def test_an_abstained_names_answer_never_becomes_a_name(tmp_path: Path):
    """The trap §7.16 names for Reconcile's inventory, applied here: reading
    an abstention as an answer would mint `not-in-passage` as a name."""
    notes = [
        _chunk_frontmatter(
            chunk_id="asfix_013_abstained_names", answers=_answers(names="not-in-passage")
        )
    ]
    vault_dir = _write_vault(tmp_path, notes)

    evidence = assemble_evidence(["asfix_013_abstained_names"], vault_dir=vault_dir)

    assert evidence.name_counts == {}


def test_empty_evidence_set_assembles_cleanly(vault_dir: Path):
    evidence = assemble_evidence([], vault_dir=vault_dir)

    assert evidence == EvidenceSet(chunk_ids=[], chunks=[], name_counts={})


def test_an_id_that_does_not_resolve_to_a_chunk_is_dropped_not_raised(vault_dir: Path):
    # The retrieval loop's evidence_ids channel pools ids from every tool a
    # model called, so a non-chunk id can arrive -- assembly must not crash.
    ids = ["asfix_001_syria_a", "Charles Tilly"]

    evidence = assemble_evidence(ids, vault_dir=vault_dir)

    assert evidence.chunk_ids == ["asfix_001_syria_a"]
    assert len(evidence.chunks) == 1
