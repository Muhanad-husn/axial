"""Outer acceptance test for issue #247, slice 01 (brief-intake-and-id).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a brief file config/briefs/dev/fixture-syria-displacement.yaml carrying
      case: "Syria" and request: "How did displacement reshape local
      authority?"
When  `axial brief show config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command exits 0, prints case "Syria", the request text, and a
      brief_id
  And running the same command a second time prints the identical brief_id

Given a second brief file whose content is byte-identical to the first but
      whose filename differs
When  `axial brief show` runs on it
Then  the printed brief_id is identical to the first file's brief_id

Given a brief file with a `case` key that is absent or an empty string
When  `axial brief show` runs on it
Then  the command exits non-zero with a logged reason naming `case`
  And no partially-constructed brief is emitted

See specs/PHASE-B.md §7.1 (the brief input contract, [FIRM]: shape
`{brief_id, case, request, lens?}`), §6 (repository structure --
src/axial/brief/, config/briefs/dev/), and §8 P0-9 (CLI surface,
inspect-before-spend precedent) for the source of truth. See
plans/analysis-foundation/01-brief-intake-and-id.md for the slice's
acceptance criterion.

Fixture note: config/briefs/dev/fixture-syria-displacement.yaml is the
implementer's deliverable (this slice lands it), not the test-author's --
this test references it by its real, spec-named repo path and is expected to
fail until that file and the `axial brief` CLI namespace both exist. The
scenario-2 (byte-identical/different-filename) and scenario-3 (malformed
case) fixtures are constructed on the fly under tmp_path, since neither is a
committed repo deliverable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

# Gotcha (see CLAUDE.local.md / dispatch note): this file lives at
# tests/analysis/test_brief_intake.py, so it takes THREE .parent hops to
# reach the repo root, not two.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

REAL_FIXTURE = REPO_ROOT / "config" / "briefs" / "dev" / "fixture-syria-displacement.yaml"

EXPECTED_CASE = "Syria"
EXPECTED_REQUEST = "How did displacement reshape local authority?"

# Pulls the id token out of the CLI's printed output without pinning exact
# formatting -- only that the literal §7.1 field name `brief_id` (tolerating
# harmless separator/case variants like "Brief ID") is present, immediately
# followed by an id-shaped token.
_BRIEF_ID_PATTERN = re.compile(r"brief[_ -]?id\D{0,10}([A-Za-z0-9_-]{6,})", re.IGNORECASE)


def _run_brief_show(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "axial", "brief", "show", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    """Guard against a false pass: argparse's own "invalid choice"/
    "unrecognized arguments" error (raised while `axial brief show` isn't a
    real subcommand yet) can satisfy a naive substring check on an
    expected-failure scenario without any real validation logic existing.
    Reject that generic failure mode explicitly (mirrors
    tests/cli/test_schema_show.py and tests/cli/test_schema_validate.py).
    """
    combined_output = result.stdout + result.stderr
    assert (
        "invalid choice" not in combined_output and "unrecognized arguments" not in combined_output
    ), (
        "expected a real 'brief show' error path (a validation failure "
        "naming the offending field), not an argparse fallback -- this "
        "means the `axial brief show` CLI subcommand does not exist yet:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def _extract_brief_id(result: subprocess.CompletedProcess) -> str:
    combined_output = result.stdout + result.stderr
    match = _BRIEF_ID_PATTERN.search(combined_output)
    assert match, (
        "expected the printed output to name a brief_id (the §7.1 field) "
        f"followed by an id value, got:\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    return match.group(1)


def test_brief_show_prints_case_request_and_a_stable_brief_id():
    """Scenario 1 (issue #247): the committed dev fixture round-trips
    through `axial brief show`, printing case, request, and a brief_id that
    is identical across two independent runs (deterministic: no randomness,
    no timestamps)."""
    first = _run_brief_show(str(REAL_FIXTURE))

    assert first.returncode == 0, (
        "expected exit 0 for config/briefs/dev/fixture-syria-displacement.yaml, "
        f"got {first.returncode}\nstdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    )

    assert EXPECTED_CASE in first.stdout, (
        f"expected case {EXPECTED_CASE!r} in stdout, got: {first.stdout!r}"
    )
    assert EXPECTED_REQUEST in first.stdout, (
        f"expected the request text {EXPECTED_REQUEST!r} in stdout, got: {first.stdout!r}"
    )

    first_id = _extract_brief_id(first)

    # Run the SAME command a second, fully independent time (a fresh
    # subprocess, not a cached value) -- the gherkin's actual claim under
    # test is that brief_id is deterministic across runs, not merely that a
    # variable equals itself.
    second = _run_brief_show(str(REAL_FIXTURE))
    assert second.returncode == 0, (
        f"expected exit 0 on a second run, got {second.returncode}\n"
        f"stdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    )
    second_id = _extract_brief_id(second)

    assert first_id == second_id, (
        "expected the identical brief_id across two independent runs of the "
        f"same file, got {first_id!r} then {second_id!r} -- brief_id must be "
        "deterministic (no randomness, no timestamps, per §7.1)"
    )


def test_brief_show_id_is_content_derived_not_path_derived(tmp_path: Path):
    """Scenario 2 (issue #247): a byte-identical copy of the real fixture,
    saved under a different filename, must print the identical brief_id --
    proving the id is a hash of the brief's content, never of its filename
    or path."""
    renamed_copy = tmp_path / "a-completely-different-filename.yaml"
    shutil.copyfile(REAL_FIXTURE, renamed_copy)

    # The copy must be byte-identical to the original -- the scenario's own
    # premise -- so a divergence here would invalidate the test itself
    # rather than exercise real loader behavior.
    assert renamed_copy.read_bytes() == REAL_FIXTURE.read_bytes()

    original_result = _run_brief_show(str(REAL_FIXTURE))
    renamed_result = _run_brief_show(str(renamed_copy))

    assert renamed_result.returncode == 0, (
        "expected exit 0 for a byte-identical, differently-named copy, got "
        f"{renamed_result.returncode}\nstdout: {renamed_result.stdout!r}\n"
        f"stderr: {renamed_result.stderr!r}"
    )

    original_id = _extract_brief_id(original_result)
    renamed_id = _extract_brief_id(renamed_result)

    assert original_id == renamed_id, (
        "expected the identical brief_id for byte-identical content under a "
        f"different filename, got {original_id!r} (original path) vs "
        f"{renamed_id!r} (renamed copy) -- brief_id must be content-derived, "
        "never filename-derived (§7.1)"
    )


@pytest.mark.parametrize(
    "fixture_name, brief_body, sentinel",
    [
        pytest.param(
            "brief_no_case_key.yaml",
            'request: "SENTINEL_REQUEST_NO_CASE_KEY_9f3a1c"\n',
            "SENTINEL_REQUEST_NO_CASE_KEY_9f3a1c",
            id="case-key-absent",
        ),
        pytest.param(
            "brief_blank_case_value.yaml",
            'case: ""\nrequest: "SENTINEL_REQUEST_BLANK_CASE_2b7e40"\n',
            "SENTINEL_REQUEST_BLANK_CASE_2b7e40",
            id="case-value-empty-string",
        ),
    ],
)
def test_brief_show_rejects_missing_or_empty_case(
    tmp_path: Path, fixture_name: str, brief_body: str, sentinel: str
):
    """Scenario 3 (issue #247): a brief whose `case` is absent or an empty
    string must fail loudly -- nonzero exit, `case` named in the error -- and
    must emit no partially-constructed brief: the request text a successful
    load would echo (per scenario 1) must never leak into the output of a
    load that failed validation."""
    malformed = tmp_path / fixture_name
    malformed.write_text(brief_body, encoding="utf-8")

    result = _run_brief_show(str(malformed))

    assert result.returncode != 0, (
        "expected nonzero exit for a brief with case missing/empty, got 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    _assert_not_argparse_fallback(result)

    combined_output = result.stdout + result.stderr
    assert "case" in combined_output, (
        "expected the offending field 'case' to be named in the error, got:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    assert sentinel not in combined_output, (
        "expected no partially-constructed brief to be emitted for a brief "
        f"that failed validation -- its request text {sentinel!r} must not "
        f"appear anywhere in output, got:\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
