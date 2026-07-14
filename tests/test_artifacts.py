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

import axial.artifacts as artifacts_module
import axial.chunk as chunk_module
from axial.chunk import HashingEmbedder, run_chunk_embedding
from axial.envelope import compute_source_id
from axial.llm import ARTIFACTS_PASS_NAME
from axial.schema import load_schema

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


# ===========================================================================
# Outer acceptance test for issue #168 (source-router slice 03:
# artifact-caption-routing).
#
# Locked behavioral contract (DEC-1) -- do not edit once committed red.
#
# Spec: plans/source-router/03-artifact-caption-routing.md; PRD §7.8 (source
# router), §5 stage 5 / §7.2 (artifact notes). The artifact pass collects
# artifact-routed blocks (table/picture become vault artifact notes as
# today); a `caption` block attaches to its figure/table -- its text rides
# on that artifact's own record rather than being lost or chunked.
# Apparatus-routed blocks (document_index, footnote) are never picked up as
# artifacts.
#
# Acceptance criterion (issue #168 plan)
# ---------------------------------------------------------------------
# Given a persisted tree with a captioned figure, a table, a
#       table-of-contents (document_index), and an endnotes (footnote)
#       section
# When  the operator runs `axial artifacts` on the source
# Then  the figure and the table each become one vault artifact note
# And   the figure's artifact note carries its caption text (attached, not
#       lost)
# And   no artifact note is produced for the document_index or footnote
#       blocks
# And   the caption is absent from data/chunks/<source_id>.jsonl
#       (established in slice 02, still true)
#
# As of this commit, `_artifact_nodes_with_section` scans raw
# `type == "artifact"` nodes only; a `caption` node is `type == "prose"`
# (label `"caption"`) and is therefore INVISIBLE to that scan -- its text
# never reaches the figure's record at all. This test is expected to fail
# red on exactly that: the figure's artifact record carries no trace of its
# caption's own sentinel text. It must not fail on an import error, a
# fixture-arrangement error, or a call-signature mismatch.
#
# Seam decision 1 -- bypassing docling entirely via a monkeypatched
# `axial.artifacts.extract`, calling `run_artifacts` directly
# ---------------------------------------------------------------------
# Mirrors tests/test_tag_artifacts_input_guard.py's own artifacts-pass seam
# (issue #132) exactly: `run_artifacts` imports `extract` directly into its
# own module namespace, so monkeypatching `axial.artifacts.extract` redirects
# every call to a fake returning a hand-built, synthetic extraction tree --
# no real PDF, no docling, no network. This is a deliberately LIGHTER-weight
# harness than this file's other (subprocess + real-PDF-fixture) tests
# above, chosen because this slice's whole point is the tree-node
# collection/attachment logic inside `run_artifacts` itself, not CLI wiring
# or a real docling conversion (which #30/#32's own tests already cover).
#
# Seam decision 2 -- a counting LLM client answering deterministically valid
# ---------------------------------------------------------------------
# Mirrors tests/test_tag_artifacts_input_guard.py's `_ArtifactsCountingClient`
# exactly: a fake client returning a well-formed, schema-valid classification
# from the REAL loaded domain (config/domains/syria) every time. Since the
# response is always valid, no bounded correction re-ask ever fires, so a
# call count of "one call per genuine artifact node (table + picture)" is a
# direct, implementation-agnostic proof that the caption -- never itself a
# classified artifact, only attached metadata -- is not separately sent to
# the model.
#
# Seam decision 3 -- the caption-attachment assertion stays agnostic to the
# exact field name the implementer chooses
# ---------------------------------------------------------------------
# Neither the plan nor the PRD names an exact field for "the caption text
# riding on the figure's record" (the plan explicitly leaves this to the
# implementer). This test therefore does not hardcode a new field name (e.g.
# "caption") -- it asserts the OBSERVABLE behavior the acceptance criterion
# actually requires: the caption's own distinctive sentinel text appears
# SOMEWHERE among the figure record's own string values (recursively, since
# an implementer might nest it under a dict/list), while the same sentinel
# text is absent from the table's record (the caption is adjacent to the
# figure only, in this fixture, so it must not "leak" onto an unrelated
# artifact).
#
# Seam decision 4 -- the chunk-absence clause reuses slice 02's own patch
# seam directly, on the SAME synthetic tree
# ---------------------------------------------------------------------
# tests/test_source_router.py's own `_patch_tree` helper (issue #167)
# monkeypatches `axial.chunk.tree_path`/`axial.chunk.load_persisted_tree` to
# feed `run_chunk_embedding` a synthetic tree with no docling/network. This
# test reuses that exact mechanism (inlined here, not imported cross-file,
# to keep this file's own contract self-contained) against the SAME tree
# fixture used for `run_artifacts` above, to lock the Gherkin's final
# "still true" clause without inventing a second fixture or a heavier
# integration. This part of the assertion is expected to already hold today
# (slice 02 is merged) -- it is included as a regression lock, not as this
# test's primary source of redness (see the caption-attachment assertion
# above for that).
#
# Test hygiene: every path this test touches (the synthetic source file,
# chunks_dir) lives under pytest's own tmp_path, outside this repo entirely
# -- nothing here reads or writes any real data/ directory (both `extract`
# and `tree_path`/`load_persisted_tree` are monkeypatched out entirely), and
# no real LLM/network/docling call is ever made.
# ===========================================================================

_ARTIFACT_ROUTING_DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"

_ROUTING_PROSE_BODY = (
    "Ordinary prose sentinel discussing the excavation's overall stratigraphic "
    "sequence across the three seasons of fieldwork in careful detail."
)
_ROUTING_TABLE_BODY = (
    "Table sentinel: quarterly summary of measured artifact counts across "
    "the three excavation trenches, tallied by depth and material type."
)
_ROUTING_FIGURE_BODY = "Figure node placeholder text (docling picture item)."
_ROUTING_CAPTION_BODY = (
    "Caption sentinel: aerial photograph of the northern excavation trench "
    "taken during the spring survey season by the site photographer."
)
_ROUTING_TOC_BODY = (
    "Table-of-contents sentinel entry: Chapter One .. 1, Chapter Two .. 40, "
    "Appendix .. 88, listing every part of the report in reading order."
)
_ROUTING_FOOTNOTE_BODY = (
    "Footnote sentinel: see supplementary note four for the full derivation "
    "of the radiocarbon calibration used throughout this report."
)


def _build_caption_routing_tree() -> dict:
    """A tree with, in one prose section: ordinary prose, a table, a
    captioned figure (caption immediately follows the figure -- the natural
    reading-order adjacency), and a document_index (TOC) block; and, in a
    second section, a footnote (endnotes) block -- mirroring the Gherkin's
    "captioned figure, a table, a table-of-contents, and an endnotes
    section" verbatim."""
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Findings",
                "label": "section_header",
                "children": [
                    {
                        "type": "prose",
                        "order": "1.1",
                        "label": "text",
                        "text": _ROUTING_PROSE_BODY,
                    },
                    {
                        "type": "artifact",
                        "order": "1.2",
                        "label": "table",
                        "text": _ROUTING_TABLE_BODY,
                    },
                    {
                        "type": "artifact",
                        "order": "1.3",
                        "label": "picture",
                        "text": _ROUTING_FIGURE_BODY,
                    },
                    {
                        "type": "prose",
                        "order": "1.4",
                        "label": "caption",
                        "text": _ROUTING_CAPTION_BODY,
                    },
                    {
                        "type": "prose",
                        "order": "1.5",
                        "label": "document_index",
                        "text": _ROUTING_TOC_BODY,
                    },
                ],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Endnotes",
                "label": "section_header",
                "children": [
                    {
                        "type": "prose",
                        "order": "2.1",
                        "label": "footnote",
                        "text": _ROUTING_FOOTNOTE_BODY,
                    },
                ],
            },
        ]
    }


def _stub_artifact_payload() -> str:
    """A complete, schema-valid artifacts-pass response, built from the REAL
    loaded schema's own vocabulary at test time -- never a hardcoded tag id
    (mirrors tests/test_tag_artifacts_input_guard.py's own
    `_valid_artifact_payload`)."""
    schema = load_schema(_ARTIFACT_ROUTING_DOMAIN_DIR)
    role = next(iter(schema.axes["artifact_role"].tag_ids))
    field_primary = next(iter(schema.axes["field"].tag_ids))
    return json.dumps({"artifact_role": role, "field": {"primary": field_primary, "secondary": []}})


class _RoutingCountingClient:
    """Fake LLMClient: counts every artifacts-pass call made, always
    answering with a well-formed, schema-valid classification (see module
    docstring above, seam decision 2)."""

    def __init__(self, payload: str):
        self.prompts: list[str] = []
        self._payload = payload

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        assert pass_name == ARTIFACTS_PASS_NAME, (
            f"expected pass_name={ARTIFACTS_PASS_NAME!r}, got {pass_name!r}"
        )
        self.prompts.append(prompt)
        return self._payload

    @property
    def call_count(self) -> int:
        return len(self.prompts)


def _record_contains_text(value: object, text: str) -> bool:
    """Recursively scan `value` (a JSON-shaped artifact record: nested
    dicts/lists/strings) for `text` appearing as a substring of any string
    it contains -- deliberately field-name-agnostic (see module docstring
    above, seam decision 3): the implementer is free to choose whatever key
    carries the attached caption text."""
    if isinstance(value, str):
        return text in value
    if isinstance(value, dict):
        return any(_record_contains_text(v, text) for v in value.values())
    if isinstance(value, list):
        return any(_record_contains_text(v, text) for v in value)
    return False


def test_captioned_figure_and_table_become_artifact_notes_apparatus_excluded(tmp_path, monkeypatch):
    tree = _build_caption_routing_tree()
    monkeypatch.setattr(artifacts_module, "extract", lambda path: tree)

    source_path = tmp_path / "artifact_caption_routing_source.txt"
    source_path.write_text("issue 168 artifact caption routing test source", encoding="utf-8")
    source_id = compute_source_id(source_path)

    payload = _stub_artifact_payload()
    client = _RoutingCountingClient(payload)

    records = artifacts_module.run_artifacts(
        source_path, client=client, domain_dir=_ARTIFACT_ROUTING_DOMAIN_DIR
    )

    assert isinstance(records, list), (
        f"expected run_artifacts to return a list, got {type(records).__name__}: {records!r}"
    )

    table_artifact_id = f"{source_id}_art_1.2"
    figure_artifact_id = f"{source_id}_art_1.3"

    # --- exactly one artifact note per figure/table; the TOC and footnote
    # blocks never become artifact notes at all ------------------------------
    assert len(records) == 2, (
        f"expected exactly one artifact note for the table and one for the "
        f"figure (two total) -- the document_index and footnote blocks must "
        f"never become artifact notes, and the caption must attach to the "
        f"figure rather than becoming a THIRD, standalone artifact note -- "
        f"got {len(records)} records: {records!r}"
    )

    ids_seen = {r.get("artifact_id") for r in records}
    assert ids_seen == {table_artifact_id, figure_artifact_id}, (
        f"expected artifact_ids {{{table_artifact_id!r}, {figure_artifact_id!r}}} "
        f"(table + figure only), got {sorted(ids_seen)!r}. Full records: {records!r}"
    )

    table_record = next(r for r in records if r.get("artifact_id") == table_artifact_id)
    figure_record = next(r for r in records if r.get("artifact_id") == figure_artifact_id)

    # --- the figure's artifact note carries its caption text (attached,
    # not lost) -- the genuinely NEW behavior this slice delivers, and this
    # test's primary source of redness today -----------------------------
    assert _record_contains_text(figure_record, _ROUTING_CAPTION_BODY), (
        f"expected the figure's own artifact record to carry its caption's "
        f"text SOMEWHERE among its own string values (PRD/plan: 'the "
        f"caption attached, not lost') -- today `_artifact_nodes_with_section` "
        f"only scans raw type=='artifact' nodes, and a caption is "
        f"type=='prose' (label=='caption'), so it is invisible to that scan "
        f"and its text never reaches the figure's record at all. Figure "
        f"record: {figure_record!r}"
    )

    # --- the caption must not leak onto the UNRELATED table's record too
    # (it is adjacent to the figure only, in this fixture) ------------------
    assert not _record_contains_text(table_record, _ROUTING_CAPTION_BODY), (
        f"expected the caption's text to attach to the FIGURE only (it is "
        f"adjacent to the figure, not the table, in this fixture), but "
        f"found it on the table's own record too: {table_record!r}"
    )

    # --- no artifact note for the document_index or footnote blocks --------
    for record in records:
        assert not _record_contains_text(record, _ROUTING_TOC_BODY), (
            f"expected the document_index (TOC) block's own text to never "
            f"appear on any artifact record (it is apparatus, never "
            f"artifact-noted), but found it on: {record!r}"
        )
        assert not _record_contains_text(record, _ROUTING_FOOTNOTE_BODY), (
            f"expected the footnote (endnotes) block's own text to never "
            f"appear on any artifact record (it is apparatus, never "
            f"artifact-noted), but found it on: {record!r}"
        )

    # --- the caption is never itself sent to the model as a distinct
    # artifact to classify (it attaches as metadata, it is not classified
    # on its own) -- exactly one LLM call per genuine artifact node
    # (table + picture) -------------------------------------------------
    assert client.call_count == 2, (
        f"expected exactly 2 LLM calls (one for the table, one for the "
        f"figure) -- the caption is attached metadata, never itself a "
        f"separately classified artifact -- got {client.call_count}"
    )

    # --- the caption is absent from data/chunks/<source_id>.jsonl
    # (established in slice 02, still true) ------------------------------
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(json.dumps(tree), encoding="utf-8")
    monkeypatch.setattr(chunk_module, "tree_path", lambda source_id: tree_file)
    monkeypatch.setattr(chunk_module, "load_persisted_tree", lambda path: tree)

    chunks_dir = tmp_path / "chunks"
    chunk_records = run_chunk_embedding(
        source_path, embedder=HashingEmbedder(), chunks_dir=chunks_dir
    )

    leaked_caption = [r for r in chunk_records if _ROUTING_CAPTION_BODY in r.get("text", "")]
    assert not leaked_caption, (
        f"expected the caption to remain absent from the emitted chunks "
        f"(slice 02's own invariant, still true): found it in {leaked_caption!r}"
    )


# ===========================================================================
# Regression test for issue #172 follow-up (PR #180 fix-lane): a fallback-
# path 'FigureCaption' block must attach to its preceding artifact
#
# Locked behavioral contract (DEC-1) -- do not edit once committed red.
#
# Spec: `specs/PRODUCT.md` §7.8 / §7.2 (a caption attaches to the nearest
# preceding table/picture; its text rides on that artifact's own record
# rather than being lost, chunked, or classified as its own standalone
# artifact). On the docling extraction path a caption block's `label` is
# the lowercase `"caption"` token, and `axial.artifacts._artifact_nodes_
# with_section`/`_attach_captions` correctly recognize it (issue #168,
# proven by `test_captioned_figure_and_table_become_artifact_notes_
# apparatus_excluded` above). On the Unstructured FALLBACK extraction path
# (P0-2), the same semantic block instead carries the raw Unstructured
# `element.category` spelling `"FigureCaption"` as its `label`. `axial.
# router.route_for` already normalizes `"FigureCaption"` to ARTIFACT (issue
# #172's alias table maps `"figurecaption"` -> `"caption"`), so the block IS
# collected by `_routed_artifact_blocks` -- but `_artifact_nodes_with_
# section` (`node.get("label") != "caption"`) and `_attach_captions`
# (`node.get("label") == "caption"`) both compare the RAW label literally,
# never through the router's own canonical-token normalization, so a
# `"FigureCaption"` node is treated as a genuine standalone artifact instead
# of an attaching caption: it is sent to the model as its own artifact and
# produces its own artifact record, and its text never reaches the
# preceding figure's record at all. This test pins the fallback-path
# behavior the fix must deliver (attach, not stand alone) while a sibling
# test locks that the existing docling lowercase-'caption' path keeps
# working identically -- so the fix can't regress the primary path while
# fixing the fallback one.
#
# Seam decision -- reuses this file's own `_build_caption_routing_tree`-
# style monkeypatched-`extract` seam and the module-level `_stub_artifact_
# payload`/`_RoutingCountingClient` helpers directly, on a smaller
# purpose-built two-node tree (one picture, one immediately-following
# caption block) -- the minimal fixture that isolates the attach/no-attach
# behavior without the TOC/footnote apparatus noise the larger #168 fixture
# above already covers.
# ===========================================================================

_ATTACH_FIGURE_BODY = (
    "Attach-regression figure sentinel: cross-section diagram of the "
    "eastern trench wall showing the three distinct stratigraphic layers."
)
_ATTACH_CAPTION_BODY = (
    "Attach-regression caption sentinel: cross-section diagram annotated "
    "with layer boundaries, drawn by the site surveyor after the final dig."
)


def _build_single_captioned_figure_tree(caption_label: str) -> dict:
    """A minimal tree: one section holding one picture immediately followed
    by one caption block carrying `caption_label` as its own `label` --
    isolates the attach/no-attach behavior for exactly that label spelling,
    independent of any TOC/footnote apparatus noise."""
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Findings",
                "label": "section_header",
                "children": [
                    {
                        "type": "artifact",
                        "order": "1.1",
                        "label": "picture",
                        "text": _ATTACH_FIGURE_BODY,
                    },
                    {
                        "type": "prose",
                        "order": "1.2",
                        "label": caption_label,
                        "text": _ATTACH_CAPTION_BODY,
                    },
                ],
            },
        ]
    }


def _run_single_captioned_figure_case(tmp_path, monkeypatch, caption_label: str):
    """Shared arrange+act for the attach-regression cases below: builds a
    single-picture-plus-caption tree with `caption_label`, runs
    `run_artifacts` against it via the monkeypatched-`extract` seam, and
    returns `(records, client, source_id)` for the caller's own
    label-specific assertions."""
    tree = _build_single_captioned_figure_tree(caption_label)
    monkeypatch.setattr(artifacts_module, "extract", lambda path: tree)

    source_path = tmp_path / f"attach_regression_source_{caption_label}.txt"
    source_path.write_text(
        f"issue #172 follow-up attach-regression source ({caption_label})",
        encoding="utf-8",
    )
    source_id = compute_source_id(source_path)

    payload = _stub_artifact_payload()
    client = _RoutingCountingClient(payload)

    records = artifacts_module.run_artifacts(
        source_path, client=client, domain_dir=_ARTIFACT_ROUTING_DOMAIN_DIR
    )
    return records, client, source_id


def test_fallback_figurecaption_label_attaches_to_preceding_figure(tmp_path, monkeypatch):
    """The FALLBACK-path spelling ('FigureCaption', raw Unstructured
    element.category) must attach to its preceding figure exactly like the
    docling lowercase 'caption' spelling does -- not become its own
    standalone artifact record. Expected to FAIL today: two records (the
    figure PLUS a standalone 'FigureCaption' artifact) and two LLM calls,
    because `_artifact_nodes_with_section`/`_attach_captions` compare the
    raw label literally against `"caption"` rather than through the
    router's own normalization."""
    records, client, source_id = _run_single_captioned_figure_case(
        tmp_path, monkeypatch, "FigureCaption"
    )

    figure_artifact_id = f"{source_id}_art_1.1"

    assert len(records) == 1, (
        f"expected exactly ONE artifact record (the figure, with the "
        f"'FigureCaption' block's text attached) -- not a second, standalone "
        f"artifact record for the caption block itself -- got {len(records)} "
        f"records: {records!r}"
    )

    figure_record = records[0]
    assert figure_record.get("artifact_id") == figure_artifact_id, (
        f"expected the sole artifact record to be the figure "
        f"({figure_artifact_id!r}), got {figure_record.get('artifact_id')!r} "
        f"-- full record: {figure_record!r}"
    )

    assert _record_contains_text(figure_record, _ATTACH_CAPTION_BODY), (
        f"expected the figure's own artifact record to carry the "
        f"'FigureCaption' block's text SOMEWHERE among its own string "
        f"values (attached, not lost, not standalone) -- got: "
        f"{figure_record!r}"
    )

    assert client.call_count == 1, (
        f"expected exactly ONE artifacts-pass LLM call (the figure only) -- "
        f"the 'FigureCaption' block must never be sent to the model as its "
        f"own distinct artifact to classify -- got {client.call_count} calls"
    )


def test_docling_lowercase_caption_label_still_attaches_to_preceding_figure(tmp_path, monkeypatch):
    """Regression guard: the existing docling lowercase 'caption' spelling
    must keep attaching identically -- this sibling case must stay GREEN
    both before and after the fallback-label fix above, proving the fix
    cannot regress the primary path while it corrects the fallback one."""
    records, client, source_id = _run_single_captioned_figure_case(tmp_path, monkeypatch, "caption")

    figure_artifact_id = f"{source_id}_art_1.1"

    assert len(records) == 1, (
        f"expected exactly ONE artifact record (the figure, with the "
        f"lowercase 'caption' block's text attached), got {len(records)} "
        f"records: {records!r}"
    )

    figure_record = records[0]
    assert figure_record.get("artifact_id") == figure_artifact_id, (
        f"expected the sole artifact record to be the figure "
        f"({figure_artifact_id!r}), got {figure_record.get('artifact_id')!r} "
        f"-- full record: {figure_record!r}"
    )

    assert _record_contains_text(figure_record, _ATTACH_CAPTION_BODY), (
        f"expected the figure's own artifact record to carry the lowercase "
        f"'caption' block's text SOMEWHERE among its own string values, "
        f"got: {figure_record!r}"
    )

    assert client.call_count == 1, (
        f"expected exactly ONE artifacts-pass LLM call (the figure only), "
        f"got {client.call_count} calls"
    )
