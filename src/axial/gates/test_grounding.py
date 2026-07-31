"""Inner unit tests for the grounding gate (issue #262, specs/PHASE-B.md
§10). Co-located under src/axial/gates/ per the repo's existing test
layout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.gates.grounding import (
    GroundingCheckFailedError,
    SelfGradingError,
    UnresolvableGroundsError,
    run_grounding_gate,
)
from axial.llm import ExplodingLLMClient

CHUNK_ID = "gatefix_001_syria_a"
MISSING_CHUNK_ID = "gatefix_999_missing"

DISTINCT_MODELS = {"synthesize": "model-a", "grounding": "model-b"}
SAME_MODEL = {"synthesize": "model-x", "grounding": "model-x"}


class ScriptedJudgeClient:
    """A minimal `LLMClient` test double: `model_for_pass` answers from a
    caller-supplied per-pass mapping, and `complete` answers the next
    element of a scripted response queue, one per call -- so a test can
    script "supports x9, does_not_support x1" across ten judge calls.
    Records every `(pass_name, prompt)` pair it was called with."""

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
        raise NotImplementedError("the grounding gate never calls this")


def _write_vault(root: Path, *, n_chunks: int = 1) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n_chunks):
        chunk_id = CHUNK_ID if i == 0 else f"{CHUNK_ID}-{i}"
        frontmatter = {
            "chunk_id": chunk_id,
            "section": "Synthetic Section",
            "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose supporting the claim.",
            "source_meta": {
                "author": "A",
                "title": "T",
                "date": 2020,
                "thesis": "X",
                "scope": "Y",
            },
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
        (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")
    return root / "vault"


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    return _write_vault(tmp_path)


def _a_claim(claim_id: str, *, chunk_id: str = CHUNK_ID) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "kind": "a",
        "text": f"Claim text for {claim_id}.",
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
    }


def _b_claim(claim_id: str, *, chunk_id: str = CHUNK_ID) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "kind": "b",
        "text": f"Cross-source inference for {claim_id}.",
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
    }


def test_nine_of_ten_support_yields_0_9_and_passes(vault_dir: Path, tmp_path: Path):
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS,
        responses=[json.dumps({"verdict": "supports"})] * 9
        + [json.dumps({"verdict": "does_not_support"})],
    )
    records = [{"claims": [_a_claim(f"c-{i}") for i in range(10)]}]

    report = run_grounding_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    metric = report.metrics[0]
    assert metric.metric == "grounding_support_rate"
    assert metric.value == pytest.approx(0.9)
    assert metric.threshold == 0.90
    assert metric.passed is True
    assert metric.n == 10


def test_judge_call_receives_claim_text_and_resolved_chunk_text(vault_dir: Path, tmp_path: Path):
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS, responses=[json.dumps({"verdict": "supports"})]
    )
    records = [{"claims": [_a_claim("c-1")]}]

    run_grounding_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    assert len(client.calls) == 1
    pass_name, prompt = client.calls[0]
    assert pass_name == "grounding"
    assert pass_name != "synthesize"
    assert "Claim text for c-1." in prompt
    assert f"SENTINEL_{CHUNK_ID}" in prompt


def test_kind_c_claims_excluded_from_both_grounding_metrics(vault_dir: Path, tmp_path: Path):
    """(c) claims never reach either judge: `grounding_support_rate` is
    (a)-only per §10, and the (b)-claim contradiction check (issue #550) is
    (b)-only. A kind-"b" claim IS now judged -- separately, reported rather
    than gated -- which is the behavior this test used to pin as "excluded"
    before #550; edited here rather than left to assert the old exclusion,
    since asserting it would now be pinning the exact defect the issue
    fixes (33 of 112 claims in the smoke-v4 records were (b) and none were
    grounding-judged at all)."""
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS,
        responses=[
            json.dumps({"verdict": "supports"}),
            json.dumps({"verdict": "does_not_contradict"}),
        ],
    )
    records = [
        {
            "claims": [
                _a_claim("c-1"),
                _b_claim("c-2"),
                {"claim_id": "c-3", "kind": "c", "text": "x", "grounds": []},
            ]
        }
    ]

    report = run_grounding_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    assert report.metrics[0].n == 1, "grounding_support_rate stays (a)-claims only"
    b_claim_report = report.reported["b_claim_contradiction_rate"]
    assert b_claim_report["denominator"] == 1, "the (c) claim never reaches the (b) check either"
    assert b_claim_report["value"] == 0.0
    assert len(client.calls) == 2


def test_unresolvable_grounds_pointer_is_a_gate_error_not_a_verdict(
    vault_dir: Path, tmp_path: Path
):
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS, responses=[json.dumps({"verdict": "supports"})]
    )
    records = [{"claims": [_a_claim("c-1", chunk_id=MISSING_CHUNK_ID)]}]

    with pytest.raises(UnresolvableGroundsError):
        run_grounding_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )
    assert client.calls == [], "an unresolvable pointer must never reach the judge"


def test_self_grading_guard_raises_before_any_judge_call(vault_dir: Path, tmp_path: Path):
    client = ScriptedJudgeClient(
        model_by_pass=SAME_MODEL, responses=[json.dumps({"verdict": "supports"})]
    )
    records = [{"claims": [_a_claim("c-1")]}]

    with pytest.raises(SelfGradingError) as excinfo:
        run_grounding_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )
    assert "model-x" in str(excinfo.value)
    assert client.calls == [], "zero judge calls when the self-grading guard fires"


def test_explode_provider_never_fires_when_self_grading_guard_raises(
    vault_dir: Path, tmp_path: Path
):
    """Mirrors the `explode` provider seam convention: a `ExplodingLLMClient`
    configured for `model_for_pass` alone (never `.complete()`) proves the
    guard raises before any completion call by simply never invoking one."""

    class SameModelExplodingClient(ExplodingLLMClient):
        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "same-model"

    records = [{"claims": [_a_claim("c-1")]}]
    with pytest.raises(SelfGradingError):
        run_grounding_gate(
            records,
            client=SameModelExplodingClient(),
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )


def test_empty_a_claims_reports_failed_not_vacuous(tmp_path: Path):
    records = [{"claims": [{"claim_id": "c-1", "kind": "c", "text": "x", "grounds": []}]}]
    report = run_grounding_gate(
        records,
        client=ExplodingLLMClient(),
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    metric = report.metrics[0]
    assert metric.value is None
    assert metric.passed is False
    assert metric.n == 0


# -- b_claim_contradiction_rate: reported, never gated (issue #550) ---------


def test_b_claim_contradiction_rate_counts_contradictions_and_is_reported_not_gated(
    vault_dir: Path, tmp_path: Path
):
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS,
        responses=[
            json.dumps({"verdict": "contradicts"}),
            json.dumps({"verdict": "does_not_contradict"}),
        ],
    )
    records = [{"claims": [_b_claim("c-1"), _b_claim("c-2")]}]

    report = run_grounding_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    b_claim_report = report.reported["b_claim_contradiction_rate"]
    assert b_claim_report["value"] == pytest.approx(0.5)
    assert b_claim_report["numerator"] == 1
    assert b_claim_report["denominator"] == 2
    assert b_claim_report["contradicted_claim_ids"] == ["c-1"]
    # It is REPORTED, never gated: no (a) claims at all, yet the metric that
    # DOES gate (grounding_support_rate) still reports its own honest empty
    # state rather than absorbing the (b)-claim number.
    assert report.metrics[0].metric == "grounding_support_rate"
    assert report.metrics[0].n == 0
    # A contradiction rate of 0.5 would fail any threshold this repo has ever
    # asserted for a rate metric -- and it must not, because nothing here
    # gates on it (no baseline exists yet, per the issue).
    assert report.passed is False, "the metric list alone still gates: no (a) claims found"
    assert "b_claim_contradiction_rate" not in [m.metric for m in report.metrics]


def test_b_claim_contradiction_judge_receives_the_inference_framing_prompt(
    vault_dir: Path, tmp_path: Path
):
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS, responses=[json.dumps({"verdict": "does_not_contradict"})]
    )
    records = [{"claims": [_b_claim("c-1")]}]

    run_grounding_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    assert len(client.calls) == 1
    pass_name, prompt = client.calls[0]
    assert pass_name == "grounding", "the (b)-claim check runs under the SAME judge pass"
    assert "Cross-source inference for c-1." in prompt
    assert f"SENTINEL_{CHUNK_ID}" in prompt
    assert "CONTRADICT" in prompt
    assert "does_not_contradict" in prompt


def test_b_claim_unresolvable_grounds_pointer_is_a_gate_error_not_a_verdict(
    vault_dir: Path, tmp_path: Path
):
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS, responses=[json.dumps({"verdict": "does_not_contradict"})]
    )
    records = [{"claims": [_b_claim("c-1", chunk_id=MISSING_CHUNK_ID)]}]

    with pytest.raises(UnresolvableGroundsError):
        run_grounding_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )
    assert client.calls == [], "an unresolvable pointer must never reach the judge"


def test_self_grading_guard_covers_b_claims_when_no_a_claim_exists(vault_dir: Path, tmp_path: Path):
    """The guard must fire for a record set that carries ONLY (b) claims --
    it must not be skipped just because `_iter_a_claims` came back empty."""
    client = ScriptedJudgeClient(
        model_by_pass=SAME_MODEL, responses=[json.dumps({"verdict": "does_not_contradict"})]
    )
    records = [{"claims": [_b_claim("c-1")]}]

    with pytest.raises(SelfGradingError):
        run_grounding_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )
    assert client.calls == [], "zero judge calls when the self-grading guard fires"


def test_no_b_claims_reports_none_value_with_a_reason(vault_dir: Path, tmp_path: Path):
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS, responses=[json.dumps({"verdict": "supports"})]
    )
    records = [{"claims": [_a_claim("c-1")]}]

    report = run_grounding_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    b_claim_report = report.reported["b_claim_contradiction_rate"]
    assert b_claim_report["value"] is None
    assert b_claim_report["denominator"] == 0
    assert "reason" in b_claim_report


def test_judge_response_missing_verdict_raises(vault_dir: Path, tmp_path: Path):
    client = ScriptedJudgeClient(
        model_by_pass=DISTINCT_MODELS, responses=[json.dumps({"not_verdict": "x"})]
    )
    records = [{"claims": [_a_claim("c-1")]}]
    with pytest.raises(GroundingCheckFailedError):
        run_grounding_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )
