"""Outer acceptance test for issue #8, slice 03 (codebook-validate).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given the committed schema.yaml and codebook.yaml for config/domains/syria
When  the user runs `uv run axial schema validate config/domains/syria`
Then  it exits 0 and reports every axis consistent
And   run against a fixture domain dir whose codebook omits one schema tag,
      it exits nonzero and names that tag and its axis
And   run against a fixture whose codebook carries a tag absent from the
      schema, it exits nonzero and names it

See specs/PRODUCT.md §7.1 (loader contract), §8 P0-6 ("a tag not in the
schema is a hard error"), and Appendices B-G (line 400: "codebook.yaml
mirrors this, adding definition, positive_example, negative_example per
tag") for the source of truth. See plans/schema-loader/03-codebook-validate.md
for the slice's acceptance criterion.

Fixture note: the two broken-pair fixtures under tests/fixtures/ each carry
a schema.yaml + codebook.yaml pair mirroring the real schema's simplest axis
shape (a flat `values` list, as the real schema's `field` axis uses) so the
cross-check (schema tags <-> codebook tags) is exercised without pulling in
subtags/groups, which are orthogonal to this slice's behavioral contract.
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The six axes the real, committed v0.1 Syria schema.yaml declares (mirrors
# tests/test_schema_show.py's EXPECTED_AXES) -- used only to assert that a
# consistent-pair report surfaces every axis, not to pin exact wording.
REAL_SCHEMA_AXES = [
    "field",
    "claim_type",
    "empirical_scope",
    "theory_school",
    "artifact_role",
    "role_in_argument",
]


def _run_schema_validate(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "axial", "schema", "validate", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    """Guard against a false pass: argparse's own "unrecognized arguments"
    error (raised while `schema validate` isn't a real subcommand yet) can
    happen to satisfy a naive substring check on an expected-failure test
    without any real validation logic existing. Reject that generic failure
    mode explicitly, exactly as tests/test_schema_show.py does.
    """
    combined_output = result.stdout + result.stderr
    assert "unrecognized arguments" not in combined_output, (
        "expected a real 'schema validate' error path (a cross-check "
        "finding), not an argparse 'unrecognized arguments' fallback -- "
        "this means the `schema validate` subcommand does not exist yet:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_schema_validate_against_real_syria_pair_exits_zero_and_reports_consistency():
    """The committed config/domains/syria/{schema.yaml,codebook.yaml} pair is
    the end state this slice delivers: every schema tag has a codebook entry
    and vice versa. Running `schema validate` against it must exit 0 and
    report every one of the six axes as consistent.
    """
    result = _run_schema_validate("config/domains/syria")

    assert result.returncode == 0, (
        "expected exit code 0 for the real, consistent Syria schema/codebook "
        f"pair, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    stdout = result.stdout

    missing_axes = [axis for axis in REAL_SCHEMA_AXES if axis not in stdout]
    assert not missing_axes, (
        "expected a consistency report naming every axis, missing: "
        f"{missing_axes}\nstdout: {stdout!r}"
    )

    # The report must actually claim consistency somewhere -- not just print
    # axis names with no verdict. We don't pin exact wording, just that some
    # affirmative consistency signal is present and no failure/error signal
    # is present (so a report that merely echoes axis names without judging
    # them cannot pass).
    lowered = stdout.lower()
    consistency_signal = any(token in lowered for token in ("consistent", "ok", "valid", "pass"))
    assert consistency_signal, (
        "expected the report to affirmatively state consistency (e.g. the "
        f"word 'consistent'), got stdout: {stdout!r}"
    )
    failure_signal = any(token in lowered for token in ("missing", "error", "inconsistent", "fail"))
    assert not failure_signal, (
        "expected no failure/error signal in a report over a consistent "
        f"pair, got stdout: {stdout!r}"
    )


def test_schema_validate_flags_schema_tag_missing_from_codebook():
    """Fixture: tests/fixtures/codebook_missing_tag/ -- schema declares tag
    `gamma` on axis `topic`; the paired codebook.yaml omits it entirely.
    `schema validate` must exit nonzero and name both the tag and its axis.
    """
    fixture_dir = "tests/fixtures/codebook_missing_tag"

    result = _run_schema_validate(fixture_dir)

    assert result.returncode != 0, (
        "expected nonzero exit for a codebook missing a schema tag, got 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    _assert_not_argparse_fallback(result)

    combined_output = result.stdout + result.stderr
    assert "gamma" in combined_output, (
        "expected the offending tag 'gamma' to be named in the output:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "topic" in combined_output, (
        "expected the offending tag's axis 'topic' to be named in the "
        f"output:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_schema_validate_flags_codebook_tag_absent_from_schema():
    """Fixture: tests/fixtures/codebook_extra_tag/ -- codebook.yaml carries a
    tag, `delta`, on axis `topic` that schema.yaml never declares.
    `schema validate` must exit nonzero and name that extra tag.
    """
    fixture_dir = "tests/fixtures/codebook_extra_tag"

    result = _run_schema_validate(fixture_dir)

    assert result.returncode != 0, (
        "expected nonzero exit for a codebook tag absent from the schema, "
        f"got 0\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    _assert_not_argparse_fallback(result)

    combined_output = result.stdout + result.stderr
    assert "delta" in combined_output, (
        "expected the offending extra tag 'delta' to be named in the "
        f"output:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
