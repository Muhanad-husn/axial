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


def _chunk_frontmatter(chunk_id: str, *, author: str, arguing_against: list[str]) -> dict[str, Any]:
    """A prose note in the shape `axial.materialize` writes today: source
    metadata plus the §7.15 answer block. Contested detection reads what the
    notes say (D3, issue #490), so the fixture states an opposition instead
    of carrying a `theory_school` no live note has any more."""
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL: synthetic prose for {chunk_id}.",
        "source_meta": {
            "author": author,
            "title": f"A Book by {author}",
            "date": 2020,
            "thesis": "X",
            "scope": "Y",
        },
        "schema_version": "0.1",
        "frame_version": "0.1",
        "answers": {
            "claim": f"Claim of {chunk_id}.",
            "position_of": "the author",
            "arguing_against": arguing_against,
            "names": [],
        },
    }


def _write_chunk(
    vault_dir: Path, chunk_id: str, *, author: str, arguing_against: list[str]
) -> None:
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = _chunk_frontmatter(chunk_id, author=author, arguing_against=arguing_against)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    _write_chunk(vault, CHUNK_A, author="Charles Tilly", arguing_against=["Theda Skocpol"])
    _write_chunk(vault, CHUNK_B, author="Theda Skocpol", arguing_against=[])
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


def test_zero_contested_records_reports_not_scoreable(vault_dir: Path, tmp_path: Path):
    """Issue #401: zero contested records is neither a vacuous pass nor a
    fail -- the metric never ran, and the reason must name the CONTESTED
    subset as empty, not misreport an empty claim set (these records do
    carry claims). Since presence itself is not-scoreable (not a pass),
    steelman's own silence is unaccounted for too -- also not-scoreable,
    never not-applicable (issue #405)."""
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
    assert presence.passed is None
    assert "contested" in presence.detail["reason"]

    steelman = next(m for m in report.metrics if m.metric == "steelman_quality")
    assert steelman.passed is None
    assert "not_applicable" not in steelman.detail


def test_two_failing_contested_records_score_0_83_and_are_named(vault_dir: Path, tmp_path: Path):
    """Issue #405, replaying #401's own slice-1 evidence: BAD1/BAD2 carry
    `present: false, corpus_one_sided: false` -- neither present nor
    disclosed, which presence correctly FAILS. Steelman never ran for any
    record here, and since presence did NOT pass, that silence is
    genuinely unmeasured -- not-scoreable, never not-applicable."""
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

    steelman = next(m for m in report.metrics if m.metric == "steelman_quality")
    assert steelman.passed is None
    assert "not_applicable" not in steelman.detail


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
    """Issue #405 (a #401 follow-up): every contested record here properly
    DISCLOSED the corpus as one-sided (§7.8's own equal-standing clean
    outcome), so `counter_position_presence_rate` passes. Steelman has
    nothing left to judge for a legitimate, accounted-for reason -- that is
    **not-applicable**, a real pass (never blocking release), distinctly
    flagged from an ordinary pass so it is never mistaken for #401's
    original vacuous `passed: true` on a check that simply never ran."""
    records = [_contested_record("DEV1", counter_position=_disclosed_one_sided())]
    report = run_synthesis_quality_gate(
        records,
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    presence = next(m for m in report.metrics if m.metric == "counter_position_presence_rate")
    assert presence.passed is True

    steelman = next(m for m in report.metrics if m.metric == "steelman_quality")
    assert steelman.n == 0
    assert steelman.value is None
    assert steelman.passed is True, "not-applicable is a real pass, never blocks release"
    assert steelman.detail["not_applicable"] is True
    assert "disclosed" in steelman.detail["reason"]

    assert report.passed is True, "a clean, fully-disclosed gate is an overall pass"


def test_ten_disclosed_contested_records_gate_passes_overall(vault_dir: Path, tmp_path: Path):
    """The exact CI scenario (tests/analysis/test_synthesis_and_calibration_
    gates.py::test_scenario1): 10 contested records, all properly disclosed
    one-sided. `overall` must read PASS, not NOT-SCOREABLE -- disclosure at
    scale is still a clean, complete outcome (issue #405)."""
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
    assert report.passed is True


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
