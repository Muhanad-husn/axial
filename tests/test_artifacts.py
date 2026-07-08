"""Outer acceptance test for issue #30, slice 01 (artifact classification).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given an extracted fixture source containing at least one artifact node (a
      table or figure), and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial artifacts <fixture>`
Then  it exits 0 and emits one record per artifact node as JSON
And   each record carries a stable artifact_id, an artifact_role drawn from
      the schema's artifact_role axis, and source/section provenance
And   a stub returning a role absent from the schema exits non-zero with a
      clear error

See specs/PRODUCT.md §5 stage 5 ("Artifact classification & routing. Each
non-text artifact receives a role tag from the artifact-role taxonomy...
Output: tagged artifacts in the artifact pool."), §7.2 ("Artifact notes
carry: artifact_role, fields, source/section provenance, and cited_by
back-references to prose chunks."), Appendix D (the closed artifact_role
vocabulary: case-study, framework-illustration, quote-pool, framework,
reference-material, discard), and §8 P0-5 ("Each non-text artifact receives
exactly one artifact_role from the taxonomy... Any tag produced that is
absent from the schema raises a hard error" -- P0-5/P0-6) for the source of
truth. Routing artifacts to data/vault/artifacts/ on disk is out of scope
for this slice (slice 02); this slice's contract ends at stdout.

Fixture reuse: tests/fixtures/extract/prose_and_table.pdf (see
tests/test_extract.py and its _generate.py) is a two-section fixture --
"Introduction" (two paragraphs, then one bordered-grid table) followed by
"Discussion" (two paragraphs, no artifact). _generate.py's
`make_prose_and_table_pdf` adds exactly one `Table` flowable to the whole
document, so this fixture carries exactly one artifact node, nested under
the "Introduction" section (extract.py's tree-builder nests trailing content
under the most recent heading until the next one) -- never under
"Discussion". That single, unambiguous artifact node is this test's target:
its enclosing section's own verbatim heading, "Introduction", is the
expected section-provenance value below. No new fixture is needed since
P0-5 only requires "at least one artifact node", and this one already
carries exactly one, unambiguously placed.

Seam decision 1 -- extending the stub dispatch to a third pass
-----------------------------------------------------------------------
src/axial/llm.py already dispatches `StubLLMClient`/`RecordLLMClient`'s
canned response by `pass_name` (`pass_name="chunk"` -> a chunk-shaped
response; anything else -> the original envelope-shaped one -- see
tests/test_chunk.py's seam decision 1 for the collision this already
resolved once). The artifacts pass (per the slice plan) calls
`client.complete(prompt, pass_name="artifacts")`, a THIRD pass sharing the
same stub. This test does not dictate the dispatch mechanism (a `pass_name`
branch, a prompt-shape sniff, or something else) or the raw JSON shape the
stub replies with -- it only requires, behaviorally, that `AXIAL_LLM_PROVIDER
=stub` configured for `axial artifacts <fixture>` yields a response the
artifacts pass can parse into a single, in-schema `artifact_role` per
artifact node. Implementing that third-pass response is this test's whole
point for the happy path, exactly as slice-05's chunk-shaped response was
for tests/test_chunk.py.

Seam decision 2 -- forcing an out-of-schema role: a NEW env var,
AXIAL_STUB_ARTIFACT_ROLE
-----------------------------------------------------------------------
The acceptance criterion's hard-error branch needs the stub to return a
role that is NOT in the schema, on demand, without inventing a whole new
provider value (mirroring the `AXIAL_FORCE_DOCLING_FAILURE` fault-injection
convention already established in src/axial/extract.py). This test locks a
new environment variable, `AXIAL_STUB_ARTIFACT_ROLE`:

    unset / ""  -> the stub's `pass_name="artifacts"` response carries some
                    fixed, in-schema `artifact_role` value (this test does
                    not lock which one -- only that it is a member of the
                    schema's artifact_role axis, see
                    tests/fixtures... note below). This is the happy path.
    set, e.g.
    "not-a-real-role" -> the stub's `pass_name="artifacts"` response instead
                    carries EXACTLY that string as the returned role, valid
                    or not, so this test can drive the hard-error path
                    deterministically without needing a real model to
                    misbehave. Selecting this env var without
                    AXIAL_LLM_PROVIDER=stub is not exercised by this test
                    (left to the implementer).

This test never asserts what the *raw* stub response text looks like (no
JSON-shape lock on the model-facing wire format) -- only the env var's
black-box effect on the parsed, in-schema-or-not `artifact_role` that ends
up on stdout (happy path) or named in the hard-error message (error path).
This keeps the implementer free to choose the internal response envelope
(e.g. `{"artifact_role": "..."}` vs. `{"role": "..."}` vs. something else)
exactly as tests/test_chunk.py's seam decision 1 left the chunk-shaped
response's exact JSON keys unlocked.

Seam decision 3 -- artifact_id: locking the prefix and stability, not the
exact order suffix
-----------------------------------------------------------------------
The slice plan locks `artifact_id` as `<source_id>_art_<order>`, where
`source_id` is `axial.envelope.compute_source_id`'s deterministic
filename-stem + content-hash id (computable here directly, without running
extraction, exactly as tests/test_chunk.py computes source_id-independent
facts directly) and `order` is the artifact node's own dotted position
string from extract.py's tree-builder (e.g. "1.3"). This test asserts the
locked PREFIX (`f"{source_id}_art_"`) and a dotted-digits SHAPE for the
remainder (extract.py's `order` values are always digits, optionally
dot-separated -- see src/axial/extract.py's `_build_tree`), plus STABILITY
across two consecutive runs on the same fixture (mirroring
tests/test_chunk.py's chunk_id stability check) -- but deliberately does NOT
hardcode the exact order suffix. The real docling conversion of a real PDF
(as opposed to the synthetic in-memory documents tests/test_extract.py's
unit tests use) is not itself pinned to a specific node-count/order by any
existing locked test (tests/test_extract.py's own end-to-end docling test
only asserts prose/artifact types are both present, never exact positions),
so hardcoding an exact order value here would risk locking an accidental
docling-version detail into this contract rather than the behavior P0-5
actually requires.

Seam decision 4 -- record field names locked by this test
-----------------------------------------------------------------------
Neither the PRD nor the slice plan names exact JSON field names for an
artifact record (only the concepts "a stable artifact_id", "an
artifact_role", and "source/section provenance"), so -- mirroring
tests/test_chunk.py's seam decision 4, which had to pick a field name for
"section provenance" the same way -- this test locks the minimum needed to
make the acceptance criterion executable:
  - "artifact_id": see seam decision 3.
  - "artifact_role": the exact axis name from schema.yaml (Appendix D),
    reused verbatim as the record's field name since the PRD's own
    vocabulary already supplies it (no naming choice was actually needed
    here, unlike section provenance).
  - "section": the enclosing section's own verbatim heading text. This test
    reuses the exact field name tests/test_chunk.py already locked for
    prose-chunk section provenance (PRD §7.2 groups "source/section
    provenance" under one umbrella for both prose and artifacts, so the
    same field name is the natural, minimal choice for the same concept).
  - "source_id": the source's own deterministic id (see seam decision 3),
    reused verbatim from the field name `axial.envelope`'s own envelope
    JSON already uses for the same concept (PRD §7.3's envelope shape),
    rather than inventing a second name (e.g. "source") for one idea.

Seam decision 5 -- stdout shape leniency
-----------------------------------------------------------------------
As in tests/test_chunk.py's seam decision 4, no source of truth dictates an
exact stdout envelope shape, so this test's parsing helper accepts any of:
a bare top-level JSON array, a JSON object with a top-level "artifacts"
array, or newline-delimited JSON (one record object per line).

Test hygiene: this slice writes nothing to disk on its own account (records
go to stdout only -- routing to data/vault/artifacts/ is slice 02's job).
The one thing it does write -- the pre-placed tree fixture under
data/trees/, see below -- is isolated by tests/conftest.py's shared,
content-snapshot-based `_isolate_persisted_tree_and_envelope_state` autouse
fixture, so no local fixture is needed here either.

Arrange-mechanism change (issue #45, tree-cache) -- no behavioral assertion
changed
-----------------------------------------------------------------------
This test's PURPOSE is artifact classification (artifact_id/artifact_role/
provenance) -- it consumes the structural tree only as input (walking its
`type == "artifact"` nodes), it never asserts anything about extraction/tree
shape itself (that is tests/test_extract.py's contract). `axial artifacts`
calls `axial.extract.extract` directly, which -- per the now-locked
tree-persist contract (tests/test_tree_persist.py, PRD §7.4) -- reuses a
persisted tree verbatim at data/trees/<source_id>.json instead of re-running
docling. So this test now pre-places the committed REAL tree fixture
(tests/fixtures/extract/prose_and_table_tree.json -- exactly `axial
extract`'s own output for this fixture, see that directory's _generate.py
for the regeneration recipe) before every run, exactly as it would look
after a real extraction, only without paying for one. Every existing
assertion is unchanged: the stub LLM's artifact_role response does not
depend on the source text, and the artifact node's own shape (hence
artifact_id/section) is byte-identical to a real extraction's, since the
fixture IS a real extraction's output.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "extract"
DEFAULT_DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"
TREES_DIR = REPO_ROOT / "data" / "trees"

PROSE_AND_TABLE_PDF = FIXTURES_DIR / "prose_and_table.pdf"
PROSE_AND_TABLE_TREE_FIXTURE = FIXTURES_DIR / "prose_and_table_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
# New seam this test relies on -- see module docstring, seam decision 2.
STUB_ARTIFACT_ROLE_ENV_VAR = "AXIAL_STUB_ARTIFACT_ROLE"

# The bogus role this test forces the stub to return to drive the
# hard-error branch. Deliberately unmistakable as never a real schema value.
BOGUS_ROLE = "not-a-real-role"

# This fixture's only artifact node (a single bordered-grid table) sits
# under this section's heading, verbatim (see module docstring, "Fixture
# reuse").
EXPECTED_SECTION = "Introduction"

# argparse's fallback error for an as-yet-nonexistent subcommand, e.g.
# "axial: error: argument command: invalid choice: 'artifacts' (choose
# from 'schema', 'intake', 'extract', 'envelope', 'chunk', 'vault')". Any of
# these substrings in the combined output means the target subcommand's
# logic was never actually exercised -- the process failed before real
# behavior ran. Reject that generic failure mode explicitly so this test
# can only pass once real `artifacts` behavior exists.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_artifacts(
    *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "stub"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["uv", "run", "axial", "artifacts", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `artifacts` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `artifacts` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _parse_artifact_records(stdout: str) -> list[dict]:
    """Parse artifact records from `axial artifacts`'s stdout, tolerating any
    of the three stdout shapes this test locks (see module docstring, seam
    decision 5): a bare JSON array, a JSON object with an "artifacts" array,
    or newline-delimited JSON (one record per line)."""
    stripped = stdout.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None

    if data is not None:
        if isinstance(data, dict):
            assert "artifacts" in data, (
                f"expected a top-level 'artifacts' key when artifacts stdout "
                f"is a JSON object, got keys: {sorted(data.keys())}; stdout: {stdout!r}"
            )
            records = data["artifacts"]
        else:
            records = data
        assert isinstance(records, list), (
            f"expected artifact records to be a JSON array (bare, or under "
            f"an 'artifacts' key), got {type(records).__name__}: {records!r}"
        )
        return records

    records = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"expected artifacts stdout to be either one parseable JSON "
                f"document (a bare array, or an object with a top-level "
                f"'artifacts' array) or newline-delimited JSON (one artifact "
                f"record object per line); line {line!r} failed to parse "
                f"({exc}). Full stdout: {stdout!r}"
            ) from None
    return records


def _in_schema_artifact_roles() -> set[str]:
    """The schema's artifact_role axis values, loaded from the default
    domain (config/domains/syria/schema.yaml, Appendix D)."""
    from axial.schema import load_schema

    schema = load_schema(DEFAULT_DOMAIN_DIR)
    return schema.axes["artifact_role"].tag_ids


def _expected_source_id() -> str:
    """This fixture's deterministic source_id, computed directly (no
    extraction needed) via the same function the artifacts pass must reuse
    for its `artifact_id` prefix (see module docstring, seam decision 3)."""
    from axial.envelope import compute_source_id

    return compute_source_id(PROSE_AND_TABLE_PDF)


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    data/trees/<source_id>.json (source_id via
    axial.envelope.compute_source_id) so `axial.extract.extract` reuses it
    verbatim instead of running docling (see module docstring, "Arrange-
    mechanism change"). Returns the tree path."""
    from axial.envelope import compute_source_id

    source_id = compute_source_id(source_pdf)
    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def test_artifacts_emits_one_record_per_artifact_node_with_id_role_and_provenance():
    in_schema_roles = _in_schema_artifact_roles()
    source_id = _expected_source_id()
    _place_tree_fixture(PROSE_AND_TABLE_PDF, PROSE_AND_TABLE_TREE_FIXTURE)

    # --- first run: stub provider, no forced role -- the happy path ---
    first = _run_artifacts(str(PROSE_AND_TABLE_PDF))
    _assert_not_argparse_fallback(first)
    assert first.returncode == 0, (
        f"expected exit code 0 for `axial artifacts` on a fixture source "
        f"with an artifact node and the stub LLM provider, got "
        f"{first.returncode}\nstdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    )

    first_records = _parse_artifact_records(first.stdout)
    assert len(first_records) == 1, (
        f"expected exactly one artifact record (this fixture carries exactly "
        f"one artifact node -- see module docstring, 'Fixture reuse'), got "
        f"{len(first_records)}; stdout: {first.stdout!r}"
    )

    record = first_records[0]
    assert isinstance(record, dict), (
        f"expected the artifact record to be a JSON object, got {type(record).__name__}: {record!r}"
    )

    artifact_id = record.get("artifact_id")
    assert isinstance(artifact_id, str) and artifact_id.strip(), (
        f"expected the artifact record to carry a non-empty string "
        f"'artifact_id', got {artifact_id!r} (full record: {record!r})"
    )
    assert re.fullmatch(rf"{re.escape(source_id)}_art_[0-9]+(\.[0-9]+)*", artifact_id), (
        f"expected artifact_id to match '<source_id>_art_<order>' "
        f"(source_id={source_id!r}, order a dotted-digits string per "
        f"extract.py -- see module docstring, seam decision 3), got "
        f"{artifact_id!r}"
    )

    artifact_role = record.get("artifact_role")
    assert artifact_role in in_schema_roles, (
        f"expected 'artifact_role' to be a member of the schema's "
        f"artifact_role axis {sorted(in_schema_roles)} (PRD Appendix D), "
        f"got {artifact_role!r} (full record: {record!r})"
    )

    assert record.get("source_id") == source_id, (
        f"expected the artifact record to carry 'source_id' == {source_id!r} "
        f"(source provenance, PRD §7.2), got {record.get('source_id')!r} "
        f"(full record: {record!r})"
    )
    assert record.get("section") == EXPECTED_SECTION, (
        f"expected the artifact record to carry 'section' == "
        f"{EXPECTED_SECTION!r} (this fixture's enclosing section's own "
        f"verbatim heading -- section provenance, PRD §7.2), got "
        f"{record.get('section')!r} (full record: {record!r})"
    )

    # --- second run: same fixture, same stub provider -- artifact_id must be stable ---
    second = _run_artifacts(str(PROSE_AND_TABLE_PDF))
    _assert_not_argparse_fallback(second)
    assert second.returncode == 0, (
        f"expected exit code 0 on a repeat `axial artifacts` run over the "
        f"same fixture, got {second.returncode}\n"
        f"stdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    )

    second_records = _parse_artifact_records(second.stdout)
    assert len(second_records) == 1, (
        f"expected exactly one artifact record on the repeat run too, got "
        f"{len(second_records)}; stdout: {second.stdout!r}"
    )
    assert second_records[0].get("artifact_id") == artifact_id, (
        f"expected a stable/deterministic artifact_id across repeat runs on "
        f"the same input (PRD §8 P0-5 read together with P0-4's 'stable' "
        f"precedent for chunk_id), got {artifact_id!r} on the first run and "
        f"{second_records[0].get('artifact_id')!r} on the second run"
    )


def test_artifacts_hard_errors_on_a_role_absent_from_the_schema():
    in_schema_roles = _in_schema_artifact_roles()
    assert BOGUS_ROLE not in in_schema_roles, (
        f"test setup invariant broken: {BOGUS_ROLE!r} must not be a real "
        f"schema value, but the schema's artifact_role axis is "
        f"{sorted(in_schema_roles)}"
    )
    _place_tree_fixture(PROSE_AND_TABLE_PDF, PROSE_AND_TABLE_TREE_FIXTURE)

    result = _run_artifacts(
        str(PROSE_AND_TABLE_PDF),
        extra_env={STUB_ARTIFACT_ROLE_ENV_VAR: BOGUS_ROLE},
    )
    _assert_not_argparse_fallback(result)

    assert result.returncode != 0, (
        f"expected a non-zero exit code when the stub returns an "
        f"out-of-schema artifact_role ({BOGUS_ROLE!r}) -- PRD §8 P0-5/P0-6, "
        f"'a tag not in the schema is a hard error, not a silent pass' -- "
        f"got exit code 0\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    assert "Traceback (most recent call last)" not in result.stderr, (
        f"expected a clear, handled error message naming the offending role, "
        f"not a bare Python traceback; stderr: {result.stderr!r}"
    )

    stderr_lower = result.stderr.lower()
    assert BOGUS_ROLE.lower() in stderr_lower, (
        f"expected the error message to name the offending role "
        f"({BOGUS_ROLE!r}) so a human can tell what went wrong, got stderr: "
        f"{result.stderr!r}"
    )
    assert "artifact_role" in stderr_lower or "schema" in stderr_lower, (
        f"expected the error message to name the axis ('artifact_role') or "
        f"reference the schema, not just the bare bad value, got stderr: "
        f"{result.stderr!r}"
    )
