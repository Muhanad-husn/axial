"""Outer acceptance test for issue #102 (P0-6 refinement: a bounded
correction re-ask for an out-of-vocabulary tag, instead of an immediate hard
error).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a stubbed tag-pass response whose `claim_type.subtags` carries an
      out-of-vocabulary value on its FIRST answer for a chunk, and a
      genuinely in-vocabulary value on the SECOND (bounded correction
      re-ask) answer for that same chunk
When  the user runs `axial vault write <fixture>`
Then  it exits 0 and every written note's frontmatter carries the
      corrected, in-vocabulary subtag -- never the out-of-vocabulary one --
      and the run's own recorded LLM traffic proves the correction re-ask
      genuinely fired exactly once per chunk (never zero, never more)

Given a stubbed tag-pass response whose `claim_type.subtags` carries the
      SAME out-of-vocabulary value on EVERY call the run makes -- the
      original ask AND whatever correction re-ask the bounded budget
      affords
Then  `axial vault write` still exits non-zero, naming the offending value
      and axis with the existing `TagNotInSchemaError` wording on stderr,
      and the recorded traffic proves the bounded re-ask fired exactly once
      before the run gave up (P0-6's hard-error guard survives introducing
      the re-ask; the re-ask itself never loops unboundedly)

Given that same still-fatal run
Then  no file anywhere under the vault carries the valid value the model
      never actually returned -- the only path to a corrected tag is the
      MODEL correcting itself, never a code-side guess/normalization of the
      out-of-vocabulary string

Given a stubbed tag-pass response that is already in-vocabulary on its
      first answer for every chunk
Then  `axial vault write` exits 0 and the tag pass makes exactly one LLM
      call per chunk -- the correction path never fires, so the happy path
      pays no extra cost

See specs/PRODUCT.md §7.1 (loader contract) and §8 P0-6, both just revised:
"A tag absent from the schema triggers a bounded correction re-ask: the
tagger is shown that axis's controlled vocabulary and must return a valid
value or an explicit NONE. A tag still absent from the schema after that
single bounded re-ask is a hard error -- never a silent pass, and never a
code-side guess or normalization of the value. Only the model
self-corrects."

Fixture reuse: exactly tests/test_vault_write.py's and
tests/test_tag_axis_prefix.py's fixture (tests/fixtures/envelope/
thesis_paper.pdf + its committed real tree fixture
tests/fixtures/envelope/thesis_paper_tree.json). No new fixture is needed:
this issue is about tag-value validation/re-ask, not extraction/chunk shape.

Seam decision 1 -- driving the CLI end-to-end via `axial vault write`,
`isolated_vault_root`, and the already-locked `AXIAL_STUB_TAG_RESPONSE`
override seam
-----------------------------------------------------------------------
Exactly like tests/test_tag_axis_prefix.py's seam decision 1: the
still-fatal scenarios (2 and 3) reuse the already-locked
`AXIAL_STUB_TAG_RESPONSE` env var, which substitutes ONE raw tag-pass
response for EVERY tag-pass-family call the run makes (`src/axial/llm.py`'s
`_canned_response_for`) -- exactly the shape "the same out-of-vocab value on
every call, including the correction re-ask" needs, with no new seam
required for those two scenarios. `isolated_vault_root` (tests/conftest.py)
runs the `axial` CLI subprocess from a fresh, private staging directory so
this test can never collide with, or be polluted by, the real
`data/vault/` a concurrent ingestion run also writes into.

Seam decision 2 -- the NEW seam this test specifies for scenario 1
(correction succeeds): `AXIAL_STUB_TAG_RESPONSE_SEQUENCE`
-----------------------------------------------------------------------
No existing seam lets the tag pass's first call for a chunk return one raw
response and a LATER call (the bounded correction re-ask) return a
DIFFERENT one -- `AXIAL_STUB_TAG_RESPONSE` is one fixed string for the
entire process. This test locks a new seam, precisely, for the implementer
to build in `src/axial/llm.py`, mirroring the existing
`AXIAL_STUB_TAG_FAIL_AT` seam's "read fresh from the environment, driven by
the shared per-process tag-pass call counter" convention:

    AXIAL_STUB_TAG_RESPONSE_SEQUENCE (env var): a JSON-encoded array of raw
    strings, each string in exactly the shape `AXIAL_STUB_TAG_RESPONSE`
    already accepts (a complete raw tag-pass response body). When set to a
    non-empty JSON array, it takes priority over `AXIAL_STUB_TAG_RESPONSE`
    for the tag-pass-family canned-response dispatch (both `stub` and
    `record`, since `record` delegates to the same dispatch). The SAME
    per-process, 1-indexed counter that already drives
    `AXIAL_STUB_TAG_FAIL_AT` (`_tag_pass_call_count` today) selects which
    element answers the Nth such call: `sequence[(N - 1) % len(sequence)]`
    -- cycling once the array is exhausted, so e.g. a 2-element sequence
    alternates forever. Read fresh (JSON-decoded) from the environment on
    every call, exactly like every other seam this module already
    documents as "read fresh."

    Critically, this counter/dispatch must fire, and be incremented, for
    EVERY tag-pass-family LLM call the run makes -- an original per-chunk
    ask AND a P0-6 bounded correction re-ask alike, however the implementer
    chooses to shape or route the correction re-ask's own prompt -- so this
    seam can drive "chunk N's first answer is X, its correction answer is
    Y" end-to-end from a test, without this test needing to know or assert
    anything about the correction re-ask's internal prompt wording.

This test drives scenario 1 with `sequence = [<out-of-vocab payload>,
<corrected payload>]`: every ODD-numbered tag-pass-family call across the
whole run returns the out-of-vocab payload, every EVEN-numbered call
returns the corrected one. Because P0-6 mandates exactly ONE bounded
re-ask (see seam decision 5), each chunk consumes exactly two calls when
its first answer is bad -- which, by construction here, every chunk's
first answer always is -- so the odd/even parity self-sustains across
however many chunks this fixture yields, without this test ever having to
hardcode or predict a chunk count.

Seam decision 3 -- why the corrected/offending value lives on
`claim_type.subtags`, never `claim_type.primary`
-----------------------------------------------------------------------
`config/domains/syria/schema.yaml`'s `claim_type` axis is a list of `{id,
status, subtags: [...]}` entries; `axial.schema.load_schema`'s own
flattening (`_flatten_tag_ids`) extracts only each entry's top-level `id`
into the axis's vocabulary set -- `nationalism-theory`'s own declared
`subtags` (`nationalism:modernist`, `nationalism:ethno-symbolist`,
`nationalism:practice-based`) are NEVER folded into that set. So
`nationalism:modernist` is a genuine, real member of the schema's
`claim_type` vocabulary only as `nationalism-theory`'s own declared
SUBTAG (validated separately, by `validate_multi_value_tag`'s
subtags loop against that specific primary's own declared subtags) --
never as a legal `claim_type.primary` value in its own right. This test
fixes `claim_type.primary == "nationalism-theory"` (asserted at test time
to be a real member of the loaded schema's `claim_type` tag set) on EVERY
response in every scenario, and exercises the re-ask/hard-error/no-guess
contract entirely through the `subtags` entry -- `"sub:modernist"`
(asserted at test time to be declared under NEITHER `nationalism-theory`
nor any subtag it declares) as the out-of-vocab value, `"nationalism:
modernist"` (asserted at test time to be genuinely declared under
`nationalism-theory`) as the corrected one. This is the one deliberate,
justified deviation from the issue's own illustrative wording (which
named `claim_type primary = "sub:modernist"`): validating the literal
example against the real schema at test time (this file's own invariant
assertions) showed the corrected value is only ever legal as a subtag, so
this test targets the subtags field specifically rather than asserting a
correction path that could never actually succeed against the real schema.
The re-ask/hard-error/no-guess mechanism this issue locks is per-tag-value
and axis-agnostic -- it does not matter, behaviorally, whether the
offending value sits in a `primary` or a `subtags` slot.

Seam decision 4 -- proving the correction re-ask actually fired, via the
`record` provider and every OTHER pass's own prompt marker
-----------------------------------------------------------------------
Mirrors tests/test_vault_resume.py's seam decision 3 (counting LLM calls
through the already-existing `record` provider / `AXIAL_LLM_RECORD_PATH`
channel, never by patching internals), but generalized one step further:
this issue's spec never pins down the correction re-ask's own prompt
wording (only that it "shows that axis's controlled vocabulary"), so this
test does NOT invent or require a marker string for it -- doing so would
lock an implementation detail (the re-ask's exact prompt phrasing) this
issue's Acceptance never claims. Instead, this test identifies every OTHER
pass's calls by their own stable, already-committed prompt markers and
treats everything else recorded during a `vault write` run as
tag-pass-family (an original per-chunk ask OR a correction re-ask,
regardless of the re-ask's own wording):

  - chunk-pass calls: `CHUNK_PROMPT_MARKER`, drawn verbatim from
    `axial.chunk._CHUNK_PROMPT_TEMPLATE`'s own opening sentence.
  - xref-pass calls: `XREF_PROMPT_MARKER`, drawn verbatim from
    `axial.xref._XREF_PROMPT_TEMPLATE`'s own opening sentence. Unlike
    artifacts-pass calls (genuinely zero for this fixture, which
    tests/test_vault_write.py's own
    `test_vault_write_prose_pool_is_separate_from_empty_artifact_pool`
    already establishes has zero artifacts), `axial.xref.run_xref` calls
    the LLM once PER CHUNK regardless of whether the source has any
    artifacts at all (its own module docstring: "For each chunk, calls the
    LLM once") -- confirmed empirically while drafting this test (an
    earlier draft that excluded only the chunk marker overcounted by
    exactly one xref call per chunk), so excluding it explicitly is load-
    bearing, not cosmetic.

This test counts every recorded prompt matching NEITHER marker as the
proxy for "how many tag-pass-family LLM calls did this run make," and
compares it against the independently-derived chunk count (`axial chunk`,
run standalone as an arrange step, exactly as tests/test_vault_write.py's
seam decision 2 already establishes) to prove: scenario 1 makes exactly 2
tag-pass-family calls per chunk (the correction genuinely fired for every
chunk, and never looped further); scenario 2 makes exactly 2 total (one
ask + one bounded re-ask for the single chunk that fails, before the whole
run aborts); scenario 4 makes exactly 1 per chunk (the correction path
never fires on an already-valid answer).

Seam decision 5 -- asserting the re-ask is BOUNDED, literally
-----------------------------------------------------------------------
P0-6's own revised wording says "that SINGLE bounded re-ask." This test
takes that literally: scenario 1 asserts EXACTLY 2 tag-pass-family calls
per chunk (not "at least 2" -- an unbounded retry loop hoping for a
correction would also produce a note with the eventually-corrected value,
but must not be allowed to loop past the single bounded attempt), and
scenario 2 asserts EXACTLY 2 total calls before the hard error (proving
the bounded re-ask is not silently skipped either -- it must actually
fire once, even though it is scripted to fail again in that scenario).

Seam decision 6 -- error-quality assertions mirror the existing locked
discipline
-----------------------------------------------------------------------
Mirrors tests/test_tag_axis_prefix.py's seam decision 3: the still-fatal
scenario asserts the combined stdout+stderr carries the substring "not in
the schema" (the already-locked, exact wording of `TagNotInSchemaError`'s
own message in `src/axial/tag.py`: "tag {tag!r} is not in the schema's
{axis_name!r} axis"), plus the offending value and the axis name, printed
verbatim by the CLI's existing `error: {exc}` convention
(`src/axial/cli.py`) -- never asserting a Python exception class name that
is never actually printed to the user.

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

import yaml

from axial.chunk import run_chunk
from axial.envelope import compute_source_id
from axial.llm import StubLLMClient
from axial.schema import Schema, load_schema

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
STUB_TAG_RESPONSE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE"
# The new seam this test specifies (module docstring, seam decision 2). Not
# yet implemented anywhere in src/axial/llm.py as of this commit -- that is
# precisely why the correction-succeeds scenario is expected to fail red.
STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE_SEQUENCE"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# Drawn verbatim from axial.chunk._CHUNK_PROMPT_TEMPLATE's own opening
# sentence (module docstring, seam decision 4) -- the proxy this test uses
# to separate chunk-pass calls from tag-pass-family calls in a recorded run.
CHUNK_PROMPT_MARKER = "argumentative chunk boundaries"
# Drawn verbatim from axial.xref._XREF_PROMPT_TEMPLATE's own opening
# sentence (module docstring, seam decision 4) -- xref calls the LLM once
# per chunk regardless of whether the source has any artifacts, so this
# must be excluded too, or it is miscounted as a tag-pass-family call.
XREF_PROMPT_MARKER = "the source's known artifacts"

# The claim_type primary this test fixes on every response (module
# docstring, seam decision 3): a real, top-level claim_type vocabulary
# member whose OWN declared subtags include the corrected value under test.
CLAIM_TYPE_PRIMARY_UNDER_TEST = "nationalism-theory"
CLAIM_TYPE_AXIS = "claim_type"
OUT_OF_VOCAB_SUBTAG = "sub:modernist"
CORRECTED_SUBTAG = "nationalism:modernist"

# argparse's fallback error for an as-yet-nonexistent subcommand/flag. Any of
# these substrings in the combined output means the target subcommand's
# logic was never actually exercised. Mirrors tests/test_vault_write.py and
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
    """Temporarily change the process cwd to `path` (issue #151 slice 01
    migration -- see `_arrange_expected_chunk_count` below): the OLD
    `axial.chunk.run_chunk` mechanism calls `axial.extract.extract`
    internally, which resolves its persisted-tree cache directory
    (`axial.extract.TREES_DIR`) as a plain, cwd-relative path with no
    override parameter. Calling `run_chunk` in-process instead of shelling
    out to `axial chunk` (whose CLI verb now runs the NEW embedding-based
    mechanism as of issue #151) needs this to reproduce the exact
    resolution the old subprocess's own `cwd=` argument achieved."""
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
    name.)"""
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
    return next(iter(new_files))


def _arrange_expected_chunk_count(root: Path) -> int:
    """Independently call the OLD `axial.chunk.run_chunk` mechanism
    IN-PROCESS (stub client) to obtain the real number of chunks this
    fixture produces, used as ground truth for the tag-pass-family
    call-count assertions (module docstring, seam decision 4) -- never a
    hardcoded chunk count. Requires a stored envelope to already exist.

    Migrated off a subprocess call to the standalone `axial chunk` CLI
    (issue #151 slice 01): that CLI verb now runs the NEW embedding-based
    chunk mechanism and no longer emits chunk records on stdout at all. The
    OLD mechanism `axial vault write` itself still calls in-process
    (`axial.chunk.run_chunk`) ships unchanged until issue #154 retires it,
    so calling it here in-process too keeps this ground truth identical to
    what that unchanged call site actually produces."""
    with _chdir(root):
        records = run_chunk(
            THESIS_PAPER_PDF, client=StubLLMClient(), envelopes_dir=_envelopes_dir(root)
        )
    assert len(records) >= 1, (
        f"arrange step failed: expected at least one chunk record from run_chunk, got {len(records)}"
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
    notes)."""
    prose_dir = _prose_dir(root)
    assert prose_dir.exists(), (
        f"expected {prose_dir} to exist after `axial vault write` ran, but it does not"
    )
    note_paths = [p for p in prose_dir.iterdir() if p.is_file()]
    assert note_paths, f"expected at least one prose note under {prose_dir}, got none"
    return [_split_frontmatter(p.read_text(encoding="utf-8"), p)[0] for p in note_paths]


def _declared_subtags_for(schema: Schema, axis_name: str, primary: str) -> set[str]:
    """The `primary` tag's own declared `subtags` list, read directly from
    the schema's own raw `values` (mirrors `axial.tag._declared_subtags`'s
    logic, reimplemented locally here purely to build/verify this test's own
    fixture literals against the real schema -- never asserting on the
    private function itself)."""
    axis = schema.axes[axis_name]
    for entry in axis.raw.get("values") or []:
        if isinstance(entry, dict) and entry.get("id") == primary:
            return set(entry.get("subtags") or [])
    return set()


def _baseline_tag_payload(schema: Schema) -> dict:
    """A complete, schema-valid multi-axis tag-pass payload (every value a
    real member of its own axis's vocabulary, loaded at test time), with
    `claim_type.primary` fixed to `CLAIM_TYPE_PRIMARY_UNDER_TEST` and an
    empty `subtags` list. Callers overwrite `claim_type.subtags` per
    scenario; every other axis stays a genuine, in-schema value so the tag
    loop (which validates ALL tagged axes in one response) never aborts on
    an axis this test isn't exercising."""
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
    theory_school_status = schema.axes["theory_school"].raw.get("status")

    return {
        "role_in_argument": role_in_argument,
        "empirical_scope": empirical_scope,
        "field": {"primary": field_primary, "secondary": []},
        "claim_type": {
            "primary": CLAIM_TYPE_PRIMARY_UNDER_TEST,
            "secondary": None,
            "subtags": [],
        },
        "theory_school": {"primary": theory_school_primary, "status": theory_school_status},
    }


def _read_recorded_prompts(record_path: Path) -> list[str]:
    """Every recorded prompt (one JSON-encoded string per line, written by
    `axial.llm.RecordLLMClient`), in call order (mirrors
    tests/test_vault_resume.py's `_count_marker_occurrences` reading logic)."""
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
    call (module docstring, seam decision 4): for this fixture (zero
    artifacts, so zero artifacts-pass LLM calls), this is exactly the count
    of tag-pass-family calls -- an original per-chunk ask or a P0-6 bounded
    correction re-ask alike, regardless of the re-ask's own prompt
    wording."""
    prompts = _read_recorded_prompts(record_path)
    return sum(
        1
        for prompt in prompts
        if CHUNK_PROMPT_MARKER not in prompt and XREF_PROMPT_MARKER not in prompt
    )


def _assert_schema_invariants(schema: Schema) -> None:
    """Validate this test's own fixture literals against the REAL schema at
    test time (module docstring, seam decision 3) -- never hardcoding a
    correctness claim about the schema's contents."""
    assert CLAIM_TYPE_PRIMARY_UNDER_TEST in schema.axes[CLAIM_TYPE_AXIS].tag_ids, (
        f"test setup invariant broken: {CLAIM_TYPE_PRIMARY_UNDER_TEST!r} "
        f"must be a real top-level member of the schema's claim_type axis, "
        f"or this test's baseline payload would not even be valid"
    )
    declared = _declared_subtags_for(schema, CLAIM_TYPE_AXIS, CLAIM_TYPE_PRIMARY_UNDER_TEST)
    assert CORRECTED_SUBTAG in declared, (
        f"test setup invariant broken: {CORRECTED_SUBTAG!r} must be a real "
        f"declared subtag of {CLAIM_TYPE_PRIMARY_UNDER_TEST!r} in the "
        f"schema, or this test would not actually be exercising a genuine "
        f"correction path"
    )
    assert OUT_OF_VOCAB_SUBTAG not in declared, (
        f"test setup invariant broken: {OUT_OF_VOCAB_SUBTAG!r} must NOT be "
        f"a declared subtag of {CLAIM_TYPE_PRIMARY_UNDER_TEST!r}, or this "
        f"test would not actually be exercising the out-of-vocab path"
    )


def test_out_of_vocab_subtag_corrects_on_bounded_reask(isolated_vault_root):
    """Issue #102 acceptance clause 1: an out-of-vocab claim_type subtag on
    the first tag-pass answer, corrected to a genuinely in-vocab subtag on
    the bounded correction re-ask, tags the chunk with the CORRECTED value
    and `axial vault write` succeeds -- proven both by the written
    frontmatter and by the recorded call count (exactly 2 tag-pass-family
    calls per chunk, never more, never fewer)."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    _assert_schema_invariants(schema)

    expected_chunk_count = _arrange_expected_chunk_count(root)

    bad_payload = _baseline_tag_payload(schema)
    bad_payload["claim_type"]["subtags"] = [OUT_OF_VOCAB_SUBTAG]

    good_payload = _baseline_tag_payload(schema)
    good_payload["claim_type"]["subtags"] = [CORRECTED_SUBTAG]

    sequence = [json.dumps(bad_payload), json.dumps(good_payload)]
    record_path = root.parent / f"{root.name}_correction_succeeds_record.jsonl"

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
        f"first answer for each chunk carries an out-of-vocab claim_type "
        f"subtag ({OUT_OF_VOCAB_SUBTAG!r}) but the bounded correction "
        f"re-ask's answer carries a genuinely in-vocab one "
        f"({CORRECTED_SUBTAG!r}) -- issue #102: the model's self-correction "
        f"must be accepted, not treated as still-fatal -- got exit code "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    frontmatters = _all_prose_note_frontmatters(root)
    for frontmatter in frontmatters:
        claim_type = frontmatter.get("claim_type")
        assert isinstance(claim_type, dict) and isinstance(claim_type.get("subtags"), list), (
            f"expected every note's frontmatter 'claim_type' to be an "
            f"object with a 'subtags' list, got {claim_type!r}"
        )
        subtags = claim_type["subtags"]
        assert CORRECTED_SUBTAG in subtags, (
            f"expected the corrected, in-vocabulary subtag {CORRECTED_SUBTAG!r} "
            f"(issue #102: the bounded correction re-ask's own answer) in "
            f"the written note's claim_type.subtags, got {subtags!r} (full "
            f"frontmatter: {frontmatter!r})"
        )
        assert OUT_OF_VOCAB_SUBTAG not in subtags, (
            f"expected the out-of-vocab subtag {OUT_OF_VOCAB_SUBTAG!r} (the "
            f"tag pass's own FIRST, uncorrected answer) to never survive "
            f"into the written note -- only the model's own corrected "
            f"answer may land in frontmatter, never the original bad one -- "
            f"got claim_type.subtags {subtags!r} (full frontmatter: {frontmatter!r})"
        )

    tag_family_calls = _count_tag_family_calls(record_path)
    expected_calls = 2 * expected_chunk_count
    assert tag_family_calls == expected_calls, (
        f"expected exactly {expected_calls} tag-pass-family LLM call(s) "
        f"({expected_chunk_count} chunk(s) x 2: one original ask + exactly "
        f"one bounded correction re-ask each, issue #102's own 'single "
        f"bounded re-ask' wording), got {tag_family_calls} recorded "
        f"non-chunk-pass call(s) in {record_path}. This would fail either "
        f"if the correction re-ask never actually fired (too few calls) or "
        f"if it looped past the single bounded attempt (too many)."
    )


def test_persistently_out_of_vocab_subtag_still_hard_errors_after_bounded_reask(
    isolated_vault_root,
):
    """Issue #102 acceptance clause 2 (P0-6 preservation): a claim_type
    subtag that stays out-of-vocab on EVERY tag-pass answer, including the
    bounded correction re-ask, still raises the schema-gap hard error --
    and the recorded call count proves the bounded re-ask genuinely fired
    once (not skipped) before the run gave up (not looped further)."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    _assert_schema_invariants(schema)

    payload = _baseline_tag_payload(schema)
    payload["claim_type"]["subtags"] = [OUT_OF_VOCAB_SUBTAG]

    record_path = root.parent / f"{root.name}_still_fatal_record.jsonl"

    result = _run_vault_write(
        "record",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={
            STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload),
            RECORD_PATH_ENV_VAR: str(record_path),
        },
    )
    _assert_not_argparse_fallback(result, "vault write")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial vault write` when the "
        f"tag-pass response's claim_type.subtags is {OUT_OF_VOCAB_SUBTAG!r} "
        f"on EVERY call, including the bounded correction re-ask (issue "
        f"#102, P0-6: 'a tag still absent from the schema after that "
        f"single bounded re-ask is a hard error'), got exit code 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "not in the schema" in combined, (
        f"expected the existing TagNotInSchemaError wording ('... is not "
        f"in the schema's ... axis') to still surface once the bounded "
        f"re-ask is exhausted, got combined output: {combined!r}"
    )
    assert OUT_OF_VOCAB_SUBTAG in combined, (
        f"expected the offending value {OUT_OF_VOCAB_SUBTAG!r} to be named "
        f"in the error output, got combined output: {combined!r}"
    )
    assert CLAIM_TYPE_AXIS in combined, (
        f"expected the offending axis {CLAIM_TYPE_AXIS!r} to be named in "
        f"the error output, got combined output: {combined!r}"
    )

    tag_family_calls = _count_tag_family_calls(record_path)
    assert tag_family_calls == 2, (
        f"expected exactly 2 tag-pass-family LLM call(s) before the hard "
        f"error (one original ask + exactly one bounded correction re-ask "
        f"for the single chunk that fails, issue #102's own 'single "
        f"bounded re-ask' wording -- the run must abort on this chunk "
        f"before ever reaching a later one), got {tag_family_calls} "
        f"recorded non-chunk-pass call(s) in {record_path}. This would "
        f"fail either if the bounded re-ask was silently skipped (too few "
        f"calls) or if it looped past the single bounded attempt (too many)."
    )


def test_persistently_out_of_vocab_subtag_never_yields_a_code_side_guessed_note(
    isolated_vault_root,
):
    """Issue #102 acceptance clause 3 (no code-side guess): when the model
    only ever emits the out-of-vocab subtag (never self-corrects), no file
    anywhere under the vault ever carries the valid value the code could
    only have gotten by guessing/normalizing -- proving the only path to a
    corrected tag is the model itself returning one."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    _assert_schema_invariants(schema)

    payload = _baseline_tag_payload(schema)
    payload["claim_type"]["subtags"] = [OUT_OF_VOCAB_SUBTAG]

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial vault write` when the "
        f"model only ever emits the out-of-vocab subtag {OUT_OF_VOCAB_SUBTAG!r} "
        f"-- this scenario is the P0-6 preservation guard's own arrange "
        f"step; got exit code 0\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    vault_dir = _vault_dir(root)
    offending_files = []
    if vault_dir.exists():
        for path in vault_dir.rglob("*"):
            if not path.is_file():
                continue
            if CORRECTED_SUBTAG in path.read_text(encoding="utf-8"):
                offending_files.append(path)
    assert offending_files == [], (
        f"expected NO file anywhere under {vault_dir} to carry the valid "
        f"value {CORRECTED_SUBTAG!r} -- the model, driven by "
        f"{STUB_TAG_RESPONSE_ENV_VAR}, NEVER once returned it (only "
        f"{OUT_OF_VOCAB_SUBTAG!r}, on every call) -- issue #102: 'never a "
        f"code-side guess or normalization of the value; only the model "
        f"self-corrects'; got offending file(s): {sorted(offending_files)}"
    )


def test_in_vocab_subtag_never_triggers_correction_reask(isolated_vault_root):
    """Issue #102 acceptance clause 4 (happy path unaffected): a claim_type
    subtag that is already in-vocabulary on its first answer for every
    chunk tags immediately, with `axial vault write` exiting 0 and the tag
    pass making exactly one LLM call per chunk -- the correction path never
    fires, so the happy path pays no extra cost."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    _assert_schema_invariants(schema)

    expected_chunk_count = _arrange_expected_chunk_count(root)

    payload = _baseline_tag_payload(schema)
    payload["claim_type"]["subtags"] = [CORRECTED_SUBTAG]

    record_path = root.parent / f"{root.name}_happy_path_record.jsonl"

    result = _run_vault_write(
        "record",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={
            STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload),
            RECORD_PATH_ENV_VAR: str(record_path),
        },
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` when the tag-pass "
        f"response is already in-vocab on its first answer for every "
        f"chunk, got exit code {result.returncode}\nstdout: "
        f"{result.stdout!r}\nstderr: {result.stderr!r}"
    )

    frontmatters = _all_prose_note_frontmatters(root)
    for frontmatter in frontmatters:
        claim_type = frontmatter.get("claim_type")
        assert isinstance(claim_type, dict) and isinstance(claim_type.get("subtags"), list), (
            f"expected every note's frontmatter 'claim_type' to be an "
            f"object with a 'subtags' list, got {claim_type!r}"
        )
        assert claim_type["subtags"] == [CORRECTED_SUBTAG], (
            f"expected claim_type.subtags to be exactly {[CORRECTED_SUBTAG]!r} "
            f"(untouched, already in-vocab), got {claim_type['subtags']!r} "
            f"(full frontmatter: {frontmatter!r})"
        )

    tag_family_calls = _count_tag_family_calls(record_path)
    assert tag_family_calls == expected_chunk_count, (
        f"expected exactly {expected_chunk_count} tag-pass-family LLM "
        f"call(s) (one per chunk, issue #102: 'the happy path is "
        f"unaffected' -- the correction re-ask must never fire when the "
        f"first answer is already in-vocab), got {tag_family_calls} "
        f"recorded non-chunk-pass call(s) in {record_path}. Extra calls "
        f"here would mean the correction path fired even though nothing "
        f"was out-of-vocab."
    )
