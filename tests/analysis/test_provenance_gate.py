"""Outer acceptance test for issue #606 (B1 + B5 of #605, specs/PHASE-C.md
§10.1, §7.4, §8 P0-8/P0-12): the provenance-integrity gate, plus the
paper-record loader/CLI plumbing.

Given a paper record whose citation markers all resolve to a claim carrying
      grounds that resolve to real vault ids, and no carried or new claim
      exceeds its §7.4 confidence ceiling
When  `axial gate run provenance-integrity --records <dir>` runs
Then  the report records `provenance_completeness` = 1.00 (passed) and
      `confidence_upgrade_count` = 0 (passed), the report carries no
      `panel` field, and the command exits 0 with ZERO LLM calls made
      (`AXIAL_LLM_PROVIDER=explode`)

Given the same paper record plus one more citation marker naming a
      `paper_claim_id` absent from `claims`
When  the gate runs
Then  `provenance_completeness` drops below 1.00, fails, and the report
      names the dangling `paper_claim_id`; the command exits non-zero

Given a paper record carrying a claim whose `origin` names a source
      analysis record, where the origin claim's own coverage clamps its
      band to `medium`, but the carried claim discloses `high`
When  the gate runs
Then  `confidence_upgrade_count` is 1 (fails), and the report names the
      offending `paper_claim_id`; the command exits non-zero

See specs/PHASE-C.md §10.1 (P0-8) and §8 P0-12 for this slice's own
acceptance criteria.

Seam decisions
--------------
Mirrors tests/analysis/test_gate_harness_attribution_grounding.py's CLI
subprocess pattern exactly: an isolated `tmp_path` cwd (so `resolve_trusted`
naturally reports `trusted: False` with no setup), the `explode` LLM
provider proving zero model calls (P0-8's own "zero model calls" bullet),
and `--records <dir>` as an absolute path. The one addition this gate needs
over the attribution/grounding pattern: a `data/analyses/<brief_id>.json`
fixture under the isolated cwd, since a carried claim's ceiling is checked
against its ORIGIN analysis record (§7.4) -- `axial.gates.provenance`'s own
`analyses_dir` default resolves `data/analyses` relative to the process cwd,
exactly like `axial.query.reader`'s `vault_dir` default already does for the
existing gates' fixture vault.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

CHUNK_ID = "provgate_syr_0001"
MISSING_CHUNK_ID = "provgate_syr_9999"


def _chunk_frontmatter(*, chunk_id: str = CHUNK_ID) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": "A. Synthetic Author",
            "title": "A Synthetic Fixture Source",
            "date": 2021,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
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


def _write_fixture_vault(root: Path) -> None:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    text = "---\n" + yaml.safe_dump(_chunk_frontmatter(), sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{CHUNK_ID}.md").write_text(text, encoding="utf-8")


def _write_origin_analysis(root: Path, brief_id: str, record: dict[str, Any]) -> None:
    analyses_dir = root / "data" / "analyses"
    analyses_dir.mkdir(parents=True, exist_ok=True)
    (analyses_dir / f"{brief_id}.json").write_text(json.dumps(record), encoding="utf-8")


def _paper_claim(
    paper_claim_id: str, *, origin: dict[str, Any], confidence: str, chunk_id: str = CHUNK_ID
) -> dict[str, Any]:
    return {
        "paper_claim_id": paper_claim_id,
        "text": f"Paper claim text for {paper_claim_id}.",
        "kind": "a",
        "origin": origin,
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        "confidence": confidence,
        "names_touched": [],
        "derived_from": [],
    }


def _write_paper_record(root: Path, stem: str, record: dict[str, Any]) -> Path:
    records_dir = root / "papers"
    records_dir.mkdir(parents=True, exist_ok=True)
    (records_dir / f"{stem}.json").write_text(json.dumps(record), encoding="utf-8")
    return records_dir


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_fixture_vault(tmp_path)
    return tmp_path


def _run_gate_cli(root: Path, records_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "axial",
            "gate",
            "run",
            "provenance-integrity",
            "--records",
            str(records_dir),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ("invalid choice", "unrecognized arguments"):
        assert marker not in combined, (
            f"expected a real `gate run provenance-integrity` behavior path, not an "
            f"argparse fallback (found {marker!r}):\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


def _load_report(root: Path) -> dict[str, Any]:
    report_path = root / "evals" / "reports" / "provenance-integrity.json"
    assert report_path.is_file(), f"expected a report at {report_path}"
    return json.loads(report_path.read_text(encoding="utf-8"))


def test_scenario1_clean_record_passes_both_metrics_with_zero_llm_calls(fixture_root: Path):
    origin = {"brief_id": "b1", "claim_id": "c1"}
    _write_origin_analysis(
        fixture_root,
        "b1",
        {
            "claims": [{"claim_id": "c1", "confidence": "high", "names_touched": []}],
            "coverage_map": {},
        },
    )
    record = {
        "paper_brief_id": "pb-1",
        "claims": [_paper_claim("pc-1", origin=origin, confidence="high")],
        "citations": [{"section_id": "s1", "sentence_index": 0, "paper_claim_id": "pc-1"}],
    }
    records_dir = _write_paper_record(fixture_root, "pb-1", record)

    result = _run_gate_cli(fixture_root, records_dir)

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0 (explode provider means any LLM call would have crashed the run), "
        f"got {result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    report = _load_report(fixture_root)
    assert report["trusted"] is False
    assert "panel" not in report

    completeness = next(m for m in report["metrics"] if m["metric"] == "provenance_completeness")
    assert completeness["value"] == 1.00
    assert completeness["passed"] is True

    upgrades = next(m for m in report["metrics"] if m["metric"] == "confidence_upgrade_count")
    assert upgrades["value"] == 0
    assert upgrades["passed"] is True


def test_scenario2_dangling_marker_fails_and_names_it(fixture_root: Path):
    origin = {"brief_id": "b1", "claim_id": "c1"}
    _write_origin_analysis(
        fixture_root,
        "b1",
        {
            "claims": [{"claim_id": "c1", "confidence": "high", "names_touched": []}],
            "coverage_map": {},
        },
    )
    record = {
        "paper_brief_id": "pb-1",
        "claims": [_paper_claim("pc-1", origin=origin, confidence="high")],
        "citations": [
            {"section_id": "s1", "sentence_index": 0, "paper_claim_id": "pc-1"},
            {"section_id": "s1", "sentence_index": 1, "paper_claim_id": "pc-does-not-exist"},
        ],
    }
    records_dir = _write_paper_record(fixture_root, "pb-1", record)

    result = _run_gate_cli(fixture_root, records_dir)

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"

    report = _load_report(fixture_root)
    completeness = next(m for m in report["metrics"] if m["metric"] == "provenance_completeness")
    assert completeness["value"] < 1.00
    assert completeness["passed"] is False
    assert "pc-does-not-exist" in completeness["dangling_paper_claim_ids"]
    assert "pc-does-not-exist" in result.stdout


def test_scenario3_upgraded_band_fails_confidence_upgrade_count(fixture_root: Path):
    """The origin claim touches 'Syria', whose coverage_band 'moderate'
    clamps confidence to 'medium' (issue #550); the carried claim discloses
    the unclamped 'high' instead -- exactly P0-4's own observable."""
    origin = {"brief_id": "b1", "claim_id": "c1"}
    _write_origin_analysis(
        fixture_root,
        "b1",
        {
            "claims": [{"claim_id": "c1", "confidence": "high", "names_touched": ["Syria"]}],
            "coverage_map": {"Syria": {"coverage_band": "moderate"}},
        },
    )
    record = {
        "paper_brief_id": "pb-1",
        "claims": [_paper_claim("pc-1", origin=origin, confidence="high")],
        "citations": [{"section_id": "s1", "sentence_index": 0, "paper_claim_id": "pc-1"}],
    }
    records_dir = _write_paper_record(fixture_root, "pb-1", record)

    result = _run_gate_cli(fixture_root, records_dir)

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"

    report = _load_report(fixture_root)
    upgrades = next(m for m in report["metrics"] if m["metric"] == "confidence_upgrade_count")
    assert upgrades["value"] == 1
    assert upgrades["passed"] is False
    assert "pc-1" in upgrades["violating_paper_claim_ids"]
    assert "pc-1" in result.stdout
