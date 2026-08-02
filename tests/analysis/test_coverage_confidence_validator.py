"""Outer acceptance test for the per-name coverage map and its release gate
(issues #260 and #490, Phase B, sub:analysis-v0).

Given a fixture vault whose name page for "Charles Tilly" carries
      member_count 240 and whose page for "Asef Bayat" carries 6
  And an analysis record at data/analyses/DEV25.json whose claims touch both
      and whose trajectory retrieved on both
  And config coverage_bands of {thin: <20, moderate: 20-99, dense: >=100}
When  `axial brief coverage DEV25` runs
Then  the map is computed for real from the name layer: Tilly is `dense` with
      corpus_note_count 240, Bayat is `thin` with corpus_note_count 6, each
      alongside its evidence_note_count
  And zero LLM calls were made building it (the `explode` provider never
      fires)

Given an analysis record at data/analyses/DEV20.json disclosing that same map
When  `axial brief validate DEV20` runs
Then  the command exits 0 and no `high` band accompanies the `thin` entry

Given an analysis record at data/analyses/DEV21.json whose claims touch a
      name the run retrieved on
  And whose coverage_map has no entry for it
When  `axial brief validate DEV21` runs
Then  the command exits non-zero, the report reason is
      "missing_coverage_entry" naming it, and no answer is released

Given an analysis record at data/analyses/DEV22.json with a complete
      coverage_map
  And whose confidence is {overall_band: null, rationale: ""}
When  `axial brief validate DEV22` runs
Then  the command exits non-zero with reason "missing_confidence_disclosure"

Given an analysis record at data/analyses/DEV23.json whose coverage_map
      contains a "thin" name and whose confidence.overall_band is the top
      band
When  `axial brief validate DEV23` runs
Then  the command exits non-zero with reason "confidence_exceeds_coverage"
      naming the thin name

See specs/PHASE-B.md §7.7 (the per-name coverage map) and §7.9 (the
validators) for the source of truth.

Seam decisions
--------------
Runs the CLI via subprocess with cwd set to an isolated `tmp_path` staging
root, mirroring tests/analysis/test_attribution_validator.py exactly (both
`axial brief validate` and `axial brief coverage` read an already-persisted
record; neither loads or re-interrogates a brief).

The four `brief validate` scenarios use `kind: "c"` claims with empty
grounds: those checks read only the record's own `claims`/`trajectory` and
its persisted `coverage_map`/`confidence`, isolating each scenario's
assertion to the reason under test. The `brief coverage` scenario is the
opposite by design -- it computes the map for real, so it needs real name
pages and real grounds.

`AXIAL_LLM_PROVIDER=explode` is the DEFAULT for every scenario here: the
coverage/confidence validator takes no LLM client at all and
`compute_coverage_map` is model-free by construction (`_brief_coverage`
never even constructs a client), so a real poison-client crash would
surface immediately if anything on that path ever attempted a model call.

**The four `brief validate` scenarios override that default (issue #589).**
A kind-"c" claim now reaches the attribution validator's bounded
(b)/(c)-seam check (specs/PHASE-B.md §7.9), which needs a real, callable
client under `pass_name`s that resolve to two DIFFERENT models -- the
`explode` provider answers the same fixed "explode" id for every pass, so
constructing a record this way would trip the same-model guard before the
coverage/confidence assertion under test ever ran. These four scenarios use
`AXIAL_LLM_PROVIDER=stub` with `AXIAL_STUB_MODEL_BY_PASS` mapping the
synthesis and attribution passes to different ids (mirroring
`test_attribution_validator.py`'s own DEV01 pattern): the canned stub
response flags nothing, so the (c)-seam check passes silently and each
scenario's assertion still isolates the coverage/confidence reason under
test. `brief coverage` (DEV25/DEV26) never calls `validate_attribution` at
all, so it keeps the `explode` default unmodified.
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

# issue #589: the four `brief validate` scenarios below use this to resolve
# the synthesis and attribution passes to different models under the `stub`
# provider, satisfying the (b)/(c)-seam check's same-model guard so the
# canned (nothing-flagged) response is what actually runs.
DISTINCT_MODELS_ENV_VALUE = json.dumps({"synthesize": "model-a", "attribution": "model-b"})

TILLY = "Charles Tilly"
BAYAT = "Asef Bayat"

TILLY_CHUNK = "tilly-1978_001_intro_001"
BAYAT_CHUNK = "bayat-2017_001_intro_001"


def _speculative_claim(claim_id: str, *, names_touched: list[str]) -> dict[str, Any]:
    """A minimally-shaped §7.4 claim: kind "c" (speculation) carries no
    grounds requirement, so these fixtures need no fixture vault at all --
    only `names_touched` (half the coverage scope's own input) and the
    fields the attribution validator's mechanical checks read."""
    return {
        "claim_id": claim_id,
        "text": f"Speculative claim text for {claim_id}.",
        "kind": "c",
        "grounds": [],
        "confidence": "medium",
        "names_touched": names_touched,
    }


def _grounded_claim(
    claim_id: str, *, names_touched: list[str], chunk_ids: list[str]
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": f"Grounded claim text for {claim_id}.",
        "kind": "a",
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids],
        "confidence": "medium",
        "names_touched": names_touched,
    }


def _retrieved(*canonicals: str) -> list[dict[str, Any]]:
    """A §7.6 trajectory that retrieved on each name -- the other half of the
    §7.7 scope. Without it the map covers nothing, which is the honest
    outcome for a run that never resolved a name at all."""
    return [
        {
            "step": index,
            "tool": "get_name",
            "args": {"canonical": canonical},
            "result_ids": [],
            "result_count": 0,
        }
        for index, canonical in enumerate(canonicals, start=1)
    ]


def _write_record(
    root: Path,
    brief_id: str,
    *,
    claims: list[dict[str, Any]],
    coverage_map: dict[str, Any],
    confidence: dict[str, Any],
    trajectory: list[dict[str, Any]] | None = None,
) -> Path:
    analyses_dir = root / "data" / "analyses"
    analyses_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "brief_id": brief_id,
        "brief": {"brief_id": brief_id, "case": "Syria", "request": "A request.", "lens": None},
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
        "coverage_map": coverage_map,
        "confidence": confidence,
        "trajectory": trajectory or [],
        "model_by_pass": {},
    }
    path = analyses_dir / f"{brief_id}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


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


def _write_name_page(root: Path, name: str, *, member_ids: list[str], member_count: int) -> None:
    """A name page as Materialize writes one (§7.17): `member_count` is the
    §7.7 denominator, and the member list is what `evidence_note_count`
    intersects this run's grounds with. The two differ here exactly as they
    do on the real corpus, where a dense name's page holds far more members
    than any one run cites."""
    names_dir = root / "data" / "vault" / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {"name": name, "kind": "person", "aliases": [], "member_count": member_count}
    lines = ["**Member notes:**"]
    lines += [f"- [[{chunk_id}]] — An Author (1978): A claim." for chunk_id in member_ids]
    body = yaml.safe_dump(frontmatter, sort_keys=False)
    (names_dir / f"{name}.md").write_text(
        "---\n" + body + "---\n" + "\n".join(lines) + "\n", encoding="utf-8"
    )


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    _write_chunk(tmp_path, TILLY_CHUNK)
    _write_chunk(tmp_path, BAYAT_CHUNK)
    _write_name_page(tmp_path, TILLY, member_ids=[TILLY_CHUNK], member_count=240)
    _write_name_page(tmp_path, BAYAT, member_ids=[BAYAT_CHUNK], member_count=6)
    return tmp_path


def _run_cli(
    root: Path, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """Defaults to `AXIAL_LLM_PROVIDER=explode`: `brief coverage` never
    constructs an LLM client at all, and `compute_coverage_map` is
    model-free by construction -- a real model call anywhere on that path
    would crash the process instead of passing quietly. `extra_env`
    overrides this default (issue #589: the `brief validate` scenarios need
    a real, distinctly-modelled `stub` client, since a kind-"c" claim now
    reaches the (b)/(c)-seam check, which `explode`'s single fixed model id
    cannot satisfy)."""
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", "brief", *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ("invalid choice", "unrecognized arguments"):
        assert marker not in combined, (
            "expected a real behavior path, not an argparse fallback "
            f"(found {marker!r}):\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


_DENSE_MAP = {
    TILLY: {"corpus_note_count": 240, "evidence_note_count": 1, "coverage_band": "dense"},
    BAYAT: {"corpus_note_count": 6, "evidence_note_count": 1, "coverage_band": "thin"},
}


def test_the_map_is_computed_for_real_and_a_thin_name_is_disclosed_thin(vault_root: Path):
    """The headline of #490: `coverage_count` returned 0 entries against the
    v1 vault, so the map was empty on every run. Here it is computed from the
    live name layer, and the thinly-covered name the claims touch is
    disclosed as thin, with the counts that justify the band beside it
    (§7.4/§7.10: a band is never rendered bare)."""
    _write_record(
        vault_root,
        "DEV25",
        claims=[
            _grounded_claim(
                "c-1", names_touched=[TILLY, BAYAT], chunk_ids=[TILLY_CHUNK, BAYAT_CHUNK]
            )
        ],
        coverage_map={},
        confidence={"overall_band": "low", "rationale": "recomputed by this command"},
        trajectory=_retrieved(TILLY, BAYAT),
    )

    result = _run_cli(vault_root, "coverage", "DEV25")

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    lines = {
        line.strip().split(":", 1)[0]: line.strip()
        for line in result.stdout.splitlines()
        if ":" in line
    }
    assert TILLY in lines, result.stdout
    assert "corpus_note_count=240" in lines[TILLY]
    assert "evidence_note_count=1" in lines[TILLY]
    assert "coverage_band='dense'" in lines[TILLY]

    assert BAYAT in lines, result.stdout
    assert "corpus_note_count=6" in lines[BAYAT]
    assert "coverage_band='thin'" in lines[BAYAT]


def test_a_name_the_run_never_retrieved_on_stays_out_of_the_computed_map(vault_root: Path):
    """Measured on the real corpus: a 24-note evidence set's grounds notes
    name 423 distinct canonicals on average, so keying the map on
    `names_touched` alone makes it several hundred rows and pins overall
    confidence to `low` on every brief."""
    _write_record(
        vault_root,
        "DEV26",
        claims=[
            _grounded_claim(
                "c-1", names_touched=[TILLY, BAYAT], chunk_ids=[TILLY_CHUNK, BAYAT_CHUNK]
            )
        ],
        coverage_map={},
        confidence={"overall_band": "low", "rationale": "recomputed by this command"},
        trajectory=_retrieved(TILLY),
    )

    result = _run_cli(vault_root, "coverage", "DEV26")

    assert result.returncode == 0, result.stderr
    assert TILLY in result.stdout
    assert BAYAT not in result.stdout


def test_scenario1_complete_map_and_valid_confidence_passes(fixture_root: Path):
    """DEV20: both names in scope have a complete entry, confidence is
    disclosed with a non-empty rationale, and confidence is not the top band
    -- exit 0. Runs under `stub` with distinct per-pass models (issue #589:
    the kind-"c" claim now reaches the (c)-seam check, whose canned reply
    flags nothing) rather than `explode`."""
    _write_record(
        fixture_root,
        "DEV20",
        claims=[_speculative_claim("c-1", names_touched=[TILLY, BAYAT])],
        coverage_map=_DENSE_MAP,
        confidence={
            "overall_band": "low",
            "rationale": f"{TILLY} (dense: 240 corpus notes); {BAYAT} (thin: 6 corpus notes)",
        },
        trajectory=_retrieved(TILLY, BAYAT),
    )

    result = _run_cli(
        fixture_root,
        "validate",
        "DEV20",
        extra_env={
            PROVIDER_ENV_VAR: "stub",
            STUB_MODEL_BY_PASS_ENV_VAR: DISTINCT_MODELS_ENV_VALUE,
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "PASS" in result.stdout
    assert "dense" in result.stdout
    assert "thin" in result.stdout
    assert "240" in result.stdout
    assert "6" in result.stdout


def test_scenario2_missing_coverage_entry_blocks_release(fixture_root: Path):
    """DEV21: the claims touch a name the run retrieved on, but coverage_map
    carries no entry for it -- exit non-zero, reason
    "missing_coverage_entry" naming it, no file written."""
    _write_record(
        fixture_root,
        "DEV21",
        claims=[_speculative_claim("c-1", names_touched=[BAYAT])],
        coverage_map={},
        confidence={"overall_band": "medium", "rationale": "no coverage entry was computed"},
        trajectory=_retrieved(BAYAT),
    )
    analyses_dir = fixture_root / "data" / "analyses"
    before = set(analyses_dir.iterdir())

    result = _run_cli(
        fixture_root,
        "validate",
        "DEV21",
        extra_env={
            PROVIDER_ENV_VAR: "stub",
            STUB_MODEL_BY_PASS_ENV_VAR: DISTINCT_MODELS_ENV_VALUE,
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"
    assert "missing_coverage_entry" in result.stdout
    assert BAYAT in result.stdout

    after = set(analyses_dir.iterdir())
    assert after == before, "the validator must never write/edit any file -- no answer released"


def test_scenario3_missing_confidence_disclosure_blocks_release(fixture_root: Path):
    """DEV22: a complete coverage_map, but confidence is
    `{overall_band: null, rationale: ""}` -- exit non-zero, reason
    "missing_confidence_disclosure"."""
    _write_record(
        fixture_root,
        "DEV22",
        claims=[_speculative_claim("c-1", names_touched=[TILLY])],
        coverage_map={
            TILLY: {"corpus_note_count": 240, "evidence_note_count": 1, "coverage_band": "dense"}
        },
        confidence={"overall_band": None, "rationale": ""},
        trajectory=_retrieved(TILLY),
    )

    result = _run_cli(
        fixture_root,
        "validate",
        "DEV22",
        extra_env={
            PROVIDER_ENV_VAR: "stub",
            STUB_MODEL_BY_PASS_ENV_VAR: DISTINCT_MODELS_ENV_VALUE,
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"
    assert "missing_confidence_disclosure" in result.stdout


def test_scenario4_confidence_exceeds_coverage_blocks_release(fixture_root: Path):
    """DEV23: coverage_map contains a `thin` name while
    confidence.overall_band is the top band -- exit non-zero, reason
    "confidence_exceeds_coverage" naming the thin name. This is the
    acceptance bar's "no `high` band accompanies a `thin` entry", enforced
    at release rather than trusted."""
    _write_record(
        fixture_root,
        "DEV23",
        claims=[_speculative_claim("c-1", names_touched=[TILLY, BAYAT])],
        coverage_map=_DENSE_MAP,
        confidence={
            "overall_band": "high",
            "rationale": f"{TILLY} 240 corpus notes; {BAYAT} 6 corpus notes.",
        },
        trajectory=_retrieved(TILLY, BAYAT),
    )

    result = _run_cli(
        fixture_root,
        "validate",
        "DEV23",
        extra_env={
            PROVIDER_ENV_VAR: "stub",
            STUB_MODEL_BY_PASS_ENV_VAR: DISTINCT_MODELS_ENV_VALUE,
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"
    assert "confidence_exceeds_coverage" in result.stdout
    assert BAYAT in result.stdout


def test_refuse_disposition_empty_claims_passes_vacuously(fixture_root: Path):
    """§7.2: a `refuse` disposition carries an empty `claims` list -- the
    coverage-entry check passes vacuously (nothing in scope); confidence is
    still required and disclosed here, so the whole command exits 0."""
    _write_record(
        fixture_root,
        "DEV24",
        claims=[],
        coverage_map={},
        confidence={"overall_band": "low", "rationale": "refused; no synthesis was attempted"},
    )

    result = _run_cli(fixture_root, "validate", "DEV24")

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0 on an empty claim list, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "PASS" in result.stdout
