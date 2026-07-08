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

Arrange-mechanism change (issue #45, tree-cache) -- no behavioral assertion
changed
-----------------------------------------------------------------------
This test's PURPOSE is the tagging pass's own behavior -- it CONSUMES the
stored envelope and this fixture's chunk records, never asserting anything
about extraction/tree shape itself (that is tests/test_extract.py's
contract). The arrange step's `axial envelope` call internally calls
`axial.extract.extract`, which -- per the now-locked tree-persist contract
(tests/test_tree_persist.py, PRD §7.4) -- reuses a persisted tree verbatim
at data/trees/<source_id>.json instead of re-running docling. So
`_arrange_stored_envelope` below now pre-places the committed REAL tree
fixture (tests/fixtures/envelope/thesis_paper_tree.json -- exactly `axial
extract`'s own output for this fixture, see that directory's _generate.py
for the regeneration recipe) before calling `axial envelope`, exactly as it
would look after a real extraction, only without paying for one. Every
existing assertion is unchanged. data/trees/ isolation is handled by the
shared, content-snapshot-based `_isolate_persisted_tree_and_envelope_state`
autouse fixture in tests/conftest.py.

---------------------------------------------------------------------------
Slice 02 (issue #28, plans/tag/02-scope-and-country.md) -- empirical_scope
axis + the scope:country-case `country` extra field
---------------------------------------------------------------------------

Given an extracted fixture source with a stored envelope and chunks,
      AXIAL_LLM_PROVIDER=stub returning empirical_scope=scope:country-case
      with country=Syria
When  the user runs `axial tag <fixture>`
Then  each record carries exactly one `empirical_scope` value drawn from
      the schema
And   a `scope:country-case` record carries a `country` drawn from the
      schema's country_list
And   a country-case with a missing or out-of-list country exits non-zero
      with a clear error

See specs/PRODUCT.md Appendix C (empirical-scope axis, single-cardinality,
with `scope:country-case`'s `country` extra field drawn from Appendix G's
`country_list`) and §7.1 ("a tag not in the schema is a hard error, not a
silent pass").

Seam decision 5 -- default stub tag response now carries empirical_scope +
country, agreed with the implementer as the fixed seam for this slice
-----------------------------------------------------------------------
The Gherkin's Given clause locks the stub's DEFAULT tag-shaped canned
response (see src/axial/llm.py's `_CANNED_TAG_RESPONSE`, dispatched by
`pass_name=TAG_PASS_NAME` exactly as slice 01's seam decision 1 describes)
to include `empirical_scope: "scope:country-case"` and `country: "Syria"`
alongside slice 01's `role_in_argument: "role:claim"`. That means a plain
`axial tag <fixture>` run under `AXIAL_LLM_PROVIDER=stub` -- no special env
-- is sufficient to exercise the happy path end-to-end, mirroring how
slice 01 needed no special env either. This test does not hardcode "Syria"
into any assertion (see seam decision 6); it only relies on the Given
clause's stub behavior to *produce* a country-case record to check against
the schema-loaded country_list.

To drive the two hard-error scenarios (missing / out-of-list country) end
to end via subprocess without a second stub client shape, the fixed seam
agreed with the implementer is the env var `AXIAL_STUB_TAG_RESPONSE`: when
set, the stub's tag-pass response becomes that raw JSON string verbatim
instead of the default canned one, letting this test drive exactly which
malformed tag payload the pipeline receives -- without this test asserting
anything about how the override is implemented internally, only that the
env var name and shape are honored end-to-end.

Seam decision 6 -- empirical_scope vocabulary and country_list loaded at
test time, never hardcoded (mirrors slice 01's seam decision 2)
-----------------------------------------------------------------------
Exactly as slice 01 refused to hardcode `role_in_argument` vocabulary, this
test never hardcodes `"scope:country-case"`, any other scope value, or any
country name as a *correctness* assertion. It calls `load_schema` at test
time and asserts every record's `empirical_scope` is a member of
`schema.axes["empirical_scope"].tag_ids`, and every country-case record's
`country` is a member of `schema.country_list`. The one place a literal
value is compared is in the two hard-error scenarios' fabricated
`AXIAL_STUB_TAG_RESPONSE` payloads themselves (test *input*, not a
correctness assertion about schema vocabulary) and in checking that the
CLI's error output actually names the offending out-of-list value the test
itself chose to inject -- that is an error-quality check ("clear error"
per the Gherkin), not a vocabulary hardcode.

Seam decision 7 -- "exactly one" enforced as a scalar, not a list
-----------------------------------------------------------------------
The Gherkin says "exactly one empirical_scope value", and Appendix C
declares `cardinality: single`. This test asserts `record["empirical_scope"]`
is itself a `str` (a single scalar tag id), not a list/array of one -- a
list-of-one would satisfy a naive "at least one, all in schema" check but
would misrepresent the axis's single-cardinality contract and silently
permit a future regression to multi-valued scope tagging.

Seam decision 8 -- error scenarios assert exit-code and message quality,
not exact wording
-----------------------------------------------------------------------
Mirroring this file's existing `_assert_not_argparse_fallback` discipline,
the two hard-error tests assert: (a) a non-zero exit code, (b) the combined
output carries none of `ARGPARSE_FALLBACK_MARKERS` (so a generic argparse
failure -- e.g. a malformed CLI invocation -- cannot masquerade as the real
country-validation error path), and (c) for the out-of-list case, that the
offending value itself ("Atlantis", chosen locally in that test, not a
module-level constant, since it is disposable test input rather than a
locked vocabulary term) appears in the combined stdout+stderr, proving the
error actually names what was wrong rather than failing generically. No
assertion pins the exact wording of the error message beyond that.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from axial.envelope import compute_source_id
from axial.schema import load_schema

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
ENVELOPES_DIR = REPO_ROOT / "data" / "envelopes"
TREES_DIR = REPO_ROOT / "data" / "trees"
DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# Slice 02's fixed seam (agreed with the implementer): when set, the stub's
# tag-pass response becomes this raw JSON string verbatim instead of the
# default canned tag response, so this test can drive malformed country-case
# payloads end-to-end via subprocess (seam decision 5).
STUB_TAG_RESPONSE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE"

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


def _run_tag(
    provider: str,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return _run_axial("tag", provider, *args, extra_env=extra_env)


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


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    data/trees/<source_id>.json (source_id via
    axial.envelope.compute_source_id) so `axial.extract.extract` reuses it
    verbatim instead of running docling (see module docstring, "Arrange-
    mechanism change"). Returns the tree path."""
    source_id = compute_source_id(source_pdf)
    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _arrange_stored_envelope() -> Path:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope exists on disk before tagging, and
    return its path. Asserts the arrange step itself succeeded and produced
    exactly one new envelope file."""
    _place_tree_fixture(THESIS_PAPER_PDF, THESIS_PAPER_TREE_FIXTURE)
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


def test_tag_assigns_single_in_schema_empirical_scope_and_country(clean_envelopes):
    """Slice 02 happy path (issue #28). Given the stub's default tag-pass
    response carries empirical_scope=scope:country-case with country=Syria
    (seam decision 5, the Gherkin's Given clause), a plain `axial tag
    <fixture>` run must emit records that each carry exactly one
    empirical_scope value drawn from the schema, and -- for a
    scope:country-case record -- a country drawn from the schema's
    country_list. Also checks slice 01's role_in_argument is not regressed."""
    _arrange_stored_envelope()

    # --- load the schema at test time: never hardcode the empirical_scope
    # vocabulary, the country_list, or the role_in_argument vocabulary
    # (seam decision 6) ---
    schema = load_schema(str(DOMAIN_DIR))
    valid_scopes = schema.axes["empirical_scope"].tag_ids
    assert valid_scopes, "arrange step failed: schema's empirical_scope axis has no tag ids"
    valid_roles = schema.axes["role_in_argument"].tag_ids
    assert valid_roles, "arrange step failed: schema's role_in_argument axis has no tag ids"
    valid_countries = schema.country_list
    assert valid_countries, "arrange step failed: schema's country_list is empty"

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

    country_case_seen = False
    for record in tag_records:
        assert isinstance(record, dict), (
            f"expected each tagged record to be a JSON object, got "
            f"{type(record).__name__}: {record!r}"
        )

        # --- exactly one empirical_scope value, a scalar, drawn from the
        # schema (Gherkin + seam decision 7) ---
        scope = record.get("empirical_scope")
        assert isinstance(scope, str), (
            f"expected tagged record's 'empirical_scope' to be a single "
            f"scalar string (Appendix C: cardinality 'single'; Gherkin: "
            f"'exactly one empirical_scope value'), got "
            f"{type(scope).__name__}: {scope!r} (full record: {record!r})"
        )
        assert scope in valid_scopes, (
            f"expected tagged record's 'empirical_scope' to be a member of "
            f"the schema's empirical_scope tag set {sorted(valid_scopes)} "
            f"(PRD §7.1, 'every tag applied by the tagger must exist in the "
            f"loaded schema'), got {scope!r} (full record: {record!r})"
        )

        # --- a scope:country-case record carries an in-list country ---
        if scope == "scope:country-case":
            country_case_seen = True
            country = record.get("country")
            assert isinstance(country, str) and country.strip(), (
                f"expected a scope:country-case tagged record to carry a "
                f"non-empty string 'country' (Appendix C/G, Gherkin: 'a "
                f"scope:country-case record carries a country drawn from "
                f"the schema's country_list'), got {country!r} (full "
                f"record: {record!r})"
            )
            assert country in valid_countries, (
                f"expected the country-case record's 'country' to be a "
                f"member of the schema's country_list {valid_countries!r}, "
                f"got {country!r} (full record: {record!r})"
            )
        else:
            assert "country" not in record or not record.get("country"), (
                f"expected a non-country-case tagged record to carry no "
                f"'country' field, got {record.get('country')!r} in a "
                f"{scope!r}-scoped record (full record: {record!r})"
            )

        # --- regression: slice 01's role_in_argument still present and
        # in-schema ---
        role = record.get("role_in_argument")
        assert role in valid_roles, (
            f"regression: expected tagged record's 'role_in_argument' to "
            f"still be a member of the schema's role_in_argument tag set "
            f"{sorted(valid_roles)} (slice 01 contract), got {role!r} "
            f"(full record: {record!r})"
        )

    # --- the Given clause locks the stub's default tag response to
    # scope:country-case/Syria, so at least one record must have exercised
    # the country-case branch above; otherwise this test would silently
    # never check the country assertions at all ---
    assert country_case_seen, (
        f"expected at least one tagged record with empirical_scope == "
        f"'scope:country-case' given the stub's default tag-pass response "
        f"(seam decision 5), got none among: {tag_records!r}"
    )


def test_tag_country_case_missing_country_errors_out(clean_envelopes):
    """Slice 02 error path (issue #28). A scope:country-case tag response
    with no `country` key at all is a hard error: `axial tag` must exit
    non-zero with a clear error, not silently pass or crash generically."""
    _arrange_stored_envelope()

    malformed_response = json.dumps(
        {
            "role_in_argument": "role:claim",
            "empirical_scope": "scope:country-case",
        }
    )

    tag_result = _run_tag(
        "stub",
        str(THESIS_PAPER_PDF),
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: malformed_response},
    )
    _assert_not_argparse_fallback(tag_result, "tag")

    assert tag_result.returncode != 0, (
        f"expected a non-zero exit code for `axial tag` when the tag-pass "
        f"response declares empirical_scope=scope:country-case with no "
        f"'country' key at all (PRD Appendix C/G, Gherkin: 'a country-case "
        f"with a missing ... country exits non-zero with a clear error'), "
        f"got exit code 0\nstdout: {tag_result.stdout!r}\n"
        f"stderr: {tag_result.stderr!r}"
    )

    assert tag_result.stderr.strip(), (
        f"expected `axial tag` to report a clear, non-empty error on "
        f"stderr for a missing-country country-case record (the CLI's "
        f"error convention is `error: ...`, per slice 01's hard-error "
        f"handling), got empty stderr\nstdout: {tag_result.stdout!r}\n"
        f"stderr: {tag_result.stderr!r}"
    )
    combined = tag_result.stdout + tag_result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real country-validation error path, not a generic "
            f"argparse fallback (found {marker!r}) masquerading as the "
            f"missing-country error\nstdout: {tag_result.stdout!r}\n"
            f"stderr: {tag_result.stderr!r}"
        )


def test_tag_country_case_out_of_list_country_errors_out(clean_envelopes):
    """Slice 02 error path (issue #28). A scope:country-case tag response
    whose `country` value is not a member of the schema's country_list is
    a hard error: `axial tag` must exit non-zero with a clear error naming
    the offending value."""
    _arrange_stored_envelope()

    offending_country = "Atlantis"
    schema = load_schema(str(DOMAIN_DIR))
    assert offending_country not in schema.country_list, (
        f"test setup invariant broken: {offending_country!r} must not "
        f"already be a member of the schema's country_list "
        f"{schema.country_list!r}, or this test would not actually be "
        f"exercising the out-of-list error path"
    )

    malformed_response = json.dumps(
        {
            "role_in_argument": "role:claim",
            "empirical_scope": "scope:country-case",
            "country": offending_country,
        }
    )

    tag_result = _run_tag(
        "stub",
        str(THESIS_PAPER_PDF),
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: malformed_response},
    )
    _assert_not_argparse_fallback(tag_result, "tag")

    assert tag_result.returncode != 0, (
        f"expected a non-zero exit code for `axial tag` when the tag-pass "
        f"response declares country={offending_country!r}, which is not a "
        f"member of the schema's country_list (PRD Appendix C/G, Gherkin: "
        f"'a country-case with a ... out-of-list country exits non-zero "
        f"with a clear error'), got exit code 0\nstdout: "
        f"{tag_result.stdout!r}\nstderr: {tag_result.stderr!r}"
    )

    combined = tag_result.stdout + tag_result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real country-validation error path, not a generic "
            f"argparse fallback (found {marker!r}) masquerading as the "
            f"out-of-list-country error\nstdout: {tag_result.stdout!r}\n"
            f"stderr: {tag_result.stderr!r}"
        )
    assert offending_country in combined, (
        f"expected `axial tag`'s error output to name the offending "
        f"country value {offending_country!r} (Gherkin: 'clear error'; "
        f"this test's own error-quality bar), got combined output that "
        f"does not mention it\nstdout: {tag_result.stdout!r}\n"
        f"stderr: {tag_result.stderr!r}"
    )
