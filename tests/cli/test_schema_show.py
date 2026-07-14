"""Outer acceptance test for issue #7, slice 02 (schema-load).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given the committed placeholder schema at config/domains/syria/schema.yaml
      (version 0.1)
When  the user runs `uv run axial schema show config/domains/syria`
Then  it exits 0 and lists the six axes (field, claim_type, empirical_scope,
      theory_school, artifact_role, role_in_argument), each with its
      cardinality and value count, and the schema version
And   running it against a nonexistent directory exits nonzero with a
      message naming the missing file

See specs/PRODUCT.md §7.1 (loader contract) and Appendix G (schema.yaml
shape) for the source of truth.
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# The six axes the v0.1 Syria schema.yaml must declare (Appendix G / §7.1).
EXPECTED_AXES = {
    "field": "primary_plus_secondary",
    "claim_type": "primary_plus_optional_secondary",
    "empirical_scope": "single",
    "theory_school": "primary_plus_optional_secondary",
    "artifact_role": "single",
    "role_in_argument": "single",
}

SCHEMA_VERSION = "0.1"


def _run_schema_show(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "axial", "schema", "show", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_schema_show_lists_all_six_axes_with_cardinality_count_and_version():
    result = _run_schema_show("config/domains/syria")

    assert result.returncode == 0, (
        f"expected exit code 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    stdout = result.stdout

    # Every axis name must be present.
    missing_axes = [axis for axis in EXPECTED_AXES if axis not in stdout]
    assert not missing_axes, (
        f"expected all six axes in stdout, missing: {missing_axes}\nstdout: {stdout!r}"
    )

    # Each axis's declared cardinality token must appear somewhere "close to"
    # its axis name -- we don't pin exact layout, just that the cardinality
    # is surfaced and locatable per-axis (e.g. on the same or adjacent line).
    for axis, cardinality in EXPECTED_AXES.items():
        axis_positions = [m.start() for m in re.finditer(re.escape(axis), stdout)]
        assert axis_positions, f"axis {axis!r} not found in stdout"

        cardinality_positions = [m.start() for m in re.finditer(re.escape(cardinality), stdout)]
        assert cardinality_positions, (
            f"cardinality {cardinality!r} for axis {axis!r} not found anywhere "
            f"in stdout: {stdout!r}"
        )

        # At least one occurrence of the cardinality token must be within a
        # generous window of an occurrence of the axis name, so the pairing
        # is legible to a human reader without over-specifying formatting.
        window = 200
        paired = any(
            abs(a_pos - c_pos) <= window
            for a_pos in axis_positions
            for c_pos in cardinality_positions
        )
        assert paired, (
            f"expected cardinality {cardinality!r} to appear near axis "
            f"{axis!r} (within {window} chars) in stdout: {stdout!r}"
        )

    # Each axis must show a value count: a digit sequence appearing near the
    # axis name (distinct from merely repeating the cardinality string).
    for axis in EXPECTED_AXES:
        axis_positions = [m.start() for m in re.finditer(re.escape(axis), stdout)]
        digit_positions = [m.start() for m in re.finditer(r"\d+", stdout)]
        assert digit_positions, f"no value counts (digits) found in stdout at all: {stdout!r}"

        window = 200
        has_count_nearby = any(
            abs(a_pos - d_pos) <= window for a_pos in axis_positions for d_pos in digit_positions
        )
        assert has_count_nearby, (
            f"expected a value count (digits) near axis {axis!r} in stdout: {stdout!r}"
        )

    # The schema version must be surfaced.
    assert SCHEMA_VERSION in stdout, (
        f"expected schema version {SCHEMA_VERSION!r} in stdout: {stdout!r}"
    )


def test_schema_show_against_missing_domain_dir_fails_naming_the_path():
    missing_dir = "config/domains/does-not-exist"

    result = _run_schema_show(missing_dir)

    assert result.returncode != 0, (
        f"expected nonzero exit code for missing domain dir, got 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    combined_output = result.stdout + result.stderr

    # Guard against a false pass: argparse's own "unrecognized arguments"
    # error (raised when `schema show` isn't a real subcommand yet) happens
    # to echo the missing path back verbatim, which would otherwise satisfy
    # a naive substring check without any real missing-file handling
    # existing. Reject that generic failure mode explicitly.
    assert "unrecognized arguments" not in combined_output, (
        "expected a real 'schema show' error path (missing domain/schema "
        "file), not an argparse 'unrecognized arguments' fallback -- this "
        "means the `schema show` subcommand does not exist yet:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # The message must name the missing path/file so a user can act on it --
    # either the domain directory itself or the schema.yaml file within it.
    assert missing_dir in combined_output or "schema.yaml" in combined_output, (
        f"expected error message naming the missing file/path, got:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
