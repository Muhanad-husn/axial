"""Outer acceptance test for issue #266, slice 02 of the source-usage
subproject (Phase B, sub:analysis-v0): `axial brief usage`, the cross-run
aggregation affordance of §7.13 ("Design for the aggregate") / §8 P0-13.

Given a fixture data/analyses/ holding five analysis records on corpus_pin
      "PIN-A" and one on corpus_pin "PIN-B"
  And in three of the PIN-A records, filters_observed contains
      theory_school:world-systems, and in those three source_id "tilly"
      shows usage_ratio 3.1, 2.8, and 3.4
  And in the other two PIN-A records, which do not query that filter,
      "tilly" shows usage_ratio 1.0 and 0.9
When  `axial brief usage` runs
Then  the command exits 0
  And the report covers the five PIN-A records and states that one record
      on PIN-B was excluded as not comparable
  And "tilly" is named among the heaviest-weighing sources, with the
      record count behind its pooled ratio
  And the per-filter breakdown shows "tilly" against
      theory_school:world-systems at a pooled ratio near 3 over 3 records,
      distinctly above its pooled ratio across all five
  And zero LLM calls were made (the `explode` provider never fires)

Given the same fixture
When  `axial brief usage --pin PIN-B` runs
Then  the report covers only the single PIN-B record and states its record
      count

Given a fixture data/analyses/ holding only records whose
      source_usage.sources is empty (refusals)
When  `axial brief usage` runs
Then  the command exits 0 and reports no source rows, without error

Given an empty data/analyses/
When  `axial brief usage` runs
Then  the command exits 0 and says there are no records to report on

See specs/PHASE-B.md §7.13 ("Design for the aggregate": "per-source usage
ratios can be pooled across every record sharing a corpus pin ... a
cross-run inspection affordance over data/analyses/ is in scope for this
phase (P0-13)") and §7.12 (the corpus-pin partition rule) for the source of
truth, and plans/source-usage/02-cross-run-usage-report.md for this slice's
own plan.

Isolation -- the isolated staging root, no config/pipeline.yaml
-----------------------------------------------------------------------
`axial.paths.default_analyses_dir` resolves `data/analyses/` as a plain,
cwd-relative path (falling back to `ANALYSES_DIR` when no
`config/pipeline.yaml` is present) -- the same seam
`tests/analysis/test_source_usage.py` and `tests/chunk/test_chunk_examine.py`
already establish: the CLI subprocess runs with `cwd` set to a fresh,
isolated `tmp_path`, never the real repo's shared `data/`.

LLM-free by construction
-----------------------------------------------------------------------
Every CLI invocation below runs with `AXIAL_LLM_PROVIDER=explode`
(`ExplodingLLMClient.complete()` raises if a text-generating call is ever
attempted). `axial brief usage` never even constructs a client -- it only
reads JSON already on disk under `data/analyses/` and does arithmetic -- so
a run succeeding under this env var directly proves zero model calls.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"


def _source_entry(source_id: str, usage_ratio: float | None) -> dict[str, Any]:
    """A minimal, honest §7.13 source_usage.sources entry -- only the
    fields `axial brief usage` actually reads (`source_id`, `usage_ratio`)
    are load-bearing here; the rest are filled in for shape realism."""
    return {
        "source_id": source_id,
        "evidence_chunk_count": 1,
        "evidence_share": 1.0,
        "available_chunk_count": 1,
        "available_share": 1.0,
        "usage_ratio": usage_ratio,
    }


WORLD_SYSTEMS_FILTER = {"tool": "query_by_tag", "args": {"theory_school": "world-systems"}}
OTHER_FILTER = {"tool": "query_by_tag", "args": {"field": "political-science"}}


def _record(
    brief_id: str,
    *,
    corpus_pin: str,
    filters_observed: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    disposition: str = "proceed",
) -> dict[str, Any]:
    return {
        "brief_id": brief_id,
        "brief": {"brief_id": brief_id, "case": "Test", "request": "Test?", "lens": None},
        "corpus_pin": corpus_pin,
        "schema_version": "0.1",
        "lens": "default",
        "interrogation": {
            "premises_found": [],
            "bounds_applied": [],
            "refusal": None if disposition != "refuse" else {"reason": "no coverage"},
            "disposition": disposition,
        },
        "claims": [],
        "counter_position": {
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "coverage_map": {},
        "confidence": {"overall_band": "low", "rationale": "placeholder"},
        "trajectory": [],
        "model_by_pass": {"interrogate": "stub"},
        "source_usage": {"filters_observed": filters_observed, "sources": sources},
    }


def _write_records(analyses_dir: Path, records: list[dict[str, Any]]) -> None:
    analyses_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        path = analyses_dir / f"{record['brief_id']}.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_brief_usage(
    root: Path, *, extra_args: list[str] | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"  # poison: any text-gen LLM call crashes the run
    args = ["uv", "run", "--project", str(REPO_ROOT), "axial", "brief", "usage"]
    if extra_args:
        args.extend(extra_args)
    return subprocess.run(args, cwd=root, capture_output=True, text=True, env=env)


def _find_ratio_near(
    combined: str, required: tuple[str, ...], forbidden: tuple[str, ...] = ()
) -> float | None:
    """Loosely locate a bare decimal figure appearing within a window that
    also contains every keyword in `required` and none in `forbidden` --
    mirrors tests/chunk/test_chunk_examine.py's own `_number_flanked_by`
    restraint on exact report layout/wording: this test does not dictate
    HOW the implementer renders a pooled ratio, only that the right number
    is discoverable near the right labels. A tight window (one report row's
    worth of text) keeps this from crossing into an unrelated row/section
    that happens to also mention one of the required keywords."""
    window = 60
    for match in re.finditer(r"[0-9]+\.[0-9]+", combined):
        start = max(0, match.start() - window)
        end = min(len(combined), match.end() + window)
        context = combined[start:end]
        if all(keyword in context for keyword in required) and not any(
            keyword in context for keyword in forbidden
        ):
            return float(match.group(0))
    return None


@pytest.fixture
def five_and_one_fixture_root(tmp_path: Path) -> Path:
    analyses_dir = tmp_path / "data" / "analyses"
    records = [
        _record(
            "A1",
            corpus_pin="PIN-A",
            filters_observed=[WORLD_SYSTEMS_FILTER],
            sources=[_source_entry("tilly", 3.1)],
        ),
        _record(
            "A2",
            corpus_pin="PIN-A",
            filters_observed=[WORLD_SYSTEMS_FILTER],
            sources=[_source_entry("tilly", 2.8)],
        ),
        _record(
            "A3",
            corpus_pin="PIN-A",
            filters_observed=[WORLD_SYSTEMS_FILTER],
            sources=[_source_entry("tilly", 3.4)],
        ),
        _record(
            "A4",
            corpus_pin="PIN-A",
            filters_observed=[OTHER_FILTER],
            sources=[_source_entry("tilly", 1.0)],
        ),
        _record(
            "A5",
            corpus_pin="PIN-A",
            filters_observed=[OTHER_FILTER],
            sources=[_source_entry("tilly", 0.9)],
        ),
        _record(
            "B1",
            corpus_pin="PIN-B",
            filters_observed=[OTHER_FILTER],
            sources=[_source_entry("tilly", 1.0)],
        ),
    ]
    _write_records(analyses_dir, records)
    return tmp_path


def test_usage_report_pools_pin_a_names_tilly_and_shows_filter_skew(five_and_one_fixture_root):
    result = _run_brief_usage(five_and_one_fixture_root)
    combined = result.stdout + result.stderr

    assert result.returncode == 0, (
        f"expected exit 0 for `axial brief usage`, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # covers the five PIN-A records
    assert "5" in combined and "PIN-A" in combined, combined
    # states the PIN-B exclusion
    assert "PIN-B" in combined and "1" in combined and "excluded" in combined.lower(), combined

    # tilly named among the heaviest-weighing sources, with a record count
    assert "tilly" in combined
    assert re.search(r"tilly.{0,20}over 5 record", combined), combined

    # pooled ratio across all five PIN-A records = (3.1+2.8+3.4+1.0+0.9)/5 = 2.24,
    # located near "tilly" but away from the per-filter breakdown row.
    ratio_all = _find_ratio_near(combined, required=("tilly",), forbidden=("world-systems",))
    assert ratio_all is not None, combined
    assert abs(ratio_all - 2.24) < 0.1, (ratio_all, combined)

    # per-filter breakdown: tilly @ theory_school:world-systems = (3.1+2.8+3.4)/3 = 3.1,
    # over 3 records, distinctly above its pooled ratio across all five.
    assert "theory_school:world-systems" in combined
    assert re.search(r"theory_school:world-systems.{0,40}over 3 record", combined), combined
    ratio_filter = _find_ratio_near(combined, required=("tilly", "world-systems"), forbidden=())
    assert ratio_filter is not None, combined
    assert abs(ratio_filter - 3.1) < 0.1, (ratio_filter, combined)
    assert ratio_filter > ratio_all + 0.5, (
        f"expected the theory_school:world-systems pooled ratio ({ratio_filter}) to sit "
        f"distinctly above tilly's pooled ratio across all five records ({ratio_all})"
    )


def test_usage_report_pin_flag_selects_only_that_pins_records(five_and_one_fixture_root):
    result = _run_brief_usage(five_and_one_fixture_root, extra_args=["--pin", "PIN-B"])
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "PIN-B" in combined
    assert re.search(r"\b1\b", combined), combined
    assert "PIN-A" not in combined.split("\n")[0]  # the covered-pin line names PIN-B, not PIN-A


def test_usage_report_refusals_only_reports_no_source_rows(tmp_path: Path):
    analyses_dir = tmp_path / "data" / "analyses"
    records = [
        _record(
            "R1",
            corpus_pin="PIN-A",
            filters_observed=[],
            sources=[],
            disposition="refuse",
        ),
        _record(
            "R2",
            corpus_pin="PIN-A",
            filters_observed=[],
            sources=[],
            disposition="refuse",
        ),
    ]
    _write_records(analyses_dir, records)

    result = _run_brief_usage(tmp_path)
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "no source rows" in combined.lower() or "(no source rows)" in combined


def test_usage_report_empty_analyses_dir_says_nothing_to_report(tmp_path: Path):
    result = _run_brief_usage(tmp_path)
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "no" in combined.lower() and "report on" in combined.lower()
