"""Inner unit tests for the stage-5 counter-position validator (issue #259,
specs/PHASE-B.md §7.8, §7.9). Co-located under src/axial/validators/ per the
repo's existing test layout (mirrors src/axial/validators/test_attribution.py).

Covers plans/analysis-validators/02-counter-position-validator.md's inner-loop
checklist: the contested predicate's two signals (theory_school spread,
role_in_argument counter-position), sentinel exclusion, the config-driven
tunable, signal persistence, the presence-or-disclosure check's four
combinations, release blocking, the steelman-quality check's
present-only/zero-model-calls-otherwise property, its distinct-pass_name/
same-model guard, and its non-blocking strawman verdict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.llm import ExplodingLLMClient
from axial.validators.counter_position import (
    REASON_CONTESTED_WITHOUT_COUNTER_POSITION,
    SIGNAL_ROLE_COUNTER_POSITION,
    SIGNAL_THEORY_SCHOOL_SPREAD,
    VERDICT_STRAWMAN,
    CounterPositionCheckFailedError,
    SamePassModelError,
    validate_counter_position,
)

CHUNK_A = "unitfix_cp_001_bellicist"
CHUNK_B = "unitfix_cp_002_marxist"
CHUNK_C = "unitfix_cp_003_bellicist_again"
CHUNK_COUNTER = "unitfix_cp_004_counter_role"
CHUNK_NOT_APPLICABLE = "unitfix_cp_005_not_applicable"


class FakeClient:
    """Minimal `LLMClient` test double, mirroring
    `test_attribution.FakeClient` exactly: `model_for_pass` answers from a
    caller-supplied per-pass mapping, `complete` answers a scripted JSON
    string, recording every `pass_name` it was called with."""

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
        raise NotImplementedError("the counter-position validator never calls this")


def _chunk_frontmatter(
    chunk_id: str, *, theory_school_primary: str, role_in_argument: str = "role:claim"
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL: synthetic prose for {chunk_id}.",
        "source_meta": {
            "author": "A",
            "title": "T",
            "date": 2020,
            "thesis": "X",
            "scope": "Y",
        },
        "schema_version": "0.1",
        "role_in_argument": role_in_argument,
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


def _write_chunk(vault_dir: Path, chunk_id: str, **kwargs: Any) -> None:
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = _chunk_frontmatter(chunk_id, **kwargs)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "prose").mkdir(parents=True, exist_ok=True)
    (vault / "artifacts").mkdir(parents=True, exist_ok=True)
    return vault


def _grounds(*chunk_ids: str) -> list[dict[str, str]]:
    return [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids]


def _claim(claim_id: str, *chunk_ids: str, kind: str = "a") -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": f"Text for {claim_id}.",
        "kind": kind,
        "grounds": _grounds(*chunk_ids),
    }


def _no_counter_position() -> dict[str, Any]:
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


def _present_counter_position(
    *chunk_ids: str, stance: str = "The opposing school holds..."
) -> dict[str, Any]:
    return {
        "present": True,
        "stance": stance,
        "grounds": _grounds(*chunk_ids),
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


def _disclosed_one_sided(
    reason: str = "corpus carries no opposing school on this case",
) -> dict[str, Any]:
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": True,
        "one_sided_reason": reason,
    }


def _record(claims: list[dict[str, Any]], counter_position: dict[str, Any]) -> dict[str, Any]:
    return {"claims": claims, "counter_position": counter_position}


# -- contested predicate: theory_school spread ------------------------------


def test_two_distinct_theory_schools_is_contested(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    report = validate_counter_position(
        _record(claims, _disclosed_one_sided()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
    )
    assert report.contested.contested is True
    assert report.contested.signal == SIGNAL_THEORY_SCHOOL_SPREAD


def test_single_theory_school_is_not_contested(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_C, theory_school_primary="bellicist")
    claims = [_claim("c-1", CHUNK_A, CHUNK_C)]
    report = validate_counter_position(
        _record(claims, _no_counter_position()), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert report.contested.contested is False
    assert report.contested.signal is None


def test_zero_evidence_is_not_contested(vault_dir: Path):
    report = validate_counter_position(
        _record([], _no_counter_position()), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert report.contested.contested is False
    assert report.contested.signal is None


def test_sentinel_values_are_excluded_from_the_spread_count(vault_dir: Path):
    """A `not-applicable` chunk beside a `bellicist` chunk is not opposition
    -- it's silence on one side (§7.8) -- so this must NOT be contested on
    the spread signal alone."""
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_NOT_APPLICABLE, theory_school_primary="not-applicable")
    claims = [_claim("c-1", CHUNK_A, CHUNK_NOT_APPLICABLE)]
    report = validate_counter_position(
        _record(claims, _no_counter_position()), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert report.contested.contested is False


def test_two_unlisted_chunks_are_not_known_to_oppose_each_other(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="unlisted")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="unlisted")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    report = validate_counter_position(
        _record(claims, _no_counter_position()), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert report.contested.contested is False


# -- contested predicate: role_in_argument counter-position ------------------


def test_role_counter_position_alone_is_contested_even_with_a_single_school(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(
        vault_dir,
        CHUNK_COUNTER,
        theory_school_primary="bellicist",
        role_in_argument="role:counter-position",
    )
    claims = [_claim("c-1", CHUNK_A, CHUNK_COUNTER)]
    report = validate_counter_position(
        _record(claims, _disclosed_one_sided()), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert report.contested.contested is True
    assert report.contested.signal == SIGNAL_ROLE_COUNTER_POSITION


# -- the config-driven tunable ------------------------------------------------


def test_config_override_changes_the_outcome(vault_dir: Path, tmp_path: Path):
    """Overriding `contested_detection.min_distinct_theory_schools` to 3
    changes the outcome with no code change -- two distinct schools is no
    longer enough."""
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]

    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        yaml.safe_dump({"contested_detection": {"min_distinct_theory_schools": 3}}),
        encoding="utf-8",
    )

    report = validate_counter_position(
        _record(claims, _no_counter_position()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        config_path=config_path,
    )
    assert report.contested.contested is False


def test_absent_config_file_falls_back_to_the_default(vault_dir: Path, tmp_path: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    report = validate_counter_position(
        _record(claims, _no_counter_position()),
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        config_path=tmp_path / "does-not-exist.yaml",
    )
    assert report.contested.contested is True
    assert report.contested.signal == SIGNAL_THEORY_SCHOOL_SPREAD


# -- presence-or-disclosure check --------------------------------------------


def test_present_true_with_nonempty_grounds_passes(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    client = FakeClient(
        model_by_pass={"synthesize": "model-a", "counter_position": "model-b"},
        response=json.dumps({"verdict": "steelman", "detail": "solid"}),
    )
    report = validate_counter_position(
        _record(claims, _present_counter_position(CHUNK_B)), client=client, vault_dir=vault_dir
    )
    assert report.passed
    assert report.failures == []


def test_present_true_with_empty_grounds_fails(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    counter_position = {
        "present": True,
        "stance": "A stance with no grounds.",
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }
    report = validate_counter_position(
        _record(claims, counter_position), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert not report.passed
    assert report.failures[0].reason == REASON_CONTESTED_WITHOUT_COUNTER_POSITION


def test_corpus_one_sided_with_reason_passes(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    report = validate_counter_position(
        _record(claims, _disclosed_one_sided()), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert report.passed


def test_corpus_one_sided_with_empty_reason_fails(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    counter_position = {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": True,
        "one_sided_reason": None,
    }
    report = validate_counter_position(
        _record(claims, counter_position), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert not report.passed
    assert report.failures[0].reason == REASON_CONTESTED_WITHOUT_COUNTER_POSITION


def test_neither_present_nor_disclosed_fails(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    report = validate_counter_position(
        _record(claims, _no_counter_position()), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert not report.passed
    assert report.failures[0].reason == REASON_CONTESTED_WITHOUT_COUNTER_POSITION


def test_uncontested_brief_never_requires_the_section(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    claims = [_claim("c-1", CHUNK_A)]
    report = validate_counter_position(
        _record(claims, _no_counter_position()), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert report.contested.contested is False
    assert report.passed


# -- steelman-quality check: present-only, zero calls otherwise -------------


def test_steelman_check_does_not_run_when_section_is_not_present(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    report = validate_counter_position(
        _record(claims, _disclosed_one_sided()), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert report.steelman.ran is False
    assert report.steelman.verdict is None


def test_steelman_check_does_not_run_on_an_uncontested_brief_with_no_section(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    claims = [_claim("c-1", CHUNK_A)]
    report = validate_counter_position(
        _record(claims, _no_counter_position()), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert report.steelman.ran is False


def test_steelman_check_runs_when_present_true_with_grounds(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    client = FakeClient(
        model_by_pass={"synthesize": "model-a", "counter_position": "model-b"},
        response=json.dumps({"verdict": "steelman", "detail": "genuinely strong"}),
    )
    report = validate_counter_position(
        _record(claims, _present_counter_position(CHUNK_B)), client=client, vault_dir=vault_dir
    )
    assert report.steelman.ran is True
    assert report.steelman.verdict == "steelman"
    assert client.calls == ["counter_position"], "must run under its own distinct pass_name"


def test_scripted_strawman_is_recorded_but_does_not_block(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    client = FakeClient(
        model_by_pass={"synthesize": "model-a", "counter_position": "model-b"},
        response=json.dumps({"verdict": "strawman", "detail": "dismissive of the real position"}),
    )
    report = validate_counter_position(
        _record(claims, _present_counter_position(CHUNK_B)), client=client, vault_dir=vault_dir
    )
    assert report.steelman.verdict == VERDICT_STRAWMAN
    assert report.passed, "a strawman verdict must not block release in this slice"


# -- steelman-quality check: same-model config guard -------------------------


def test_same_model_for_both_passes_raises_before_any_call(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    client = FakeClient(
        model_by_pass={"synthesize": "model-x", "counter_position": "model-x"},
        response=json.dumps({"verdict": "steelman", "detail": ""}),
    )
    with pytest.raises(SamePassModelError) as excinfo:
        validate_counter_position(
            _record(claims, _present_counter_position(CHUNK_B)), client=client, vault_dir=vault_dir
        )
    assert "model-x" in str(excinfo.value)
    assert client.calls == [], "the guard must raise BEFORE any model call is made"


def test_steelman_response_missing_verdict_raises(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    client = FakeClient(
        model_by_pass={"synthesize": "model-a", "counter_position": "model-b"},
        response=json.dumps({"not_verdict": "steelman"}),
    )
    with pytest.raises(CounterPositionCheckFailedError):
        validate_counter_position(
            _record(claims, _present_counter_position(CHUNK_B)), client=client, vault_dir=vault_dir
        )


# -- never edits the record ---------------------------------------------------


def test_never_mutates_the_input_record(vault_dir: Path):
    _write_chunk(vault_dir, CHUNK_A, theory_school_primary="bellicist")
    _write_chunk(vault_dir, CHUNK_B, theory_school_primary="marxist-political-economy")
    claims = [_claim("c-1", CHUNK_A, CHUNK_B)]
    record = _record(claims, _disclosed_one_sided())
    before = json.dumps(record, sort_keys=True)
    validate_counter_position(record, client=ExplodingLLMClient(), vault_dir=vault_dir)
    assert json.dumps(record, sort_keys=True) == before
