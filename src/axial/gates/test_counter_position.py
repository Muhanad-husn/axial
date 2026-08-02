"""Inner unit tests for the paper-side counter-position gate (specs/
PHASE-C.md §10.1, §7.14, §8 P0-14; issue #608, B3 of #605). Co-located
under src/axial/gates/ per the repo's existing test layout (mirrors
src/axial/gates/test_provenance.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.gates.counter_position import UnresolvableSourceRecordError, run_counter_position_gate
from axial.llm import ExplodingLLMClient

TILLY_CHUNK = "tilly-1978_001_intro_001"
SKOCPOL_CHUNK = "skocpol-1979_001_intro_001"


def _chunk_frontmatter(
    chunk_id: str, *, author: str, title: str, arguing_against: Any = None
) -> dict[str, Any]:
    answers: dict[str, Any] = {"position_of": "the author"}
    if arguing_against is not None:
        answers["arguing_against"] = arguing_against
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL: synthetic prose for {chunk_id}.",
        "source_meta": {
            "author": author,
            "title": title,
            "date": 1979,
            "thesis": "X",
            "scope": "Y",
        },
        "answers": answers,
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
    _write_chunk(
        vault,
        TILLY_CHUNK,
        author="Charles Tilly",
        title="From Mobilization to Revolution",
        arguing_against=["Skocpol"],
    )
    _write_chunk(
        vault,
        SKOCPOL_CHUNK,
        author="Theda Skocpol",
        title="States and Social Revolutions",
        arguing_against=[],
    )
    return vault


def _grounds(*chunk_ids: str) -> list[dict[str, str]]:
    return [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids]


def _paper_claim(paper_claim_id: str, *chunk_ids: str) -> dict[str, Any]:
    return {
        "paper_claim_id": paper_claim_id,
        "text": f"Text for {paper_claim_id}.",
        "kind": "a",
        "grounds": _grounds(*chunk_ids),
        "names_touched": [],
    }


def _no_counter_position() -> dict[str, Any]:
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


def _disclosed_one_sided(
    reason: str = "the corpus carries no opposing school here",
) -> dict[str, Any]:
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": True,
        "one_sided_reason": reason,
    }


def _failed_counter_position() -> dict[str, Any]:
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
        "failed": True,
        "failure_reason": "counter-position generation call failed: boom",
    }


def _paper_record(
    *,
    claims: list[dict[str, Any]],
    counter_position: dict[str, Any],
    source_analyses: list[str] | None = None,
    coverage_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "paper_brief_id": "pb-1",
        "claims": claims,
        "counter_position": counter_position,
        "source_analyses": source_analyses or [],
        "coverage_map": coverage_map or {},
    }


def _write_source_record(analyses_dir: Path, brief_id: str, record: dict[str, Any]) -> None:
    analyses_dir.mkdir(parents=True, exist_ok=True)
    (analyses_dir / f"{brief_id}.json").write_text(json.dumps(record), encoding="utf-8")


# -- an uncontested paper leaves the denominator (§10.1, P0-14) -------------


def test_uncontested_paper_is_not_scoreable_never_a_vacuous_pass(tmp_path: Path):
    record = _paper_record(claims=[], counter_position=_no_counter_position())
    report = run_counter_position_gate(
        [record],
        client=ExplodingLLMClient(),
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=tmp_path / "analyses",
    )
    metric = report.metrics[0]
    assert metric.metric == "paper_counter_position_presence_rate"
    assert metric.value is None
    assert metric.passed is None
    assert metric.n == 0


# -- the fourth arm: a named source record's own fields (§7.14) -------------


def test_fourth_arm_contested_paper_with_present_counter_position_passes(tmp_path: Path):
    _write_source_record(
        tmp_path / "analyses", "b1", {"counter_position": _present_counter_position("x")}
    )
    record = _paper_record(
        claims=[],
        counter_position=_present_counter_position("x"),
        source_analyses=["b1"],
    )
    report = run_counter_position_gate(
        [record],
        client=ExplodingLLMClient(),
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=tmp_path / "analyses",
    )
    metric = report.metrics[0]
    assert metric.value == pytest.approx(1.0)
    assert metric.threshold == 1.00
    assert metric.passed is True
    assert metric.n == 1


def test_fourth_arm_contested_paper_with_neither_present_nor_disclosed_fails(tmp_path: Path):
    """A source record disclosed one-sidedness, but the PAPER's own
    counter_position is neither present nor disclosed -- a drafter that
    dropped the disclosure -- the gate must fail and name the paper."""
    _write_source_record(tmp_path / "analyses", "b1", {"counter_position": _disclosed_one_sided()})
    record = _paper_record(
        claims=[], counter_position=_no_counter_position(), source_analyses=["b1"]
    )
    report = run_counter_position_gate(
        [record],
        client=ExplodingLLMClient(),
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=tmp_path / "analyses",
    )
    metric = report.metrics[0]
    assert metric.value == pytest.approx(0.0)
    assert metric.passed is False
    assert "pb-1" in metric.detail["failing_brief_ids"]


def test_fourth_arm_a_failed_source_counter_position_never_fires_alone(tmp_path: Path):
    """§7.3/PR #558: a `failed` section on the SOURCE record is a run that
    died, never a disclosure of a one-sided corpus -- it must not
    manufacture a contested paper."""
    _write_source_record(
        tmp_path / "analyses", "b1", {"counter_position": _failed_counter_position(), "claims": []}
    )
    record = _paper_record(
        claims=[], counter_position=_no_counter_position(), source_analyses=["b1"]
    )
    report = run_counter_position_gate(
        [record],
        client=ExplodingLLMClient(),
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=tmp_path / "analyses",
    )
    metric = report.metrics[0]
    assert metric.passed is None, "no arm fired -- uncontested, never a fail"
    assert metric.n == 0


def test_missing_source_analysis_record_raises(tmp_path: Path):
    record = _paper_record(
        claims=[], counter_position=_no_counter_position(), source_analyses=["no-such-brief"]
    )
    with pytest.raises(UnresolvableSourceRecordError):
        run_counter_position_gate(
            [record],
            client=ExplodingLLMClient(),
            corpus_pin=None,
            trusted=False,
            config_path=tmp_path / "nonexistent.yaml",
            analyses_dir=tmp_path / "analyses",
        )


# -- the three inherited arms, over the paper's OWN cited claims ------------


def test_inherited_opposed_positions_arm_contested_paper_passes_with_grounds(
    vault_dir: Path, tmp_path: Path
):
    claims = [_paper_claim("pc-1", TILLY_CHUNK, SKOCPOL_CHUNK)]
    record = _paper_record(claims=claims, counter_position=_present_counter_position(SKOCPOL_CHUNK))
    report = run_counter_position_gate(
        [record],
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=tmp_path / "analyses",
    )
    metric = report.metrics[0]
    assert metric.value == pytest.approx(1.0)
    assert metric.n == 1


def test_inherited_arm_fires_even_with_a_resolvable_source_record_present(
    vault_dir: Path, tmp_path: Path
):
    """When an inherited arm already fires over the paper's own cited
    claims, `detect_paper_contested` never reaches the fourth arm at all
    (§7.14's stated order) -- a named, uncontested source record must not
    change the outcome. Source records are loaded eagerly, once per paper
    record, regardless of which arm ends up firing (module docstring): a
    paper's `source_analyses` naming a record that does not resolve is
    surfaced as `UnresolvableSourceRecordError` unconditionally, the same
    way `axial.gates.provenance` treats an unresolvable origin."""
    _write_source_record(tmp_path / "analyses", "b1", {"counter_position": _no_counter_position()})
    claims = [_paper_claim("pc-1", TILLY_CHUNK, SKOCPOL_CHUNK)]
    record = _paper_record(
        claims=claims,
        counter_position=_present_counter_position(SKOCPOL_CHUNK),
        source_analyses=["b1"],
    )
    report = run_counter_position_gate(
        [record],
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=tmp_path / "analyses",
    )
    metric = report.metrics[0]
    assert metric.n == 1
    assert metric.passed is True


# -- zero model calls, gate name -------------------------------------------


def test_zero_model_calls_ever(tmp_path: Path):
    record = _paper_record(claims=[], counter_position=_no_counter_position())
    report = run_counter_position_gate(
        [record],
        client=ExplodingLLMClient(),
        corpus_pin="baseline",
        trusted=True,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=tmp_path / "analyses",
    )
    assert report.gate == "counter-position"
    assert report.corpus_pin == "baseline"
    assert report.trusted is True
