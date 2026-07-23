"""Inner unit tests for the stage-5 attribution validator (issue #258,
specs/PHASE-B.md §7.9). Co-located under src/axial/validators/ per the
repo's existing test layout (mirrors src/axial/query/test_reader.py,
src/axial/analyze/test_synthesis.py).

Covers plans/analysis-validators/01-attribution-validator.md's inner-loop
checklist: the kind check, grounds-presence, grounds-resolution via the
query API (asserted by call, not string match), partial-failure reporting,
release blocking, the (b)-seam check's zero-model-calls-when-no-b-claims
property, its distinct-pass_name/same-model guard, and the vacuous pass on
an empty claims list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.llm import SYNTHESIZE_PASS_NAME, ExplodingLLMClient
from axial.validators.attribution import (
    REASON_B_SEAM_VOICED_AS_SOURCE,
    REASON_EMPTY_GROUNDS,
    REASON_MISSING_KIND,
    REASON_UNRESOLVABLE_GROUNDS,
    AttributionCheckFailedError,
    SamePassModelError,
    validate_attribution,
)

CHUNK_ID = "unitfix_001_syria_a"
ARTIFACT_ID = "unitfix_002_artifact"
MISSING_CHUNK_ID = "unitfix_999_missing"


class FakeClient:
    """A minimal `LLMClient` test double: `model_for_pass` answers from a
    caller-supplied per-pass mapping (so a test can make the synthesis pass
    and the (b)-seam pass resolve to the SAME or DIFFERENT models on
    demand), and `complete`/`complete_with_tools` answer a scripted JSON
    string, recording every `pass_name` they were called with."""

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
        raise NotImplementedError("the attribution validator never calls this")


def _write_vault(root: Path) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    chunk_frontmatter = {
        "chunk_id": CHUNK_ID,
        "section": "Synthetic Section",
        "chunk_text": "SENTINEL: synthetic prose.",
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
    text = "---\n" + yaml.safe_dump(chunk_frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{CHUNK_ID}.md").write_text(text, encoding="utf-8")

    artifacts_dir = root / "vault" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_frontmatter = {
        "artifact_id": ARTIFACT_ID,
        "artifact_role": "case-study",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "source_id": "unitfix",
        "section": "Synthetic Section",
        "retrievable": True,
        "cited_by": [],
    }
    text = "---\n" + yaml.safe_dump(artifact_frontmatter, sort_keys=False) + "---\nBody.\n"
    (artifacts_dir / f"{ARTIFACT_ID}.md").write_text(text, encoding="utf-8")
    return root / "vault"


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    return _write_vault(tmp_path)


def _claim(
    claim_id: str, *, kind: Any = "a", grounds: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {"claim_id": claim_id, "text": f"Text for {claim_id}."}
    if kind is not None:
        entry["kind"] = kind
    if grounds is not None:
        entry["grounds"] = grounds
    return entry


def _record(claims: list[dict[str, Any]]) -> dict[str, Any]:
    return {"claims": claims}


DISTINCT_MODELS = {"synthesize": "model-a", "attribution": "model-b"}
SAME_MODEL = {"synthesize": "model-x", "attribution": "model-x"}


# -- kind check ----------------------------------------------------------


@pytest.mark.parametrize("bad_kind", [None, "", "d", "not-a-real-kind"])
def test_kind_absent_null_blank_or_out_of_vocabulary_fails(bad_kind, vault_dir: Path):
    claims = [_claim("c-1", kind=bad_kind, grounds=[])]
    report = validate_attribution(_record(claims), client=ExplodingLLMClient(), vault_dir=vault_dir)
    assert not report.passed
    assert report.failures[0].claim_id == "c-1"
    assert report.failures[0].reason == REASON_MISSING_KIND


@pytest.mark.parametrize("good_kind", ["a", "b", "c"])
def test_every_real_kind_passes_the_kind_check(good_kind, vault_dir: Path):
    grounds = [] if good_kind == "c" else [{"ref_type": "chunk", "ref_id": CHUNK_ID}]
    client = FakeClient(
        model_by_pass=DISTINCT_MODELS, response=json.dumps({"flagged_claim_ids": []})
    )
    report = validate_attribution(
        _record([_claim("c-1", kind=good_kind, grounds=grounds)]),
        client=client,
        vault_dir=vault_dir,
    )
    assert report.passed, report.failures


# -- grounds-presence ------------------------------------------------------


def test_kind_a_with_empty_grounds_fails():
    report = validate_attribution(
        _record([_claim("c-1", kind="a", grounds=[])]), client=ExplodingLLMClient()
    )
    assert not report.passed
    assert report.failures[0].reason == REASON_EMPTY_GROUNDS


def test_kind_b_with_absent_grounds_fails():
    claim = {"claim_id": "c-1", "text": "x", "kind": "b"}  # no "grounds" key at all
    report = validate_attribution(_record([claim]), client=ExplodingLLMClient())
    assert not report.passed
    assert report.failures[0].reason == REASON_EMPTY_GROUNDS


def test_kind_c_with_empty_grounds_passes():
    report = validate_attribution(
        _record([_claim("c-1", kind="c", grounds=[])]), client=ExplodingLLMClient()
    )
    assert report.passed


# -- grounds-resolution, via the query API ---------------------------------


def test_chunk_grounds_resolves_via_get_chunk(vault_dir: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    import axial.validators.attribution as attribution_module

    real_get_chunk = attribution_module.get_chunk

    def spy_get_chunk(chunk_id: str, vault_dir=None):
        calls.append(chunk_id)
        return real_get_chunk(chunk_id, vault_dir=vault_dir)

    monkeypatch.setattr(attribution_module, "get_chunk", spy_get_chunk)

    claim = _claim("c-1", kind="a", grounds=[{"ref_type": "chunk", "ref_id": CHUNK_ID}])
    report = validate_attribution(
        _record([claim]), client=ExplodingLLMClient(), vault_dir=vault_dir
    )

    assert report.passed
    assert calls == [CHUNK_ID], "grounds resolution must call get_chunk, not string-match"


def test_artifact_grounds_resolves_via_get_artifact(
    vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[str] = []
    import axial.validators.attribution as attribution_module

    real_get_artifact = attribution_module.get_artifact

    def spy_get_artifact(artifact_id: str, vault_dir=None):
        calls.append(artifact_id)
        return real_get_artifact(artifact_id, vault_dir=vault_dir)

    monkeypatch.setattr(attribution_module, "get_artifact", spy_get_artifact)

    claim = _claim("c-1", kind="a", grounds=[{"ref_type": "artifact", "ref_id": ARTIFACT_ID}])
    report = validate_attribution(
        _record([claim]), client=ExplodingLLMClient(), vault_dir=vault_dir
    )

    assert report.passed
    assert calls == [ARTIFACT_ID], "grounds resolution must call get_artifact, not string-match"


def test_chunk_ref_id_that_does_not_resolve_fails(vault_dir: Path):
    claim = _claim("c-5", kind="a", grounds=[{"ref_type": "chunk", "ref_id": MISSING_CHUNK_ID}])
    report = validate_attribution(
        _record([claim]), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert not report.passed
    assert report.failures[0].claim_id == "c-5"
    assert report.failures[0].reason == REASON_UNRESOLVABLE_GROUNDS


def test_unknown_ref_type_fails(vault_dir: Path):
    claim = _claim("c-1", kind="a", grounds=[{"ref_type": "url", "ref_id": "https://example.com"}])
    report = validate_attribution(
        _record([claim]), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert not report.passed
    assert report.failures[0].reason == REASON_UNRESOLVABLE_GROUNDS


# -- partial failure --------------------------------------------------------


def test_one_bad_claim_among_five_names_exactly_that_one(vault_dir: Path):
    good_grounds = [{"ref_type": "chunk", "ref_id": CHUNK_ID}]
    claims = [
        _claim("c-1", kind="a", grounds=good_grounds),
        _claim("c-2", kind="a", grounds=good_grounds),
        _claim("c-3", kind=None, grounds=[]),  # the one bad claim
        _claim("c-4", kind="c", grounds=[]),
        _claim("c-5", kind="a", grounds=good_grounds),
    ]
    report = validate_attribution(_record(claims), client=ExplodingLLMClient(), vault_dir=vault_dir)
    assert not report.passed
    assert [f.claim_id for f in report.failures] == ["c-3"]


def test_report_lists_every_failure_not_just_the_first(vault_dir: Path):
    claims = [
        _claim("c-1", kind=None, grounds=[]),
        _claim("c-2", kind="a", grounds=[]),
        _claim("c-3", kind="a", grounds=[{"ref_type": "chunk", "ref_id": MISSING_CHUNK_ID}]),
    ]
    report = validate_attribution(_record(claims), client=ExplodingLLMClient(), vault_dir=vault_dir)
    assert {f.claim_id for f in report.failures} == {"c-1", "c-2", "c-3"}
    assert len(report.failures) == 3


# -- release blocking --------------------------------------------------------


def test_failing_report_is_not_passed():
    report = validate_attribution(
        _record([_claim("c-1", kind=None, grounds=[])]), client=ExplodingLLMClient()
    )
    assert report.passed is False
    assert len(report.failures) > 0


# -- (b)-seam check: zero model calls when no (b) claims ---------------------


def test_no_b_claims_means_zero_model_calls(vault_dir: Path):
    # ExplodingLLMClient raises the instant .complete()/.complete_with_tools()
    # is invoked -- a record with only a/c claims must never reach it.
    claims = [
        _claim("c-1", kind="a", grounds=[{"ref_type": "chunk", "ref_id": CHUNK_ID}]),
        _claim("c-2", kind="c", grounds=[]),
    ]
    report = validate_attribution(_record(claims), client=ExplodingLLMClient(), vault_dir=vault_dir)
    assert report.passed


def test_a_b_claim_that_already_failed_mechanically_is_never_seam_checked(vault_dir: Path):
    # A "b" claim with unresolvable grounds already failed the mechanical
    # check -- there's nothing to learn from also wording-checking it, and
    # doing so would be a second call the ExplodingLLMClient would catch.
    claim = _claim("c-1", kind="b", grounds=[{"ref_type": "chunk", "ref_id": MISSING_CHUNK_ID}])
    report = validate_attribution(
        _record([claim]), client=ExplodingLLMClient(), vault_dir=vault_dir
    )
    assert not report.passed
    assert report.failures[0].reason == REASON_UNRESOLVABLE_GROUNDS


# -- (b)-seam check: flags a claim scripted as voiced-as-source --------------


def test_b_seam_check_flags_the_scripted_claim_id(vault_dir: Path):
    client = FakeClient(
        model_by_pass=DISTINCT_MODELS, response=json.dumps({"flagged_claim_ids": ["c-2"]})
    )
    claims = [
        _claim("c-1", kind="b", grounds=[{"ref_type": "chunk", "ref_id": CHUNK_ID}]),
        _claim("c-2", kind="b", grounds=[{"ref_type": "chunk", "ref_id": CHUNK_ID}]),
    ]
    report = validate_attribution(_record(claims), client=client, vault_dir=vault_dir)
    assert not report.passed
    assert [f.claim_id for f in report.failures] == ["c-2"]
    assert report.failures[0].reason == REASON_B_SEAM_VOICED_AS_SOURCE
    assert client.calls == ["attribution"], "the check must run under its own distinct pass_name"


def test_b_seam_check_runs_under_a_pass_name_distinct_from_synthesis(vault_dir: Path):
    client = FakeClient(
        model_by_pass=DISTINCT_MODELS, response=json.dumps({"flagged_claim_ids": []})
    )
    claim = _claim("c-1", kind="b", grounds=[{"ref_type": "chunk", "ref_id": CHUNK_ID}])
    validate_attribution(_record([claim]), client=client, vault_dir=vault_dir)
    assert client.calls == ["attribution"]
    assert client.calls[0] != SYNTHESIZE_PASS_NAME


# -- (b)-seam check: same-model config guard ---------------------------------


def test_same_model_for_both_passes_raises_a_clear_error(vault_dir: Path):
    client = FakeClient(model_by_pass=SAME_MODEL, response=json.dumps({"flagged_claim_ids": []}))
    claim = _claim("c-1", kind="b", grounds=[{"ref_type": "chunk", "ref_id": CHUNK_ID}])
    with pytest.raises(SamePassModelError) as excinfo:
        validate_attribution(_record([claim]), client=client, vault_dir=vault_dir)
    assert "model-x" in str(excinfo.value)
    assert client.calls == [], "the guard must raise BEFORE any model call is made"


def test_distinct_models_do_not_raise(vault_dir: Path):
    client = FakeClient(
        model_by_pass=DISTINCT_MODELS, response=json.dumps({"flagged_claim_ids": []})
    )
    claim = _claim("c-1", kind="b", grounds=[{"ref_type": "chunk", "ref_id": CHUNK_ID}])
    report = validate_attribution(_record([claim]), client=client, vault_dir=vault_dir)
    assert report.passed
    assert client.calls == ["attribution"]


def test_b_seam_response_missing_flagged_claim_ids_key_raises(vault_dir: Path):
    client = FakeClient(model_by_pass=DISTINCT_MODELS, response=json.dumps({"not_flagged": []}))
    claim = _claim("c-1", kind="b", grounds=[{"ref_type": "chunk", "ref_id": CHUNK_ID}])
    with pytest.raises(AttributionCheckFailedError):
        validate_attribution(_record([claim]), client=client, vault_dir=vault_dir)


# -- disposition: refuse (empty claims) passes vacuously ---------------------


def test_empty_claims_list_passes_vacuously():
    report = validate_attribution(
        {"claims": [], "interrogation": {"disposition": "refuse"}}, client=ExplodingLLMClient()
    )
    assert report.passed
    assert report.failures == []


def test_claims_key_absent_passes_vacuously():
    report = validate_attribution({}, client=ExplodingLLMClient())
    assert report.passed
