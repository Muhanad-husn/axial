"""Inner unit tests for `axial.argmap.ask.run_map_ask_for_brief`'s
vocabulary-step wiring (issue #807): `use_vocabulary=True` adds
`vocabulary_neighbours`'s own positions to what assembly walks, between the
corridor and the round-robin order, and threads a `VocabularyJoinResult`
back on `AskResult.vocabulary`. `use_vocabulary=False` (the default, the
`map` arm) is unchanged -- `AskResult.vocabulary` stays `None` and
`assemble_map_evidence` never sees a vocabulary position at all.

No real encoder and no network: `encode` is a deterministic fixture --
identical text lands with cosine similarity 1.0, distinct text lands near
0 -- so the door's own canned response reliably lands on a known position
without downloading a sentence-transformer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Sequence

import numpy as np
import pytest

from axial.argmap.ask import ENCODER_MODEL, run_map_ask_for_brief
from axial.argmap.vocabulary_join import NoVocabularyError
from axial.brief.intake import Brief
from axial.llm import StubLLMClient


def _fake_encode(texts: Sequence[str]) -> np.ndarray:
    vectors = []
    for text in texts:
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (2**32)
        rng = np.random.default_rng(seed)
        vector = rng.normal(size=16)
        vectors.append(vector / np.linalg.norm(vector))
    return np.array(vectors)


class _DecomposeOnlyClient(StubLLMClient):
    """Answers the door's own call with `arguments`, verbatim, whatever
    text the test asked it to land on -- and raises on any other pass,
    since nothing here should reach interrogation or synthesis at all."""

    def __init__(self, arguments: list[str]) -> None:
        super().__init__()
        self._arguments = arguments

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        return json.dumps({"arguments": self._arguments})

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "test-double-model"


def _position(position_id: str, chunk_ids: list[str], sources: list[str], argument: str) -> dict:
    return {
        "position_id": position_id,
        "argument": argument,
        "size": len(chunk_ids),
        "sources": sources,
        "authors": [f"{source}-author" for source in sources],
        "chunk_ids": chunk_ids,
    }


def _write_map(map_root: Path, positions: list[dict], relations: list[dict] | None = None) -> Path:
    """Writes `<map_root>/pin/` (`map.json`/`positions.jsonl`), returns
    `map_root` -- a caller passes `map_dir=map_root, pin="pin"` to
    `run_map_ask_for_brief`, which appends the pin itself."""
    map_dir = map_root / "pin"
    map_dir.mkdir(parents=True, exist_ok=True)
    (map_dir / "map.json").write_text(
        json.dumps({"encoder": ENCODER_MODEL}), encoding="utf-8"
    )
    (map_dir / "positions.jsonl").write_text(
        "\n".join(json.dumps(position) for position in positions), encoding="utf-8"
    )
    if relations:
        (map_dir / "relations.jsonl").write_text(
            "\n".join(json.dumps(relation) for relation in relations), encoding="utf-8"
        )
    return map_root


def _assignment(chunk_id: str, source_id: str, category_id: str | None) -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "column": "mechanism",
        "element_index": 0,
        "level": 1,
        "value": f"value for {chunk_id}",
        "category_id": category_id,
        "refused": category_id is None,
    }


def _write_vocabulary(root: Path, column: str, assignments: list[dict]) -> Path:
    column_dir = root / column
    column_dir.mkdir(parents=True, exist_ok=True)
    (column_dir / "assignments.jsonl").write_text(
        "\n".join(json.dumps(record) for record in assignments), encoding="utf-8"
    )
    (column_dir / "manifest.json").write_text(
        json.dumps({"column": column, "scheme_version": "v1", "max_level": 1, "categories": []}),
        encoding="utf-8",
    )
    return root


def _brief() -> Brief:
    return Brief(brief_id="vocab_join_001", case="A case.", request="A question?")


def test_use_vocabulary_false_leaves_ask_result_vocabulary_none(tmp_path: Path):
    argument = "States extract resources through coercion."
    map_dir = _write_map(
        tmp_path / "map",
        [_position("pos-landed", ["n1"], ["src-1"], argument)],
    )
    client = _DecomposeOnlyClient([argument])

    result = run_map_ask_for_brief(
        _brief(), client=client, map_dir=map_dir, pin="pin", encode=_fake_encode
    )

    assert result.vocabulary is None
    assert result.assembled_chunk_ids == ("n1",)


def test_use_vocabulary_true_adds_neighbours_to_assembled_evidence(tmp_path: Path):
    argument = "States extract resources through coercion."
    pos_landed = _position("pos-landed", ["n1"], ["src-1"], argument)
    pos_other = _position("pos-other", ["n2"], ["src-2"], "An unrelated argument.")
    map_dir = _write_map(tmp_path / "map", [pos_landed, pos_other])

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [
            _assignment("n1", "src-1", "war-and-state"),
            _assignment("n2", "src-2", "war-and-state"),
        ],
    )
    client = _DecomposeOnlyClient([argument])

    result = run_map_ask_for_brief(
        _brief(),
        client=client,
        map_dir=map_dir,
        pin="pin",
        encode=_fake_encode,
        use_vocabulary=True,
        vocabulary_column="mechanism",
        vocabulary_dir=vocabulary_dir,
        # `land_arguments` has no similarity floor -- it keeps the top
        # `top_k` positions per ask regardless of score, so with only two
        # positions on the map `pos-other` would land too (defeating the
        # point of this fixture: it must stay UNLANDED, reached only
        # through the vocabulary step). `top_k=1` keeps just the best
        # match, `pos-landed`'s own exact-text argument (cosine 1.0).
        top_k=1,
    )

    assert result.vocabulary is not None
    assert [p.position_id for p in result.vocabulary.positions] == ["pos-other"]
    # n2 reached assembly ONLY through the vocabulary step -- it is not one
    # of pos-landed's own chunk_ids and no corridor relation touches it.
    assert "n2" in result.assembled_chunk_ids
    assert [c.category_id for c in result.vocabulary.categories] == ["war-and-state"]


def test_a_position_already_landed_is_never_reported_as_a_vocabulary_neighbour(tmp_path: Path):
    """Both positions' own notes reach the same category, but only one
    position exists here -- `pos-landed` itself -- so the vocabulary step
    must find no OTHER position to report (the same guard `build_corridor`
    already applies at its own hop)."""
    argument = "States extract resources through coercion."
    pos_landed = _position("pos-landed", ["n1", "n2"], ["src-1"], argument)
    map_dir = _write_map(tmp_path / "map", [pos_landed])

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [
            _assignment("n1", "src-1", "war-and-state"),
            _assignment("n2", "src-1", "war-and-state"),
        ],
    )
    client = _DecomposeOnlyClient([argument])

    result = run_map_ask_for_brief(
        _brief(),
        client=client,
        map_dir=map_dir,
        pin="pin",
        encode=_fake_encode,
        use_vocabulary=True,
        vocabulary_dir=vocabulary_dir,
    )

    assert result.vocabulary.positions == ()


def test_use_vocabulary_true_with_no_persisted_column_raises_naming_the_column(tmp_path: Path):
    argument = "States extract resources through coercion."
    map_dir = _write_map(
        tmp_path / "map", [_position("pos-landed", ["n1"], ["src-1"], argument)]
    )
    client = _DecomposeOnlyClient([argument])

    with pytest.raises(NoVocabularyError):
        run_map_ask_for_brief(
            _brief(),
            client=client,
            map_dir=map_dir,
            pin="pin",
            encode=_fake_encode,
            use_vocabulary=True,
            vocabulary_column="mechanism",
            vocabulary_dir=tmp_path / "empty-vocab",
        )
