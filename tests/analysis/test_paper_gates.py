"""Outer acceptance test for issue #608 (B2/B3/B4 of #605, specs/PHASE-C.md
§10.1, §7.14, §8 P0-9/P0-14): the (b)/(c)-seam gate, the grounding gate, and
the counter-position gate, all wired to Phase-C paper records.

Given a paper record carrying one new (b) claim (`origin: null`) whose
      grounds resolve, and a scripted (b)/(c)-seam judge that flags nothing
When  `axial gate run paper-attribution-fidelity --records <dir>` runs
Then  `b_seam_mislabel_rate` is 0.00, passed, and the command exits 0

Given the same paper record, but the scripted judge flags the claim
When  the gate runs
Then  `b_seam_mislabel_rate` is 1.00, failed, and the command exits non-zero,
      naming the flagged claim

Given a paper record carrying one new (b) claim whose grounds resolve, and a
      scripted grounding judge answering "does_not_contradict"
When  `axial gate run paper-grounding --records <dir>` runs
Then  `b_claim_noncontradiction_rate` is 1.00, passed, and the command
      exits 0

Given a config in which the grounding judge pass resolves to the same model
      as the paper-drafting pass
When  `axial gate run paper-grounding --records <dir>` runs
Then  the command exits non-zero with an error naming self-grading and the
      paper-drafting pass, and zero judge calls are made

Given a paper record whose own cited claims argue opposite sides (the
      `opposed_positions` arm) and carry a present-with-grounds
      counter-position
When  `axial gate run counter-position --records <dir>` runs
Then  `paper_counter_position_presence_rate` is 1.00, passed, and the
      command exits 0 with ZERO LLM calls made (`AXIAL_LLM_PROVIDER=explode`)

Given a paper record whose named source analysis record disclosed the corpus
      as one-sided (§7.14's fourth arm), but the paper's own counter-position
      is neither present nor disclosed
When  the gate runs
Then  the metric fails, names the paper, and the command exits non-zero

See specs/PHASE-C.md §10.1 (P0-9, P0-14) and §8 for this slice's own
acceptance criteria.

Seam decisions
--------------
Mirrors tests/analysis/test_provenance_gate.py's CLI subprocess pattern
exactly: an isolated `tmp_path` cwd (so `resolve_trusted` naturally reports
`trusted: False`), `--records <dir>` as an absolute path, and a `data/
analyses/<brief_id>.json` fixture under the isolated cwd for the
counter-position gate's fourth arm (mirrors the provenance gate's own origin
fixture). The (b)/(c)-seam and grounding scenarios use the `stub`/`record`
provider with `AXIAL_STUB_ATTRIBUTION_RESPONSE`/`AXIAL_STUB_GROUNDING_
RESPONSE_SEQUENCE` and `AXIAL_STUB_MODEL_BY_PASS` exactly as tests/analysis/
test_gate_harness_attribution_grounding.py already does; the counter-position
gate is mechanical (zero model calls), so its scenarios use `explode`.
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
STUB_MODEL_BY_PASS_ENV_VAR = "AXIAL_STUB_MODEL_BY_PASS"
STUB_ATTRIBUTION_RESPONSE_ENV_VAR = "AXIAL_STUB_ATTRIBUTION_RESPONSE"
STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_GROUNDING_RESPONSE_SEQUENCE"

CHUNK_ID = "papergate_syr_0001"
TILLY_CHUNK = "papergate_tilly_0001"
SKOCPOL_CHUNK = "papergate_skocpol_0001"


def _chunk_frontmatter(
    chunk_id: str, *, author: str = "A. Synthetic Author", arguing_against: Any = None
) -> dict[str, Any]:
    frontmatter: dict[str, Any] = {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": author,
            "title": "A Synthetic Fixture Source",
            "date": 2021,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
    }
    if arguing_against is not None:
        frontmatter["answers"] = {"position_of": "the author", "arguing_against": arguing_against}
    return frontmatter


def _write_chunk(root: Path, chunk_id: str, **kwargs: Any) -> None:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    text = (
        "---\n"
        + yaml.safe_dump(_chunk_frontmatter(chunk_id, **kwargs), sort_keys=False)
        + "---\nBody.\n"
    )
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


def _write_paper_record(root: Path, stem: str, record: dict[str, Any]) -> Path:
    records_dir = root / "papers"
    records_dir.mkdir(parents=True, exist_ok=True)
    (records_dir / f"{stem}.json").write_text(json.dumps(record), encoding="utf-8")
    return records_dir


def _write_source_analysis(root: Path, brief_id: str, record: dict[str, Any]) -> None:
    analyses_dir = root / "data" / "analyses"
    analyses_dir.mkdir(parents=True, exist_ok=True)
    (analyses_dir / f"{brief_id}.json").write_text(json.dumps(record), encoding="utf-8")


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_chunk(tmp_path, CHUNK_ID)
    return tmp_path


def _run_gate_cli(
    root: Path, gate: str, records_dir: Path, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop(STUB_MODEL_BY_PASS_ENV_VAR, None)
    env.pop(STUB_ATTRIBUTION_RESPONSE_ENV_VAR, None)
    env.pop(STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR, None)
    env[PROVIDER_ENV_VAR] = "stub"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "axial",
            "gate",
            "run",
            gate,
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
            f"expected a real `gate run` behavior path, not an argparse fallback "
            f"(found {marker!r}):\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _load_report(root: Path, gate: str) -> dict[str, Any]:
    report_path = root / "evals" / "reports" / f"{gate}.json"
    assert report_path.is_file(), f"expected a report at {report_path}"
    return json.loads(report_path.read_text(encoding="utf-8"))


def _new_b_claim(paper_claim_id: str, *, chunk_id: str = CHUNK_ID) -> dict[str, Any]:
    return {
        "paper_claim_id": paper_claim_id,
        "text": f"New cross-source claim for {paper_claim_id}.",
        "kind": "b",
        "origin": None,
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        "confidence": "medium",
        "names_touched": [],
        "derived_from": ["pc-0", "pc-1"],
    }


# -- paper-attribution-fidelity: the (b)/(c)-seam gate wired to papers -----


def test_paper_attribution_fidelity_clean_claim_passes(fixture_root: Path):
    record = {"paper_brief_id": "pb-1", "claims": [_new_b_claim("pc-2")]}
    records_dir = _write_paper_record(fixture_root, "pb-1", record)

    result = _run_gate_cli(
        fixture_root,
        "paper-attribution-fidelity",
        records_dir,
        extra_env={
            STUB_ATTRIBUTION_RESPONSE_ENV_VAR: json.dumps(
                {"flagged_claim_ids": [], "flagged_c_claim_ids": []}
            ),
            STUB_MODEL_BY_PASS_ENV_VAR: json.dumps(
                {"synthesize": "model-a", "attribution": "model-b"}
            ),
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    report = _load_report(fixture_root, "paper-attribution-fidelity")
    b_seam = next(m for m in report["metrics"] if m["metric"] == "b_seam_mislabel_rate")
    assert b_seam["value"] == pytest.approx(0.0)
    assert b_seam["passed"] is True


def test_paper_attribution_fidelity_flagged_claim_fails_and_names_it(fixture_root: Path):
    record = {"paper_brief_id": "pb-1", "claims": [_new_b_claim("pc-2")]}
    records_dir = _write_paper_record(fixture_root, "pb-1", record)

    result = _run_gate_cli(
        fixture_root,
        "paper-attribution-fidelity",
        records_dir,
        extra_env={
            STUB_ATTRIBUTION_RESPONSE_ENV_VAR: json.dumps(
                {"flagged_claim_ids": ["pc-2"], "flagged_c_claim_ids": []}
            ),
            STUB_MODEL_BY_PASS_ENV_VAR: json.dumps(
                {"synthesize": "model-a", "attribution": "model-b"}
            ),
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"stdout: {result.stdout!r}"
    report = _load_report(fixture_root, "paper-attribution-fidelity")
    b_seam = next(m for m in report["metrics"] if m["metric"] == "b_seam_mislabel_rate")
    assert b_seam["value"] == pytest.approx(1.0)
    assert b_seam["passed"] is False
    assert "pc-2" in b_seam["flagged_claim_ids"]


# -- paper-grounding: the re-barred (b)-claim grounding gate ---------------


def test_paper_grounding_clean_new_b_claim_passes(fixture_root: Path):
    record = {"paper_brief_id": "pb-1", "claims": [_new_b_claim("pc-2")]}
    records_dir = _write_paper_record(fixture_root, "pb-1", record)

    result = _run_gate_cli(
        fixture_root,
        "paper-grounding",
        records_dir,
        extra_env={
            STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR: json.dumps(
                [json.dumps({"verdict": "does_not_contradict"})]
            ),
            STUB_MODEL_BY_PASS_ENV_VAR: json.dumps(
                {"paper_draft": "model-a", "grounding": "model-b"}
            ),
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    report = _load_report(fixture_root, "paper-grounding")
    metric = next(m for m in report["metrics"] if m["metric"] == "b_claim_noncontradiction_rate")
    assert metric["value"] == pytest.approx(1.0)
    assert metric["threshold"] == 0.90
    assert metric["passed"] is True


def test_paper_grounding_self_grading_guard_names_paper_draft(fixture_root: Path):
    record = {"paper_brief_id": "pb-1", "claims": [_new_b_claim("pc-2")]}
    records_dir = _write_paper_record(fixture_root, "pb-1", record)

    result = _run_gate_cli(
        fixture_root, "paper-grounding", records_dir, extra_env={PROVIDER_ENV_VAR: "explode"}
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"stdout: {result.stdout!r}"
    combined = result.stdout + result.stderr
    assert "self-grading" in combined or "self grading" in combined
    assert "paper_draft" in combined
    assert "RuntimeError" not in combined, (
        "the explode provider's .complete() must never fire -- zero judge calls"
    )


# -- counter-position: mechanical presence-or-disclosure over papers -------


def test_counter_position_contested_paper_with_grounds_passes(fixture_root: Path):
    _write_chunk(fixture_root, TILLY_CHUNK, author="Charles Tilly", arguing_against=["Skocpol"])
    _write_chunk(fixture_root, SKOCPOL_CHUNK, author="Theda Skocpol", arguing_against=[])
    record = {
        "paper_brief_id": "pb-1",
        "claims": [
            {
                "paper_claim_id": "pc-1",
                "text": "Text.",
                "kind": "a",
                "grounds": [
                    {"ref_type": "chunk", "ref_id": TILLY_CHUNK},
                    {"ref_type": "chunk", "ref_id": SKOCPOL_CHUNK},
                ],
                "names_touched": [],
            }
        ],
        "counter_position": {
            "present": True,
            "stance": "The opposing school holds...",
            "grounds": [{"ref_type": "chunk", "ref_id": SKOCPOL_CHUNK}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "source_analyses": [],
        "coverage_map": {},
    }
    records_dir = _write_paper_record(fixture_root, "pb-1", record)

    result = _run_gate_cli(
        fixture_root, "counter-position", records_dir, extra_env={PROVIDER_ENV_VAR: "explode"}
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    report = _load_report(fixture_root, "counter-position")
    metric = next(
        m for m in report["metrics"] if m["metric"] == "paper_counter_position_presence_rate"
    )
    assert metric["value"] == pytest.approx(1.0)
    assert metric["threshold"] == 1.00
    assert metric["passed"] is True


def test_counter_position_fourth_arm_fails_when_paper_drops_the_disclosure(fixture_root: Path):
    _write_source_analysis(
        fixture_root,
        "b1",
        {
            "counter_position": {
                "present": False,
                "stance": None,
                "grounds": [],
                "corpus_one_sided": True,
                "one_sided_reason": "the corpus carries no opposing school here",
            }
        },
    )
    record = {
        "paper_brief_id": "pb-1",
        "claims": [],
        "counter_position": {
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "source_analyses": ["b1"],
        "coverage_map": {},
    }
    records_dir = _write_paper_record(fixture_root, "pb-1", record)

    result = _run_gate_cli(
        fixture_root, "counter-position", records_dir, extra_env={PROVIDER_ENV_VAR: "explode"}
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"stdout: {result.stdout!r}"
    report = _load_report(fixture_root, "counter-position")
    metric = next(
        m for m in report["metrics"] if m["metric"] == "paper_counter_position_presence_rate"
    )
    assert metric["value"] == pytest.approx(0.0)
    assert metric["passed"] is False
    assert "pb-1" in metric["failing_brief_ids"]
