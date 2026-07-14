"""Outer acceptance test for issue #105 (tag pass: accept bare-string and
single-element-list axis dialects -- shape coercion, before vocabulary
validation).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a stubbed tag-pass response whose `theory_school` axis (a
      `primary_plus_optional_secondary` axis) arrives as a BARE, in-vocab
      string (e.g. `"discursive"`) instead of the object shape
      `{"primary": "discursive"}` the parser otherwise requires
When   the user runs `axial vault write <fixture>`
Then   it exits 0 and the written note's frontmatter carries
       `theory_school.primary == "discursive"` -- the bare-string dialect is
       coerced to the object shape, not rejected as a shape error

Given a stubbed response whose `claim_type` axis (also
      `primary_plus_optional_secondary`) gives its single-string `secondary`
      as a ONE-ELEMENT list (e.g. `["mobilization-and-recruitment"]`) instead
      of the bare scalar the axis's cardinality requires
Then   `axial vault write` still exits 0 and the note's frontmatter carries
       `claim_type.secondary == "mobilization-and-recruitment"` (the scalar,
       never the list) -- the single-element-list dialect is coerced too

Given a stubbed tag-pass response whose `theory_school` axis is a bare
      string that is OUT of vocabulary on its FIRST answer for a chunk, and a
      properly-shaped, genuinely in-vocab object on the SECOND (bounded
      correction re-ask, issue #102) answer for that same chunk
Then   `axial vault write` still exits 0 and the note's frontmatter carries
       the CORRECTED, in-vocab value -- proving the bare-string dialect is
       coerced to shape FIRST, so the out-of-vocab value reaches vocabulary
       validation and genuinely triggers the #102 re-ask, rather than a shape
       error bypassing the re-ask and hard-failing the run immediately

Given a stubbed response whose `theory_school`/`claim_type` axis value is
      genuinely malformed -- a number, an object with no `primary` key, or a
      MULTI-element list where a single string is required -- none of which
      is one of the two unambiguous coercible dialects
Then   `axial vault write` still exits non-zero, naming the offending axis --
       coercion must never paper over real malformation

See GitHub issue #105 ("tag pass: accept bare-string and single-element-list
axis dialects (shape coercion)"): "Safely coerce the two unambiguous
dialects before validation: bare string S for a
primary_plus_optional_secondary axis -> {primary: S}; single-element list
[S] where a single-string secondary is expected -> S ... Vocabulary
validation still runs after coercion, so a coerced value that is
out-of-vocab still gets the #102 re-ask; the P0-6 hard-error path is
preserved."

Fixture reuse: exactly tests/test_vault_write.py's, tests/test_tag_axis_
prefix.py's, and tests/test_tag_vocab_reask.py's fixture
(tests/fixtures/envelope/thesis_paper.pdf + its committed real tree fixture
tests/fixtures/envelope/thesis_paper_tree.json). No new fixture is needed:
this issue is about tag-value parsing/shape, not extraction/chunk shape.

Seam decision 1 -- driving the CLI end-to-end via `axial vault write`,
`isolated_vault_root`, and the already-locked `AXIAL_STUB_TAG_RESPONSE`
override seam
-----------------------------------------------------------------------
Mirrors tests/test_tag_axis_prefix.py's seam decision 1 exactly: the
one-shot scenarios (bare-string coercion, single-element-list coercion, each
malformed-shape regression guard) drive the already-locked
`AXIAL_STUB_TAG_RESPONSE` env var, which substitutes ONE raw tag-pass
response for EVERY tag-pass-family call the run makes
(`src/axial/llm.py`'s `_canned_response_for`). `isolated_vault_root`
(tests/conftest.py) runs the `axial` CLI subprocess from a fresh, private
staging directory so this test can never collide with, or be polluted by,
the real `data/vault/` a concurrent ingestion run also writes into.

Seam decision 2 -- the re-ask scenario reuses `AXIAL_STUB_TAG_RESPONSE_
SEQUENCE` (already locked by issue #102 / tests/test_tag_vocab_reask.py),
never a new seam -- but BOTH sequence entries must be the bare-string
dialect, never a well-formed dict, or this test would pass for the wrong
reason
-----------------------------------------------------------------------
This test's third scenario needs the tag pass's FIRST answer for a chunk to
differ from its bounded-correction-re-ask answer -- exactly what
`AXIAL_STUB_TAG_RESPONSE_SEQUENCE` (a JSON array of raw responses, indexed
by the shared per-process tag-pass call counter, cycling) already provides
(module docstring, tests/test_tag_vocab_reask.py, seam decision 2). No new
seam is needed for issue #105.

A first draft of this test used the obvious two-element sequence
`[<bad-shape bare-string payload>, <well-formed, in-vocab dict payload>]`
and found it PASSES even against today's unfixed `src/axial/tag.py` --
for the wrong reason, discovered empirically while drafting this test (see
below), which is precisely the "tautological acceptance test" trap this
file's own authoring instructions warn against. The cause: `run_tag`'s
`complete_json(..., validate=reject_degenerate_tag_values)` call (`tag.py`)
ALSO parses every axis with the same `parse_multi_value_tag_response` this
issue patches, treats ANY exception `validate` raises (including today's
shape `TagParseError`) as re-askable within `complete_json`'s OWN generic,
bounded degeneracy budget (`attempts=3`, `axial/model_json.py`) -- entirely
independent of, and BEFORE, `run_tag`'s real per-chunk parse+validate flow
and the #102 correction-reask ever run. So a `[bad, good]` two-element
sequence lets `complete_json`'s own retry silently swallow the first
(bad-shaped) attempt and land on the second (well-formed, in-vocab) one
directly -- masking today's real bug (a persistent bare-string dialect
slip DOES still hard-fail live, per this issue's own live evidence: "It is
recoverable today only via a full auto-requeue cycle") without ever
exercising the #102 vocab-reask mechanism issue #105 is actually about.

This test instead uses a two-element sequence where BOTH entries are the
SAME bare-string dialect -- `[<bare, out-of-vocab string>, <bare, in-vocab
string>]` -- so that TODAY (no coercion in `parse_multi_value_tag_response`
at all), every one of `complete_json`'s three attempts for a chunk sees a
bare string, `reject_degenerate_tag_values` raises `TagParseError` on
EVERY one of them regardless of vocabulary, `complete_json`'s degeneracy
budget is genuinely exhausted, and the run hard-fails BEFORE the #102
mechanism is ever reached -- deterministically RED, and empirically
verified against this commit's own unfixed `src/axial/tag.py` (see the
"Verify RED" step in this issue's own commit process). Once issue #105's
coercion lands in `parse_multi_value_tag_response`, the FIRST bare-string
attempt coerces to shape cleanly (regardless of vocabulary --
`reject_degenerate_tag_values` never checks vocabulary, only shape/
blankness), so `complete_json` returns it after exactly ONE call; `run_tag`'s
own `_parse_and_validate_tags` then coerces it again, `validate_tag` finds
it out-of-vocabulary, and the ALREADY-EXISTING #102 `apply_correction_reask`
fires its own single bounded re-ask -- calling `client.complete()`
DIRECTLY, never through `complete_json`/`reject_degenerate_tag_values`
again (`tag.py`'s `apply_correction_reask`) -- which consumes the
sequence's second (bare, in-vocab) entry, coerces it too, validates
in-vocabulary, and succeeds: exactly 2 tag-pass-family calls per chunk,
via the GENUINE #102 mechanism this time, not `complete_json`'s masking.

Seam decision 3 -- why `theory_school` carries the bare-string scenarios and
`claim_type` carries the single-element-list scenario
-----------------------------------------------------------------------
Both axes are `primary_plus_optional_secondary` (verified at test time
against the real schema, seam decision 5 below), so either could carry
either dialect; this test follows the issue's own live-evidence examples
(`theory_school` got a bare string, `claim_type.secondary` got a list) to
keep each scenario's fixture literal traceable to a real, previously-
observed model response shape, not an invented one.

Seam decision 4 -- proving the re-ask genuinely fired, via the `record`
provider and every OTHER pass's own prompt marker
-----------------------------------------------------------------------
Mirrors tests/test_tag_vocab_reask.py's seam decision 4 verbatim: this test
identifies every OTHER pass's calls by their own stable, already-committed
prompt markers (`CHUNK_PROMPT_MARKER`, `XREF_PROMPT_MARKER`) and treats
everything else recorded during a `vault write` run as tag-pass-family (an
original per-chunk ask OR a correction re-ask). The re-ask scenario asserts
EXACTLY 2 tag-pass-family calls per chunk (not "at least 2"): if the bare
out-of-vocab string still hit today's shape error, `apply_correction_reask`
would never see a `TagNotInSchemaError` to catch, the run would hard-fail on
the FIRST call, and this count (and the exit code) would betray that the
re-ask never fired at all.

Seam decision 5 -- a schema-derived baseline payload, only the axis/axes
under test overridden, with every fixture literal verified against the real
schema at test time
-----------------------------------------------------------------------
Mirrors tests/test_tag_axis_prefix.py's seam decision 2 and tests/
test_tag_vocab_reask.py's seam decision 3: the tag pass validates every
prose axis in one response, so this test loads the schema at test time
(`axial.schema.load_schema`) and builds one baseline payload whose non-
under-test axes are ordinary, real members of their own axis's vocabulary
-- never hardcoded as a correctness claim. `_assert_schema_invariants`
checks every literal this file fixes (the bare in-vocab `theory_school`
value, the two `claim_type` ids, the out-of-vocab `theory_school` string)
against the loaded schema before any scenario runs, so a future schema edit
that invalidates one of these literals fails loudly at the assertion, not
silently by testing the wrong thing.

Seam decision 6 -- error-quality assertions for the malformed-shape
regression guard, without over-asserting a specific error-message wording
-----------------------------------------------------------------------
The issue's Acceptance clause 4 says only that these shapes "still raise"
-- it does not pin down which exception class or message. This test
therefore asserts only the externally-observable contract: a non-zero exit
code, and the offending axis's name present in the combined output (mirrors
the "offending axis is named" discipline of every other test in this
family) -- never a hardcoded Python exception class name, and never a
specific parse-error phrase that would lock an implementation detail this
issue's Acceptance never claims.

Test hygiene: `isolated_vault_root` (opt-in, tests/conftest.py) gives each
test its own private staging directory outside this repo, torn down with
`tmp_path`; the real `data/vault/`, `data/trees/`, and `data/envelopes/`
directories a concurrent ingestion run depends on are never read, moved, or
written by this test.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from axial.chunk import HashingEmbedder, read_chunks, run_chunk_embedding
from axial.envelope import compute_source_id
from axial.schema import Schema, load_schema

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
STUB_TAG_RESPONSE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE"
STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE_SEQUENCE"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# Drawn verbatim from axial.chunk._CHUNK_PROMPT_TEMPLATE's own opening
# sentence (mirrors tests/test_tag_vocab_reask.py, seam decision 4).
CHUNK_PROMPT_MARKER = "argumentative chunk boundaries"
# Drawn verbatim from axial.xref._XREF_PROMPT_TEMPLATE's own opening
# sentence -- xref calls the LLM once per chunk regardless of whether the
# source has any artifacts, so it must be excluded too.
XREF_PROMPT_MARKER = "the source's known artifacts"

THEORY_SCHOOL_AXIS = "theory_school"
CLAIM_TYPE_AXIS = "claim_type"

# The bare-string dialect fixture (issue #105's own live evidence: "got str:
# 'discursive'"), asserted at test time to be a genuine in-vocab
# theory_school value.
BARE_STRING_IN_VOCAB_THEORY_SCHOOL = "discursive"

# An out-of-vocab bare-string theory_school value, asserted at test time to
# NOT be in vocabulary -- drives the re-ask scenario's first, uncorrected
# answer.
OUT_OF_VOCAB_BARE_STRING_THEORY_SCHOOL = "not-a-real-theory-school-value"

# Two distinct, real claim_type top-level ids (asserted at test time),
# fixing claim_type.primary and the single-element-list secondary dialect
# fixture (issue #105's own live evidence names this axis, though with a
# two-element list -- that shape belongs to this file's malformed-shape
# regression guard instead, see CLAIM_TYPE_MULTI_SECONDARY below).
CLAIM_TYPE_PRIMARY = "nationalism-theory"
CLAIM_TYPE_SINGLE_SECONDARY = "mobilization-and-recruitment"
CLAIM_TYPE_MULTI_SECONDARY_OTHER = "civilian-targeting"

# argparse's fallback error for an as-yet-nonexistent subcommand/flag. Any of
# these substrings in the combined output means the target subcommand/flag
# was never actually reached. Mirrors tests/test_vault_write.py and
# tests/test_tag_axis_prefix.py.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _trees_dir(root: Path) -> Path:
    return root / "data" / "trees"


def _envelopes_dir(root: Path) -> Path:
    return root / "data" / "envelopes"


def _vault_dir(root: Path) -> Path:
    return root / "data" / "vault"


def _prose_dir(root: Path) -> Path:
    return _vault_dir(root) / "prose"


def _run_axial(
    args: list[str],
    provider: str,
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


@contextlib.contextmanager
def _chdir(path: Path):
    """Temporarily change the process cwd to `path` -- see
    `_arrange_stored_envelope` below: `run_chunk_embedding` resolves its
    persisted-tree read (`axial.extract.tree_path`, via
    `axial.extract.TREES_DIR`) as a plain, cwd-relative path with no
    override parameter (only its OWN write target, `chunks_dir`, is
    overridable). Calling it in-process instead of shelling out to `axial
    chunk` needs this to reproduce the exact resolution a `cwd=`-scoped
    subprocess would get."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _run_envelope(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["envelope", *args], provider, cwd=cwd)


def _run_vault_write(
    provider: str,
    *args: str,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return _run_axial(["vault", "write", *args], provider, cwd=cwd, extra_env=extra_env)


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess, command: str) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `{command}` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `{command}` "
            f"subcommand/flag does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _existing_envelope_files(root: Path) -> set[Path]:
    envelopes_dir = _envelopes_dir(root)
    if not envelopes_dir.exists():
        return set()
    return set(envelopes_dir.glob("*.json"))


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path, root: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    <root>/data/trees/<source_id>.json so `axial.extract.extract` reuses it
    verbatim instead of running docling (mirrors tests/test_vault_write.py)."""
    source_id = compute_source_id(source_pdf)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _arrange_stored_envelope(root: Path) -> Path:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope exists on disk before vault write.
    Asserts the arrange step itself succeeded and produced exactly one new
    envelope file. (Mirrors tests/test_vault_write.py's helper of the same
    name.)

    Also writes the real, on-disk chunk artifact for this fixture (issue
    #154 slice 04: `axial vault write` no longer computes chunks itself --
    it reads `data/chunks/<source_id>.jsonl` via `axial.chunk.read_chunks`,
    and every test in this file drives `axial vault write` through this one
    shared arrange step, so the artifact is written here, once, for all of
    them)."""
    _place_tree_fixture(THESIS_PAPER_PDF, THESIS_PAPER_TREE_FIXTURE, root)
    before_files = _existing_envelope_files(root)

    result = _run_envelope("stub", str(THESIS_PAPER_PDF), cwd=root)
    _assert_not_argparse_fallback(result, "envelope")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` on "
        f"the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    new_files = _existing_envelope_files(root) - before_files
    assert len(new_files) == 1, (
        f"arrange step failed: expected exactly one new file under "
        f"{_envelopes_dir(root)} after `axial envelope`, got {len(new_files)}: "
        f"{sorted(new_files)}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    with _chdir(root):
        run_chunk_embedding(THESIS_PAPER_PDF, embedder=HashingEmbedder())

    return next(iter(new_files))


def _arrange_expected_chunk_count(root: Path) -> int:
    """Read the on-disk chunk artifact `_arrange_stored_envelope` already
    wrote and return the number of chunk records this fixture produces,
    used as ground truth for the tag-pass-family call-count assertion in
    the re-ask scenario -- never a hardcoded chunk count."""
    source_id = compute_source_id(THESIS_PAPER_PDF)
    with _chdir(root):
        records = read_chunks(source_id)
    assert len(records) >= 1, (
        f"arrange step failed: expected at least one chunk record in the "
        f"on-disk chunk artifact, got {len(records)}"
    )
    return len(records)


def _split_frontmatter(text: str, note_path: Path) -> tuple[dict, str]:
    """Split a note's text into its parsed YAML frontmatter mapping and its
    body string (mirrors tests/test_vault_write.py's helper of the same
    name)."""
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", (
        f"expected {note_path} to open with a YAML frontmatter block "
        f"delimited by a leading '---' line, got first line "
        f"{(lines[0] if lines else None)!r}. Full text (truncated): {text[:500]!r}"
    )

    closing_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing_index = index
            break
    assert closing_index is not None, (
        f"expected {note_path} to have a closing '---' line ending its "
        f"YAML frontmatter block, found none. Full text (truncated): {text[:1000]!r}"
    )

    frontmatter_text = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1 :])

    frontmatter = yaml.safe_load(frontmatter_text)
    assert isinstance(frontmatter, dict), (
        f"expected {note_path}'s YAML frontmatter block to parse to a "
        f"mapping/object, got {type(frontmatter).__name__}: {frontmatter!r}"
    )
    return frontmatter, body


def _all_prose_note_frontmatters(root: Path) -> list[dict]:
    """Every note under data/vault/prose/, parsed to its frontmatter mapping
    (asserts at least one exists, and that vault write actually produced
    notes -- an empty result here would silently make every downstream
    assertion in this file vacuous)."""
    prose_dir = _prose_dir(root)
    assert prose_dir.exists(), (
        f"expected {prose_dir} to exist after `axial vault write` ran, but it does not"
    )
    note_paths = [p for p in prose_dir.iterdir() if p.is_file()]
    assert note_paths, f"expected at least one prose note under {prose_dir}, got none"
    return [_split_frontmatter(p.read_text(encoding="utf-8"), p)[0] for p in note_paths]


def _read_recorded_prompts(record_path: Path) -> list[str]:
    """Every recorded prompt (one JSON-encoded string per line, written by
    `axial.llm.RecordLLMClient`), in call order (mirrors
    tests/test_tag_vocab_reask.py's helper of the same name)."""
    if not record_path.exists():
        return []
    prompts = []
    for line in record_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        prompt = json.loads(line)
        assert isinstance(prompt, str), (
            f"expected {record_path} to hold one JSON-encoded prompt string "
            f"per line (RecordLLMClient's own contract), got a "
            f"{type(prompt).__name__}: {prompt!r}"
        )
        prompts.append(prompt)
    return prompts


def _count_tag_family_calls(record_path: Path) -> int:
    """Every recorded prompt that is NEITHER a chunk-pass NOR an xref-pass
    call (mirrors tests/test_tag_vocab_reask.py's helper of the same name):
    for this fixture (zero artifacts), this is exactly the count of tag-
    pass-family calls -- an original per-chunk ask or a P0-6 bounded
    correction re-ask alike."""
    prompts = _read_recorded_prompts(record_path)
    return sum(
        1
        for prompt in prompts
        if CHUNK_PROMPT_MARKER not in prompt and XREF_PROMPT_MARKER not in prompt
    )


def _baseline_tag_payload(schema: Schema) -> dict:
    """A complete, schema-valid multi-axis tag-pass payload (every value a
    real member of its own axis's vocabulary, loaded at test time -- mirrors
    tests/test_tag_axis_prefix.py's helper of the same name). Callers
    override only the axis/axes this issue is about; every other axis stays
    a genuine, in-schema, PROPERLY-SHAPED value so the tag loop (which
    validates ALL of TAGGED_AXES in one response) never aborts on an axis
    this test isn't exercising."""
    role_in_argument = next(iter(schema.axes["role_in_argument"].tag_ids))

    non_country_scopes = [
        scope for scope in schema.axes["empirical_scope"].tag_ids if scope != "scope:country-case"
    ]
    assert non_country_scopes, (
        "arrange step failed: schema's empirical_scope axis has no "
        "non-country-case value to build a minimal valid payload with"
    )
    empirical_scope = non_country_scopes[0]

    field_primary = next(iter(schema.axes["field"].tag_ids))

    theory_school_primary = next(iter(schema.axes["theory_school"].tag_ids))

    return {
        "role_in_argument": role_in_argument,
        "empirical_scope": empirical_scope,
        "field": {"primary": field_primary, "secondary": []},
        "claim_type": {"primary": CLAIM_TYPE_PRIMARY, "secondary": None, "subtags": []},
        "theory_school": {"primary": theory_school_primary},
    }


def _assert_schema_invariants(schema: Schema) -> None:
    """Validate this test's own fixture literals against the REAL schema at
    test time (module docstring, seam decision 5) -- never hardcoding a
    correctness claim about the schema's contents."""
    theory_school_ids = schema.axes[THEORY_SCHOOL_AXIS].tag_ids
    assert schema.axes[THEORY_SCHOOL_AXIS].cardinality == "primary_plus_optional_secondary", (
        f"test setup invariant broken: {THEORY_SCHOOL_AXIS!r} must be a "
        f"primary_plus_optional_secondary axis, or this test would not be "
        f"exercising the dialect this issue is about"
    )
    assert BARE_STRING_IN_VOCAB_THEORY_SCHOOL in theory_school_ids, (
        f"test setup invariant broken: {BARE_STRING_IN_VOCAB_THEORY_SCHOOL!r} "
        f"must be a real member of the schema's theory_school axis, or the "
        f"bare-string coercion scenario would not actually be exercising an "
        f"in-vocab value"
    )
    assert OUT_OF_VOCAB_BARE_STRING_THEORY_SCHOOL not in theory_school_ids, (
        f"test setup invariant broken: {OUT_OF_VOCAB_BARE_STRING_THEORY_SCHOOL!r} "
        f"must NOT be a member of the schema's theory_school axis, or the "
        f"re-ask scenario would not actually be exercising the out-of-vocab path"
    )

    claim_type_ids = schema.axes[CLAIM_TYPE_AXIS].tag_ids
    assert schema.axes[CLAIM_TYPE_AXIS].cardinality == "primary_plus_optional_secondary", (
        f"test setup invariant broken: {CLAIM_TYPE_AXIS!r} must be a "
        f"primary_plus_optional_secondary axis, or this test would not be "
        f"exercising the dialect this issue is about"
    )
    for value, label in (
        (CLAIM_TYPE_PRIMARY, "CLAIM_TYPE_PRIMARY"),
        (CLAIM_TYPE_SINGLE_SECONDARY, "CLAIM_TYPE_SINGLE_SECONDARY"),
        (CLAIM_TYPE_MULTI_SECONDARY_OTHER, "CLAIM_TYPE_MULTI_SECONDARY_OTHER"),
    ):
        assert value in claim_type_ids, (
            f"test setup invariant broken: {label} ({value!r}) must be a "
            f"real top-level member of the schema's claim_type axis"
        )
    assert (
        len({CLAIM_TYPE_PRIMARY, CLAIM_TYPE_SINGLE_SECONDARY, CLAIM_TYPE_MULTI_SECONDARY_OTHER})
        == 3
    ), (
        "test setup invariant broken: CLAIM_TYPE_PRIMARY, "
        "CLAIM_TYPE_SINGLE_SECONDARY, and CLAIM_TYPE_MULTI_SECONDARY_OTHER "
        "must all be distinct claim_type ids"
    )


def test_theory_school_bare_string_primary_coerces_to_object_shape(isolated_vault_root):
    """Issue #105 acceptance clause 1: a bare, in-vocab string for
    theory_school (a primary_plus_optional_secondary axis) is coerced to
    `{"primary": <string>}` before validation and tags successfully -- never
    rejected as a shape error."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    _assert_schema_invariants(schema)

    payload = _baseline_tag_payload(schema)
    payload[THEORY_SCHOOL_AXIS] = BARE_STRING_IN_VOCAB_THEORY_SCHOOL

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` when the tag-pass "
        f"response declares theory_school as the bare string "
        f"{BARE_STRING_IN_VOCAB_THEORY_SCHOOL!r} (issue #105: a bare, "
        f"unambiguous string for a primary_plus_optional_secondary axis "
        f"must be coerced to {{'primary': <string>}} before validation, "
        f"never rejected as a shape error) -- got exit code "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    frontmatters = _all_prose_note_frontmatters(root)
    for frontmatter in frontmatters:
        theory_school = frontmatter.get(THEORY_SCHOOL_AXIS)
        assert isinstance(theory_school, dict), (
            f"expected every note's frontmatter {THEORY_SCHOOL_AXIS!r} to "
            f"be an object with a 'primary' key, got "
            f"{type(theory_school).__name__}: {theory_school!r}"
        )
        assert theory_school.get("primary") == BARE_STRING_IN_VOCAB_THEORY_SCHOOL, (
            f"expected theory_school.primary == "
            f"{BARE_STRING_IN_VOCAB_THEORY_SCHOOL!r} (the model's bare-"
            f"string dialect answer, coerced to the object shape), got "
            f"{theory_school.get('primary')!r} (full frontmatter: {frontmatter!r})"
        )


def test_claim_type_single_element_list_secondary_coerces_to_scalar(isolated_vault_root):
    """Issue #105 acceptance clause 2: a single-string secondary given as a
    one-element list is coerced to the bare scalar and tags successfully."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    _assert_schema_invariants(schema)

    payload = _baseline_tag_payload(schema)
    payload[CLAIM_TYPE_AXIS] = {
        "primary": CLAIM_TYPE_PRIMARY,
        "secondary": [CLAIM_TYPE_SINGLE_SECONDARY],
        "subtags": [],
    }

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` when the tag-pass "
        f"response declares claim_type.secondary as the one-element list "
        f"{[CLAIM_TYPE_SINGLE_SECONDARY]!r} (issue #105: a single-string "
        f"secondary given as a one-element list must be coerced to the bare "
        f"scalar, never rejected as a shape error) -- got exit code "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    frontmatters = _all_prose_note_frontmatters(root)
    for frontmatter in frontmatters:
        claim_type = frontmatter.get(CLAIM_TYPE_AXIS)
        assert isinstance(claim_type, dict), (
            f"expected every note's frontmatter {CLAIM_TYPE_AXIS!r} to be "
            f"an object, got {type(claim_type).__name__}: {claim_type!r}"
        )
        assert claim_type.get("secondary") == CLAIM_TYPE_SINGLE_SECONDARY, (
            f"expected claim_type.secondary == {CLAIM_TYPE_SINGLE_SECONDARY!r} "
            f"(the SCALAR, coerced from the model's one-element-list "
            f"dialect answer {[CLAIM_TYPE_SINGLE_SECONDARY]!r}), got "
            f"{claim_type.get('secondary')!r} (full frontmatter: {frontmatter!r})"
        )


def test_out_of_vocab_bare_string_still_triggers_correction_reask(isolated_vault_root):
    """Issue #105 acceptance clause 3: an out-of-vocab bare string for
    theory_school on the tag pass's first answer is coerced to shape FIRST,
    so it reaches vocabulary validation and genuinely triggers the #102
    bounded correction re-ask -- proven both by the final written value and
    by the recorded call count (exactly 2 tag-pass-family calls per chunk).

    Both sequence entries are the BARE-STRING dialect (module docstring,
    seam decision 2) -- never a well-formed dict for the second (corrected)
    entry -- specifically so `complete_json`'s own, unrelated generic
    degeneracy-reask budget (`axial/model_json.py`, `attempts=3`) cannot
    silently swallow the first bad-shaped attempt and land on a well-formed
    one before `run_tag`'s real parse+validate+#102-reask flow ever runs:
    that would make this test pass today, for the wrong reason, even
    without issue #105's fix (empirically confirmed while drafting this
    test). With both entries bare-string, TODAY's unfixed code raises a
    shape `TagParseError` on every one of `complete_json`'s 3 attempts
    (regardless of vocabulary) and hard-fails before ever reaching the #102
    mechanism -- this is asserted RED below. Once issue #105's coercion
    lands, the first (bare, out-of-vocab) attempt coerces to shape cleanly
    on `complete_json`'s very first try (`reject_degenerate_tag_values`
    never checks vocabulary), `run_tag`'s own validation then finds it
    out-of-vocab and the ALREADY-EXISTING #102 `apply_correction_reask`
    fires its single bounded re-ask -- calling `client.complete()` directly,
    bypassing `complete_json`/`reject_degenerate_tag_values` entirely for
    that second call -- landing on the second (bare, in-vocab) entry, which
    coerces and validates successfully."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    _assert_schema_invariants(schema)

    expected_chunk_count = _arrange_expected_chunk_count(root)

    bad_payload = _baseline_tag_payload(schema)
    bad_payload[THEORY_SCHOOL_AXIS] = OUT_OF_VOCAB_BARE_STRING_THEORY_SCHOOL

    good_payload = _baseline_tag_payload(schema)
    good_payload[THEORY_SCHOOL_AXIS] = BARE_STRING_IN_VOCAB_THEORY_SCHOOL

    sequence = [json.dumps(bad_payload), json.dumps(good_payload)]
    record_path = root.parent / f"{root.name}_shape_coercion_reask_record.jsonl"

    result = _run_vault_write(
        "record",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={
            STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR: json.dumps(sequence),
            RECORD_PATH_ENV_VAR: str(record_path),
        },
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` when the tag-pass's "
        f"first answer for each chunk carries the out-of-vocab bare string "
        f"{OUT_OF_VOCAB_BARE_STRING_THEORY_SCHOOL!r} for theory_school but "
        f"the bounded correction re-ask's answer carries a genuinely "
        f"in-vocab, properly-shaped value -- issue #105: coercion must run "
        f"BEFORE vocabulary validation, so this out-of-vocab bare string "
        f"reaches the existing #102 re-ask instead of hard-failing as a "
        f"shape error -- got exit code {result.returncode}\nstdout: "
        f"{result.stdout!r}\nstderr: {result.stderr!r}"
    )

    frontmatters = _all_prose_note_frontmatters(root)
    for frontmatter in frontmatters:
        theory_school = frontmatter.get(THEORY_SCHOOL_AXIS)
        assert isinstance(theory_school, dict), (
            f"expected every note's frontmatter {THEORY_SCHOOL_AXIS!r} to "
            f"be an object, got {type(theory_school).__name__}: {theory_school!r}"
        )
        assert theory_school.get("primary") == BARE_STRING_IN_VOCAB_THEORY_SCHOOL, (
            f"expected the corrected, in-vocab value "
            f"{BARE_STRING_IN_VOCAB_THEORY_SCHOOL!r} (the bounded "
            f"correction re-ask's own answer) in the written note's "
            f"theory_school.primary, got {theory_school.get('primary')!r} "
            f"(full frontmatter: {frontmatter!r})"
        )
        assert theory_school.get("primary") != OUT_OF_VOCAB_BARE_STRING_THEORY_SCHOOL, (
            f"expected the out-of-vocab bare string "
            f"{OUT_OF_VOCAB_BARE_STRING_THEORY_SCHOOL!r} (the tag pass's "
            f"own first, uncorrected answer) to never survive into the "
            f"written note -- got theory_school {theory_school!r}"
        )

    tag_family_calls = _count_tag_family_calls(record_path)
    expected_calls = 2 * expected_chunk_count
    assert tag_family_calls == expected_calls, (
        f"expected exactly {expected_calls} tag-pass-family LLM call(s) "
        f"({expected_chunk_count} chunk(s) x 2: one original ask + exactly "
        f"one bounded #102 correction re-ask each), got {tag_family_calls} "
        f"recorded non-chunk/xref-pass call(s) in {record_path}. Too few "
        f"means the out-of-vocab bare string hit a shape error instead of "
        f"reaching vocabulary validation, so the #102 re-ask never fired "
        f"(issue #105's own bug); too many means it looped past the single "
        f"bounded re-ask."
    )


@pytest.mark.parametrize(
    "axis_name, malformed_value, label",
    [
        (THEORY_SCHOOL_AXIS, 42, "number"),
        (THEORY_SCHOOL_AXIS, {"foo": "bar"}, "object with no 'primary' key"),
    ],
)
def test_genuinely_malformed_axis_shapes_still_raise(
    isolated_vault_root, axis_name, malformed_value, label
):
    """Issue #105 acceptance clause 4 (regression guard): a value that is
    NEITHER a bare in-vocab-shaped string NOR a single-element list -- a
    number, or an object with no 'primary' key -- is genuinely malformed and
    must still raise, never be silently coerced or accepted."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    _assert_schema_invariants(schema)

    payload = _baseline_tag_payload(schema)
    payload[axis_name] = malformed_value

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "vault write")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial vault write` when the "
        f"tag-pass response declares {axis_name}={malformed_value!r} (a "
        f"genuinely malformed shape -- {label} -- neither of the two "
        f"unambiguous coercible dialects issue #105 specifies), got exit "
        f"code 0\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert axis_name in combined, (
        f"expected the offending axis {axis_name!r} to be named in the "
        f"error output for the genuinely malformed shape ({label}), got "
        f"combined output: {combined!r}"
    )


def test_claim_type_multi_element_list_secondary_still_raises(isolated_vault_root):
    """Issue #105 acceptance clause 4 (regression guard, multi-element list
    case): a claim_type secondary given as a list with MORE than one
    element is a genuine cardinality violation -- not the single-element-
    list dialect this issue coerces -- and must still raise."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    _assert_schema_invariants(schema)

    multi_secondary = [CLAIM_TYPE_SINGLE_SECONDARY, CLAIM_TYPE_MULTI_SECONDARY_OTHER]
    payload = _baseline_tag_payload(schema)
    payload[CLAIM_TYPE_AXIS] = {
        "primary": CLAIM_TYPE_PRIMARY,
        "secondary": multi_secondary,
        "subtags": [],
    }

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "vault write")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial vault write` when the "
        f"tag-pass response declares claim_type.secondary as the MULTI-"
        f"element list {multi_secondary!r} -- issue #105: coercion is "
        f"limited to a ONE-element list, a longer list is a genuine "
        f"cardinality violation and must still raise -- got exit code 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert CLAIM_TYPE_AXIS in combined, (
        f"expected the offending axis {CLAIM_TYPE_AXIS!r} to be named in "
        f"the error output for the multi-element-list secondary, got "
        f"combined output: {combined!r}"
    )
