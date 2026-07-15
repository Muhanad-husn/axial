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
And   a `scope:country-case` record carries a non-empty `country` value
And   a country-case with a missing or empty country exits non-zero with a
      clear error
And   a country-case whose country is outside the schema's country_list
      still succeeds, carries that country verbatim, and is logged as a
      candidate addition

See specs/PRODUCT.md Appendix C (empirical-scope axis, single-cardinality,
with `scope:country-case`'s `country` extra field, model-supplied free
text) and §7.1 ("a tag not in the schema is a hard error, not a silent
pass" -- note `country` is explicitly carved out of this rule per the
Contract change below; the rule still governs every other axis).

Contract change (spec-drift #77, adjudicated 2026-07-10)
-----------------------------------------------------------------------
Issue #77: the placeholder Appendix G `country_list` (5 corpus countries)
hard-errored real comparative sources (`country 'Chile'`, `country
'Libya'`), aborting multi-hour tag passes. Founder adjudication (option b):
v0 accepts any non-empty `country` string; a missing/empty value is still
the hard error it always was, but an out-of-list value is no longer fatal
-- it is accepted, carried verbatim on the record, and logged (stderr) as
a candidate addition. The controlled list returns as an enforced
validation layer only at the post-eval schema revision (PRD §11 step 7).
This changes the *validation* behavior only: the happy-path Given clause
below (stub default response, country=Syria, in-list) is unaffected, since
in-list behavior is unchanged.

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

To drive the remaining hard-error scenario (missing country) and the
out-of-list acceptance-and-logging scenario end to end via subprocess
without a second stub client shape, the fixed seam agreed with the
implementer is the env var `AXIAL_STUB_TAG_RESPONSE`: when set, the stub's
tag-pass response becomes that raw JSON string verbatim instead of the
default canned one, letting this test drive exactly which tag payload the
pipeline receives -- without this test asserting anything about how the
override is implemented internally, only that the env var name and shape
are honored end-to-end.

Seam decision 6 -- empirical_scope vocabulary and country_list loaded at
test time, never hardcoded (mirrors slice 01's seam decision 2)
-----------------------------------------------------------------------
Exactly as slice 01 refused to hardcode `role_in_argument` vocabulary, this
test never hardcodes `"scope:country-case"`, any other scope value, or any
country name as a *correctness* assertion. It calls `load_schema` at test
time and asserts every record's `empirical_scope` is a member of
`schema.axes["empirical_scope"].tag_ids`. For a country-case record it
asserts `country` is a non-empty string (Contract change above:
membership in `schema.country_list` is no longer a correctness
requirement on the happy path, since the stub's default `country: "Syria"`
happens to be in-list but need not be). The one place a literal value is
compared is in the hard-error/acceptance scenarios' fabricated
`AXIAL_STUB_TAG_RESPONSE` payloads themselves (test *input*, not a
correctness assertion about schema vocabulary) and in checking that the
CLI's stderr output actually names the offending/out-of-list value the
test itself chose to inject -- that is an error/log-quality check ("clear
error" / "logged as a candidate addition" per the Gherkin), not a
vocabulary hardcode.

Seam decision 7 -- "exactly one" enforced as a scalar, not a list
-----------------------------------------------------------------------
The Gherkin says "exactly one empirical_scope value", and Appendix C
declares `cardinality: single`. This test asserts `record["empirical_scope"]`
is itself a `str` (a single scalar tag id), not a list/array of one -- a
list-of-one would satisfy a naive "at least one, all in schema" check but
would misrepresent the axis's single-cardinality contract and silently
permit a future regression to multi-valued scope tagging.

Seam decision 8 -- error/acceptance scenarios assert exit-code and
message quality, not exact wording
-----------------------------------------------------------------------
Mirroring this file's existing `_assert_not_argparse_fallback` discipline,
the missing-country hard-error test asserts: (a) a non-zero exit code, (b)
the combined output carries none of `ARGPARSE_FALLBACK_MARKERS` (so a
generic argparse failure -- e.g. a malformed CLI invocation -- cannot
masquerade as the real country-validation error path), and (c) non-empty
stderr. No assertion pins the exact wording of the error message beyond
that.

Contract change (spec-drift #77, adjudicated 2026-07-10): the former
out-of-list hard-error test is replaced by an acceptance-and-logging test.
It asserts (a) exit code 0, (b) no `ARGPARSE_FALLBACK_MARKERS`, (c) the
tagged record carries the out-of-list country verbatim, and (d) stderr
names the offending value AND contains the substring `"country_list"` --
this is deliberately specific (not just "non-empty stderr") because no
such diagnostic channel exists yet; this test fixes it as the seam the
implementer builds to: a stderr line naming the out-of-list country and
the string `country_list`, mirroring `axial.extract`'s existing
`_log_fallback` convention (non-fatal diagnostics go to stderr, stdout
stays pure JSON). No assertion pins the exact wording beyond those two
substrings.

---------------------------------------------------------------------------
Slice 03 (issue #29, plans/tag/03-primary-secondary-axes.md) -- the
primary+secondary axes: field, claim_type (+subtags), theory_school
(+status: candidate)
---------------------------------------------------------------------------

Given an extracted fixture source with a stored envelope and chunks,
      AXIAL_LLM_PROVIDER=stub returning a full multi-axis tag response
When  the user runs `axial tag <fixture>`
Then  each record carries `field` {primary, secondary[]}, `claim_type`
      {primary, secondary?, subtags[]}, and `theory_school` {primary,
      secondary?, status: candidate}
And   every primary, secondary, and subtag exists in the schema
And   any returned tag absent from the schema exits non-zero with a hard
      error naming the axis and tag

See specs/PRODUCT.md Appendix A (field: one primary + zero-or-more
secondary), Appendix B (claim_type: one primary + optional secondary, with
its own declared subtags -- "sub-tags refine, they do not multiply the
count"), Appendix E (theory_school [CANDIDATE]: one primary + optional
secondary, grouped vocabulary), Appendix H (example prose-chunk frontmatter
showing the exact nested shape: `field: {primary, secondary}`, `claim_type:
{primary, secondary, subtags}`, `theory_school: {primary, status:
candidate}`), and §7.1 ("a tag not in the schema is a hard error, not a
silent pass").

Seam decision 9 -- the raw tag-pass response's shape for these three axes
mirrors the final record's own nested shape, fixed as the seam for both the
implementer's extended default canned response and this test's
`AXIAL_STUB_TAG_RESPONSE` override payloads
-----------------------------------------------------------------------
Slices 01/02 established a flat top-level-key-per-axis response shape
because both role_in_argument and empirical_scope are single-cardinality
scalars. `field`, `claim_type`, and `theory_school` are not scalars --
Appendix H's own example frontmatter already shows them as nested objects
(`field: {primary, secondary}`, etc.) -- so the natural, minimal extension
of the existing per-axis-key convention is for the model's raw JSON
response to carry a nested object under each of these three top-level keys
directly, in exactly the shape the final tagged record must expose. This
test fixes that as the shared seam: the implementer's extended
`StubLLMClient._CANNED_TAG_RESPONSE` (the plain-stub happy path, no special
env -- mirroring seam decision 5's "no special env" precedent) and this
test's own `AXIAL_STUB_TAG_RESPONSE` hard-error payloads both use this
shape. This test does not otherwise dictate how the tag pass internally
parses or assembles that JSON -- only that the wire shape is this one.

Seam decision 10 -- field/claim_type/theory_school vocabulary, and
claim_type's own per-tag declared subtags, loaded at test time, never
hardcoded (mirrors seam decisions 2/6)
-----------------------------------------------------------------------
This test never hardcodes a field/claim_type/theory_school tag id, or which
subtags belong to which claim_type id, as a *correctness* assertion. It
calls `load_schema` at test time and checks membership against
`schema.axes["field"].tag_ids`, `schema.axes["claim_type"].tag_ids`,
`schema.axes["theory_school"].tag_ids`, and -- for subtags -- against that
specific claim_type id's OWN declared `subtags` list, read from
`schema.axes["claim_type"].raw["values"]` (each entry's own `subtags` key,
which may be absent/empty for tags that declare none, e.g.
`state-autonomy`). `theory_school`'s `status` is checked against the
schema's own axis-level `status` field (`schema.axes["theory_school"]
.raw["status"]`), not a hardcoded `"candidate"` literal, so a future schema
edit to that flag cannot silently pass an assertion pinned to today's
wording. The only literals hardcoded anywhere in this section are: (a) each
hard-error test's fabricated, deliberately-invalid tag id or subtag id
(local variables, never module constants, exactly as seam decision 8
directs), and (b) a small number of non-`claim_type` axis values used only
to build a complete, otherwise-valid multi-axis payload around the one
axis under test in the hard-error scenarios -- those are disposable test
*input*, not vocabulary correctness assertions.

Seam decision 11 -- cardinality asserted structurally per axis, mirroring
seam decision 7
-----------------------------------------------------------------------
`field.primary` and `claim_type.primary`/`theory_school.primary` must each
be a single scalar `str`. `field.secondary` (Appendix A: "zero-or-more")
must be a `list` (any length, including empty). `claim_type.secondary` and
`theory_school.secondary` (Appendix B/E: "optional secondary") are each
either altogether absent/`None`, or -- when present -- a single scalar
`str`, never a list; a list-of-one there would misrepresent the "optional
secondary" cardinality exactly as seam decision 7 warns for
`empirical_scope`. `claim_type.subtags` must be a `list` (possibly empty),
each entry checked against that primary's own declared subtags (seam
decision 10) rather than the axis's full subtag universe -- a subtag valid
under one claim_type id is not automatically valid under another.

Seam decision 12 -- hard-error scenarios: one out-of-schema primary, one
undeclared subtag, both naming axis + offending tag
-----------------------------------------------------------------------
Mirroring seam decision 8's error-quality bar (non-zero exit, no argparse-
fallback marker, offending value named in combined output), this section
adds two hard-error tests via the same `AXIAL_STUB_TAG_RESPONSE` override
seam: (1) an out-of-schema `field.primary` value, asserting the offending
fabricated tag id AND the literal axis name `"field"` both appear in
combined stdout+stderr; (2) an undeclared subtag under an otherwise valid
`claim_type.primary` (one the schema itself declares subtags for), asserting
the offending fabricated subtag id AND the literal axis name `"claim_type"`
both appear. Both fabricated values are chosen locally in their own test,
never module-level constants, since they are disposable test input, not
locked vocabulary.

Seam decision 13 -- regression guard for slices 01/02, mirroring how slice
02 guarded slice 01
-----------------------------------------------------------------------
The happy-path test below also asserts every record's `role_in_argument`
and `empirical_scope` are still present and in-schema, exactly as slice
02's happy-path test guarded slice 01's `role_in_argument` -- so this slice
cannot silently regress the two already-locked axes while adding the three
new ones.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from axial.chunk import read_chunks, run_chunk_recursive
from axial.envelope import compute_source_id
from axial.schema import load_schema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
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
    exactly one new envelope file.

    Also writes the real, on-disk chunk artifact for this fixture (issue
    #154 slice 04: `axial tag` no longer computes chunks itself -- it reads
    `data/chunks/<source_id>.jsonl` via `axial.chunk.read_chunks`, PRD §7.7,
    and fails clearly if that artifact is absent). `run_chunk_recursive`
    (`run_chunk_recursive`) writes it into the SAME cwd-relative
    `data/chunks/` the `axial tag` subprocess below reads from (both resolve
    against REPO_ROOT, matching `_run_axial`'s own fixed `cwd=REPO_ROOT`)."""
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

    run_chunk_recursive(THESIS_PAPER_PDF)

    return next(iter(new_files))


def test_tag_emits_one_schema_valid_versioned_record_per_chunk(clean_envelopes):
    envelope_path = _arrange_stored_envelope()

    # --- independently obtain the chunk_id set the chunking pass produces
    # for this fixture, to check against below without hardcoding a count.
    # Issue #154 slice 04: `axial tag` no longer computes chunks itself --
    # it reads the same on-disk chunk artifact (`axial.chunk.read_chunks`,
    # PRD §7.7) that `_arrange_stored_envelope` above already wrote via
    # `run_chunk_recursive`. Reading it back here (rather than recomputing)
    # is the ground truth for "what `axial tag`'s own internal read_chunks
    # call will see" -- both resolve the same cwd-relative `data/chunks/`
    # path (REPO_ROOT). ---
    source_id = compute_source_id(THESIS_PAPER_PDF)
    chunk_records = read_chunks(source_id)
    expected_chunk_ids = [r.get("chunk_id") for r in chunk_records]
    assert expected_chunk_ids and all(expected_chunk_ids), (
        f"arrange step failed: expected the on-disk chunk artifact to carry "
        f"chunk records each with a non-empty chunk_id, got: {chunk_records!r}"
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
    scope:country-case record -- a non-empty country value (Contract
    change, spec-drift #77: membership in the schema's country_list is no
    longer required for correctness; see the dedicated out-of-list
    acceptance test below for that boundary). Also checks slice 01's
    role_in_argument is not regressed."""
    _arrange_stored_envelope()

    # --- load the schema at test time: never hardcode the empirical_scope
    # vocabulary or the role_in_argument vocabulary (seam decision 6) ---
    schema = load_schema(str(DOMAIN_DIR))
    valid_scopes = schema.axes["empirical_scope"].tag_ids
    assert valid_scopes, "arrange step failed: schema's empirical_scope axis has no tag ids"
    valid_roles = schema.axes["role_in_argument"].tag_ids
    assert valid_roles, "arrange step failed: schema's role_in_argument axis has no tag ids"

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

        # --- a scope:country-case record carries a non-empty country value
        # (Contract change, spec-drift #77: this happy path's country
        # happens to be in-list, but membership is no longer part of the
        # correctness contract -- see the dedicated out-of-list acceptance
        # test below) ---
        if scope == "scope:country-case":
            country_case_seen = True
            country = record.get("country")
            assert isinstance(country, str) and country.strip(), (
                f"expected a scope:country-case tagged record to carry a "
                f"non-empty string 'country' (Appendix C/G, Gherkin: 'a "
                f"scope:country-case record carries a non-empty country "
                f"value'), got {country!r} (full record: {record!r})"
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


# --- Contract change (spec-drift #77, adjudicated 2026-07-10) -------------
# The placeholder Appendix G country_list (5 corpus countries) hard-errored
# real comparative sources mid-run (`country 'Chile'`, `country 'Libya'`,
# both confirmed casualties during gold-corpus ingestion). Founder
# adjudication (issue #77, option b): v0 accepts any non-empty `country`
# string; an out-of-list value is no longer fatal. It is:
#   (a) accepted -- `axial tag` exits 0,
#   (b) carried verbatim on the tagged record (never rejected, substituted,
#       or silently coerced to an in-list value), and
#   (c) logged as a candidate addition -- a non-fatal diagnostic on stderr
#       (stdout stays pure JSON, mirroring `axial.extract`'s existing
#       `_log_fallback` convention) naming both the offending country value
#       and the string "country_list", so the log line is unambiguous
#       about what the value fell outside of. This test fixes that stderr
#       shape as the seam the implementer builds to; it does not pin exact
#       wording beyond those two substrings.
# A missing/empty country is UNCHANGED -- still the hard error asserted by
# `test_tag_country_case_missing_country_errors_out` above.
# ---------------------------------------------------------------------------
def test_tag_country_case_out_of_list_country_is_accepted_and_logged(clean_envelopes):
    """Slice 02, contract change (spec-drift #77, adjudicated 2026-07-10).
    A scope:country-case tag response whose `country` value is not a member
    of the schema's country_list is no longer a hard error: `axial tag`
    must exit 0, carry that country verbatim on the tagged record, and log
    it on stderr as a candidate addition (naming the value and the string
    'country_list')."""
    _arrange_stored_envelope()

    offending_country = "Chile"
    schema = load_schema(str(DOMAIN_DIR))
    assert offending_country not in schema.country_list, (
        f"test setup invariant broken: {offending_country!r} must not "
        f"already be a member of the schema's country_list "
        f"{schema.country_list!r}, or this test would not actually be "
        f"exercising the out-of-list acceptance path"
    )

    # --- arrange completeness: the tag loop validates every axis in the
    # response, not just empirical_scope/country (§7.1) -- under the OLD
    # contract the out-of-list raise fired before the loop reached the
    # other axes, masking this gap; now that out-of-list is non-fatal, the
    # loop correctly continues and needs a complete, in-schema payload for
    # the remaining tagged axes, mirroring StubLLMClient's own canned
    # response shape (src/axial/llm.py `_CANNED_TAG_RESPONSE`) ---
    tag_response = json.dumps(
        {
            "role_in_argument": "role:claim",
            "empirical_scope": "scope:country-case",
            "country": offending_country,
            "field": {"primary": "state", "secondary": ["ideology"]},
            "claim_type": {"primary": "state-formation", "subtags": ["formation:bellicist"]},
            "theory_school": {"primary": "bellicist", "status": "candidate"},
        }
    )

    tag_result = _run_tag(
        "stub",
        str(THESIS_PAPER_PDF),
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: tag_response},
    )
    _assert_not_argparse_fallback(tag_result, "tag")

    assert tag_result.returncode == 0, (
        f"expected exit code 0 for `axial tag` when the tag-pass response "
        f"declares country={offending_country!r}, which is not a member of "
        f"the schema's country_list -- adjudicated spec-drift #77: an "
        f"out-of-list country is accepted, never fatal, in v0 -- got exit "
        f"code {tag_result.returncode}\nstdout: {tag_result.stdout!r}\n"
        f"stderr: {tag_result.stderr!r}"
    )

    tag_records = _parse_tag_records(tag_result.stdout)
    assert tag_records, (
        f"expected at least one tagged record on stdout, got none; stdout: {tag_result.stdout!r}"
    )
    country_case_records = [
        record for record in tag_records if record.get("empirical_scope") == "scope:country-case"
    ]
    assert country_case_records, (
        f"expected at least one scope:country-case tagged record given "
        f"this test's fabricated response, got none among: {tag_records!r}"
    )
    for record in country_case_records:
        assert record.get("country") == offending_country, (
            f"expected the out-of-list country {offending_country!r} to be "
            f"carried verbatim on the tagged record (adjudicated spec-drift "
            f"#77: out-of-list values are accepted as-is, never rejected or "
            f"substituted), got {record.get('country')!r} (full record: "
            f"{record!r})"
        )

    # --- the out-of-list value must still be surfaced as a non-fatal
    # diagnostic, on stderr (stdout stays pure JSON), naming both the
    # offending country and the country_list it fell outside of ---
    assert offending_country in tag_result.stderr, (
        f"expected `axial tag`'s stderr to name the out-of-list country "
        f"value {offending_country!r} as a candidate addition (adjudicated "
        f"spec-drift #77: out-of-list values are 'logged as candidate "
        f"additions'), got stderr: {tag_result.stderr!r}"
    )
    assert "country_list" in tag_result.stderr, (
        f"expected `axial tag`'s stderr diagnostic for the out-of-list "
        f"country to name the schema's country_list (so the log line is "
        f"unambiguous about what the value fell outside of), got stderr: "
        f"{tag_result.stderr!r}"
    )


# --- Slice 03 helpers (issue #29): claim_type's own per-tag declared
# subtags, read from the schema at test time (seam decision 10) ---


def _claim_type_subtags_by_id(schema) -> dict[str, list[str]]:
    """Map each claim_type tag id to its own declared `subtags` list (empty
    if it declares none), read from `schema.axes["claim_type"].raw` --
    never hardcoded, since which claim_type ids carry which subtags is
    schema content, not a test assumption (seam decision 10)."""
    raw_values = schema.axes["claim_type"].raw.get("values") or []
    result: dict[str, list[str]] = {}
    for entry in raw_values:
        if isinstance(entry, dict) and "id" in entry:
            result[entry["id"]] = list(entry.get("subtags") or [])
    return result


def _pick_claim_type_id_with_subtags(subtags_by_id: dict[str, list[str]]) -> str:
    """Pick a claim_type id that declares at least one subtag, so a test
    exercising subtags has something real to validate against."""
    for tag_id, subtags in subtags_by_id.items():
        if subtags:
            return tag_id
    raise AssertionError(
        "arrange step failed: no claim_type tag in the loaded schema "
        "declares any subtags -- cannot exercise subtag validation"
    )


def test_tag_assigns_field_claim_type_theory_school_all_in_schema(clean_envelopes):
    """Slice 03 happy path (issue #29). Given the stub's default tag-pass
    response now also carries field/claim_type(+subtags)/theory_school
    (seam decision 9, the Gherkin's Given clause), a plain `axial tag
    <fixture>` run -- no special env, mirroring slices 01/02 -- must emit
    records that each carry the three new axes in Appendix H's nested
    shape, every primary/secondary/subtag drawn from the schema. Also
    regression-checks slices 01/02's role_in_argument and empirical_scope
    are not broken (seam decision 13)."""
    _arrange_stored_envelope()

    # --- load the schema at test time: never hardcode any axis's
    # vocabulary, claim_type's per-id subtags, or theory_school's status
    # flag (seam decision 10) ---
    schema = load_schema(str(DOMAIN_DIR))
    valid_roles = schema.axes["role_in_argument"].tag_ids
    assert valid_roles, "arrange step failed: schema's role_in_argument axis has no tag ids"
    valid_scopes = schema.axes["empirical_scope"].tag_ids
    assert valid_scopes, "arrange step failed: schema's empirical_scope axis has no tag ids"
    valid_fields = schema.axes["field"].tag_ids
    assert valid_fields, "arrange step failed: schema's field axis has no tag ids"
    valid_claim_types = schema.axes["claim_type"].tag_ids
    assert valid_claim_types, "arrange step failed: schema's claim_type axis has no tag ids"
    subtags_by_id = _claim_type_subtags_by_id(schema)
    valid_theory_schools = schema.axes["theory_school"].tag_ids
    assert valid_theory_schools, "arrange step failed: schema's theory_school axis has no tag ids"
    expected_theory_school_status = schema.axes["theory_school"].raw.get("status")
    assert expected_theory_school_status, (
        "arrange step failed: schema's theory_school axis declares no 'status' field"
    )

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

    for record in tag_records:
        assert isinstance(record, dict), (
            f"expected each tagged record to be a JSON object, got "
            f"{type(record).__name__}: {record!r}"
        )

        # --- field: one primary + zero-or-more secondary (Appendix A/H) ---
        field = record.get("field")
        assert isinstance(field, dict), (
            f"expected tagged record's 'field' to be an object with "
            f"'primary'/'secondary' keys (Appendix A/H: `field: {{primary, "
            f"secondary[]}}`), got {type(field).__name__}: {field!r} "
            f"(full record: {record!r})"
        )
        field_primary = field.get("primary")
        assert isinstance(field_primary, str) and field_primary in valid_fields, (
            f"expected field.primary to be a single in-schema field tag "
            f"(schema's field tag set {sorted(valid_fields)}), got "
            f"{field_primary!r} (full record: {record!r})"
        )
        field_secondary = field.get("secondary")
        assert isinstance(field_secondary, list), (
            f"expected field.secondary to be a list (Appendix A: 'zero-or-"
            f"more secondary'), got {type(field_secondary).__name__}: "
            f"{field_secondary!r} (full record: {record!r})"
        )
        for tag in field_secondary:
            assert tag in valid_fields, (
                f"expected every field.secondary entry to be a member of "
                f"the schema's field tag set {sorted(valid_fields)}, got "
                f"{tag!r} (full record: {record!r})"
            )

        # --- claim_type: one primary + optional secondary + its own
        # declared subtags (Appendix B/H) ---
        claim_type = record.get("claim_type")
        assert isinstance(claim_type, dict), (
            f"expected tagged record's 'claim_type' to be an object with "
            f"'primary'/'subtags' keys (Appendix B/H: `claim_type: "
            f"{{primary, secondary?, subtags[]}}`), got "
            f"{type(claim_type).__name__}: {claim_type!r} (full record: {record!r})"
        )
        claim_primary = claim_type.get("primary")
        assert isinstance(claim_primary, str) and claim_primary in valid_claim_types, (
            f"expected claim_type.primary to be a single in-schema "
            f"claim_type tag (schema's claim_type tag set "
            f"{sorted(valid_claim_types)}), got {claim_primary!r} (full "
            f"record: {record!r})"
        )
        if claim_type.get("secondary") is not None:
            claim_secondary = claim_type["secondary"]
            assert isinstance(claim_secondary, str), (
                f"expected claim_type.secondary, when present, to be a "
                f"single scalar string (Appendix B: cardinality "
                f"primary_plus_optional_secondary, not a list), got "
                f"{type(claim_secondary).__name__}: {claim_secondary!r} "
                f"(full record: {record!r})"
            )
            assert claim_secondary in valid_claim_types, (
                f"expected claim_type.secondary to be a member of the "
                f"schema's claim_type tag set {sorted(valid_claim_types)}, "
                f"got {claim_secondary!r} (full record: {record!r})"
            )
        claim_subtags = claim_type.get("subtags")
        assert isinstance(claim_subtags, list), (
            f"expected claim_type.subtags to be a list (Appendix B/H: "
            f"`subtags[]`), got {type(claim_subtags).__name__}: "
            f"{claim_subtags!r} (full record: {record!r})"
        )
        declared_subtags = set(subtags_by_id.get(claim_primary, []))
        for subtag in claim_subtags:
            assert subtag in declared_subtags, (
                f"expected every claim_type.subtags entry to be one of "
                f"claim_type {claim_primary!r}'s OWN declared subtags "
                f"{sorted(declared_subtags)} (Appendix B: 'sub-tags refine, "
                f"they do not multiply the count'), got {subtag!r} (full "
                f"record: {record!r})"
            )

        # --- theory_school: one primary + optional secondary + status
        # candidate (Appendix E/H) ---
        theory_school = record.get("theory_school")
        assert isinstance(theory_school, dict), (
            f"expected tagged record's 'theory_school' to be an object "
            f"with 'primary'/'status' keys (Appendix E/H: `theory_school: "
            f"{{primary, secondary?, status: candidate}}`), got "
            f"{type(theory_school).__name__}: {theory_school!r} (full "
            f"record: {record!r})"
        )
        theory_primary = theory_school.get("primary")
        assert isinstance(theory_primary, str) and theory_primary in valid_theory_schools, (
            f"expected theory_school.primary to be a single in-schema "
            f"theory_school tag (schema's theory_school tag set "
            f"{sorted(valid_theory_schools)}), got {theory_primary!r} "
            f"(full record: {record!r})"
        )
        if theory_school.get("secondary") is not None:
            theory_secondary = theory_school["secondary"]
            assert isinstance(theory_secondary, str), (
                f"expected theory_school.secondary, when present, to be a "
                f"single scalar string (Appendix E: cardinality "
                f"primary_plus_optional_secondary, not a list), got "
                f"{type(theory_secondary).__name__}: {theory_secondary!r} "
                f"(full record: {record!r})"
            )
            assert theory_secondary in valid_theory_schools, (
                f"expected theory_school.secondary to be a member of the "
                f"schema's theory_school tag set "
                f"{sorted(valid_theory_schools)}, got {theory_secondary!r} "
                f"(full record: {record!r})"
            )
        theory_status = theory_school.get("status")
        assert theory_status == expected_theory_school_status, (
            f"expected theory_school.status to equal the schema's own "
            f"declared axis status {expected_theory_school_status!r} "
            f"(Appendix E [CANDIDATE], Gherkin: 'status: candidate'), got "
            f"{theory_status!r} (full record: {record!r})"
        )

        # --- regression: slices 01/02 axes still present and in-schema
        # (seam decision 13) ---
        role = record.get("role_in_argument")
        assert role in valid_roles, (
            f"regression: expected tagged record's 'role_in_argument' to "
            f"still be a member of the schema's role_in_argument tag set "
            f"{sorted(valid_roles)} (slice 01 contract), got {role!r} "
            f"(full record: {record!r})"
        )
        scope = record.get("empirical_scope")
        assert scope in valid_scopes, (
            f"regression: expected tagged record's 'empirical_scope' to "
            f"still be a member of the schema's empirical_scope tag set "
            f"{sorted(valid_scopes)} (slice 02 contract), got {scope!r} "
            f"(full record: {record!r})"
        )


def test_tag_out_of_schema_field_primary_errors_out(clean_envelopes):
    """Slice 03 error path (issue #29). A `field.primary` value absent from
    the loaded schema is a hard error naming the axis and the offending
    tag (Gherkin: 'any returned tag absent from the schema exits non-zero
    with a hard error naming the axis and tag'), exactly as slice 01/02's
    `TagNotInSchemaError` already does for role_in_argument/
    empirical_scope."""
    _arrange_stored_envelope()

    schema = load_schema(str(DOMAIN_DIR))
    valid_role = next(iter(schema.axes["role_in_argument"].tag_ids))
    non_country_scopes = [
        scope for scope in schema.axes["empirical_scope"].tag_ids if scope != "scope:country-case"
    ]
    assert non_country_scopes, (
        "arrange step failed: schema's empirical_scope axis has no "
        "non-country-case value to build a minimal valid payload with"
    )
    valid_scope = non_country_scopes[0]
    subtags_by_id = _claim_type_subtags_by_id(schema)
    valid_claim_primary = _pick_claim_type_id_with_subtags(subtags_by_id)
    valid_claim_subtags = subtags_by_id[valid_claim_primary][:1]
    valid_theory_primary = next(iter(schema.axes["theory_school"].tag_ids))
    theory_status = schema.axes["theory_school"].raw.get("status")

    offending_field_tag = "field:not-a-real-field-zzz"
    assert offending_field_tag not in schema.axes["field"].tag_ids, (
        f"test setup invariant broken: {offending_field_tag!r} must not "
        f"already be a member of the schema's field tag set, or this test "
        f"would not actually be exercising the out-of-schema error path"
    )

    malformed_response = json.dumps(
        {
            "role_in_argument": valid_role,
            "empirical_scope": valid_scope,
            "field": {"primary": offending_field_tag, "secondary": []},
            "claim_type": {"primary": valid_claim_primary, "subtags": valid_claim_subtags},
            "theory_school": {"primary": valid_theory_primary, "status": theory_status},
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
        f"response declares field.primary={offending_field_tag!r}, which "
        f"is not a member of the schema's field tag set (PRD Appendix A, "
        f"§7.1: 'a tag not in the schema is a hard error'), got exit code "
        f"0\nstdout: {tag_result.stdout!r}\nstderr: {tag_result.stderr!r}"
    )

    combined = tag_result.stdout + tag_result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real field-validation error path, not a generic "
            f"argparse fallback (found {marker!r}) masquerading as the "
            f"out-of-schema field error\nstdout: {tag_result.stdout!r}\n"
            f"stderr: {tag_result.stderr!r}"
        )
    assert offending_field_tag in combined, (
        f"expected `axial tag`'s error output to name the offending field "
        f"tag {offending_field_tag!r} (Gherkin: 'a hard error naming the "
        f"axis and tag'), got combined output that does not mention it\n"
        f"stdout: {tag_result.stdout!r}\nstderr: {tag_result.stderr!r}"
    )
    assert "field" in combined, (
        f"expected `axial tag`'s error output to name the offending axis "
        f"'field' (Gherkin: 'a hard error naming the axis and tag'), got "
        f"combined output that does not mention it\nstdout: "
        f"{tag_result.stdout!r}\nstderr: {tag_result.stderr!r}"
    )


def test_tag_claim_type_undeclared_subtag_errors_out(clean_envelopes):
    """Slice 03 error path (issue #29). A `claim_type.subtags` entry not
    declared under the chosen `claim_type.primary`'s own subtags is a hard
    error naming the axis and the offending subtag (Gherkin: 'any returned
    tag absent from the schema exits non-zero with a hard error naming the
    axis and tag'; Appendix B: 'sub-tags refine, they do not multiply the
    count')."""
    _arrange_stored_envelope()

    schema = load_schema(str(DOMAIN_DIR))
    valid_role = next(iter(schema.axes["role_in_argument"].tag_ids))
    non_country_scopes = [
        scope for scope in schema.axes["empirical_scope"].tag_ids if scope != "scope:country-case"
    ]
    assert non_country_scopes, (
        "arrange step failed: schema's empirical_scope axis has no "
        "non-country-case value to build a minimal valid payload with"
    )
    valid_scope = non_country_scopes[0]
    valid_field_primary = next(iter(schema.axes["field"].tag_ids))
    subtags_by_id = _claim_type_subtags_by_id(schema)
    valid_claim_primary = _pick_claim_type_id_with_subtags(subtags_by_id)
    declared_subtags = set(subtags_by_id[valid_claim_primary])
    valid_theory_primary = next(iter(schema.axes["theory_school"].tag_ids))
    theory_status = schema.axes["theory_school"].raw.get("status")

    offending_subtag = "subtag:definitely-not-declared-zzz"
    assert offending_subtag not in declared_subtags, (
        f"test setup invariant broken: {offending_subtag!r} must not "
        f"already be one of claim_type {valid_claim_primary!r}'s declared "
        f"subtags {sorted(declared_subtags)}, or this test would not "
        f"actually be exercising the undeclared-subtag error path"
    )

    malformed_response = json.dumps(
        {
            "role_in_argument": valid_role,
            "empirical_scope": valid_scope,
            "field": {"primary": valid_field_primary, "secondary": []},
            "claim_type": {"primary": valid_claim_primary, "subtags": [offending_subtag]},
            "theory_school": {"primary": valid_theory_primary, "status": theory_status},
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
        f"response declares an undeclared subtag {offending_subtag!r} "
        f"under claim_type.primary={valid_claim_primary!r} (Appendix B: "
        f"'sub-tags refine, they do not multiply the count'; §7.1: 'a tag "
        f"not in the schema is a hard error'), got exit code 0\nstdout: "
        f"{tag_result.stdout!r}\nstderr: {tag_result.stderr!r}"
    )

    combined = tag_result.stdout + tag_result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real subtag-validation error path, not a generic "
            f"argparse fallback (found {marker!r}) masquerading as the "
            f"undeclared-subtag error\nstdout: {tag_result.stdout!r}\n"
            f"stderr: {tag_result.stderr!r}"
        )
    assert offending_subtag in combined, (
        f"expected `axial tag`'s error output to name the offending "
        f"subtag {offending_subtag!r} (Gherkin: 'a hard error naming the "
        f"axis and tag'), got combined output that does not mention it\n"
        f"stdout: {tag_result.stdout!r}\nstderr: {tag_result.stderr!r}"
    )
    assert "claim_type" in combined, (
        f"expected `axial tag`'s error output to name the offending axis "
        f"'claim_type' (Gherkin: 'a hard error naming the axis and tag'), "
        f"got combined output that does not mention it\nstdout: "
        f"{tag_result.stdout!r}\nstderr: {tag_result.stderr!r}"
    )
