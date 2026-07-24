"""Unit tests for the stage-5e outer eval (issue #353): the pure verdict-
combination logic (`compute_axis_verdict`, `run_verdict`) runs entirely off
JSON fixtures on disk, no network, no sklearn. `run_tag_cost_probe` and
`run_drift_check` are exercised against an injected fake `LLMClient` (mirrors
`axial.llm.StubLLMClient`'s own shape) with an injected chunk `sample` and
(for the drift check) injected `classifier_predictions` -- the seams this
module documents for exactly this purpose -- so neither test needs a real
vault, a real embeddings store, or network access. A live, real-corpus run of
all three passes is reported separately (see the PR body), not repeated here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.codebook import load_codebook
from axial.distill.verdict import (
    CITED_TEACHER_GOLD_AGREEMENT,
    CorpusPinRequiredError,
    NoChunksToSampleError,
    NoUsageReportedError,
    VerdictError,
    compute_axis_verdict,
    run_drift_check,
    run_tag_cost_probe,
    run_verdict,
    sample_chunks,
)
from axial.eval.corpus_pin import write_pin
from axial.schema import load_schema
from axial.tag import DEFAULT_DOMAIN_DIR

_VALID_TAG_JSON = json.dumps(
    {
        "role_in_argument": "role:claim",
        "empirical_scope": "scope:country-case",
        "polity": "Syria",
        "polities_touched": ["Syria"],
        "field": {"primary": "state", "secondary": ["ideology"]},
        "claim_type": {"primary": "state-formation", "subtags": ["formation:bellicist"]},
        "theory_school": {"primary": "bellicist", "status": "candidate"},
    }
)


class _FakeClient:
    """Minimal `LLMClient` double: real accumulator math (mirrors
    `axial.llm._accumulate_usage`'s shape), a fixed real per-call token
    count, and an optional response queue (`responses`) so a test can force
    a specific chunk's completion to raise."""

    def __init__(
        self,
        model: str = "deepseek/deepseek-v4-flash",
        prompt_tokens: int = 500,
        completion_tokens: int = 80,
        responses: list[object] | None = None,
    ):
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.calls = 0
        self._usage: dict[str, int] | None = None
        self._responses = list(responses) if responses is not None else None

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls += 1
        if self._usage is None:
            self._usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._usage["prompt_tokens"] += self.prompt_tokens
        self._usage["completion_tokens"] += self.completion_tokens
        self._usage["total_tokens"] += self.prompt_tokens + self.completion_tokens
        if self._responses is not None:
            response = self._responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return _VALID_TAG_JSON

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return self.model

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return dict(self._usage) if self._usage else None


def _stage_pin(tmp_path: Path, name: str = "baseline") -> Path:
    vault_dir = tmp_path / "data" / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    envelopes_dir = tmp_path / "data" / "envelopes"
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    evals_dir = tmp_path / "evals" / "corpus_pin"
    write_pin(name, vault_dir=vault_dir, envelopes_dir=envelopes_dir, evals_dir=evals_dir)
    return evals_dir


def _schema():
    return load_schema(DEFAULT_DOMAIN_DIR)


def _codebook():
    return load_codebook(DEFAULT_DOMAIN_DIR)


# --- compute_axis_verdict -----------------------------------------------------


def _manifest(*, teacher, thresholds):
    return {"axis": "field", "teacher_gold_agreement": teacher, "thresholds": thresholds}


def test_compute_axis_verdict_blends_coverage_and_tail_fallback():
    manifest = _manifest(
        teacher=0.767,
        thresholds=[{"threshold": 0.6, "coverage": 0.833, "accuracy_on_covered": 0.78}],
    )

    verdict = compute_axis_verdict("field", manifest, 0.6)

    expected_hybrid = 0.833 * 0.78 + 0.167 * 0.767
    assert verdict["hybrid_accuracy"] == pytest.approx(expected_hybrid)
    assert verdict["teacher_gold_agreement_source"] == "measured"
    assert verdict["meets_or_beats_teacher"] is True


def test_compute_axis_verdict_uses_cited_fallback_for_role_in_argument():
    manifest = _manifest(
        teacher=None,
        thresholds=[{"threshold": 0.6, "coverage": 0.508, "accuracy_on_covered": 0.639}],
    )

    verdict = compute_axis_verdict("role_in_argument", manifest, 0.6)

    assert verdict["teacher_gold_agreement"] == CITED_TEACHER_GOLD_AGREEMENT["role_in_argument"]
    assert verdict["teacher_gold_agreement_source"] == "cited"
    assert verdict["hybrid_accuracy"] is not None


def test_compute_axis_verdict_no_teacher_no_fallback_leaves_hybrid_accuracy_none():
    manifest = _manifest(
        teacher=None, thresholds=[{"threshold": 0.6, "coverage": 0.5, "accuracy_on_covered": 0.7}]
    )

    verdict = compute_axis_verdict("field", manifest, 0.6)  # "field" has no cited fallback

    assert verdict["hybrid_accuracy"] is None
    assert verdict["meets_or_beats_teacher"] is None


def test_compute_axis_verdict_unknown_threshold_raises():
    manifest = _manifest(
        teacher=0.5, thresholds=[{"threshold": 0.6, "coverage": 0.5, "accuracy_on_covered": 0.7}]
    )

    with pytest.raises(VerdictError):
        compute_axis_verdict("field", manifest, 0.9)


def test_compute_axis_verdict_below_teacher_is_not_meets_or_beats():
    manifest = _manifest(
        teacher=0.9, thresholds=[{"threshold": 0.6, "coverage": 0.3, "accuracy_on_covered": 0.5}]
    )

    verdict = compute_axis_verdict("field", manifest, 0.6)

    assert verdict["meets_or_beats_teacher"] is False


# --- sample_chunks -------------------------------------------------------------


def test_sample_chunks_excludes_and_caps_and_is_seed_deterministic():
    universe = {f"c{i}": f"text {i}" for i in range(20)}
    excluded = {"c0", "c1"}

    first = sample_chunks(universe, excluded, sample_size=5, seed=42)
    second = sample_chunks(universe, excluded, sample_size=5, seed=42)
    different_seed = sample_chunks(universe, excluded, sample_size=5, seed=7)

    assert first == second
    assert len(first) == 5
    assert all(chunk_id not in excluded for chunk_id, _text in first)
    assert first != different_seed  # not a tautology in practice for this universe size


# --- run_verdict ---------------------------------------------------------------


def _write_axis_manifest(
    manifest_dir: Path, axis: str, *, teacher, coverage, accuracy_on_covered, threshold=0.6
) -> None:
    manifest = {
        "axis": axis,
        "teacher_gold_agreement": teacher,
        "thresholds": [
            {
                "threshold": threshold,
                "coverage": coverage,
                "accuracy_on_covered": accuracy_on_covered,
            }
        ],
    }
    (manifest_dir / f"classify_{axis}_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def _stage_all_axis_manifests(manifest_dir: Path) -> None:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    _write_axis_manifest(
        manifest_dir, "claim_type", teacher=0.560, coverage=0.276, accuracy_on_covered=0.75
    )
    _write_axis_manifest(
        manifest_dir, "theory_school", teacher=0.543, coverage=0.345, accuracy_on_covered=0.70
    )
    _write_axis_manifest(
        manifest_dir, "field", teacher=0.767, coverage=0.833, accuracy_on_covered=0.78
    )
    _write_axis_manifest(
        manifest_dir, "role_in_argument", teacher=None, coverage=0.508, accuracy_on_covered=0.639
    )
    (manifest_dir / "embedding_manifest.json").write_text(
        json.dumps({"chunk_count": 18410}), encoding="utf-8"
    )


def test_run_verdict_missing_axis_manifest_raises(tmp_path: Path):
    evals_dir = _stage_pin(tmp_path)
    manifest_dir = tmp_path / "distill"
    manifest_dir.mkdir()

    with pytest.raises(VerdictError):
        run_verdict(
            manifest_dir=manifest_dir,
            evals_dir=evals_dir,
            output_path=tmp_path / "verdict.json",
            cost_probe_path=tmp_path / "no-cost.json",
            drift_check_path=tmp_path / "no-drift.json",
        )


def test_run_verdict_requires_corpus_pin(tmp_path: Path):
    manifest_dir = tmp_path / "distill"
    _stage_all_axis_manifests(manifest_dir)

    with pytest.raises(CorpusPinRequiredError):
        run_verdict(
            manifest_dir=manifest_dir,
            evals_dir=tmp_path / "evals" / "corpus_pin",
            output_path=tmp_path / "verdict.json",
        )


def test_run_verdict_without_cost_probe_reports_unmeasured_cost(tmp_path: Path):
    evals_dir = _stage_pin(tmp_path)
    manifest_dir = tmp_path / "distill"
    _stage_all_axis_manifests(manifest_dir)

    result = run_verdict(
        manifest_dir=manifest_dir,
        evals_dir=evals_dir,
        output_path=tmp_path / "verdict.json",
        cost_probe_path=tmp_path / "no-cost.json",
        drift_check_path=tmp_path / "no-drift.json",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["cost"]["measured"] is False
    assert "not measured" in result.overall_verdict
    assert manifest["axis_verdicts"]["empirical_scope"]["graduated"] is False


def test_run_verdict_with_cost_probe_computes_corpus_scale_savings(tmp_path: Path):
    evals_dir = _stage_pin(tmp_path)
    manifest_dir = tmp_path / "distill"
    _stage_all_axis_manifests(manifest_dir)

    cost_probe_path = tmp_path / "cost.json"
    cost_probe_path.write_text(
        json.dumps(
            {
                "model": "deepseek/deepseek-v4-flash",
                "cost_per_chunk_usd_at_votes": 0.003,
                "cost_per_chunk_usd_single_draw": 0.001,
            }
        ),
        encoding="utf-8",
    )

    result = run_verdict(
        manifest_dir=manifest_dir,
        evals_dir=evals_dir,
        output_path=tmp_path / "verdict.json",
        cost_probe_path=cost_probe_path,
        drift_check_path=tmp_path / "no-drift.json",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    cost = manifest["cost"]
    assert cost["measured"] is True
    assert cost["overall_baseline_cost_usd"] == pytest.approx(0.003 * 18410)
    assert cost["overall_hybrid_cost_usd"] == pytest.approx(0.001 * 18410)
    assert cost["dollar_savings_fraction"] == pytest.approx(1 - (0.001 / 0.003))
    assert manifest["pipeline_quality"]["quality_per_dollar_hybrid"] > 0
    # All 4 graduated axes clear their teacher at the fixture's own operating
    # point (mirrors the real manifests' own cited figures) -> "hybrid".
    assert result.overall_verdict == "hybrid"
    assert manifest["per_axis_calls"]["claim_type"] == "graduate"
    assert manifest["per_axis_calls"]["empirical_scope"].startswith("stay-llm")


# --- run_tag_cost_probe ---------------------------------------------------------


def test_run_tag_cost_probe_fires_votes_times_sample_size_and_computes_real_cost(tmp_path: Path):
    evals_dir = _stage_pin(tmp_path)
    client = _FakeClient(prompt_tokens=500, completion_tokens=80)
    sample = [("c1", "some chunk text"), ("c2", "another chunk text")]

    result = run_tag_cost_probe(
        client,
        _schema(),
        _codebook(),
        evals_dir=evals_dir,
        manifest_path=tmp_path / "probe.json",
        votes=3,
        sample=sample,
    )

    assert client.calls == len(sample) * 3
    assert result.sample_chunk_count == 2
    assert result.votes == 3
    expected_total = (500 * 6 / 1000) * 0.000098 + (80 * 6 / 1000) * 0.000196
    assert result.total_cost_usd == pytest.approx(expected_total)
    assert result.cost_per_chunk_usd_at_votes == pytest.approx(expected_total / 2)
    assert result.cost_per_chunk_usd_single_draw == pytest.approx(expected_total / 2 / 3)

    manifest = json.loads((tmp_path / "probe.json").read_text(encoding="utf-8"))
    assert manifest["sample_chunk_count"] == 2
    assert manifest["votes"] == 3
    assert manifest["sampled_chunk_ids"] == ["c1", "c2"]


def test_run_tag_cost_probe_requires_corpus_pin(tmp_path: Path):
    client = _FakeClient()

    with pytest.raises(CorpusPinRequiredError):
        run_tag_cost_probe(
            client,
            _schema(),
            _codebook(),
            evals_dir=tmp_path / "evals" / "corpus_pin",
            sample=[("c1", "text")],
        )


def test_run_tag_cost_probe_empty_sample_raises(tmp_path: Path):
    evals_dir = _stage_pin(tmp_path)

    with pytest.raises(NoChunksToSampleError):
        run_tag_cost_probe(
            _FakeClient(),
            _schema(),
            _codebook(),
            evals_dir=evals_dir,
            sample=[],
        )


def test_run_tag_cost_probe_no_usage_raises(tmp_path: Path):
    evals_dir = _stage_pin(tmp_path)

    class _NoUsageClient(_FakeClient):
        def usage_for_pass(self, pass_name=None):
            return None

    with pytest.raises(NoUsageReportedError):
        run_tag_cost_probe(
            _NoUsageClient(),
            _schema(),
            _codebook(),
            evals_dir=evals_dir,
            sample=[("c1", "text")],
        )


# --- run_drift_check -------------------------------------------------------------


def test_run_drift_check_agreement_against_injected_predictions(tmp_path: Path):
    evals_dir = _stage_pin(tmp_path)
    client = (
        _FakeClient()
    )  # every fresh LLM tag: role:claim/scope.../state/state-formation/bellicist
    sample = [("c1", "text one"), ("c2", "text two")]
    predictions = {
        # c1 agrees with the fresh LLM tag on every graduated axis.
        "c1": {
            "claim_type": "state-formation",
            "theory_school": "bellicist",
            "field": "state",
            "role_in_argument": "role:claim",
        },
        # c2 disagrees on every graduated axis.
        "c2": {
            "claim_type": "descriptive-empirical",
            "theory_school": "not-applicable",
            "field": "violence",
            "role_in_argument": "role:evidence",
        },
    }

    result = run_drift_check(
        client,
        _schema(),
        _codebook(),
        evals_dir=evals_dir,
        manifest_path=tmp_path / "drift.json",
        sample=sample,
        classifier_predictions=predictions,
    )

    assert result.sample_size == 2
    for axis in ("claim_type", "theory_school", "field", "role_in_argument"):
        assert result.per_axis_agreement[axis] == pytest.approx(0.5)

    manifest = json.loads((tmp_path / "drift.json").read_text(encoding="utf-8"))
    assert manifest["llm_error_count"] == 0
    assert manifest["per_axis_compared_count"]["field"] == 2


def test_run_drift_check_llm_error_excludes_chunk_from_all_axes(tmp_path: Path):
    evals_dir = _stage_pin(tmp_path)
    client = _FakeClient(responses=[RuntimeError("boom"), _VALID_TAG_JSON])
    sample = [("bad", "text"), ("good", "text")]
    predictions = {
        "bad": {"claim_type": "x", "theory_school": "x", "field": "x", "role_in_argument": "x"},
        "good": {
            "claim_type": "state-formation",
            "theory_school": "bellicist",
            "field": "state",
            "role_in_argument": "role:claim",
        },
    }

    result = run_drift_check(
        client,
        _schema(),
        _codebook(),
        evals_dir=evals_dir,
        manifest_path=tmp_path / "drift.json",
        sample=sample,
        classifier_predictions=predictions,
    )

    manifest = json.loads((tmp_path / "drift.json").read_text(encoding="utf-8"))
    assert manifest["llm_error_count"] == 1
    # Only "good" contributed a comparison on each axis.
    for axis in ("claim_type", "theory_school", "field", "role_in_argument"):
        assert manifest["per_axis_compared_count"][axis] == 1
        assert result.per_axis_agreement[axis] == pytest.approx(1.0)


def test_run_drift_check_requires_corpus_pin(tmp_path: Path):
    client = _FakeClient()

    with pytest.raises(CorpusPinRequiredError):
        run_drift_check(
            client,
            _schema(),
            _codebook(),
            evals_dir=tmp_path / "evals" / "corpus_pin",
            sample=[("c1", "text")],
            classifier_predictions={
                "c1": {
                    "claim_type": "x",
                    "theory_school": "x",
                    "field": "x",
                    "role_in_argument": "x",
                }
            },
        )
