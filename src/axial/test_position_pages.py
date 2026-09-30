"""Unit tests for `axial.position_pages` (issue #854, DEC-75 step 1b): the
argument map rendered as the vault, one page per position. Offline: plain
JSONL fixtures, no model call."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from axial.position_pages import write_position_pages

POSITIONS = [
    {
        "position_id": "pos-0001",
        "argument": "States arm militias to deny responsibility.",
        "variants": [
            "States arm militias to deny responsibility.",
            "Militias give the state plausible deniability.",
        ],
        "chunk_ids": ["alpha-2020-aaa_1_intro_001", "beta-2019-bbb_2_war_004"],
        "sources": ["alpha-2020-aaa", "beta-2019-bbb"],
        "authors": ["alpha", "beta"],
        "size": 2,
    },
    {
        "position_id": "pos-0002",
        "argument": "Militias arise from below, not from the state.",
        "variants": ["Militias arise from below, not from the state."],
        "chunk_ids": ["gamma-2018-ccc_3_below_002"],
        "sources": ["gamma-2018-ccc"],
        "authors": ["gamma"],
        "size": 1,
    },
    {
        "position_id": "pos-0003",
        "argument": "An argument nothing relates to.",
        "variants": ["An argument nothing relates to."],
        "chunk_ids": ["gamma-2018-ccc_3_below_003"],
        "sources": ["gamma-2018-ccc"],
        "authors": ["gamma"],
        "size": 1,
    },
]

RELATIONS = [
    {
        "from_position_id": "pos-0002",
        "to_position_id": "pos-0001",
        "relation": "contests",
        "says": "a1 denies that the state is the author of militia violence.",
    },
]

RELATION_KINDS = [
    {
        "category_id": "conflict",
        "column": "relation",
        "from_position_id": "pos-0002",
        "to_position_id": "pos-0001",
        "relation": "contests",
        "level": 1,
        "refused": False,
    },
]


def _assignment(column: str, chunk_id: str, category_id: str | None, refused: bool = False):
    return {
        "category_id": category_id,
        "chunk_id": chunk_id,
        "column": column,
        "level": 1,
        "refused": refused,
    }


ASSIGNMENTS = {
    "claim": [
        _assignment("claim", "alpha-2020-aaa_1_intro_001", "causal-argument"),
        _assignment("claim", "beta-2019-bbb_2_war_004", "causal-argument"),
        _assignment("claim", "gamma-2018-ccc_3_below_002", None, refused=True),
    ],
    "mechanism": [
        _assignment("mechanism", "alpha-2020-aaa_1_intro_001", "state-repression"),
        _assignment("mechanism", "beta-2019-bbb_2_war_004", "delegation"),
    ],
    "position": [],
}


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    map_dir = tmp_path / "map" / "pin0"
    _write_jsonl(map_dir / "positions.jsonl", POSITIONS)
    _write_jsonl(map_dir / "relations.jsonl", RELATIONS)
    vocabulary_dir = tmp_path / "vocabulary"
    for column, records in ASSIGNMENTS.items():
        _write_jsonl(vocabulary_dir / column / "assignments.jsonl", records)
    _write_jsonl(vocabulary_dir / "relation" / "assignments.jsonl", RELATION_KINDS)
    return map_dir, vocabulary_dir, tmp_path / "vault"


def _page(vault_dir: Path, position_id: str) -> tuple[dict, str]:
    text = (vault_dir / "positions" / f"{position_id}.md").read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---\n", 2)
    return yaml.safe_load(frontmatter), body


def test_every_position_gets_a_page(tmp_path: Path) -> None:
    map_dir, vocabulary_dir, vault_dir = _fixture(tmp_path)

    result = write_position_pages(
        map_dir=map_dir, vocabulary_dir=vocabulary_dir, vault_dir=vault_dir
    )

    pages = sorted(p.stem for p in (vault_dir / "positions").glob("*.md"))
    assert pages == ["pos-0001", "pos-0002", "pos-0003"]
    assert result["position_pages_written"] == 3


def test_frontmatter_carries_sources_member_count_and_committed_categories(
    tmp_path: Path,
) -> None:
    map_dir, vocabulary_dir, vault_dir = _fixture(tmp_path)
    write_position_pages(map_dir=map_dir, vocabulary_dir=vocabulary_dir, vault_dir=vault_dir)

    frontmatter, _ = _page(vault_dir, "pos-0001")

    assert frontmatter["position_id"] == "pos-0001"
    assert frontmatter["sources"] == ["alpha-2020-aaa", "beta-2019-bbb"]
    assert frontmatter["member_count"] == 2
    assert frontmatter["claim"] == ["causal-argument"]
    assert frontmatter["mechanism"] == ["delegation", "state-repression"]
    assert frontmatter["position"] == []


def test_a_refused_assignment_files_no_category(tmp_path: Path) -> None:
    map_dir, vocabulary_dir, vault_dir = _fixture(tmp_path)
    write_position_pages(map_dir=map_dir, vocabulary_dir=vocabulary_dir, vault_dir=vault_dir)

    frontmatter, _ = _page(vault_dir, "pos-0002")

    assert frontmatter["claim"] == []


def test_body_carries_argument_variants_and_passage_links(tmp_path: Path) -> None:
    map_dir, vocabulary_dir, vault_dir = _fixture(tmp_path)
    write_position_pages(map_dir=map_dir, vocabulary_dir=vocabulary_dir, vault_dir=vault_dir)

    _, body = _page(vault_dir, "pos-0001")

    assert "States arm militias to deny responsibility." in body
    assert "- Militias give the state plausible deniability." in body
    # The argument is not repeated among its own variants.
    assert body.count("States arm militias to deny responsibility.") == 1
    assert "[[alpha-2020-aaa_1_intro_001]]" in body
    assert "[[beta-2019-bbb_2_war_004]]" in body


def test_a_relation_is_a_link_on_both_endpoints_with_kind_and_says(tmp_path: Path) -> None:
    map_dir, vocabulary_dir, vault_dir = _fixture(tmp_path)
    write_position_pages(map_dir=map_dir, vocabulary_dir=vocabulary_dir, vault_dir=vault_dir)

    _, source_body = _page(vault_dir, "pos-0002")
    _, target_body = _page(vault_dir, "pos-0001")

    says = "a1 denies that the state is the author of militia violence."
    for body, other in ((source_body, "pos-0001"), (target_body, "pos-0002")):
        line = next(line for line in body.splitlines() if f"[[{other}]]" in line)
        assert "contests" in line
        assert "conflict" in line
        assert says in line


def test_isolated_positions_are_counted_from_relations(tmp_path: Path) -> None:
    map_dir, vocabulary_dir, vault_dir = _fixture(tmp_path)

    result = write_position_pages(
        map_dir=map_dir, vocabulary_dir=vocabulary_dir, vault_dir=vault_dir
    )

    assert result["position_pages_isolated"] == 1
    _, body = _page(vault_dir, "pos-0003")
    assert "[[pos-" not in body


def test_two_runs_are_byte_identical_and_drop_a_stale_page(tmp_path: Path) -> None:
    map_dir, vocabulary_dir, vault_dir = _fixture(tmp_path)
    write_position_pages(map_dir=map_dir, vocabulary_dir=vocabulary_dir, vault_dir=vault_dir)
    first = {p.name: p.read_bytes() for p in (vault_dir / "positions").glob("*.md")}
    (vault_dir / "positions" / "pos-9999.md").write_text("stale", encoding="utf-8")

    write_position_pages(map_dir=map_dir, vocabulary_dir=vocabulary_dir, vault_dir=vault_dir)
    second = {p.name: p.read_bytes() for p in (vault_dir / "positions").glob("*.md")}

    assert first == second


def test_without_a_vocabulary_the_pages_still_render(tmp_path: Path) -> None:
    map_dir, _, vault_dir = _fixture(tmp_path)

    write_position_pages(
        map_dir=map_dir, vocabulary_dir=tmp_path / "no-vocabulary", vault_dir=vault_dir
    )

    frontmatter, body = _page(vault_dir, "pos-0001")
    assert frontmatter["claim"] == []
    assert "[[pos-0002]]" in body


PROFILE_RELATIONS = [
    {
        "from_position_id": "pos-0003",
        "to_position_id": "pos-0001",
        "relation": "extends",
        "says": "a2 carries the deniability argument into a second case.",
        "generator": "profile",
    },
    {
        "from_position_id": "pos-0001",
        "to_position_id": "pos-0002",
        "relation": "answers",
        "says": "a duplicate of a pair relations.jsonl already holds.",
        "generator": "profile-context",
    },
]


def test_profile_relations_are_links_too_and_relations_jsonl_wins_a_pair(
    tmp_path: Path,
) -> None:
    map_dir, vocabulary_dir, vault_dir = _fixture(tmp_path)
    _write_jsonl(map_dir / "profile_relations.jsonl", PROFILE_RELATIONS)

    result = write_position_pages(
        map_dir=map_dir, vocabulary_dir=vocabulary_dir, vault_dir=vault_dir
    )

    assert result["position_pages_isolated"] == 0
    _, isolated_before = _page(vault_dir, "pos-0003")
    assert "[[pos-0001]]" in isolated_before
    _, body = _page(vault_dir, "pos-0001")
    assert "[[pos-0003]]" in body
    assert "extends" in body
    assert "answers" not in body
