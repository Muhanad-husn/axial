"""Outer acceptance test for issue #252, slice 01
(interrogation-pass-and-disposition).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fixture vault whose chunks give polity "Tunisia" a coverage_count of
      0, and a brief file with case "Syria" and a request whose premise
      asserts that Tunisia's transition followed the same sequence as
      Syria's, and `AXIAL_LLM_PROVIDER=record` with a canned interrogation
      response marking that premise's assessment "contradicts"
When  `axial brief interrogate <brief_file>` runs
Then  the emitted interrogation result has `premises_found` containing an
      entry whose `premise` names the Tunisian-transition premise and whose
      `assessment` is "contradicts"
  And `disposition` is one of "refuse" or "proceed_bounded" -- never "proceed"
  And the recorded prompt at AXIAL_LLM_RECORD_PATH contains the exact
      coverage counts read from the vault query API (the corpus's one real
      polity entry only -- never a synthesized row for the brief's own case)
  And the command exits 0

Given the same brief and a canned response carrying a non-null `refusal`
When  it runs
Then  `disposition` is exactly "refuse", the result is persisted, zero
      synthesis calls are made, exit code 0

Given a canned response with empty `premises_found`, empty `bounds_applied`
      and a null `refusal`, but which nonetheless emits `disposition:
      "refuse"`
When  it runs
Then  `disposition` is "proceed" (the wrapper decides, the model does not)

See specs/PHASE-B.md §7.2 (the interrogation result, [FIRM]:
`{premises_found[], bounds_applied[], refusal, disposition}`, disposition
"set by the deterministic wrapper from the fields above") and §7.5
(`coverage_count`, the vault query API) for the source of truth. See issue
#252 for this slice's own acceptance criterion (identical Gherkin).

Seam decision 1 -- isolated cwd, mirroring tests/analysis/test_corpus_pin.py
-----------------------------------------------------------------------
Per tests/conftest.py's `isolated_vault_root` docstring, no directory this
codebase resolves ever reads an env-var override, and the CLI exposes no
`--vault-dir`/`--analyses-dir` flag: `data/vault/` and `data/analyses/` are
plain paths relative to the process's current working directory. This test
runs the CLI with `cwd` set to a private `tmp_path` staging root -- never
the real, shared `data/` tree -- via `uv run --project <repo>` (required,
not bare `uv run`, since the subprocess's cwd is deliberately not the repo
checkout).

Seam decision 2 -- the fixture vault proves absence-means-absence directly,
and the coverage assertion checks the EXACT rendered lines, not a loose
substring
-----------------------------------------------------------------------
The fixture vault carries exactly one prose note, whose `polities_touched`
names "Freedonia" only. Per axial.query.reader.coverage_count's own
documented contract, a polity no chunk touches is simply absent from its
result -- so this vault's real `coverage_count()` is exactly
`{"Freedonia": 1}`; "Syria" (the brief's own `case`) and "Tunisia" are both
absent from it.

`axial.brief.interrogate.render_coverage_section` renders ONLY what
`coverage_count()` itself names (here, exactly "Freedonia: 1 chunks") --
nothing is synthesized for the brief's own `case`. An earlier version
also injected a row for the brief's raw `case` string, explicit-zero when
the corpus was silent on it; that was dropped (root-caused 2026-07-23)
because a real `case` almost always bundles a place with a date range the
coverage table has no way to speak to, so the fabricated zero-row fired as
a false "the corpus has never heard of this place" signal on nearly every
real brief, not a rare true one. This test asserts the EXACT rendered
coverage line for the corpus's one real polity, and asserts NEITHER
"Syria: ..." NOR "Tunisia: ..." appears as a coverage-table line -- a
regression back to a fabricated/mis-keyed row for either would fail it.
"Syria" and "Tunisia" may still appear inside the case/request's own
verbatim free text, which the recorded prompt is asserted NOT to mistake
for a coverage line.

Seam decision 3 -- the `record` provider observes the assembled prompt
-----------------------------------------------------------------------
`AXIAL_LLM_PROVIDER=record` (`RecordLLMClient`, src/axial/llm.py) answers
exactly like `stub` (dispatched by `pass_name`) but also appends every raw
prompt it receives to `AXIAL_LLM_RECORD_PATH`, one JSON-encoded line per
call -- the established, already-locked mechanism this whole codebase uses
to observe an assembled prompt black-box from a subprocess test (see
tests/ingestion/test_envelope_structural_grounding.py's module docstring,
seam decision 1). The canned interrogation response itself is driven by
`AXIAL_STUB_INTERROGATE_RESPONSE` (issue #252's own seam, mirroring
`AXIAL_STUB_TAG_RESPONSE` exactly): `record` delegates to the very same
canned-response dispatch `stub` uses, so this one seam drives both.
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
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"
STUB_INTERROGATE_RESPONSE_ENV_VAR = "AXIAL_STUB_INTERROGATE_RESPONSE"

CASE = "Syria"
REQUEST = "Does Tunisia's transition follow the same broad sequence as Syria's?"
TUNISIA_PREMISE_TEXT = (
    "The brief assumes Tunisia's transition followed the same sequence as Syria's."
)


def _write_fixture_vault(root: Path) -> None:
    """One synthetic prose note whose `polities_touched` names "Freedonia"
    only -- "Tunisia" (and "Syria") are absent from every chunk, so
    `coverage_count()` never carries them as keys (seam decision 2)."""
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter: dict[str, Any] = {
        "chunk_id": "bifix_001_intro",
        "section": "Synthetic Section",
        "chunk_text": "SENTINEL_BIFIX_001: synthetic prose about Freedonian institutions.",
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
        "empirical_scope": {"value": "scope:country-case", "polity": "Freedonia"},
        "polities_touched": ["Freedonia"],
        "artifact_refs": [],
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / "bifix_001_intro.md").write_text(text, encoding="utf-8")


def _write_brief(root: Path) -> Path:
    briefs_dir = root / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    path = briefs_dir / "tunisia-premise.yaml"
    body = yaml.safe_dump({"case": CASE, "request": REQUEST}, sort_keys=False)
    path.write_text(body, encoding="utf-8")
    return path


def _run_interrogate(
    root: Path,
    brief_path: Path,
    *,
    record_path: Path,
    stub_response: dict[str, Any],
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "record"
    env[RECORD_PATH_ENV_VAR] = str(record_path)
    env[STUB_INTERROGATE_RESPONSE_ENV_VAR] = json.dumps(stub_response)
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "axial",
            "brief",
            "interrogate",
            str(brief_path),
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
            "expected a real `brief interrogate` behavior path, not an "
            f"argparse fallback (found {marker!r}) -- this means the "
            "`brief interrogate` subcommand does not exist yet:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _read_recorded_prompts(record_path: Path) -> list[str]:
    if not record_path.exists():
        return []
    prompts = []
    for line in record_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        prompts.append(json.loads(line))
    return prompts


def _brief_id_from_output(result: subprocess.CompletedProcess) -> str:
    combined = result.stdout + result.stderr
    for line in combined.splitlines():
        if line.strip().lower().startswith("brief_id:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"expected a 'brief_id: <id>' line in output, got:\n{combined!r}")


def _load_persisted_interrogation(root: Path, brief_id: str) -> dict[str, Any]:
    path = root / "data" / "analyses" / f"{brief_id}.json"
    assert path.is_file(), (
        f"expected a persisted interrogation result at {path}, but it does not "
        "exist -- disposition refuse is a COMPLETED run and must still persist "
        "the result (§7.2)"
    )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_fixture_vault(tmp_path)
    return tmp_path


def test_contradicted_premise_never_proceeds_clean_and_carries_real_coverage(
    fixture_root: Path,
):
    """Scenario 1 (issue #252, regression-updated for the fabricated-
    case-row fix): a premise the corpus's real coverage contradicts is
    named in the persisted result, the disposition is never a confident
    "proceed", and the recorded prompt carries the real coverage counts
    `coverage_count()` returned (not model recall, and not a synthesized
    row for the brief's own case)."""
    brief_path = _write_brief(fixture_root)
    record_path = fixture_root / "record.jsonl"

    stub_response = {
        "premises_found": [{"premise": TUNISIA_PREMISE_TEXT, "assessment": "contradicts"}],
        "bounds_applied": [],
        "refusal": None,
    }

    result = _run_interrogate(
        fixture_root, brief_path, record_path=record_path, stub_response=stub_response
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    brief_id = _brief_id_from_output(result)
    persisted = _load_persisted_interrogation(fixture_root, brief_id)
    interrogation = persisted["interrogation"]

    premise_texts = {p["premise"]: p["assessment"] for p in interrogation["premises_found"]}
    assert TUNISIA_PREMISE_TEXT in premise_texts, (
        f"expected the Tunisian-transition premise to be named in "
        f"premises_found, got: {interrogation['premises_found']!r}"
    )
    assert premise_texts[TUNISIA_PREMISE_TEXT] == "contradicts"

    assert interrogation["disposition"] in {"refuse", "proceed_bounded"}, (
        "a premise the corpus contradicts must never come back as a "
        f"confident 'proceed', got disposition={interrogation['disposition']!r}"
    )
    assert interrogation["disposition"] != "proceed"

    prompts = _read_recorded_prompts(record_path)
    assert prompts, f"expected at least one recorded prompt at {record_path}"
    combined_prompt_text = "\n".join(prompts)

    # The EXACT rendered coverage line for the corpus's one real polity
    # entry -- proof that a genuine axial.query.reader.coverage_count()
    # value (not a fabricated or free-text-guessed one) reached the prompt.
    assert "Freedonia: 1 chunks" in combined_prompt_text, (
        "expected the recorded prompt to carry coverage_count()'s own real "
        f"entry (Freedonia: 1, the fixture vault's one real chunk), got:\n"
        f"{combined_prompt_text!r}"
    )
    # The brief's own `case` ("Syria") is absent from this fixture's real
    # coverage -- it must NOT get a fabricated coverage-table row of its
    # own (the bug this test now guards): no "Syria: ..." coverage line at
    # all, only the corpus's real "Freedonia: 1 chunks" entry above.
    assert "Syria:" not in combined_prompt_text, (
        "expected no fabricated 'Syria: ...' coverage line for the brief's "
        f"own case -- the corpus has no real coverage for it, got:\n"
        f"{combined_prompt_text!r}"
    )
    # "Tunisia" is neither the case nor a real corpus polity under this
    # vault, so it must never get a fabricated coverage-table entry of its
    # own (issue #252 review's regression) -- it may appear only inside the
    # verbatim request text, never as a "Tunisia: ..." coverage line.
    assert "Tunisia:" not in combined_prompt_text, (
        "expected no fabricated 'Tunisia: ...' coverage line -- Tunisia is "
        f"neither the case nor a real vault polity for this fixture, got:\n"
        f"{combined_prompt_text!r}"
    )
    # The prompt must tell the model the coverage table has no time
    # dimension, so it maps the case's place name(s) onto the table's real
    # rows itself instead of expecting an exact string match against a
    # date-qualified case (the fix for the false-refusal bug this test
    # locks; see src/axial/brief/interrogate.py's compose_prompt).
    assert (
        "no time" in combined_prompt_text or "no time/period dimension" in combined_prompt_text
    ), (
        "expected the recorded prompt to carry the 'coverage table has no "
        f"time dimension' guidance line, got:\n{combined_prompt_text!r}"
    )


def test_nonnull_refusal_forces_refuse_persists_and_makes_no_synthesis_call(
    fixture_root: Path,
):
    """Scenario 2 (issue #252): a canned response carrying a non-null
    `refusal` forces disposition "refuse", the result is persisted (a
    refuse disposition is a COMPLETED run, §7.2), and exactly one LLM call
    is made in the whole run (there is no synthesis call to make yet, so
    "zero synthesis calls" holds by construction -- this asserts the run
    made no MORE than the one interrogation call, proving nothing beyond it
    fired)."""
    brief_path = _write_brief(fixture_root)
    record_path = fixture_root / "record.jsonl"

    stub_response = {
        "premises_found": [],
        "bounds_applied": [],
        "refusal": {
            "reason": "the corpus holds no coverage for the polity this premise depends on"
        },
    }

    result = _run_interrogate(
        fixture_root, brief_path, record_path=record_path, stub_response=stub_response
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0 on a refuse disposition, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    brief_id = _brief_id_from_output(result)
    persisted = _load_persisted_interrogation(fixture_root, brief_id)
    interrogation = persisted["interrogation"]

    assert interrogation["disposition"] == "refuse"
    assert interrogation["refusal"] is not None

    prompts = _read_recorded_prompts(record_path)
    assert len(prompts) == 1, (
        f"expected exactly one recorded LLM call (the interrogation pass "
        f"itself, no synthesis call exists yet to make a second), got "
        f"{len(prompts)}: {prompts!r}"
    )


def test_model_supplied_disposition_is_discarded_by_the_wrapper(fixture_root: Path):
    """Scenario 3 (issue #252): the model's own `disposition` claim
    ("refuse") is never trusted -- with empty premises_found, empty
    bounds_applied, and a null refusal, the deterministic wrapper computes
    "proceed" regardless."""
    brief_path = _write_brief(fixture_root)
    record_path = fixture_root / "record.jsonl"

    stub_response = {
        "premises_found": [],
        "bounds_applied": [],
        "refusal": None,
        "disposition": "refuse",  # the model's own claim -- must be discarded
    }

    result = _run_interrogate(
        fixture_root, brief_path, record_path=record_path, stub_response=stub_response
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    brief_id = _brief_id_from_output(result)
    persisted = _load_persisted_interrogation(fixture_root, brief_id)
    interrogation = persisted["interrogation"]

    assert interrogation["disposition"] == "proceed", (
        "expected the wrapper to compute 'proceed' from empty premises_found/"
        "bounds_applied and a null refusal, ignoring the model's own "
        f"disposition claim, got {interrogation['disposition']!r}"
    )
