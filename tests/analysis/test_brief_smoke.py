"""Outer acceptance test for issue #491 Part 2 (Phase B v1, slice 06):
`axial brief smoke`, the five-brief smoke set behind mechanical checks and a
cost and latency budget (specs/PHASE-B.md §9.0, §8 P0-11).

Given a fixture vault with a name page and a name layer that resolves it
  And a directory of two fixture smoke briefs
When  `axial brief smoke --briefs-dir <dir> --sweep-dir out` runs
Then  the command exits 0
  And one analysis record and one run report exist per brief
  And every mechanical check passes
  And the output states plainly that the cost and latency budgets are
      UNMEASURED and their checks were skipped -- never that they passed
  And NO rung-3 gate was scored: no gate report is written anywhere

Given the same briefs over a vault whose name layer is absent, so no claim
      resolves a name and the coverage map comes back empty
When  the same command runs
Then  the command exits NON-ZERO, naming the empty coverage map -- the #490
      regression this check exists to make loud

Given the smoke set is `config/briefs/smoke/`
Then  it holds exactly the five briefs §9.0 names, each loadable under the
      §7.1 brief contract, and each with a case file under `evals/cases/sim/`

See specs/PHASE-B.md §9.0 (the two brief sets), §7.15 (the report the budgets
read) and issue #491 for the five checks.

Seam decisions
--------------
Drives the real CLI as a subprocess from an isolated `tmp_path` staging root
with `AXIAL_LLM_PROVIDER=stub`, mirroring tests/analysis/test_brief_sweep.py's
own seam. Two fixture briefs rather than the real five: the checks are
per-brief and identical, the five real briefs need the real corpus to say
anything, and the founder runs those separately. The last scenario asserts on
the committed set itself, with no run at all.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_LENSES_DIR = REPO_ROOT / "config" / "lenses"
SMOKE_DIR = REPO_ROOT / "config" / "briefs" / "smoke"
CASES_DIR = REPO_ROOT / "evals" / "cases" / "sim"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
STUB_TOOL_CALLS_ENV_VAR = "AXIAL_STUB_TOOL_CALLS"
STUB_SYNTHESIZE_RESPONSE_ENV_VAR = "AXIAL_STUB_SYNTHESIZE_RESPONSE"
STUB_INTERROGATE_RESPONSE_ENV_VAR = "AXIAL_STUB_INTERROGATE_RESPONSE"

TILLY = "Charles Tilly"
TILLY_CHUNK = "tilly-1978_001_intro_001"

# The set was rebuilt 2026-07-30 (§9.0): five Syria briefs out, five
# measured-anchor briefs in, P3-04 retained as the one hub anchor §7.13's
# denominator inspection needs.
EXPECTED_SMOKE_BRIEFS = ("P3-04", "S-01", "S-02", "S-03", "S-04", "S-05")


def _write_chunk(root: Path) -> None:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": TILLY_CHUNK,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{TILLY_CHUNK}: synthetic prose.",
        "source_meta": {"author": "A", "title": "T", "date": 2020, "thesis": "X", "scope": "Y"},
        "schema_version": "0.1",
        "frame_version": "0.1",
        "answers": {
            "claim": "A claim about organization.",
            "position_of": "the author",
            "names": [TILLY],
        },
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{TILLY_CHUNK}.md").write_text(text, encoding="utf-8")


def _write_name_page(root: Path) -> None:
    names_dir = root / "data" / "vault" / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {"name": TILLY, "kind": "person", "aliases": [], "member_count": 1}
    body = yaml.safe_dump(frontmatter, sort_keys=False)
    (names_dir / f"{TILLY}.md").write_text(
        "---\n"
        + body
        + "---\n**Member notes:**\n"
        + f"- [[{TILLY_CHUNK}]] — An Author (1978): A claim.\n",
        encoding="utf-8",
    )


def _write_name_layer(root: Path) -> None:
    """The alias-map/index pair `names_touched` resolves surface forms
    through (§7.4). Without it no surface resolves, so no claim touches a
    name and the coverage map is empty -- which is exactly scenario 2."""
    names_dir = root / "data" / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    (names_dir / "index.json").write_text(json.dumps({"names": [TILLY]}), encoding="utf-8")


def _write_pin(root: Path) -> None:
    evals_dir = root / "evals" / "corpus_pin"
    evals_dir.mkdir(parents=True, exist_ok=True)
    (evals_dir / "baseline.json").write_text(
        json.dumps({"sources": [], "ingest_code_sha": "deadbeef", "vault_snapshot_hash": "abc"}),
        encoding="utf-8",
    )


def _write_briefs(root: Path) -> Path:
    briefs_dir = root / "config" / "briefs" / "smokefixture"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    for stem, request in (
        ("SMOKE-01", "Does organization convert a revolutionary situation?"),
        ("SMOKE-02", "What does accumulated resource endowment explain?"),
    ):
        (briefs_dir / f"{stem}.yaml").write_text(
            yaml.safe_dump({"case": "Syria, 2011-2024", "request": request}, sort_keys=False),
            encoding="utf-8",
        )
    # A README alongside the briefs must not be swept as one.
    (briefs_dir / "README.md").write_text("not a brief\n", encoding="utf-8")
    return briefs_dir


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_chunk(tmp_path)
    _write_name_page(tmp_path)
    _write_pin(tmp_path)
    shutil.copytree(REPO_LENSES_DIR, tmp_path / "config" / "lenses")
    return tmp_path


def _run_smoke_cli(root: Path, briefs_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "stub"
    env[STUB_INTERROGATE_RESPONSE_ENV_VAR] = json.dumps(
        {"premises_found": [], "bounds_applied": [], "refusal": None}
    )
    env[STUB_TOOL_CALLS_ENV_VAR] = json.dumps(
        [{"tool": "get_name", "args": {"canonical": TILLY}}, None]
    )
    env[STUB_SYNTHESIZE_RESPONSE_ENV_VAR] = json.dumps(
        {
            "claims": [
                {
                    "text": "A claim grounded in the corpus.",
                    "kind": "a",
                    "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                    "confidence": "medium",
                }
            ]
        }
    )
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "axial",
            "brief",
            "smoke",
            "--briefs-dir",
            str(briefs_dir),
            "--sweep-dir",
            "smoke_out",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def test_smoke_passes_and_states_its_budgets_are_unmeasured(fixture_root: Path):
    _write_name_layer(fixture_root)
    briefs_dir = _write_briefs(fixture_root)

    result = _run_smoke_cli(fixture_root, briefs_dir)

    combined = result.stdout + result.stderr
    for marker in ("invalid choice", "unrecognized arguments"):
        assert marker not in combined, f"argparse fallback, not a real path: {combined!r}"
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    sweep_dir = fixture_root / "smoke_out"
    records = sorted(sweep_dir.glob("analyses/*/draw0/*.json"))
    reports = sorted(sweep_dir.glob("analyses/*/draw0/runs/*.json"))
    assert len(records) == 2, records
    assert len(reports) == 2, reports

    assert "FAIL" not in result.stdout, result.stdout
    assert "smoke: PASS" in result.stdout

    # The budgets are unset, so their checks are SKIPPED and said to be
    # unmeasured -- never reported as passed.
    assert "UNMEASURED" in result.stdout
    assert "SKIP cost_budget" in result.stdout
    assert "SKIP latency_budget" in result.stdout

    # Gate scoring is off: no rung-3 gate report exists anywhere.
    assert not list(sweep_dir.glob("analyses/*/gates/*.json"))

    # The names each run queried are printed, so a nearest-neighbour
    # substitution (the P4-04 fragmentation read) is visible by eye.
    assert f"get_name:{TILLY}" in result.stdout


def test_smoke_exits_non_zero_when_the_coverage_map_regresses_to_empty(fixture_root: Path):
    """The #490 regression must be loud: with no name layer, no claim
    resolves a name, so the map is empty on a `proceed` run."""
    briefs_dir = _write_briefs(fixture_root)

    result = _run_smoke_cli(fixture_root, briefs_dir)

    assert result.returncode == 1, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    assert "smoke: FAIL" in result.stdout
    assert "coverage_map_non_empty" in result.stdout
    assert "#490" in result.stdout


def test_the_committed_smoke_set_is_the_five_briefs_with_their_case_files():
    """§9.0/D7: five real files, not a manifest over the sim pool, each
    loadable under §7.1 and each with a case file so the mechanical
    retrieval-hit oracle is available. Issue #564 re-authored the five S-0N
    cases onto `required_citation_legs`; P3-04 is untouched and still states
    the older flat `required_citation_source_ids` (issue #560's back-compat
    path), so each stem is asserted on its own committed oracle shape rather
    than a single field name that not every case states."""
    from axial.brief.intake import load_brief

    stems = sorted(path.stem for path in SMOKE_DIR.glob("*.yaml"))
    assert stems == sorted(EXPECTED_SMOKE_BRIEFS)

    for stem in stems:
        brief = load_brief(SMOKE_DIR / f"{stem}.yaml")
        assert brief.case and brief.request
        case_path = CASES_DIR / f"{stem}.json"
        assert case_path.is_file(), f"{stem} has no case file at {case_path}"
        case: dict[str, Any] = json.loads(case_path.read_text(encoding="utf-8"))
        if stem.startswith("S-"):
            legs = case["required_citation_legs"]
            assert legs, stem
            for leg in legs:
                assert leg["any_of"], (stem, leg.get("leg"))
        else:
            assert case["required_citation_source_ids"]
        assert case["instant_dismissal_criteria"]
