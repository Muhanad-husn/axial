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

from axial.gates.attribution import (
    PAPER_GATE_NAME,
    run_attribution_fidelity_gate,
    run_paper_attribution_fidelity_gate,
)
from axial.llm import ExplodingLLMClient

CHUNK_ID = "gatefix_001_syria_a"
OTHER_SOURCE_CHUNK_ID = "othersrc_001_syria_a"
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
        self.prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls.append(pass_name)
        self.prompts.append(prompt)
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


def _write_second_source_chunk(root: Path) -> None:
    """A second chunk note whose `chunk_id` resolves to a DIFFERENT
    `source_id` (`axial.query.reader.source_id_from_chunk_id`) than
    `CHUNK_ID` -- the paper-wiring test below needs two distinct sources to
    prove the (b)-seam judge is handed each claim's distinct grounds source
    ids (PR #559) for a paper claim exactly as it already is for a Phase-B
    one."""
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": OTHER_SOURCE_CHUNK_ID,
        "section": "Synthetic Section",
        "chunk_text": "SENTINEL: synthetic prose from a second source.",
        "source_meta": {"author": "B", "title": "U", "date": 2021, "thesis": "X", "scope": "Y"},
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{OTHER_SOURCE_CHUNK_ID}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    return _write_vault(tmp_path)


@pytest.fixture
def vault_dir_two_sources(tmp_path: Path) -> Path:
    vault = _write_vault(tmp_path)
    _write_second_source_chunk(tmp_path)
    return vault


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


def test_no_b_or_c_claims_means_zero_model_calls(vault_dir: Path, tmp_path: Path):
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
    c_seam = next(m for m in report.metrics if m.metric == "c_seam_mislabel_rate")
    assert c_seam.n == 0
    assert c_seam.value == 0.0
    assert c_seam.passed is True


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


def test_c_seam_mislabel_rate_flags_the_scripted_claim_with_no_b_claims(
    vault_dir: Path, tmp_path: Path
):
    """A record carrying only kind-"c" claims (no kind-"b") still reaches
    the judge -- issue #589's widened contract -- and scores its own
    metric, numerator/denominator/detail, the same way `b_seam_mislabel_
    rate` does."""
    client = FakeClient(
        model_by_pass=DISTINCT_MODELS, response=json.dumps({"flagged_c_claim_ids": ["c-2"]})
    )
    records = [
        {
            "claims": [
                _claim("c-1", kind="c", grounds=[]),
                _claim("c-2", kind="c", grounds=[]),
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
    c_seam = next(m for m in report.metrics if m.metric == "c_seam_mislabel_rate")
    assert c_seam.n == 2
    assert c_seam.value == 0.5
    assert c_seam.detail["flagged_claim_ids"] == ["c-2"]
    assert client.calls == ["attribution"], "only one call, even with zero (b) claims present"


def test_b_and_c_seam_rates_scored_independently_from_one_combined_call(
    vault_dir: Path, tmp_path: Path
):
    """A record carrying BOTH kinds scores two independent metrics from a
    SINGLE judge call: `b_seam_mislabel_rate`'s denominator/numerator/detail
    are unaffected by the (c) claims present alongside it, and vice versa."""
    client = FakeClient(
        model_by_pass=DISTINCT_MODELS,
        response=json.dumps({"flagged_claim_ids": ["b-2"], "flagged_c_claim_ids": ["c-1"]}),
    )
    records = [
        {
            "claims": [
                _claim("b-1", kind="b", grounds=GOOD_GROUNDS),
                _claim("b-2", kind="b", grounds=GOOD_GROUNDS),
                _claim("c-1", kind="c", grounds=[]),
                _claim("c-2", kind="c", grounds=[]),
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
    c_seam = next(m for m in report.metrics if m.metric == "c_seam_mislabel_rate")
    assert b_seam.n == 2
    assert b_seam.detail["flagged_claim_ids"] == ["b-2"]
    assert c_seam.n == 2
    assert c_seam.detail["flagged_claim_ids"] == ["c-1"]
    assert client.calls == ["attribution"], "one combined call, not one per kind"


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


# -- Reuse over paper records (specs/PHASE-C.md §10.1, §8 P0-9, issue #608) --


def test_paper_gate_name_is_distinct_from_the_phase_b_gate_name():
    """A new CLI entry point, dispatched to `load_paper_records` rather
    than `load_records` (`axial.cli._gate_run`) -- never a reshaping of the
    existing `attribution-fidelity` dispatch path."""
    from axial.gates.attribution import GATE_NAME

    assert PAPER_GATE_NAME != GATE_NAME
    assert PAPER_GATE_NAME == "paper-attribution-fidelity"


def test_run_attribution_fidelity_gate_reused_wholesale_over_a_paper_claim(
    vault_dir_two_sources: Path, tmp_path: Path
):
    """The check logic `run_paper_attribution_fidelity_gate` wraps, given a
    paper-shaped record (`paper_claim_id`, no `claim_id`) whose (b) claim's
    grounds draw on TWO distinct sources -- the judge must be shown both
    (PR #559), exactly as it already is for a Phase-B claim, with zero
    change owed to the check itself to get there."""
    client = FakeClient(
        model_by_pass=DISTINCT_MODELS, response=json.dumps({"flagged_claim_ids": []})
    )
    grounds = [
        {"ref_type": "chunk", "ref_id": CHUNK_ID},
        {"ref_type": "chunk", "ref_id": OTHER_SOURCE_CHUNK_ID},
    ]
    records = [
        {
            "paper_brief_id": "pb-1",
            "claims": [
                {
                    "paper_claim_id": "pc-1",
                    "kind": "b",
                    "origin": None,
                    "text": "New cross-source claim for pc-1.",
                    "grounds": grounds,
                }
            ],
        }
    ]

    report = run_attribution_fidelity_gate(
        records,
        client=client,
        vault_dir=vault_dir_two_sources,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    b_seam = next(m for m in report.metrics if m.metric == "b_seam_mislabel_rate")
    assert b_seam.n == 1
    assert b_seam.value == 0.0
    assert client.calls == ["attribution"]
    assert "2 distinct sources -- gatefix, othersrc" in client.prompts[0]


def test_paper_wrapper_reports_its_own_gate_name_and_names_a_flagged_paper_claim(
    vault_dir: Path, tmp_path: Path
):
    """`run_paper_attribution_fidelity_gate` -- `GATE_RUNNERS[PAPER_GATE_
    NAME]`'s actual entry -- writes `gate=PAPER_GATE_NAME` on its report
    (issue #608): without this, `axial gate run paper-attribution-fidelity`
    would silently write `evals/reports/attribution-fidelity.json`, the
    SAME file a Phase-B run writes. It also proves a flagged PAPER claim is
    named by its real `paper_claim_id`, via `_claim_id_of`'s new fallback,
    never the opaque `<claim #N>` placeholder."""
    client = FakeClient(
        model_by_pass=DISTINCT_MODELS, response=json.dumps({"flagged_claim_ids": ["pc-2"]})
    )
    records = [
        {
            "paper_brief_id": "pb-1",
            "claims": [
                {
                    "paper_claim_id": "pc-2",
                    "kind": "b",
                    "origin": None,
                    "text": "New cross-source claim for pc-2.",
                    "grounds": GOOD_GROUNDS,
                }
            ],
        }
    ]

    report = run_paper_attribution_fidelity_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
    )

    assert report.gate == PAPER_GATE_NAME
    b_seam = next(m for m in report.metrics if m.metric == "b_seam_mislabel_rate")
    assert b_seam.value == pytest.approx(1.0)
    assert b_seam.detail["flagged_claim_ids"] == ["pc-2"]


def test_trusted_and_corpus_pin_pass_through_to_the_report(vault_dir: Path, tmp_path: Path):
    # A kind-"a" claim (rather than "c") keeps this record off the (b)/(c)-
    # seam judge entirely (issue #589 widened the judge to cover kind-"c"
    # claims too), so ExplodingLLMClient still pins "no model call" here --
    # this test is about corpus_pin/trusted passthrough, not seam behaviour.
    records = [{"claims": [_claim("c-1", kind="a", grounds=GOOD_GROUNDS)]}]
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
