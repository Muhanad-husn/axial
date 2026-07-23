"""Inner unit tests for the calibration gate (issue #263, specs/PHASE-B.md
§10 / §7.4). Co-located under src/axial/gates/ per the repo's existing test
layout. Mirrors src/axial/gates/test_grounding.py's own scripted-judge
pattern.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.gates.calibration import (
    CalibrationCheckFailedError,
    InvalidConfidenceBandError,
    SelfGradingError,
    run_calibration_gate,
)
from axial.gates.grounding import UnresolvableGroundsError
from axial.llm import ExplodingLLMClient

CHUNK_ID = "calfix_001_syria"
MISSING_CHUNK_ID = "calfix_999_missing"

DISTINCT_MODELS = {"synthesize": "model-a", "calibration": "model-b"}
SAME_MODEL = {"synthesize": "model-x", "calibration": "model-x"}


class ScriptedJudgeClient:
    """Mirrors `test_grounding.ScriptedJudgeClient` exactly."""

    def __init__(self, *, model_by_pass: dict[str, str], responses: list[str]):
        self._model_by_pass = model_by_pass
        self._responses = list(responses)
        self.calls: list[tuple[str | None, str]] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls.append((pass_name, prompt))
        return self._responses[(len(self.calls) - 1) % len(self._responses)]

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return self._model_by_pass.get(pass_name, "unmapped")

    def complete_with_tools(
        self, prompt: str, tools: list[dict[str, Any]], pass_name: str | None = None
    ) -> dict[str, Any] | None:
        raise NotImplementedError("the calibration gate never calls this")


def _write_vault(root: Path) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": CHUNK_ID,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{CHUNK_ID}: synthetic prose.",
        "source_meta": {"author": "A", "title": "T", "date": 2020, "thesis": "X", "scope": "Y"},
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": "Syria"},
        "polities_touched": ["Syria"],
        "artifact_refs": [],
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{CHUNK_ID}.md").write_text(text, encoding="utf-8")
    return root / "vault"


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    return _write_vault(tmp_path)


def _claim(claim_id: str, *, confidence: Any, chunk_id: str = CHUNK_ID) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "kind": "a",
        "text": f"Claim text for {claim_id}.",
        "confidence": confidence,
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
    }


def test_band_observed_rate_within_tolerance_passes(vault_dir: Path, tmp_path: Path):
    # 10 high-band claims, 9 judged correct (0.90 observed vs 0.85 target,
    # deviation 0.05 <= 0.15 threshold).
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS,
        responses=[json.dumps({"verdict": "correct"})] * 9 + [json.dumps({"verdict": "incorrect"})],
    )
    records = [{"claims": [_claim(f"c-{i}", confidence="high") for i in range(10)]}]

    report = run_calibration_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    metric = report.metrics[0]
    assert metric.metric == "band_reliability"
    assert metric.threshold == 0.15
    assert metric.detail["bands"]["high"]["observed"] == pytest.approx(0.9)
    assert metric.detail["bands"]["high"]["n"] == 10
    assert metric.value == pytest.approx(0.05)
    assert metric.passed is True


def test_ordering_violation_fails_even_within_tolerance(vault_dir: Path, tmp_path: Path):
    """medium (0.90 observed) outranks high (0.80 observed) -- both bands
    individually sit within 0.15 of their own target, but the strict
    ordering requirement (high > medium > low) is violated."""
    responses = (
        [json.dumps({"verdict": "correct"})] * 8
        + [json.dumps({"verdict": "incorrect"})] * 2  # high: 8/10 = 0.80
        + [json.dumps({"verdict": "correct"})] * 9
        + [json.dumps({"verdict": "incorrect"})]  # medium: 9/10 = 0.90
    )
    client = ScriptedJudgeClient(model_by_pass=DISTINCT_MODELS, responses=responses)
    records = [
        {
            "claims": [_claim(f"h-{i}", confidence="high") for i in range(10)]
            + [_claim(f"m-{i}", confidence="medium") for i in range(10)]
        }
    ]

    report = run_calibration_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    metric = report.metrics[0]
    assert metric.detail["strictly_ordered"] is False
    assert metric.passed is False


def test_empty_bands_excluded_from_ordering_check(vault_dir: Path, tmp_path: Path):
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS, responses=[json.dumps({"verdict": "correct"})] * 10
    )
    records = [{"claims": [_claim(f"h-{i}", confidence="high") for i in range(10)]}]

    report = run_calibration_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    metric = report.metrics[0]
    assert metric.detail["bands"]["medium"]["n"] == 0
    assert metric.detail["bands"]["medium"]["observed"] is None
    assert metric.detail["strictly_ordered"] is True


def test_ordering_inversion_across_a_gap_is_still_caught(vault_dir: Path, tmp_path: Path):
    """`medium` carries no data at all, but `low` observed above `high` is
    still a real inversion -- comparing only adjacent CONFIDENCE_BANDS slots
    would miss it since neither (high, medium) nor (medium, low) includes
    this pair."""
    responses = (
        [json.dumps({"verdict": "incorrect"})] * 10  # high: 0/10 = 0.0
        + [json.dumps({"verdict": "correct"})] * 10  # low: 10/10 = 1.0
    )
    client = ScriptedJudgeClient(model_by_pass=DISTINCT_MODELS, responses=responses)
    records = [
        {
            "claims": [_claim(f"h-{i}", confidence="high") for i in range(10)]
            + [_claim(f"l-{i}", confidence="low") for i in range(10)]
        }
    ]

    report = run_calibration_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    metric = report.metrics[0]
    assert metric.detail["strictly_ordered"] is False
    assert metric.passed is False


def test_empty_claim_set_reports_failed_not_vacuous(tmp_path: Path):
    report = run_calibration_gate(
        [],
        client=ExplodingLLMClient(),
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    metric = report.metrics[0]
    assert metric.value is None
    assert metric.passed is False
    assert metric.n == 0


def test_invalid_confidence_band_raises(vault_dir: Path, tmp_path: Path):
    records = [{"claims": [_claim("c-1", confidence="very-high")]}]
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS, responses=[json.dumps({"verdict": "correct"})]
    )
    with pytest.raises(InvalidConfidenceBandError):
        run_calibration_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )


def test_missing_confidence_raises(vault_dir: Path, tmp_path: Path):
    records = [{"claims": [_claim("c-1", confidence=None)]}]
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS, responses=[json.dumps({"verdict": "correct"})]
    )
    with pytest.raises(InvalidConfidenceBandError):
        run_calibration_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )


def test_self_grading_guard_raises_before_any_judge_call(vault_dir: Path, tmp_path: Path):
    client = ScriptedJudgeClient(
        model_by_pass=SAME_MODEL, responses=[json.dumps({"verdict": "correct"})]
    )
    records = [{"claims": [_claim("c-1", confidence="high")]}]
    with pytest.raises(SelfGradingError) as excinfo:
        run_calibration_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )
    assert "model-x" in str(excinfo.value)
    assert client.calls == [], "zero judge calls when the self-grading guard fires"


def test_unresolvable_grounds_pointer_is_a_gate_error(vault_dir: Path, tmp_path: Path):
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS, responses=[json.dumps({"verdict": "correct"})]
    )
    records = [{"claims": [_claim("c-1", confidence="high", chunk_id=MISSING_CHUNK_ID)]}]
    with pytest.raises(UnresolvableGroundsError):
        run_calibration_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )


def test_judge_response_missing_verdict_raises(vault_dir: Path, tmp_path: Path):
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS, responses=[json.dumps({"not_verdict": "x"})]
    )
    records = [{"claims": [_claim("c-1", confidence="high")]}]
    with pytest.raises(CalibrationCheckFailedError):
        run_calibration_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )


def test_band_targets_configurable(vault_dir: Path, tmp_path: Path):
    """Overriding `calibration.band_targets.high` changes the deviation and
    outcome with no code change."""
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS,
        responses=[json.dumps({"verdict": "correct"})] * 5
        + [json.dumps({"verdict": "incorrect"})] * 5,
    )
    records = [{"claims": [_claim(f"c-{i}", confidence="high") for i in range(10)]}]
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        yaml.safe_dump({"calibration": {"band_targets": {"high": 0.50}}}), encoding="utf-8"
    )

    report = run_calibration_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=config_path,
    )
    metric = report.metrics[0]
    assert metric.detail["bands"]["high"]["target"] == 0.50
    assert metric.value == pytest.approx(0.0)
    assert metric.passed is True
