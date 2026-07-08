"""Outer acceptance test for issue #27, slice 01 (tag spine -- role_in_argument,
schema-driven, hard-error, versioned).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given an extracted fixture source with a stored envelope and its chunk
      records, and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial tag <fixture>`
Then  it exits 0 and emits one tagged record per chunk as JSON
And   each record carries a `role_in_argument` value drawn from the schema's
      role_in_argument axis
And   each record carries the `schema_version` it was tagged under, plus its
      chunk_id and section provenance

See specs/PRODUCT.md §5 stage 6 ("Tagging. Each prose chunk is tagged on the
axes the schema declares ... plus a role-in-argument tag and three-level
metadata. Output: fully tagged chunks.") and §7.1 (loader contract: "Every
tag applied by the tagger must exist in the loaded schema. A tag not in the
schema is a hard error, not a silent pass."; "The schema carries a `version`
field; every note written records the schema version it was tagged under,
so a later schema change is detectable per note."). Plan:
plans/tag/01-tag-spine-single.md.

Fixture reuse: tests/fixtures/envelope/thesis_paper.pdf (see
tests/test_envelope.py and its _generate.py, and tests/test_chunk.py, which
already exercises this fixture's three top-level sections -- Introduction,
Comparative Cases, Conclusion -- through the chunking pass). No new fixture
is needed: this slice's acceptance criterion is about the shape of tagged
output records, not about any particular fixture content.

Seam decision 1 -- reusing `stub`, and the tag-pass response collision
-----------------------------------------------------------------------
tests/test_chunk.py already locked `AXIAL_LLM_PROVIDER=stub` as a dual-shaped
canned client: `pass_name="chunk"` gets a chunk-shaped response, anything
else (originally just the envelope pass) gets the envelope-shaped one. Slice
01's plan calls for the tag pass to make its own LLM call per chunk with a
NEW `pass_name="tag"` (see plans/tag/01-tag-spine-single.md, "Goal"). Today's
`StubLLMClient` has no tag-shaped canned response, so a single `axial tag
<fixture>` run under `AXIAL_LLM_PROVIDER=stub` cannot yet complete
end-to-end: the internal chunking sub-pass needs its existing chunk-shaped
response, AND each subsequent tag call needs a new tag-shaped response
distinguishable from both the chunk- and envelope-shaped ones by the same
`pass_name` dispatch mechanism. This test does not dictate how that dispatch
extension is implemented -- only that `axial tag ...` works correctly
end-to-end against `AXIAL_LLM_PROVIDER=stub` in one process, driving both
the chunk-pass and tag-pass calls through that one stub selection. Resolving
that collision is this test's whole point, exactly as test_chunk.py's own
seam decision 1 resolved the envelope/chunk collision before it.

Seam decision 2 -- role_in_argument vocabulary and schema_version loaded at
test time, never hardcoded
-----------------------------------------------------------------------
The spec (§7.1) requires every applied tag to exist in the loaded schema and
every tagged record to carry the schema version it was tagged under. Locking
the literal vocabulary (e.g. "role:claim") or the literal version string
(e.g. "0.1") into this test would make an ordinary schema.yaml edit silently
break the acceptance contract, and would additionally risk locking a
specific stub-chosen tag value into the contract the way test_envelope.py's
seam decision 3 warns against for stub wording. Instead this test calls
`axial.schema.load_schema("config/domains/syria")` itself, at test time, and
asserts every tagged record's `role_in_argument` is a MEMBER of the loaded
schema's `role_in_argument` axis tag-id set, and every record's
`schema_version` equals the loaded schema's own `version` field (coerced to
the same string form `load_schema` itself returns). This is the same domain
directory `axial tag`'s planned default resolves to (see the slice plan,
"Boundary / endpoint": "default domain config/domains/syria").

Seam decision 3 -- "one tagged record per chunk" proven behaviorally, not by
a hardcoded count
-----------------------------------------------------------------------
The plan states `axial tag` runs the argumentative-chunking pass internally,
then makes one LLM tag call per resulting chunk. Rather than hardcoding how
many chunks the stub-driven chunking pass produces for this fixture (an
implementation/stub-wording detail this test must not over-commit, mirroring
test_chunk.py's own refusal to assert exact chunk text/count), this test
independently runs `axial chunk <fixture>` (stub) to obtain the chunk_id set
the chunking pass produces for this input, then asserts the SAME set of
chunk_ids appears, with no drops and no duplicates, across the tagged
records emitted by a separate `axial tag <fixture>` run. Chunk_ids are
already locked as stable/deterministic across repeat runs on the same input
by test_chunk.py, so this equality check is a valid behavioral proof that
every chunk got exactly one tagged record -- not an accident of stub
internals.

Seam decision 4 -- tagged record shape locked by this test
-----------------------------------------------------------------------
Neither the PRD nor the slice plan names an exact stdout envelope shape for
tagged records, so -- mirroring test_chunk.py's seam decision 4 exactly --
this test tolerates any of the same three stdout shapes (bare JSON array,
JSON object with a top-level "records" or "tags" key, or newline-delimited
JSON) via a parsing helper. Field names locked to the minimum the
acceptance criterion needs to be executable: `role_in_argument` (named
verbatim by the Gherkin and the PRD), `schema_version` (named verbatim by
the Gherkin and PRD §7.1), `chunk_id` and `section` (both already locked
field names from the chunk-record contract in tests/test_chunk.py's seam
decision 4 -- this test requires the SAME field names to be preserved as
"provenance" on the tagged record, per the Gherkin's "plus its chunk_id and
section provenance"). This test deliberately does NOT assert: exact chunk
text/count, exact stub wording, which specific role value the stub returns
(only that it is in-schema), or any prompt-observation -- this acceptance
criterion is about output records, not prompt contents, so no `record`
provider is used here.

Test hygiene: any envelope file this test creates under data/envelopes/ is
removed in fixture teardown (mirrors tests/test_chunk.py's clean_envelopes).
Tagged records and chunk records are stdout-only; nothing else is written to
the repo.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from axial.schema import load_schema

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
ENVELOPES_DIR = REPO_ROOT / "data" / "envelopes"
DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# argparse's fallback error for an as-yet-nonexistent subcommand, e.g.
# "axial: error: argument command: invalid choice: 'tag' (choose from
# 'schema', 'intake', 'extract', 'envelope', 'chunk', 'vault')". Any of these
# substrings in the combined output means the target subcommand's logic was
# never actually exercised -- the process failed before real behavior ran.
# Reject that generic failure mode explicitly so this test can only pass once
# real `tag` behavior exists.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_axial(
    command: str,
    provider: str,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["uv", "run", "axial", command, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_envelope(provider: str, *args: str) -> subprocess.CompletedProcess:
    return _run_axial("envelope", provider, *args)


def _run_chunk(provider: str, *args: str) -> subprocess.CompletedProcess:
    return _run_axial("chunk", provider, *args)


def _run_tag(provider: str, *args: str) -> subprocess.CompletedProcess:
    return _run_axial("tag", provider, *args)


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess, command: str) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `{command}` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `{command}` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _existing_envelope_files() -> set[Path]:
    if not ENVELOPES_DIR.exists():
        return set()
    return set(ENVELOPES_DIR.glob("*.json"))


def _parse_records(stdout: str, container_keys: tuple[str, ...]) -> list[dict]:
    """Parse output records from an axial subcommand's stdout, tolerating a
    bare JSON array, a JSON object with one of `container_keys` as a
    top-level array, or newline-delimited JSON (one record per line). Mirrors
    tests/test_chunk.py's `_parse_chunk_records` (seam decision 4)."""
    stripped = stdout.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None

    if data is not None:
        if isinstance(data, dict):
            found_key = next((key for key in container_keys if key in data), None)
            assert found_key is not None, (
                f"expected a top-level key among {container_keys} when stdout "
                f"is a JSON object, got keys: {sorted(data.keys())}; stdout: {stdout!r}"
            )
            records = data[found_key]
        else:
            records = data
        assert isinstance(records, list), (
            f"expected records to be a JSON array (bare, or under one of "
            f"{container_keys}), got {type(records).__name__}: {records!r}"
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
                f"expected stdout to be either one parseable JSON document "
                f"(a bare array, or an object with a top-level array under "
                f"one of {container_keys}) or newline-delimited JSON (one "
                f"record object per line); line {line!r} failed to parse "
                f"({exc}). Full stdout: {stdout!r}"
            ) from None
    assert records, (
        f"expected at least one parseable record in stdout, got none. stdout: {stdout!r}"
    )
    return records


def _parse_chunk_records(stdout: str) -> list[dict]:
    return _parse_records(stdout, ("chunks",))


def _parse_tag_records(stdout: str) -> list[dict]:
    return _parse_records(stdout, ("records", "tags", "chunks"))


@pytest.fixture
def clean_envelopes():
    """Snapshot data/envelopes/*.json before the test and delete any file
    the test caused to appear, so runs stay idempotent and the repo is never
    polluted by a real e2e-run artifact."""
    before = _existing_envelope_files()
    yield
    after = _existing_envelope_files()
    for created in after - before:
        created.unlink()


def _arrange_stored_envelope() -> Path:
    """Run `axial envelope` with the stub provider so a stored envelope
    exists on disk before tagging, and return its path. Asserts the arrange
    step itself succeeded and produced exactly one new envelope file."""
    before_files = _existing_envelope_files()

    result = _run_envelope("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(result, "envelope")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` on "
        f"the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    new_files = _existing_envelope_files() - before_files
    assert len(new_files) == 1, (
        f"arrange step failed: expected exactly one new file under "
        f"{ENVELOPES_DIR} after `axial envelope`, got {len(new_files)}: "
        f"{sorted(new_files)}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    return next(iter(new_files))


def test_tag_emits_one_schema_valid_versioned_record_per_chunk(clean_envelopes):
    envelope_path = _arrange_stored_envelope()

    # --- independently obtain the chunk_id set the chunking pass produces
    # for this fixture, to check against below without hardcoding a count ---
    chunk_result = _run_chunk("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(chunk_result, "chunk")
    assert chunk_result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial chunk` on the "
        f"fixture with the stub LLM provider, got {chunk_result.returncode}\n"
        f"stdout: {chunk_result.stdout!r}\nstderr: {chunk_result.stderr!r}"
    )
    chunk_records = _parse_chunk_records(chunk_result.stdout)
    expected_chunk_ids = [r.get("chunk_id") for r in chunk_records]
    assert expected_chunk_ids and all(expected_chunk_ids), (
        f"arrange step failed: expected `axial chunk` to emit chunk records "
        f"each carrying a non-empty chunk_id, got: {chunk_records!r}"
    )

    # --- load the schema at test time: never hardcode the role_in_argument
    # vocabulary or the version literal into this test (seam decision 2) ---
    schema = load_schema(str(DOMAIN_DIR))
    valid_roles = schema.axes["role_in_argument"].tag_ids
    assert valid_roles, "arrange step failed: schema's role_in_argument axis has no tag ids"
    expected_schema_version = schema.version

    # --- the acceptance criterion itself: `axial tag <fixture>` ---
    tag_result = _run_tag("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(tag_result, "tag")
    assert tag_result.returncode == 0, (
        f"expected exit code 0 for `axial tag` on a fixture source with a "
        f"stored envelope and the stub LLM provider configured, got "
        f"{tag_result.returncode}\nstdout: {tag_result.stdout!r}\n"
        f"stderr: {tag_result.stderr!r}"
    )

    tag_records = _parse_tag_records(tag_result.stdout)
    assert tag_records, (
        f"expected at least one tagged record on stdout, got none; stdout: {tag_result.stdout!r}"
    )

    tag_chunk_ids: list[str] = []
    for record in tag_records:
        assert isinstance(record, dict), (
            f"expected each tagged record to be a JSON object, got "
            f"{type(record).__name__}: {record!r}"
        )

        chunk_id = record.get("chunk_id")
        assert isinstance(chunk_id, str) and chunk_id.strip(), (
            f"expected tagged record to carry a non-empty string 'chunk_id' "
            f"(Gherkin: 'plus its chunk_id and section provenance'), got "
            f"{chunk_id!r} (full record: {record!r})"
        )
        tag_chunk_ids.append(chunk_id)

        section = record.get("section")
        assert isinstance(section, str) and section.strip(), (
            f"expected tagged record to carry a non-empty string 'section' "
            f"(Gherkin: 'plus its chunk_id and section provenance'), got "
            f"{section!r} (full record: {record!r})"
        )

        role = record.get("role_in_argument")
        assert role in valid_roles, (
            f"expected tagged record's 'role_in_argument' to be a member of "
            f"the schema's role_in_argument tag set {sorted(valid_roles)} "
            f"(PRD §7.1, 'every tag applied by the tagger must exist in the "
            f"loaded schema'), got {role!r} (full record: {record!r})"
        )

        record_schema_version = record.get("schema_version")
        assert str(record_schema_version) == str(expected_schema_version), (
            f"expected tagged record's 'schema_version' to equal the loaded "
            f"schema's own version {expected_schema_version!r} (PRD §7.1, "
            f"'every note written records the schema version it was tagged "
            f"under'), got {record_schema_version!r} (full record: {record!r})"
        )

    # --- "one tagged record per chunk": no drops, no duplicates, tied to
    # the independently-obtained chunk_id set (seam decision 3) ---
    assert sorted(tag_chunk_ids) == sorted(expected_chunk_ids), (
        f"expected exactly one tagged record per chunk_id emitted by "
        f"`axial chunk` on the same fixture (Gherkin: 'emits one tagged "
        f"record per chunk'), got tagged chunk_ids {sorted(tag_chunk_ids)} "
        f"vs. chunking-pass chunk_ids {sorted(expected_chunk_ids)}"
    )

    # --- the stored envelope itself must be untouched by tagging (it is
    # read, not recomputed -- PRD §10, mirrors test_chunk.py) ---
    assert envelope_path.exists(), (
        f"expected the stored envelope at {envelope_path} to still exist after `axial tag` ran"
    )
