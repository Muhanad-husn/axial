"""Outer acceptance test for issue #96 (tag validation: normalize
axis-prefixed near-miss values, e.g. `field:ideology` -> `ideology`).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a stubbed tag-pass response whose `field` axis primary arrives as
      `"field:ideology"` (the axis's OWN name prefixed onto a value that IS
      legal for that axis once the prefix is stripped)
When  the user runs `axial vault write <fixture>`
Then  it exits 0 and the written note's frontmatter carries
      `field.primary == "ideology"` (the normalized, unprefixed form)

Given a stubbed response whose `field` axis primary is genuinely
      out-of-vocabulary -- either bare (`"ethnicity"`) or prefixed but still
      invalid after stripping (`"field:ethnicity"`)
Then  `axial vault write` still exits non-zero, naming the offending value
      and the axis, with the schema's existing "not in the schema" error
      wording -- the P0-6 schema-gap signal is preserved, never smoothed
      over by the new normalization

Given a stubbed response whose `empirical_scope` axis carries its own
      normal, ALREADY-prefixed vocabulary value `"scope:general"` (a value
      that is prefixed by "scope", not by the axis's own name
      "empirical_scope")
Then  `axial vault write` still exits 0 and the note's frontmatter carries
      `empirical_scope.value == "scope:general"` verbatim, completely
      unaffected by the new normalization

See GitHub issue #96 ("tag validation: normalize axis-prefixed values
('field:ideology') when the suffix is in-vocabulary"): "Before axis-
vocabulary validation ... normalize a string value of the form
`<axis_name>:<suffix>` to `<suffix>` iff `<suffix>` is in that axis's
vocabulary. Everything else is untouched: genuinely out-of-vocab values ...
still raise `TagNotInSchemaError` ...; values already carrying a legal
prefix-form vocabulary entry (e.g. `scope:country-case`, `role:setup` are
themselves the stored vocabulary forms) are unaffected because normalization
only fires when the raw value is NOT in vocabulary and the axis-name-
stripped suffix IS."

Fixture reuse: exactly tests/test_vault_write.py's and
tests/test_vault_tag_frontmatter.py's fixture
(tests/fixtures/envelope/thesis_paper.pdf + its committed real tree fixture
tests/fixtures/envelope/thesis_paper_tree.json). No new fixture is needed:
this issue is about tag-value validation, not extraction/chunk shape.

Seam decision 1 -- driving the CLI end-to-end via `axial vault write` and
the already-locked `AXIAL_STUB_TAG_RESPONSE` override seam
-----------------------------------------------------------------------
This test reuses two seams already locked by tests/test_tag.py (seam
decision 5) and tests/test_vault_tag_frontmatter.py: (a) the env var
`AXIAL_STUB_TAG_RESPONSE`, which -- when set -- becomes the stub LLM
client's tag-pass response verbatim for EVERY tag call the run makes
(src/axial/llm.py's `_canned_response_for`), letting this test drive
exactly which raw tag payload the pipeline receives without asserting
anything about how that override is implemented internally; and (b) the
`isolated_vault_root` fixture (tests/conftest.py), which runs the `axial`
CLI subprocess from a fresh, private staging directory so this test can
never collide with, or be polluted by, the real `data/vault/` a concurrent
ingestion run also writes into. The acceptance criterion is checked at the
`axial vault write` level (not `axial tag`'s own stdout) specifically
because the issue's Acceptance section is phrased in terms of the WRITTEN
note's frontmatter carrying the normalized value -- exactly mirroring how
tests/test_vault_tag_frontmatter.py already locks `frontmatter["field"]`'s
nested shape for the same axis.

Seam decision 2 -- a schema-derived baseline payload, only the axis under
test overridden
-----------------------------------------------------------------------
The tag pass validates every prose axis in one response (`TAGGED_AXES`:
role_in_argument, empirical_scope, field, claim_type, theory_school), so a
malformed/incomplete payload for any OTHER axis would abort the run before
ever reaching this issue's field-axis behavior. This test never hardcodes
which values are legal for the axes it isn't testing -- it loads the schema
at test time (`axial.schema.load_schema`) and builds one baseline payload
whose non-field-axis values are ordinary members of their own axis's
vocabulary (mirroring tests/test_tag.py's seam decision 10 discipline of
loading vocabulary at test time, never hardcoding it as a correctness
literal). Only `field` (or, in the third scenario, `empirical_scope`) is
then overridden per test with the literal value the Gherkin names -- that
literal is disposable test *input* fixed by the issue's own text
(`field:ideology`, `ethnicity`, `field:ethnicity`, `scope:general`), not a
vocabulary correctness assertion.

Seam decision 3 -- error-quality assertions mirror the existing locked
discipline, without hardcoding the exception class name
-----------------------------------------------------------------------
Mirroring tests/test_tag.py's seam decision 8/12 (non-zero exit code, no
`ARGPARSE_FALLBACK_MARKERS`, offending value and axis name named in the
combined output), the two still-fatal scenarios below also assert the
combined output carries the substring "not in the schema" -- the exact,
already-locked wording of `TagNotInSchemaError`'s own message
(`src/axial/tag.py`: "tag {tag!r} is not in the schema's {axis_name!r}
axis"), printed verbatim by the CLI's existing `error: {exc}` convention
(`src/axial/cli.py`). This locks that the SAME hard-error signal fires for
a genuinely out-of-vocab value, both with and without an axis-name prefix,
without asserting a Python exception class name that is never actually
printed to the user.

Seam decision 4 -- why `scope:general` specifically proves the "no-op"
guard, not just "any working scope value"
-----------------------------------------------------------------------
`empirical_scope`'s OWN vocabulary is itself prefix-shaped (`scope:*`), and
`scope:general` is chosen deliberately because it exercises a REAL risk: an
overly-broad normalization that strips "anything before a colon" (rather
than specifically `<axis_name>:`, i.e. only an `"empirical_scope:"` prefix
for this axis) would incorrectly rewrite `scope:general` to `general` --
which is NOT a member of `empirical_scope`'s vocabulary -- and this test
would catch that regression by asserting the value survives verbatim.
`role_in_argument`'s analogous `role:*` vocabulary is named by the issue as
the same class of case but is not separately re-tested here, since
`scope:general` alone already exercises the identical mechanism (a
`<word>:` prefix that is NOT the axis's own name).

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

from axial.chunk import run_chunk_recursive
from axial.envelope import compute_source_id
from axial.schema import load_schema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
STUB_TAG_RESPONSE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE"

# argparse's fallback error for an as-yet-nonexistent subcommand/flag. Any of
# these substrings in the combined output means the target subcommand's
# logic was never actually exercised. Mirrors tests/test_vault_write.py and
# tests/test_tag.py.
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


@contextlib.contextmanager
def _chdir(path: Path):
    """Temporarily change the process cwd to `path`: `run_chunk_recursive`
    resolves its persisted-tree read (`axial.extract.tree_path`, via
    `axial.extract.TREES_DIR`) as a plain, cwd-relative path with no
    override parameter. Calling it in-process needs this to reproduce the
    exact resolution a `cwd=`-scoped subprocess would get."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


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
        run_chunk_recursive(THESIS_PAPER_PDF)

    return next(iter(new_files))


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


def _baseline_tag_payload(schema) -> dict:
    """A complete, schema-valid multi-axis tag-pass payload (every value a
    real member of its own axis's vocabulary, loaded at test time -- seam
    decision 2). Callers override only the one axis this issue is about;
    every other axis stays a genuine, in-schema value so the tag loop
    (which validates ALL of `TAGGED_AXES` in one response) never aborts on
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

    claim_type_primary = next(iter(schema.axes["claim_type"].tag_ids))

    theory_school_primary = next(iter(schema.axes["theory_school"].tag_ids))
    theory_school_status = schema.axes["theory_school"].raw.get("status")

    return {
        "role_in_argument": role_in_argument,
        "empirical_scope": empirical_scope,
        "field": {"primary": field_primary, "secondary": []},
        "claim_type": {"primary": claim_type_primary, "subtags": []},
        "theory_school": {"primary": theory_school_primary, "status": theory_school_status},
    }


def test_field_axis_prefixed_value_normalizes_to_its_in_vocab_suffix(isolated_vault_root):
    """Issue #96 acceptance clause 1: `field:ideology` (with `ideology` in
    the field axis vocabulary) tags the chunk as `ideology` and vault write
    succeeds."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    assert "ideology" in schema.axes["field"].tag_ids, (
        "test setup invariant broken: 'ideology' must be a real member of "
        "the schema's field axis vocabulary, or this test would not "
        "actually be exercising the near-miss normalization path"
    )

    payload = _baseline_tag_payload(schema)
    payload["field"] = {"primary": "field:ideology", "secondary": []}

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` when the tag-pass "
        f"response declares field.primary='field:ideology' (axis-name-"
        f"prefixed, but 'ideology' is a real field-axis value) -- issue #96: "
        f"the raw value must be normalized to its in-vocabulary suffix "
        f"before validation, not rejected -- got exit code "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    frontmatters = _all_prose_note_frontmatters(root)
    for frontmatter in frontmatters:
        field = frontmatter.get("field")
        assert isinstance(field, dict), (
            f"expected every note's frontmatter 'field' to be an object "
            f"with a 'primary' key, got {type(field).__name__}: {field!r}"
        )
        assert field.get("primary") == "ideology", (
            f"expected the normalized, unprefixed suffix 'ideology' as "
            f"field.primary (issue #96: '<axis_name>:<suffix>' normalizes "
            f"to '<suffix>' iff the suffix is in-vocabulary) -- the raw "
            f"model value was 'field:ideology' -- got "
            f"{field.get('primary')!r} (full frontmatter: {frontmatter!r})"
        )


def test_field_axis_genuinely_out_of_vocab_bare_value_still_errors(isolated_vault_root):
    """Issue #96 acceptance clause 2 (bare form): a genuinely out-of-vocab
    value on the field axis (not merely a near-miss prefix) still raises
    the schema-gap hard error -- P0-6 is preserved."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    offending_value = "ethnicity"
    assert offending_value not in schema.axes["field"].tag_ids, (
        f"test setup invariant broken: {offending_value!r} must not already "
        f"be a member of the schema's field tag set, or this test would not "
        f"actually be exercising the genuinely-out-of-vocab error path"
    )

    payload = _baseline_tag_payload(schema)
    payload["field"] = {"primary": offending_value, "secondary": []}

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "vault write")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial vault write` when the "
        f"tag-pass response declares field.primary={offending_value!r}, a "
        f"genuinely out-of-vocab value with no valid axis-prefix reading "
        f"(issue #96, P0-6: 'genuinely out-of-vocab values must still "
        f"raise TagNotInSchemaError'), got exit code 0\nstdout: "
        f"{result.stdout!r}\nstderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "not in the schema" in combined, (
        f"expected the existing TagNotInSchemaError wording ('... is not "
        f"in the schema's ... axis') to still surface on a genuinely "
        f"out-of-vocab field value, got combined output: {combined!r}"
    )
    assert offending_value in combined, (
        f"expected the offending value {offending_value!r} to be named in "
        f"the error output, got combined output: {combined!r}"
    )
    assert "field" in combined, (
        f"expected the offending axis 'field' to be named in the error "
        f"output, got combined output: {combined!r}"
    )


def test_field_axis_prefixed_but_still_out_of_vocab_value_still_errors(isolated_vault_root):
    """Issue #96 acceptance clause 2 (prefixed form): a value that carries
    the field-axis-name prefix but whose stripped suffix is STILL not a
    real field-axis vocabulary member (`field:ethnicity`) must still be a
    hard error -- normalization only fires when the stripped suffix IS
    in-vocabulary, never as a blanket prefix-strip."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    offending_value = "field:ethnicity"
    stripped_suffix = "ethnicity"
    assert offending_value not in schema.axes["field"].tag_ids, (
        f"test setup invariant broken: {offending_value!r} must not already "
        f"be a member of the schema's field tag set"
    )
    assert stripped_suffix not in schema.axes["field"].tag_ids, (
        f"test setup invariant broken: the stripped suffix "
        f"{stripped_suffix!r} must ALSO not be a member of the schema's "
        f"field tag set, or this would exercise the normalization "
        f"(happy-path) case instead of the still-fatal one"
    )

    payload = _baseline_tag_payload(schema)
    payload["field"] = {"primary": offending_value, "secondary": []}

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "vault write")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial vault write` when the "
        f"tag-pass response declares field.primary={offending_value!r} -- "
        f"axis-name-prefixed, but the stripped suffix {stripped_suffix!r} "
        f"is ALSO not in the field axis vocabulary (issue #96: "
        f"normalization fires ONLY when the raw value is not in vocabulary "
        f"AND the stripped suffix IS -- neither condition rescues this "
        f"value), got exit code 0\nstdout: {result.stdout!r}\nstderr: "
        f"{result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "not in the schema" in combined, (
        f"expected the existing TagNotInSchemaError wording ('... is not "
        f"in the schema's ... axis') to still surface on a still-invalid "
        f"prefixed field value, got combined output: {combined!r}"
    )
    assert "field" in combined, (
        f"expected the offending axis 'field' to be named in the error "
        f"output, got combined output: {combined!r}"
    )


def test_empirical_scope_axis_own_prefixed_vocabulary_is_unaffected(isolated_vault_root):
    """Issue #96 acceptance clause 3: an axis whose OWN vocabulary values
    are themselves prefixed (`empirical_scope`'s `scope:*`) must behave
    exactly as today -- `scope:general` is not the empirical_scope axis's
    own name prefixed onto anything, so it must never be touched by the new
    normalization, verbatim in, verbatim out."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    scope_value = "scope:general"
    assert scope_value in schema.axes["empirical_scope"].tag_ids, (
        f"test setup invariant broken: {scope_value!r} must be a real "
        f"member of the schema's empirical_scope axis vocabulary, or this "
        f"test would not actually be exercising the prefixed-vocabulary "
        f"no-op guard"
    )

    payload = _baseline_tag_payload(schema)
    payload["empirical_scope"] = scope_value

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` when the tag-pass "
        f"response declares empirical_scope={scope_value!r} (its own "
        f"normal, real vocabulary value -- issue #96: axes whose "
        f"vocabulary values are themselves prefixed must behave exactly as "
        f"today), got exit code {result.returncode}\nstdout: "
        f"{result.stdout!r}\nstderr: {result.stderr!r}"
    )

    frontmatters = _all_prose_note_frontmatters(root)
    for frontmatter in frontmatters:
        empirical_scope = frontmatter.get("empirical_scope")
        assert isinstance(empirical_scope, dict), (
            f"expected every note's frontmatter 'empirical_scope' to be an "
            f"object with a 'value' key (per the already-locked reshaping "
            f"in tests/test_vault_tag_frontmatter.py), got "
            f"{type(empirical_scope).__name__}: {empirical_scope!r}"
        )
        assert empirical_scope.get("value") == scope_value, (
            f"expected empirical_scope.value to remain exactly "
            f"{scope_value!r}, completely untouched by the new axis-prefix "
            f"normalization (issue #96: 'axes whose vocabulary values are "
            f"themselves prefixed ... behave exactly as today'), got "
            f"{empirical_scope.get('value')!r} (full frontmatter: {frontmatter!r})"
        )
