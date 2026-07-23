"""Inner unit tests for the synthesis-quality gate (issue #263,
specs/PHASE-B.md §10). Co-located under src/axial/gates/ per the repo's
existing test layout. Mirrors src/axial/validators/test_counter_position.py's
own vault-fixture pattern since this gate reuses `validate_counter_position`
wholesale.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.gates.synthesis_quality import run_synthesis_quality_gate
from axial.llm import ExplodingLLMClient

CHUNK_A = "sqfix_001_bellicist"
CHUNK_B = "sqfix_002_marxist"

DISTINCT_MODELS = {"synthesize": "model-a", "counter_position": "model-b"}


class FakeClient:
    """Mirrors `test_counter_position.FakeClient` exactly."""

    def __init__(self, *, model_by_pass: dict[str, str], response: str = ""):
        self._model_by_pass = model_by_pass
        self._response = response
        self.calls: list[str | None] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls.append(pass_name)
        return self._response

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return self._model_by_pass.get(pass_name, "unmapped")

    def complete_with_tools(
        self, prompt: str, tools: list[dict[str, Any]], pass_name: str | None = None
    ) -> dict[str, Any] | None:
        raise NotImplementedError("the synthesis-quality gate never calls this")


def _chunk_frontmatter(chunk_id: str, *, theory_school_primary: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL: synthetic prose for {chunk_id}.",
        "source_meta": {"author": "A", "title": "T", "date": 2020, "thesis": "X", "scope": "Y"},
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": theory_school_primary,
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": "Syria"},
        "polities_touched": ["Syria"],
        "artifact_refs": [],
    }


def _write_chunk(vault_dir: Path, chunk_id: str, *, theory_school_primary: str) -> None:
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = _chunk_frontmatter(chunk_id, theory_school_primary=theory_school_primary)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    _write_chunk(vault, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault, CHUNK_B, theory_school_primary="marxist-political-economy")
    return vault


def _grounds(*chunk_ids: str) -> list[dict[str, str]]:
    return [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids]


def _claim(claim_id: str, *chunk_ids: str) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": f"Text for {claim_id}.",
        "kind": "a",
        "grounds": _grounds(*chunk_ids),
    }


def _disclosed_one_sided(reason: str = "corpus carries no opposing school") -> dict[str, Any]:
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": True,
        "one_sided_reason": reason,
    }


def _absent_counter_position() -> dict[str, Any]:
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


def _present_counter_position(*chunk_ids: str) -> dict[str, Any]:
    return {
        "present": True,
        "stance": "The opposing school holds...",
        "grounds": _grounds(*chunk_ids),
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


def _contested_record(brief_id: str, *, counter_position: dict[str, Any]) -> dict[str, Any]:
    return {
        "brief_id": brief_id,
        "claims": [_claim(f"{brief_id}-c1", CHUNK_A, CHUNK_B)],
        "counter_position": counter_position,
    }


def _uncontested_record(brief_id: str) -> dict[str, Any]:
    return {
        "brief_id": brief_id,
        "claims": [_claim(f"{brief_id}-c1", CHUNK_A)],
        "counter_position": _absent_counter_position(),
    }


def test_all_contested_present_or_disclosed_scores_1_0(vault_dir: Path, tmp_path: Path):
    records = [
        _contested_record(f"DEV{i}", counter_position=_disclosed_one_sided()) for i in range(10)
    ]
    report = run_synthesis_quality_gate(
        records,
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    presence = next(m for m in report.metrics if m.metric == "counter_position_presence_rate")
    assert presence.value == 1.00
    assert presence.threshold == 0.95
    assert presence.passed is True
    assert presence.n == 10


def test_uncontested_records_excluded_from_denominator(vault_dir: Path, tmp_path: Path):
    contested = [
        _contested_record(f"DEV{i}", counter_position=_disclosed_one_sided()) for i in range(10)
    ]
    uncontested = [_uncontested_record(f"UNC{i}") for i in range(10)]
    report = run_synthesis_quality_gate(
        contested + uncontested,
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    presence = next(m for m in report.metrics if m.metric == "counter_position_presence_rate")
    assert presence.n == 10, "uncontested records must never inflate the denominator"
    assert presence.value == 1.00


def test_zero_contested_records_reports_n_0_not_vacuous_pass(vault_dir: Path, tmp_path: Path):
    records = [_uncontested_record(f"UNC{i}") for i in range(5)]
    report = run_synthesis_quality_gate(
        records,
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    presence = next(m for m in report.metrics if m.metric == "counter_position_presence_rate")
    assert presence.n == 0
    assert presence.value is None
    assert presence.passed is False


def test_two_failing_contested_records_score_0_83_and_are_named(vault_dir: Path, tmp_path: Path):
    passing = [
        _contested_record(f"DEV{i}", counter_position=_disclosed_one_sided()) for i in range(10)
    ]
    failing = [
        _contested_record("BAD1", counter_position=_absent_counter_position()),
        _contested_record("BAD2", counter_position=_absent_counter_position()),
    ]
    report = run_synthesis_quality_gate(
        passing + failing,
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    presence = next(m for m in report.metrics if m.metric == "counter_position_presence_rate")
    assert presence.n == 12
    assert presence.value == pytest.approx(10 / 12)
    assert presence.passed is False
    assert set(presence.detail["failing_brief_ids"]) == {"BAD1", "BAD2"}


def test_steelman_quality_scores_the_stated_counter_position(vault_dir: Path, tmp_path: Path):
    client = FakeClient(
        model_by_pass=DISTINCT_MODELS,
        response=json.dumps({"verdict": "steelman", "detail": "solid"}),
    )
    records = [_contested_record("DEV1", counter_position=_present_counter_position(CHUNK_B))]
    report = run_synthesis_quality_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    steelman = next(m for m in report.metrics if m.metric == "steelman_quality")
    assert steelman.n == 1
    assert steelman.value == 1.0
    assert steelman.passed is True
    assert "counter_position" in client.calls
    assert "synthesize" not in client.calls


def test_steelman_check_skipped_for_one_sided_disclosure_zero_model_calls(
    vault_dir: Path, tmp_path: Path
):
    records = [_contested_record("DEV1", counter_position=_disclosed_one_sided())]
    report = run_synthesis_quality_gate(
        records,
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    steelman = next(m for m in report.metrics if m.metric == "steelman_quality")
    assert steelman.n == 0
    assert steelman.passed is True, "a legitimately empty subset is a vacuous pass, not a failure"


def test_same_model_guard_propagates_from_validate_counter_position(
    vault_dir: Path, tmp_path: Path
):
    from axial.validators.counter_position import SamePassModelError

    client = FakeClient(
        model_by_pass={"synthesize": "same", "counter_position": "same"},
        response=json.dumps({"verdict": "steelman", "detail": ""}),
    )
    records = [_contested_record("DEV1", counter_position=_present_counter_position(CHUNK_B))]
    with pytest.raises(SamePassModelError):
        run_synthesis_quality_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )
