"""Inner unit tests for the attribution-fidelity gate (issue #262,
specs/PHASE-B.md §10). Co-located under src/axial/gates/ per the repo's
existing test layout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.gates.attribution import run_attribution_fidelity_gate
from axial.llm import ExplodingLLMClient

CHUNK_ID = "gatefix_001_syria_a"
MISSING_CHUNK_ID = "gatefix_999_missing"


class FakeClient:
    """Mirrors src/axial/validators/test_attribution.py's own FakeClient --
    a minimal `LLMClient` test double whose `model_for_pass` answers from a
    caller-supplied per-pass mapping and whose `complete` answers a scripted
    JSON string."""

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
        raise NotImplementedError("the attribution gate never calls this")


def _write_vault(root: Path) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": CHUNK_ID,
        "section": "Synthetic Section",
        "chunk_text": "SENTINEL: synthetic prose.",
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


def _claim(claim_id: str, *, kind: Any, grounds: list[dict[str, Any]]) -> dict[str, Any]:
    entry: dict[str, Any] = {"claim_id": claim_id, "text": f"Text for {claim_id}."}
    if kind is not None:
        entry["kind"] = kind
    entry["grounds"] = grounds
    return entry


GOOD_GROUNDS = [{"ref_type": "chunk", "ref_id": CHUNK_ID}]
DISTINCT_MODELS = {"synthesize": "model-a", "attribution": "model-b"}


def test_all_valid_claims_score_completeness_1_0(vault_dir: Path, tmp_path: Path):
    records = [{"claims": [_claim(f"c-{i}", kind="a", grounds=GOOD_GROUNDS) for i in range(20)]}]
    report = run_attribution_fidelity_gate(
        records,
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    completeness = next(m for m in report.metrics if m.metric == "attribution_completeness")
    assert completeness.value == 1.0
    assert completeness.threshold == 1.0
    assert completeness.passed is True
    assert completeness.n == 20


def test_unresolvable_grounds_drops_completeness_and_names_the_claim(
    vault_dir: Path, tmp_path: Path
):
    records = [
        {
            "claims": [
                _claim("c-1", kind="a", grounds=GOOD_GROUNDS),
                _claim(
                    "c-2", kind="a", grounds=[{"ref_type": "chunk", "ref_id": MISSING_CHUNK_ID}]
                ),
            ]
        }
    ]
    report = run_attribution_fidelity_gate(
        records,
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    completeness = next(m for m in report.metrics if m.metric == "attribution_completeness")
    assert completeness.value < 1.0
    assert completeness.passed is False
    assert completeness.detail["failing_claim_ids"] == ["c-2"]
    assert report.passed is False


def test_missing_kind_also_drops_completeness(vault_dir: Path, tmp_path: Path):
    records = [{"claims": [_claim("c-1", kind=None, grounds=[])]}]
    report = run_attribution_fidelity_gate(
        records,
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    completeness = next(m for m in report.metrics if m.metric == "attribution_completeness")
    assert completeness.passed is False
    assert completeness.detail["failing_claim_ids"] == ["c-1"]


def test_empty_records_reports_completeness_failed_not_vacuous(tmp_path: Path):
    report = run_attribution_fidelity_gate(
        [],
        client=ExplodingLLMClient(),
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    completeness = next(m for m in report.metrics if m.metric == "attribution_completeness")
    assert completeness.value is None
    assert completeness.passed is False
    assert completeness.n == 0


def test_no_b_claims_means_zero_model_calls(vault_dir: Path, tmp_path: Path):
    records = [{"claims": [_claim("c-1", kind="a", grounds=GOOD_GROUNDS)]}]
    report = run_attribution_fidelity_gate(
        records,
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    b_seam = next(m for m in report.metrics if m.metric == "b_seam_mislabel_rate")
    assert b_seam.n == 0
    assert b_seam.value == 0.0
    assert b_seam.passed is True


def test_b_seam_mislabel_rate_flags_the_scripted_claim(vault_dir: Path, tmp_path: Path):
    client = FakeClient(
        model_by_pass=DISTINCT_MODELS, response=json.dumps({"flagged_claim_ids": ["c-2"]})
    )
    records = [
        {
            "claims": [
                _claim("c-1", kind="b", grounds=GOOD_GROUNDS),
                _claim("c-2", kind="b", grounds=GOOD_GROUNDS),
            ]
        }
    ]
    report = run_attribution_fidelity_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )
    b_seam = next(m for m in report.metrics if m.metric == "b_seam_mislabel_rate")
    assert b_seam.n == 2
    assert b_seam.value == 0.5
    assert b_seam.detail["flagged_claim_ids"] == ["c-2"]
    assert "attribution" in client.calls


def test_same_model_guard_propagates_from_validate_attribution(vault_dir: Path, tmp_path: Path):
    from axial.validators.attribution import SamePassModelError

    client = FakeClient(
        model_by_pass={"synthesize": "same", "attribution": "same"},
        response=json.dumps({"flagged_claim_ids": []}),
    )
    records = [{"claims": [_claim("c-1", kind="b", grounds=GOOD_GROUNDS)]}]
    with pytest.raises(SamePassModelError):
        run_attribution_fidelity_gate(
            records,
            client=client,
            vault_dir=vault_dir,
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
        )


def test_trusted_and_corpus_pin_pass_through_to_the_report(vault_dir: Path, tmp_path: Path):
    records = [{"claims": [_claim("c-1", kind="c", grounds=[])]}]
    report = run_attribution_fidelity_gate(
        records,
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin="baseline",
        trusted=True,
        config_path=tmp_path / "nonexistent.yaml",
    )
    assert report.corpus_pin == "baseline"
    assert report.trusted is True
