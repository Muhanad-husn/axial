"""Inner unit tests for the adversarial-brief red-teaming gate (issue #264,
specs/PHASE-B.md §10). Co-located under src/axial/gates/ per the repo's
existing test layout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.brief.intake import load_brief
from axial.gates.adversarial import (
    InvalidExpectedDispositionError,
    InvalidSeededKindError,
    MissingSeededBlockError,
    PremiseMatchCheckFailedError,
    SelfGradingError,
    load_seeded_brief,
    load_seeded_briefs,
    run_adversarial_gate,
)
from axial.llm import ExplodingLLMClient

REPO_ADVERSARIAL_DIR = Path("config/briefs/adversarial")

DISTINCT_MODELS = {"interrogate": "model-a", "premise_match": "model-b"}
SAME_MODEL = {"interrogate": "model-x", "premise_match": "model-x"}


class ScriptedAdversarialClient:
    """A minimal `LLMClient` test double for the adversarial gate: separate
    scripted response queues for the interrogate pass and the premise-match
    judge pass, each indexed independently, plus a caller-supplied
    `model_for_pass` mapping. Records every `(pass_name, prompt)` pair."""

    def __init__(
        self,
        *,
        model_by_pass: dict[str, str],
        interrogate_responses: list[str],
        match_responses: list[str] | None = None,
    ):
        self._model_by_pass = model_by_pass
        self._interrogate_responses = list(interrogate_responses)
        self._match_responses = list(match_responses or [])
        self._interrogate_index = 0
        self._match_index = 0
        self.calls: list[tuple[str | None, str]] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls.append((pass_name, prompt))
        if pass_name == "interrogate":
            response = self._interrogate_responses[
                self._interrogate_index % len(self._interrogate_responses)
            ]
            self._interrogate_index += 1
            return response
        if pass_name == "premise_match":
            response = self._match_responses[self._match_index % len(self._match_responses)]
            self._match_index += 1
            return response
        raise AssertionError(f"unexpected pass_name {pass_name!r}")

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return self._model_by_pass.get(pass_name, "unmapped")

    def complete_with_tools(
        self, prompt: str, tools: list[dict[str, Any]], pass_name: str | None = None
    ) -> dict[str, Any] | None:
        raise NotImplementedError("the adversarial gate never calls this")


def _interrogation_response(*, premise: str | None = None, assessment: str = "contradicts") -> str:
    """A well-formed interrogate-pass response naming exactly one premise
    (or none, when `premise` is `None` -- a clean `proceed`)."""
    premises_found = [{"premise": premise, "assessment": assessment}] if premise else []
    return json.dumps({"premises_found": premises_found, "bounds_applied": [], "refusal": None})


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    prose_dir = tmp_path / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path / "vault"


def _write_seeded_brief(
    root: Path,
    name: str,
    *,
    case: str = "Syria",
    request: str = "How did local order change?",
    lens: str | None = None,
    seeded: dict[str, Any] | None = None,
) -> Path:
    payload: dict[str, Any] = {"case": case, "request": request}
    if lens is not None:
        payload["lens"] = lens
    if seeded is not None:
        payload["seeded"] = seeded
    path = root / name
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


# -- seeded-brief schema loading ----------------------------------------------


def test_load_seeded_brief_parses_full_shape(tmp_path: Path):
    path = _write_seeded_brief(
        tmp_path,
        "b.yaml",
        case="Syria",
        request="What changed after 2011?",
        lens="Tillyan",
        seeded={
            "kind": "smuggled_premise",
            "premise": "The state fully collapsed.",
            "expected_disposition": "proceed_bounded",
        },
    )
    seeded_brief = load_seeded_brief(path)

    assert seeded_brief.brief.case == "Syria"
    assert seeded_brief.brief.request == "What changed after 2011?"
    assert seeded_brief.brief.lens == "Tillyan"
    assert seeded_brief.kind == "smuggled_premise"
    assert seeded_brief.premise == "The state fully collapsed."
    assert seeded_brief.expected_disposition == "proceed_bounded"


def test_load_seeded_brief_missing_seeded_block_raises(tmp_path: Path):
    path = _write_seeded_brief(tmp_path, "b.yaml", seeded=None)
    with pytest.raises(MissingSeededBlockError):
        load_seeded_brief(path)


def test_load_seeded_brief_rejects_invalid_kind(tmp_path: Path):
    path = _write_seeded_brief(
        tmp_path,
        "b.yaml",
        seeded={"kind": "bogus", "premise": "x", "expected_disposition": "refuse"},
    )
    with pytest.raises(InvalidSeededKindError):
        load_seeded_brief(path)


def test_load_seeded_brief_rejects_invalid_expected_disposition(tmp_path: Path):
    path = _write_seeded_brief(
        tmp_path,
        "b.yaml",
        seeded={
            "kind": "smuggled_premise",
            "premise": "x",
            "expected_disposition": "proceed",  # a clean proceed is never a valid EXPECTATION
        },
    )
    with pytest.raises(InvalidExpectedDispositionError):
        load_seeded_brief(path)


def test_load_seeded_briefs_sorted_by_filename(tmp_path: Path):
    _write_seeded_brief(
        tmp_path,
        "b.yaml",
        case="B",
        seeded={"kind": "smuggled_premise", "premise": "p", "expected_disposition": "refuse"},
    )
    _write_seeded_brief(
        tmp_path,
        "a.yaml",
        case="A",
        seeded={"kind": "thin_coverage_ask", "premise": "p", "expected_disposition": "refuse"},
    )
    seeded_briefs = load_seeded_briefs(tmp_path)
    assert [sb.brief.case for sb in seeded_briefs] == ["A", "B"]


def test_load_seeded_briefs_missing_directory_raises(tmp_path: Path):
    from axial.gates.adversarial import AdversarialGateError

    with pytest.raises(AdversarialGateError):
        load_seeded_briefs(tmp_path / "nonexistent")


# -- the shipped seeded set ----------------------------------------------------


def test_shipped_seeded_set_has_at_least_ten_briefs_of_both_kinds():
    seeded_briefs = load_seeded_briefs(REPO_ADVERSARIAL_DIR)
    assert len(seeded_briefs) >= 10
    kinds = {sb.kind for sb in seeded_briefs}
    assert kinds == {"smuggled_premise", "thin_coverage_ask"}


def test_every_shipped_seeded_brief_parses_under_the_real_brief_loader_once_stripped(
    tmp_path: Path,
):
    """Plan inner-loop test 2: every brief in the shipped set parses under
    `axial.brief.intake.load_brief` once the `seeded` block is stripped --
    proving the seeded file's non-oracle fields are a valid, ordinary §7.1
    brief the rest of the pipeline could load unmodified."""
    for path in sorted(REPO_ADVERSARIAL_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        stripped = {k: v for k, v in raw.items() if k != "seeded"}
        stripped_path = tmp_path / path.name
        stripped_path.write_text(yaml.safe_dump(stripped, sort_keys=False), encoding="utf-8")
        load_brief(stripped_path)  # must not raise


# -- oracle isolation: the interrogation prompt never leaks the seed ---------


def test_interrogation_prompt_leaks_no_seeded_field(vault_dir: Path, tmp_path: Path):
    seeded = load_seeded_brief(
        _write_seeded_brief(
            tmp_path,
            "b.yaml",
            case="Syria",
            request="What changed after 2011?",
            seeded={
                "kind": "smuggled_premise",
                "premise": "SENTINEL_DECLARED_PREMISE_TEXT",
                "expected_disposition": "proceed_bounded",
            },
        )
    )
    client = ScriptedAdversarialClient(
        model_by_pass=DISTINCT_MODELS,
        interrogate_responses=[_interrogation_response(premise="an unrelated found premise")],
        match_responses=[json.dumps({"verdict": "does_not_correspond"})],
    )

    run_adversarial_gate(
        [seeded],
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    interrogate_calls = [prompt for pass_name, prompt in client.calls if pass_name == "interrogate"]
    assert len(interrogate_calls) == 1
    prompt = interrogate_calls[0]
    assert "Syria" in prompt
    assert "What changed after 2011?" in prompt
    assert "SENTINEL_DECLARED_PREMISE_TEXT" not in prompt
    assert "smuggled_premise" not in prompt
    assert "proceed_bounded" not in prompt
    assert "seeded" not in prompt.lower()


# -- catch scoring --------------------------------------------------------


def test_named_premise_that_corresponds_and_is_bounded_is_a_catch(vault_dir: Path, tmp_path: Path):
    seeded = load_seeded_brief(
        _write_seeded_brief(
            tmp_path,
            "b.yaml",
            seeded={
                "kind": "smuggled_premise",
                "premise": "declared premise",
                "expected_disposition": "proceed_bounded",
            },
        )
    )
    client = ScriptedAdversarialClient(
        model_by_pass=DISTINCT_MODELS,
        interrogate_responses=[_interrogation_response(premise="a paraphrase of the premise")],
        match_responses=[json.dumps({"verdict": "corresponds"})],
    )

    report = run_adversarial_gate(
        [seeded],
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    metric = report.metrics[0]
    assert metric.metric == "premise_catch_rate"
    assert metric.value == 1.0
    assert metric.n == 1
    assert metric.detail.get("missed_brief_ids", []) == []


def test_unrelated_found_premise_does_not_count_as_a_catch(vault_dir: Path, tmp_path: Path):
    seeded = load_seeded_brief(
        _write_seeded_brief(
            tmp_path,
            "b.yaml",
            seeded={
                "kind": "smuggled_premise",
                "premise": "declared premise",
                "expected_disposition": "proceed_bounded",
            },
        )
    )
    client = ScriptedAdversarialClient(
        model_by_pass=DISTINCT_MODELS,
        interrogate_responses=[_interrogation_response(premise="a totally unrelated premise")],
        match_responses=[json.dumps({"verdict": "does_not_correspond"})],
    )

    report = run_adversarial_gate(
        [seeded],
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    metric = report.metrics[0]
    assert metric.value == 0.0
    assert seeded.brief.brief_id in metric.detail["missed_brief_ids"]


def test_empty_premises_found_is_a_miss_and_never_calls_the_judge(vault_dir: Path, tmp_path: Path):
    seeded = load_seeded_brief(
        _write_seeded_brief(
            tmp_path,
            "b.yaml",
            seeded={
                "kind": "smuggled_premise",
                "premise": "declared premise",
                "expected_disposition": "refuse",
            },
        )
    )
    client = ScriptedAdversarialClient(
        model_by_pass=DISTINCT_MODELS,
        interrogate_responses=[
            json.dumps(
                {
                    "premises_found": [],
                    "bounds_applied": [],
                    "refusal": {"reason": "cannot answer as posed"},
                }
            )
        ],
    )

    report = run_adversarial_gate(
        [seeded],
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    assert report.metrics[0].value == 0.0
    match_calls = [pass_name for pass_name, _ in client.calls if pass_name == "premise_match"]
    assert match_calls == [], "an empty premises_found must never reach the judge"


def test_clean_proceed_is_a_miss_regardless_of_premises_found(vault_dir: Path, tmp_path: Path):
    """Acceptance scenario 4: expected_disposition "refuse", actual
    disposition resolves to a clean "proceed" -- counted as a miss even
    though premises_found itself is scripted to name the exact declared
    premise (which the gate must never even check, per the miss-by-
    definition rule)."""
    seeded = load_seeded_brief(
        _write_seeded_brief(
            tmp_path,
            "b.yaml",
            seeded={
                "kind": "smuggled_premise",
                "premise": "declared premise",
                "expected_disposition": "refuse",
            },
        )
    )
    # `assessment="supports"` and no bounds/refusal resolves to a clean
    # "proceed" (axial.brief.interrogate.disposition_for), even though the
    # scripted premises_found names the declared premise verbatim.
    client = ScriptedAdversarialClient(
        model_by_pass=DISTINCT_MODELS,
        interrogate_responses=[
            _interrogation_response(premise="declared premise", assessment="supports")
        ],
        match_responses=[json.dumps({"verdict": "corresponds"})],
    )

    report = run_adversarial_gate(
        [seeded],
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    assert report.metrics[0].value == 0.0
    match_calls = [pass_name for pass_name, _ in client.calls if pass_name == "premise_match"]
    assert match_calls == [], "a clean proceed must never reach the judge either"


def test_rate_arithmetic_eight_of_ten_passes_seven_of_ten_fails(vault_dir: Path, tmp_path: Path):
    seeded_briefs = [
        load_seeded_brief(
            _write_seeded_brief(
                tmp_path,
                f"b-{i}.yaml",
                seeded={
                    "kind": "smuggled_premise",
                    "premise": "declared premise",
                    "expected_disposition": "proceed_bounded",
                },
            )
        )
        for i in range(10)
    ]

    def _run(n_caught: int):
        interrogate_responses = [
            _interrogation_response(premise="found premise") for _ in range(n_caught)
        ] + [_interrogation_response(premise=None) for _ in range(10 - n_caught)]
        client = ScriptedAdversarialClient(
            model_by_pass=DISTINCT_MODELS,
            interrogate_responses=interrogate_responses,
            match_responses=[json.dumps({"verdict": "corresponds"})] * n_caught,
        )
        return run_adversarial_gate(
            seeded_briefs,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )

    report_8 = _run(8)
    assert report_8.metrics[0].value == pytest.approx(0.80)
    assert report_8.metrics[0].passed is True

    report_7 = _run(7)
    assert report_7.metrics[0].value == pytest.approx(0.70)
    assert report_7.metrics[0].passed is False


def test_report_names_every_missed_brief_id(vault_dir: Path, tmp_path: Path):
    caught = load_seeded_brief(
        _write_seeded_brief(
            tmp_path,
            "caught.yaml",
            case="Caught",
            seeded={
                "kind": "smuggled_premise",
                "premise": "p",
                "expected_disposition": "proceed_bounded",
            },
        )
    )
    missed = load_seeded_brief(
        _write_seeded_brief(
            tmp_path,
            "missed.yaml",
            case="Missed",
            seeded={
                "kind": "smuggled_premise",
                "premise": "p",
                "expected_disposition": "proceed_bounded",
            },
        )
    )
    client = ScriptedAdversarialClient(
        model_by_pass=DISTINCT_MODELS,
        interrogate_responses=[
            _interrogation_response(premise="found premise"),
            _interrogation_response(premise=None),
        ],
        match_responses=[json.dumps({"verdict": "corresponds"})],
    )

    report = run_adversarial_gate(
        [caught, missed],
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    assert report.metrics[0].detail["missed_brief_ids"] == [missed.brief.brief_id]


def test_empty_seeded_set_reports_failed_not_vacuous(tmp_path: Path):
    report = run_adversarial_gate(
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


# -- self-grading guard --------------------------------------------------------


def test_self_grading_guard_raises_before_any_call(vault_dir: Path, tmp_path: Path):
    seeded = load_seeded_brief(
        _write_seeded_brief(
            tmp_path,
            "b.yaml",
            seeded={
                "kind": "smuggled_premise",
                "premise": "p",
                "expected_disposition": "proceed_bounded",
            },
        )
    )
    client = ScriptedAdversarialClient(
        model_by_pass=SAME_MODEL,
        interrogate_responses=[_interrogation_response(premise="p")],
        match_responses=[json.dumps({"verdict": "corresponds"})],
    )

    with pytest.raises(SelfGradingError) as excinfo:
        run_adversarial_gate(
            [seeded],
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )
    assert "model-x" in str(excinfo.value)
    assert client.calls == [], "zero calls of any kind when the self-grading guard fires"


def test_explode_provider_never_fires_when_self_grading_guard_raises(
    vault_dir: Path, tmp_path: Path
):
    seeded = load_seeded_brief(
        _write_seeded_brief(
            tmp_path,
            "b.yaml",
            seeded={
                "kind": "smuggled_premise",
                "premise": "p",
                "expected_disposition": "proceed_bounded",
            },
        )
    )

    class SameModelExplodingClient(ExplodingLLMClient):
        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "same-model"

    with pytest.raises(SelfGradingError):
        run_adversarial_gate(
            [seeded],
            client=SameModelExplodingClient(),
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )


def test_premise_match_judge_response_missing_verdict_raises(vault_dir: Path, tmp_path: Path):
    seeded = load_seeded_brief(
        _write_seeded_brief(
            tmp_path,
            "b.yaml",
            seeded={
                "kind": "smuggled_premise",
                "premise": "p",
                "expected_disposition": "proceed_bounded",
            },
        )
    )
    client = ScriptedAdversarialClient(
        model_by_pass=DISTINCT_MODELS,
        interrogate_responses=[_interrogation_response(premise="p")],
        match_responses=[json.dumps({"not_verdict": "x"})],
    )
    with pytest.raises(PremiseMatchCheckFailedError):
        run_adversarial_gate(
            [seeded],
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )
