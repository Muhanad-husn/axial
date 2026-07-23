"""Outer acceptance test for issue #255, slice 01 of the
analysis-synthesis subproject (Phase B, sub:analysis-v0): evidence
assembly and `axial brief examine` -- inspect before spend.

Given a fixture vault and brief file config/briefs/dev/fixture-syria-displacement.yaml
  And AXIAL_LLM_PROVIDER=record so interrogation/retrieval are scripted and
      every prompt is logged to AXIAL_LLM_RECORD_PATH
  And the scripted retrieval loop returns a known evidence set of chunk ids
When  `axial brief examine config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command exits 0
  And stdout lists exactly the retrieved chunk_ids, in retrieval order
  And stdout reports corpus_chunk_count + evidence_chunk_count for every
      polity the evidence set touches
  And stdout reports the interrogation result's disposition/premises_found/
      bounds_applied
  And no file is written under data/analyses/

Given the same brief/vault
  And the client that answers interrogation/retrieval is wrapped so any
      call NOT identifiable as interrogation or retrieval (i.e. a would-be
      stage-4 synthesis call) raises and increments a counter
When  `axial brief examine`'s library entry point (`run_examine`) runs
Then  it completes without raising
  And the synthesis call count is 0

Given a brief whose scripted interrogation yields disposition "refuse" with
      a reason
When  `axial brief examine` runs on it
Then  the command exits 0
  And stdout states the refusal and its reason
  And exactly one LLM call was made (the interrogation call itself -- proof
      that no retrieval and no synthesis call followed the refusal)

See specs/PHASE-B.md §5 stage 4, §7.5 (the vault query API), §7.7 (the raw
per-polity coverage counts), §7.2 (the interrogation result), and §8
P0-4/P0-9 (inspect-before-spend) for the source of truth, and
plans/analysis-synthesis/01-evidence-assembly-and-examine.md for this
slice's own acceptance criterion (identical Gherkin).

Seam decisions
--------------
Scenario 1 and 3 run the CLI via subprocess with cwd set to an isolated
`tmp_path` staging root (mirroring tests/analysis/test_brief_interrogation.py's
seam decision 1) -- `data/vault/` and `data/analyses/` are plain paths
relative to the process cwd, and this test must never touch the real,
shared `data/` tree. The brief file itself is still
config/briefs/dev/fixture-syria-displacement.yaml, the real repo file named
by the acceptance criterion, passed by its absolute path so it resolves
regardless of the isolated cwd.

Scenario 2 uses the library entry point (`axial.analyze.examine.run_examine`)
directly, in-process, with a wrapping "poisoned synthesis" client -- the
plan's own documented alternative to `AXIAL_LLM_PROVIDER=explode` (which
poisons *every* call, useless here since interrogation and retrieval must
both succeed for `examine` to run at all). The wrapper answers exactly the
two pass_names `examine`'s own pipeline is allowed to call
(`INTERROGATE_PASS_NAME`, `RETRIEVE_PASS_NAME`) via a real `StubLLMClient`,
and raises -- incrementing `synthesis_call_count` -- on any other pass_name,
mechanically proving the "zero stage-4 synthesis calls" property rather
than merely asserting it in a comment.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.analyze.examine import run_examine
from axial.brief.intake import Brief
from axial.llm import (
    INTERROGATE_PASS_NAME,
    RETRIEVE_PASS_NAME,
    STUB_TOOL_CALLS_ENV_VAR,
    StubLLMClient,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_BRIEF_PATH = REPO_ROOT / "config" / "briefs" / "dev" / "fixture-syria-displacement.yaml"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"
STUB_INTERROGATE_RESPONSE_ENV_VAR = "AXIAL_STUB_INTERROGATE_RESPONSE"

SYRIA_A = "exfix_001_syria_a"
SYRIA_B = "exfix_002_syria_b"
SYRIA_C = "exfix_003_syria_c"  # never retrieved -- proves corpus != evidence count
IRAQ_A = "exfix_004_iraq"


def _chunk_frontmatter(*, chunk_id: str, polities_touched: list[str]) -> dict[str, Any]:
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
        "empirical_scope": {
            "value": "scope:country-case",
            "polity": polities_touched[0] if polities_touched else None,
        },
        "polities_touched": polities_touched,
        "artifact_refs": [],
    }


def _write_fixture_vault(root: Path) -> Path:
    """Four synthetic prose notes: three touch "Syria" (only two of them are
    ever retrieved, so corpus_chunk_count=3 must differ from
    evidence_chunk_count=2), one touches "Iraq" (retrieved, so its counts
    are equal)."""
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    notes = [
        _chunk_frontmatter(chunk_id=SYRIA_A, polities_touched=["Syria"]),
        _chunk_frontmatter(chunk_id=SYRIA_B, polities_touched=["Syria"]),
        _chunk_frontmatter(chunk_id=SYRIA_C, polities_touched=["Syria"]),
        _chunk_frontmatter(chunk_id=IRAQ_A, polities_touched=["Iraq"]),
    ]
    for frontmatter in notes:
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    return _write_fixture_vault(tmp_path)


def _run_examine_cli(
    root: Path,
    *,
    record_path: Path,
    stub_interrogate_response: dict[str, Any],
    stub_tool_calls: list[dict[str, Any] | None],
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "record"
    env[RECORD_PATH_ENV_VAR] = str(record_path)
    env[STUB_INTERROGATE_RESPONSE_ENV_VAR] = json.dumps(stub_interrogate_response)
    env[STUB_TOOL_CALLS_ENV_VAR] = json.dumps(stub_tool_calls)
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "axial",
            "brief",
            "examine",
            str(FIXTURE_BRIEF_PATH),
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
            "expected a real `brief examine` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `brief examine` "
            f"subcommand does not exist yet:\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


def _read_recorded_prompts(record_path: Path) -> list[str]:
    if not record_path.exists():
        return []
    return [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]


def test_examine_reports_evidence_coverage_and_interrogation_writes_nothing(
    fixture_root: Path,
):
    """Scenario 1 (issue #255): the retrieved chunk_ids print in retrieval
    order, the per-polity raw coverage counts are reported (corpus vs.
    evidence), the interrogation result's disposition/premises_found/
    bounds_applied are reported, and data/analyses/ stays untouched."""
    record_path = fixture_root / "record.jsonl"
    stub_interrogate_response = {
        "premises_found": [
            {
                "premise": "The brief assumes stable pre-war Syrian local authority.",
                "assessment": "supports",
            }
        ],
        "bounds_applied": [
            "Corpus covers Syria's civil-war-era displacement, not pre-2000 governance."
        ],
        "refusal": None,
    }
    # get_chunk calls returned in a deliberately non-alphabetical order --
    # B then A then Iraq -- so "retrieval order" is a real, checkable claim,
    # not an accidental sort. asfix/exfix_003 (Syria C) is never called.
    stub_tool_calls = [
        {"tool": "get_chunk", "args": {"chunk_id": SYRIA_B}},
        {"tool": "get_chunk", "args": {"chunk_id": SYRIA_A}},
        {"tool": "get_chunk", "args": {"chunk_id": IRAQ_A}},
        None,
    ]

    result = _run_examine_cli(
        fixture_root,
        record_path=record_path,
        stub_interrogate_response=stub_interrogate_response,
        stub_tool_calls=stub_tool_calls,
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    stdout = result.stdout

    assert "disposition: proceed_bounded" in stdout
    assert "premise (supports): The brief assumes stable pre-war Syrian local authority." in stdout
    assert (
        "bound: Corpus covers Syria's civil-war-era displacement, not pre-2000 governance."
        in stdout
    )

    # The retrieved chunk_ids, in exact retrieval order.
    retrieved_index = stdout.index("retrieved chunk_ids")
    coverage_index = stdout.index("polity coverage:")
    retrieved_block = stdout[retrieved_index:coverage_index]
    assert (
        retrieved_block.index(SYRIA_B)
        < retrieved_block.index(SYRIA_A)
        < retrieved_block.index(IRAQ_A)
    ), f"expected chunk_ids in retrieval order (B, A, Iraq) in:\n{retrieved_block!r}"
    assert SYRIA_C not in retrieved_block, (
        f"chunk {SYRIA_C!r} was never retrieved and must not appear, got:\n{retrieved_block!r}"
    )

    # Raw per-polity coverage: Syria's corpus count (3) must differ from its
    # evidence count (2, only A and B retrieved); Iraq's are equal (1 and 1).
    assert "Syria: corpus_chunk_count=3 evidence_chunk_count=2" in stdout, stdout
    assert "Iraq: corpus_chunk_count=1 evidence_chunk_count=1" in stdout, stdout

    analyses_dir = fixture_root / "data" / "analyses"
    assert not analyses_dir.exists() or not any(analyses_dir.iterdir()), (
        f"expected nothing written under data/analyses/, found: "
        f"{list(analyses_dir.iterdir()) if analyses_dir.exists() else 'n/a'}"
    )


def test_examine_makes_zero_stage_4_synthesis_calls(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 2 (issue #255): `run_examine` never makes a call outside
    the interrogate/retrieve pass_names -- mechanically asserted via a
    wrapping poison client's `synthesis_call_count`, not just claimed."""
    monkeypatch.setenv(
        STUB_INTERROGATE_RESPONSE_ENV_VAR,
        json.dumps({"premises_found": [], "bounds_applied": [], "refusal": None}),
    )
    monkeypatch.setenv(
        STUB_TOOL_CALLS_ENV_VAR,
        json.dumps([{"tool": "get_chunk", "args": {"chunk_id": SYRIA_A}}, None]),
    )

    class PoisonedSynthesisClient:
        """Answers exactly the two pass_names `examine` is allowed to call;
        any other call raises and is counted -- the seam the plan's own
        acceptance criterion names as the alternative to
        AXIAL_LLM_PROVIDER=explode (which would also poison the
        interrogation/retrieval calls `examine` legitimately needs)."""

        _ALLOWED = {INTERROGATE_PASS_NAME, RETRIEVE_PASS_NAME}

        def __init__(self) -> None:
            self._inner = StubLLMClient()
            self.synthesis_call_count = 0

        def _guard(self, pass_name: str | None) -> None:
            if pass_name not in self._ALLOWED:
                self.synthesis_call_count += 1
                raise RuntimeError(
                    f"unexpected LLM call with pass_name={pass_name!r}: examine must "
                    "make ZERO stage-4 synthesis calls"
                )

        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            self._guard(pass_name)
            return self._inner.complete(prompt, pass_name=pass_name)

        def complete_with_tools(
            self, prompt: str, tools: list[dict[str, Any]], pass_name: str | None = None
        ) -> dict[str, Any] | None:
            self._guard(pass_name)
            return self._inner.complete_with_tools(prompt, tools, pass_name=pass_name)

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return self._inner.model_for_pass(pass_name)

    client = PoisonedSynthesisClient()
    brief = Brief(
        brief_id="test-examine-brief",
        case="Syria",
        request="How did displacement reshape local authority?",
        lens=None,
    )
    vault_dir = fixture_root / "data" / "vault"

    result = run_examine(client=client, brief=brief, vault_dir=vault_dir)

    assert client.synthesis_call_count == 0
    assert SYRIA_A in result.evidence.chunk_ids


def test_examine_on_refuse_disposition_exits_0_and_prints_the_refusal(fixture_root: Path):
    """Scenario 3 (issue #255): a `refuse` disposition still exits 0
    (§7.2: a completed run, not an error), prints the refusal and its
    reason, and exactly one LLM call is made in the whole run -- the
    interrogation call itself, proving no retrieval and no synthesis call
    ever followed the refusal."""
    record_path = fixture_root / "record.jsonl"
    stub_interrogate_response = {
        "premises_found": [],
        "bounds_applied": [],
        "refusal": {"reason": "the corpus holds no coverage for the polity this brief depends on"},
    }

    result = _run_examine_cli(
        fixture_root,
        record_path=record_path,
        stub_interrogate_response=stub_interrogate_response,
        stub_tool_calls=[],
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0 on a refuse disposition, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    assert "disposition: refuse" in result.stdout
    assert (
        "refusal: the corpus holds no coverage for the polity this brief depends on"
        in result.stdout
    )

    prompts = _read_recorded_prompts(record_path)
    assert len(prompts) == 1, (
        f"expected exactly one recorded LLM call (interrogation only -- no "
        f"retrieval, no synthesis call), got {len(prompts)}: {prompts!r}"
    )
