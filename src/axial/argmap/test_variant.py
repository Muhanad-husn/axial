"""Issue #859: a variant build re-extracts the SAME bags under another
model, in its own directory, never touching the baseline pin's."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from axial.argmap.build import MapError, _prior_pin_dir, run_map_build
from axial.llm import StubLLMClient

_GROUP_A = [[1.0, 0.0, 0.0], [0.99, 0.02, 0.0], [0.98, 0.03, 0.0]]
_GROUP_B = [[0.0, 1.0, 0.0], [0.0, 0.99, 0.02]]


class _Client(StubLLMClient):
    def __init__(self, model: str) -> None:
        super().__init__()
        self.model = model

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        return json.dumps({"arguments": [], "unassigned": []})

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return self.model


def _cluster(vectors: np.ndarray, threshold: float) -> list[int]:
    reps: list[np.ndarray] = []
    labels: list[int] = []
    for vector in vectors:
        match = None
        for label, rep in enumerate(reps):
            cosine = float(np.dot(vector, rep) / (np.linalg.norm(vector) * np.linalg.norm(rep)))
            if 1.0 - cosine <= threshold:
                match = label
                break
        if match is None:
            match = len(reps)
            reps.append(np.asarray(vector, dtype=np.float64))
        labels.append(match)
    return labels


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[float]]:
    monkeypatch.setattr("axial.argmap.build.load_back_matter_sections", lambda trees_dir: {})
    monkeypatch.setattr("axial.argmap.build._agglomerative_cluster", _cluster)
    answers = tmp_path / "answers"
    answers.mkdir()
    vectors: dict[str, list[float]] = {}
    lines = []
    for prefix, group in (("A", _GROUP_A), ("B", _GROUP_B)):
        for i, vector in enumerate(group):
            claim = f"Claim {prefix}{i}."
            vectors[claim] = vector
            lines.append(
                {
                    "source_id": "alpha-2020-book",
                    "chunk_id": f"alpha-2020-book_{prefix}{i}_body_001",
                    "answers": {
                        "claim": claim,
                        "mechanism": "m",
                        "comparison": "not-in-passage",
                        "concedes": "not-in-passage",
                        "assumes": "not-in-passage",
                        "position_of": "not-in-passage",
                        "ranges_over": "not-in-passage",
                    },
                }
            )
    (answers / "alpha-2020-book.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    return vectors


def _build(tmp_path: Path, vectors: dict[str, list[float]], client: _Client, **kwargs):
    return run_map_build(
        answers_dir=tmp_path / "answers",
        trees_dir=tmp_path / "trees",
        map_dir=tmp_path / "map",
        client=client,
        encode=lambda claims: [vectors[c] for c in claims],
        pin="pin1",
        guard=False,
        log=lambda _msg: None,
        **kwargs,
    )


def test_variant_build_writes_its_own_directory_and_leaves_the_baseline_alone(
    tmp_path: Path, corpus
) -> None:
    _build(tmp_path, corpus, _Client("flash"))
    base_dir = tmp_path / "map" / "pin1"
    before = {p.name: p.read_bytes() for p in base_dir.iterdir()}

    variant = _Client("vendor/frontier")
    manifest = _build(tmp_path, corpus, variant, variant="vendor-frontier")

    assert {p.name: p.read_bytes() for p in base_dir.iterdir()} == before
    var_dir = tmp_path / "map" / "pin1-variant-vendor-frontier"
    # Bagging is the baseline's own, byte for byte.
    assert (var_dir / "bag_state.json").read_bytes() == before["bag_state.json"]
    # Re-extracted, not seeded from the baseline's reads: every read was asked.
    assert variant.call_count == manifest["counts"]["reads"] > 0
    assert manifest["counts"]["units_reused"] == 0
    written = json.loads((var_dir / "map.json").read_text(encoding="utf-8"))
    assert written["model"] == "vendor/frontier"
    assert "cost_usd" in written and "usage" in written and "relations" in written


def test_variant_build_refuses_without_a_reusable_baseline_bag_state(
    tmp_path: Path, corpus
) -> None:
    with pytest.raises(MapError, match="baseline"):
        _build(tmp_path, corpus, _Client("vendor/frontier"), variant="vendor-frontier")


def test_a_variant_directory_is_never_the_prior_pin_of_a_later_build(tmp_path: Path) -> None:
    for name in ("aaaa", "aaaa-variant-x"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "map.json").write_text("{}", encoding="utf-8")
    # The variant is the newer one; it must still not be chosen.
    assert _prior_pin_dir(tmp_path, "bbbb") == tmp_path / "aaaa"
