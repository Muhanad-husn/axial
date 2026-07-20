"""Regression test for issue #275 (fix lane).

`specs/PHASE-B.md` §7.1 (spec commit `ca7bf58`):

    `lens` -- optional named lens from `config/lenses/`; when absent the
    analysis stage selects one and records which, so the choice is always
    disclosed. The key is optional; its value is not. A present `lens` must
    be a non-empty string, and a blank or whitespace-only value is rejected
    exactly as a blank `case` or `request` is. Omitting the key is the only
    way to ask the stage to choose.

`src/axial/brief/intake.py`, `_validate_lens`, does the opposite as of
`main`: `return stripped or None` silently coerces a present-but-blank
`lens: ""` into `None`, routing it into the analysis stage's auto-selection
path as though the key had been omitted at all.

Given a brief with `lens: ""`
When  `axial brief show` runs on it
Then  the command exits non-zero with a logged reason naming `lens`

Given a brief with a whitespace-only `lens` (e.g. `"   "`)
When  `axial brief show` runs on it
Then  the command exits non-zero with a logged reason naming `lens` (same
      rule as blank, not a distinct code path)

Given a brief that omits the `lens` key entirely
When  `axial brief show` runs on it
Then  the command exits 0 -- omission, not blankness, is the only way to ask
      the stage to choose (guards against a fix that overcorrects and starts
      rejecting the documented "stage chooses" path too)

See specs/PHASE-B.md §7.1 for the source of truth and
tests/analysis/test_brief_intake.py for the CLI-subprocess idiom this file
copies (including its argparse-fallback guard). This is a fix-lane
regression test (issue #275), not #247's locked outer contract -- kept in
its own file so it never touches that pinned criterion.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Gotcha (see CLAUDE.local.md / dispatch note): this file lives at
# tests/analysis/test_brief_lens_validation.py, so it takes THREE .parent
# hops to reach the repo root, not two.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# A minimal otherwise-valid brief body: only the `lens` field varies per
# scenario. case/request are non-empty so a failure can only be attributed
# to lens validation, not to the already-covered case/request rules.
_VALID_CASE = 'case: "Syria"\n'
_VALID_REQUEST = 'request: "How did displacement reshape local authority?"\n'


def _run_brief_show(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "axial", "brief", "show", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    """Guard against a false pass: argparse's own "invalid choice"/
    "unrecognized arguments" error can satisfy a naive nonzero-exit check
    without any real `lens` validation logic ever running. Reject that
    generic failure mode explicitly (mirrors
    tests/analysis/test_brief_intake.py and tests/cli/test_schema_show.py).
    """
    combined_output = result.stdout + result.stderr
    assert (
        "invalid choice" not in combined_output and "unrecognized arguments" not in combined_output
    ), (
        "expected a real 'brief show' error path (a validation failure "
        "naming the offending field), not an argparse fallback -- this "
        "means the `axial brief show` CLI subcommand does not exist:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def _write_brief(tmp_path: Path, name: str, lens_line: str) -> Path:
    brief = tmp_path / name
    brief.write_text(_VALID_CASE + _VALID_REQUEST + lens_line, encoding="utf-8")
    return brief


def test_blank_lens_is_rejected(tmp_path: Path):
    """Scenario 1 (issue #275): `lens: ""` must fail loudly -- nonzero
    exit, `lens` named in the error -- exactly like a blank `case` or
    `request`. Currently `_validate_lens` coerces this to `None` instead,
    so this is expected to fail (exit 0) until the fix lands."""
    malformed = _write_brief(tmp_path, "brief_blank_lens.yaml", 'lens: ""\n')

    result = _run_brief_show(str(malformed))

    assert result.returncode != 0, (
        'expected nonzero exit for a brief with lens: "" (blank), got 0 -- '
        "a present-but-blank `lens` must be rejected, not silently coerced "
        'to "the stage chooses" (§7.1)\n'
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    _assert_not_argparse_fallback(result)

    combined_output = result.stdout + result.stderr
    assert "lens" in combined_output, (
        "expected the offending field 'lens' to be named in the error, got:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_whitespace_only_lens_is_rejected(tmp_path: Path):
    """Scenario 2 (issue #275): a whitespace-only `lens` (e.g. `"   "`)
    must be rejected under the same rule as an empty string -- §7.1 does
    not distinguish "blank" from "whitespace-only". Currently
    `_validate_lens` strips it to an empty string and then coerces that to
    `None`, so this is expected to fail (exit 0) until the fix lands."""
    malformed = _write_brief(tmp_path, "brief_whitespace_lens.yaml", 'lens: "   "\n')

    result = _run_brief_show(str(malformed))

    assert result.returncode != 0, (
        "expected nonzero exit for a brief with a whitespace-only lens, "
        f"got 0\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    _assert_not_argparse_fallback(result)

    combined_output = result.stdout + result.stderr
    assert "lens" in combined_output, (
        "expected the offending field 'lens' to be named in the error, got:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_omitted_lens_still_loads_and_means_stage_chooses(tmp_path: Path):
    """Scenario 3 (issue #275): omitting the `lens` key entirely is the
    ONLY way to ask the stage to choose, per §7.1 -- this must keep working
    exactly as it does today. This guard should already pass; it exists so
    a fix that overcorrects (e.g. rejecting `lens=None` outright) is caught
    immediately, not just the blank/whitespace-only cases."""
    valid = tmp_path / "brief_no_lens_key.yaml"
    valid.write_text(_VALID_CASE + _VALID_REQUEST, encoding="utf-8")

    result = _run_brief_show(str(valid))

    assert result.returncode == 0, (
        "expected exit 0 for a brief that omits `lens` entirely -- omission "
        'must continue to mean "the stage chooses" (§7.1), not be treated '
        f"as an error\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    combined_output = result.stdout + result.stderr
    assert "lens" in combined_output, (
        "expected the CLI to still report a lens field (disclosing "
        f"'(none)' or similar) for the omitted-key path, got:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
