"""Outer acceptance test for issue #491 Part 1 (Phase B v1, slice 06): the
per-run report (specs/PHASE-B.md §7.15, §8 P0-14) and the §7.13 source-usage
denominator re-based onto the names a run queried.

Given a fixture vault holding two sources (`tilly-1978`, `bayat-2017`) and a
      name page per scholar
  And a fixture brief whose retrieval calls `get_name` on both names
When  `axial brief run <brief>` runs
Then  the command exits 0
  And a run report is written to data/runs/<brief_id>.json
  And it is keyed on brief_id AND corpus_pin, so two runs of the same brief
      at the same pin join on those two keys
  And it names an elapsed wall-clock time for every pass model_by_pass names
  And the reported total latency is exactly the sum of those per-pass
      figures, never a second measurement
  And the record's source_usage carries names_queried (never the struck
      filters_observed), a non-zero available_chunk_count per source, and a
      non-null usage_ratio

Given the same run, whose one (b) claim is grounded in two distinct sources
When  the report is read
Then  cross_source_rate is 1.0

Given a hand-built record whose every (b) claim is grounded in one book
When  build_run_report runs over it with the `explode` provider installed
Then  zero LLM calls are made
  And cross_source_rate is 0.0, however completely the claims are attributed
  And the two judged accuracy numbers are reported as not-scored with a
      stated reason, never as 0 and never as a pass

Given a case file evals/cases/sim/DEVCASE.json naming two required citation
      legs (issue #560) -- one whose `any_of` is reached through a
      non-leader member, one wholly unreached
When  the report is built with that case_id
Then  retrieval_hit is 0.5, naming the reached and the missed leg BY NAME

Given the same case restated in the older flat `required_citation_source_ids`
      form (one id per leg)
When  the report is built with that case_id
Then  retrieval_hit scores identically to the leg form -- back-compat for the
      cases not being re-authored in this slice

Given the same persisted record and the same per-pass latencies
When  the report is built twice
Then  the two reports are identical

See specs/PHASE-B.md §7.15 (the run report), §7.13 (source usage, re-based),
§7.14 (cost) and §10.0 (the four accuracy measures) for the source of truth.

Seam decisions
--------------
Scenario 1 drives the real `axial brief run` CLI as a subprocess from an
isolated `tmp_path` staging root with `AXIAL_LLM_PROVIDER=stub` and the
scripted tool-call channel, mirroring
tests/analysis/test_source_usage.py's own CLI seam. Every other scenario
calls `build_run_report` directly over a hand-built record: a report is a
pure function of an already-finished record plus the latencies the running
process held, so there is no engine call to script, and `explode` proves the
zero-model-call contract by crashing rather than by an assertion that
happens not to trip.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_LENSES_DIR = REPO_ROOT / "config" / "lenses"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
STUB_INTERROGATE_RESPONSE_ENV_VAR = "AXIAL_STUB_INTERROGATE_RESPONSE"
STUB_TOOL_CALLS_ENV_VAR = "AXIAL_STUB_TOOL_CALLS"
STUB_SYNTHESIZE_RESPONSE_ENV_VAR = "AXIAL_STUB_SYNTHESIZE_RESPONSE"

_BRIEF_ID_PATTERN = re.compile(r"brief_id:\s*(\S+)")

TILLY = "Charles Tilly"
BAYAT = "Asef Bayat"
TILLY_CHUNK = "tilly-1978_001_intro_001"
BAYAT_CHUNK = "bayat-2017_001_intro_001"
TILLY_SOURCE = "tilly-1978"
BAYAT_SOURCE = "bayat-2017"


# ---------------------------------------------------------------------------
# Fixture vault
# ---------------------------------------------------------------------------


def _write_chunk(root: Path, chunk_id: str) -> None:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {"author": "A", "title": "T", "date": 2020, "thesis": "X", "scope": "Y"},
        "schema_version": "0.1",
        "frame_version": "0.1",
        "answers": {"claim": f"Claim of {chunk_id}.", "position_of": "the author"},
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


def _write_name_page(root: Path, name: str, *, member_ids: list[str]) -> None:
    names_dir = root / "data" / "vault" / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "name": name,
        "kind": "person",
        "aliases": [],
        "member_count": len(member_ids),
    }
    lines = ["**Member notes:**"]
    lines += [f"- [[{chunk_id}]] — An Author (1978): A claim." for chunk_id in member_ids]
    body = yaml.safe_dump(frontmatter, sort_keys=False)
    (names_dir / f"{name}.md").write_text(
        "---\n" + body + "---\n" + "\n".join(lines) + "\n", encoding="utf-8"
    )


def _write_fixture_pin(root: Path, name: str = "baseline") -> None:
    evals_dir = root / "evals" / "corpus_pin"
    evals_dir.mkdir(parents=True, exist_ok=True)
    (evals_dir / f"{name}.json").write_text(
        json.dumps({"sources": [], "ingest_code_sha": "deadbeef", "vault_snapshot_hash": "abc"}),
        encoding="utf-8",
    )


def _write_fixture_brief(root: Path) -> Path:
    briefs_dir = root / "config" / "briefs" / "dev"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    path = briefs_dir / "fixture-run-report.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "case": "Syria, 2011-2024",
                "request": "Do Tilly and Bayat explain sustained mobilization differently?",
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_chunk(tmp_path, TILLY_CHUNK)
    _write_chunk(tmp_path, BAYAT_CHUNK)
    _write_name_page(tmp_path, TILLY, member_ids=[TILLY_CHUNK])
    _write_name_page(tmp_path, BAYAT, member_ids=[BAYAT_CHUNK])
    _write_fixture_pin(tmp_path)
    shutil.copytree(REPO_LENSES_DIR, tmp_path / "config" / "lenses")
    return tmp_path


def _run_brief_run_cli(root: Path, brief_path: Path, **env_overrides: str):
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "stub"
    env.update(env_overrides)
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", "brief", "run", str(brief_path)],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Scenario 1: the report exists, is keyed to join, and carries per-pass clocks
# ---------------------------------------------------------------------------


def test_brief_run_writes_a_run_report_keyed_on_brief_id_and_pin(fixture_root: Path):
    brief_path = _write_fixture_brief(fixture_root)
    tool_calls = [
        {"tool": "get_name", "args": {"canonical": TILLY}},
        {"tool": "get_name", "args": {"canonical": BAYAT}},
        None,
    ]
    synthesize_response = {
        "claims": [
            {
                "text": "A cross-source inference over both books.",
                "kind": "b",
                "grounds": [
                    {"ref_type": "chunk", "ref_id": "[c1]"},
                    {"ref_type": "chunk", "ref_id": "[c2]"},
                ],
                "confidence": "medium",
            }
        ]
    }

    result = _run_brief_run_cli(
        fixture_root,
        brief_path,
        **{
            STUB_INTERROGATE_RESPONSE_ENV_VAR: json.dumps(
                {"premises_found": [], "bounds_applied": [], "refusal": None}
            ),
            STUB_TOOL_CALLS_ENV_VAR: json.dumps(tool_calls),
            STUB_SYNTHESIZE_RESPONSE_ENV_VAR: json.dumps(synthesize_response),
        },
    )
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    match = _BRIEF_ID_PATTERN.search(result.stdout + result.stderr)
    assert match, result.stdout
    brief_id = match.group(1)

    report_path = fixture_root / "data" / "runs" / f"{brief_id}.json"
    assert report_path.is_file(), (
        f"expected a §7.15 run report at {report_path}; stdout: {result.stdout!r}"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # Keyed on brief_id AND corpus_pin so two runs join (P0-14).
    assert report["brief_id"] == brief_id
    assert report["corpus_pin"] == "baseline"

    record = json.loads(
        (fixture_root / "data" / "analyses" / f"{brief_id}.json").read_text(encoding="utf-8")
    )

    # Per-pass wall clock: one figure per pass `model_by_pass` names, and the
    # total is exactly their sum -- never a second measurement.
    latency = report["operational"]["latency_seconds"]
    assert set(latency["by_pass"]) == set(record["model_by_pass"]), (
        f"expected one elapsed time per named pass, got {latency!r} for {record['model_by_pass']!r}"
    )
    assert all(value >= 0 for value in latency["by_pass"].values())
    assert latency["total"] == pytest.approx(sum(latency["by_pass"].values()))

    # The denominator re-based onto the names queried (§7.13).
    source_usage = record["source_usage"]
    assert "filters_observed" not in source_usage
    assert source_usage["names_queried"] == [
        {"tool": "get_name", "args": {"canonical": TILLY}},
        {"tool": "get_name", "args": {"canonical": BAYAT}},
    ]
    assert source_usage["denominator_by_name"] == {TILLY: 1, BAYAT: 1}
    by_source = {entry["source_id"]: entry for entry in source_usage["sources"]}
    assert by_source[TILLY_SOURCE]["available_chunk_count"] == 1
    assert by_source[TILLY_SOURCE]["available_share"] == pytest.approx(0.5)
    assert by_source[TILLY_SOURCE]["usage_ratio"] == pytest.approx(1.0)

    # The headline: this (b) claim's grounds span two books.
    assert report["response_quality"]["cross_source_rate"]["value"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Scenarios 2-4: the report as a pure function of a finished record
# ---------------------------------------------------------------------------


def _claim(claim_id: str, kind: str, chunk_ids: list[str], names: list[str]) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": f"Claim text for {claim_id}.",
        "kind": kind,
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids],
        "confidence": "medium",
        "names_touched": names,
    }


def _record(claims: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "brief_id": "DEV91",
        "brief": {"brief_id": "DEV91", "case": "Syria", "request": "R?", "lens": None},
        "corpus_pin": "baseline",
        "lens": "political-economy",
        "interrogation": {
            "premises_found": [],
            "bounds_applied": [],
            "refusal": None,
            "disposition": "proceed",
        },
        "claims": claims,
        "counter_position": {
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "coverage_map": {
            TILLY: {"corpus_note_count": 1, "evidence_note_count": 1, "coverage_band": "thin"}
        },
        "confidence": {"overall_band": "low", "rationale": "thin"},
        "trajectory": [
            {
                "step": 1,
                "tool": "get_name",
                "args": {"canonical": TILLY},
                "result_ids": [TILLY_CHUNK],
                "result_count": 1,
            },
            {
                "step": 2,
                "tool": "get_chunk",
                "args": {"chunk_id": TILLY_CHUNK},
                "result_ids": [TILLY_CHUNK],
                "result_count": 1,
            },
        ],
        "model_by_pass": {"interrogate": "stub", "retrieve": "stub", "synthesize": "stub"},
        "cost": {
            "by_pass": {
                "interrogate": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "usd": None,
                }
            },
            "total_usd": None,
        },
        "source_usage": {"names_queried": [], "denominator_by_name": {}, "sources": []},
    }


_LATENCIES = {"interrogate": 1.5, "retrieve": 2.0, "synthesize": 4.5}


def test_single_book_b_claims_report_a_cross_source_rate_of_zero(tmp_path: Path, monkeypatch):
    """D9's own observable: a run every one of whose (b) claims is grounded
    in a single book reports 0, however well attributed it is -- and the
    whole report is computed with zero model calls (`explode` crashes on
    any)."""
    monkeypatch.setenv(PROVIDER_ENV_VAR, "explode")
    from axial.answer.run_report import build_run_report

    _write_chunk(tmp_path, TILLY_CHUNK)
    _write_chunk(tmp_path, "tilly-1978_001_intro_002")
    vault_dir = tmp_path / "data" / "vault"

    record = _record(
        [
            _claim("c1", "b", [TILLY_CHUNK, "tilly-1978_001_intro_002"], [TILLY]),
            _claim("c2", "a", [TILLY_CHUNK], [TILLY]),
        ]
    )

    report = build_run_report(record, latency_by_pass=_LATENCIES, vault_dir=vault_dir)

    assert report["response_quality"]["cross_source_rate"]["value"] == 0.0
    assert report["response_quality"]["cross_source_rate"]["denominator"] == 1
    assert report["accuracy"]["attribution_completeness"]["value"] == pytest.approx(1.0)

    # The two judged numbers are reported as not-scored with a reason, never
    # as a 0 that reads like a measurement and never as a silent pass.
    for name in ("grounding_support_rate", "instant_dismissal_violations"):
        judged = report["accuracy"][name]
        assert judged["value"] is None
        assert judged["reason"]


def test_retrieval_hit_scores_against_required_citation_legs(tmp_path: Path, monkeypatch):
    """Issue #560: a leg is reached when the run's grounds cite ANY source
    in its `any_of`, so a leg is reached here through the SECOND
    (non-leader) member of its `any_of` -- the whole point of the schema is
    that reaching a leg never depends on which book in the list carried it.
    The unreached leg is named, not just counted, since which demand an
    answer missed is the point of the oracle."""
    monkeypatch.setenv(PROVIDER_ENV_VAR, "explode")
    from axial.answer.run_report import build_run_report

    _write_chunk(tmp_path, TILLY_CHUNK)
    vault_dir = tmp_path / "data" / "vault"

    cases_dir = tmp_path / "evals" / "cases" / "sim"
    cases_dir.mkdir(parents=True)
    (cases_dir / "DEVCASE.json").write_text(
        json.dumps(
            {
                "case_id": "DEVCASE",
                "question": "Q",
                "answer_kind": "rubric",
                "required_citation_legs": [
                    {"leg": "the tilly leg", "any_of": [BAYAT_SOURCE, TILLY_SOURCE]},
                    {"leg": "the unreached leg", "any_of": [BAYAT_SOURCE]},
                ],
                "rubric": [],
                "instant_dismissal_criteria": ["Anything that ignores organization."],
            }
        ),
        encoding="utf-8",
    )

    record = _record([_claim("c1", "a", [TILLY_CHUNK], [TILLY])])
    report = build_run_report(
        record,
        latency_by_pass=_LATENCIES,
        vault_dir=vault_dir,
        case_id="DEVCASE",
        cases_dir=cases_dir,
    )

    hit = report["accuracy"]["retrieval_hit"]
    assert hit["value"] == pytest.approx(0.5)
    assert hit["reached_legs"] == ["the tilly leg"]
    assert hit["missed_legs"] == ["the unreached leg"]


def test_retrieval_hit_old_flat_form_scores_identically_to_before(tmp_path: Path, monkeypatch):
    """Back-compat (issue #560): a case stating only the older flat
    `required_citation_source_ids` is read as one leg per id, so the 23
    cases not being re-authored in this slice score exactly as they always
    did."""
    monkeypatch.setenv(PROVIDER_ENV_VAR, "explode")
    from axial.answer.run_report import build_run_report

    _write_chunk(tmp_path, TILLY_CHUNK)
    vault_dir = tmp_path / "data" / "vault"

    cases_dir = tmp_path / "evals" / "cases" / "sim"
    cases_dir.mkdir(parents=True)
    (cases_dir / "DEVCASE.json").write_text(
        json.dumps(
            {
                "case_id": "DEVCASE",
                "question": "Q",
                "answer_kind": "rubric",
                "required_citation_source_ids": [TILLY_SOURCE, BAYAT_SOURCE],
                "rubric": [],
                "instant_dismissal_criteria": ["Anything that ignores organization."],
            }
        ),
        encoding="utf-8",
    )

    record = _record([_claim("c1", "a", [TILLY_CHUNK], [TILLY])])
    report = build_run_report(
        record,
        latency_by_pass=_LATENCIES,
        vault_dir=vault_dir,
        case_id="DEVCASE",
        cases_dir=cases_dir,
    )

    hit = report["accuracy"]["retrieval_hit"]
    assert hit["value"] == pytest.approx(0.5)
    assert hit["reached_legs"] == [TILLY_SOURCE]
    assert hit["missed_legs"] == [BAYAT_SOURCE]


def test_the_report_is_deterministic_over_the_same_record(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(PROVIDER_ENV_VAR, "explode")
    from axial.answer.run_report import build_run_report

    _write_chunk(tmp_path, TILLY_CHUNK)
    vault_dir = tmp_path / "data" / "vault"
    record = _record([_claim("c1", "a", [TILLY_CHUNK], [TILLY])])

    first = build_run_report(record, latency_by_pass=_LATENCIES, vault_dir=vault_dir)
    second = build_run_report(record, latency_by_pass=_LATENCIES, vault_dir=vault_dir)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_turns_that_added_no_new_evidence_are_counted(tmp_path: Path, monkeypatch):
    """#505's convergence signal: `get_chunk` returns one id and
    `assemble_evidence_ids` dedupes, so a turn re-fetching a seen id changes
    nothing downstream. Here turn 2 re-fetches turn 1's own id."""
    monkeypatch.setenv(PROVIDER_ENV_VAR, "explode")
    from axial.answer.run_report import build_run_report

    _write_chunk(tmp_path, TILLY_CHUNK)
    vault_dir = tmp_path / "data" / "vault"
    record = _record([_claim("c1", "a", [TILLY_CHUNK], [TILLY])])

    report = build_run_report(record, latency_by_pass=_LATENCIES, vault_dir=vault_dir)
    trajectory = report["operational"]["trajectory"]
    assert trajectory["tool_calls"] == 2
    assert trajectory["evidence_tool_calls"] == 2
    assert trajectory["turns_without_new_evidence"] == 1
