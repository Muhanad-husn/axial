"""Outer acceptance test for issue #194, slice 05 ("Loosen & enrich polity
capture in tagging").

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given an extracted fixture source with a stored envelope and chunks,
      AXIAL_LLM_PROVIDER=stub returning empirical_scope=scope:country-case
      with polity=<a non-example value> and
      polities_touched=[<two engaged polities>]
When   the user runs `axial tag <fixture>`
Then   each scope:country-case record carries a free-text `polity` (never a
       `country` key)
And    a `polity` outside the schema's `polity_examples` is accepted and
       logged as a candidate, never fatal (#77)
And    a scope:country-case record with a missing/empty `polity` exits
       non-zero with a clear error (unchanged hard error)
And    each record carries a many-valued `polities_touched` list, validated
       as free text (no closed-vocabulary check)
And    `axial vault write` round-trips both `empirical_scope.polity` and the
       `polities_touched` list into the prose note frontmatter

See specs/PRODUCT.md (spec commit e60fd5b) Appendix C ("Empirical-scope
axis": "The field is named `polity`, not `country`, deliberately ... Emitting
a value outside the examples is the intended behaviour, not disobedience ...
accepted and logged as candidate additions, never fatal in v0"; "Polities-
touched facet": "`polities_touched` is a many-valued list of every polity the
chunk *substantively engages* ... each a free-text value under the same
faithful-naming ... rules as `polity` above"), Appendix G (`polity_examples:
[...]` replacing `country_list`; the new `polities_touched` axis:
`cardinality: many`, `values: free_text`), Appendix H (`empirical_scope: {
value: scope:country-case, polity: Syria }` / `polities_touched: [Syria,
Iraq]`), and §5 stage 6 / §7.2 (chunk-level metadata: "empirical-scope value
(+ `polity` where applicable), the `polities_touched` list ..."). Plan:
plans/tag/05-polity-capture.md.

Fixture reuse: exactly tests/ingestion/test_tag.py's and tests/ingestion/
test_vault_tag_frontmatter.py's fixture (tests/fixtures/envelope/
thesis_paper.pdf + its committed real tree fixture thesis_paper_tree.json).
No new fixture is needed: this slice is about tag-value naming/shape, not
extraction/chunk shape.

Seam decision 1 -- driving a custom polity/polities_touched payload via the
already-locked `AXIAL_STUB_TAG_RESPONSE` env var, never touching src/
-----------------------------------------------------------------------
Mirrors tests/ingestion/test_tag.py's (slice 02) and tests/ingestion/
test_tag_shape_coercion.py's seam exactly: `AXIAL_STUB_TAG_RESPONSE`, when
set, substitutes the stub/record clients' tag-pass response with that raw
JSON string verbatim for every tag-pass-family call the run makes. This
test builds a schema-derived baseline payload (every OTHER axis a genuine,
in-schema, properly-shaped value, read at test time -- never hardcoded) and
overrides only `polity` and `polities_touched`, the two fields this slice
is about.

Seam decision 2 -- the offending polity is verified OUT of the schema's
example list at test time, never assumed
-----------------------------------------------------------------------
This test drives `polity="Ottoman Empire"` -- a historical, supra-national
referent absent from any nation-state example list by construction -- but
never hardcodes that absence as a correctness claim. It loads the schema at
test time and asserts `"Ottoman Empire" not in schema.polity_examples`
before running anything, so if a future schema edit ever adds it, this test
fails loudly at that assertion instead of silently exercising the wrong
path. This also fixes `Schema.polity_examples` (the Appendix G rename from
`country_list`) as part of the locked contract: today's loader exposes
`country_list`, not `polity_examples`, so this assertion is expected to be
part of the initial red.

Seam decision 3 -- "never a `country` key", not merely "carries `polity`"
-----------------------------------------------------------------------
The Gherkin's strongest, most specific clause is "never a `country` key" --
a naive implementation could add `polity` alongside a still-emitted legacy
`country` and accidentally satisfy a weaker "carries polity" check. This
test asserts BOTH: every tagged record (and, for the vault round-trip, every
note's `empirical_scope` frontmatter block) carries no `country` key at all,
AND a scope:country-case record's `polity` equals the injected value
verbatim.

Seam decision 4 -- missing-polity hard error: a genuine regression guard,
not a discriminating red by itself
-----------------------------------------------------------------------
Because today's (pre-slice) code already hard-errors whenever the top-level
`country` key it looks for is absent -- which it always is once the payload
uses `polity` instead -- this specific scenario can pass today for an
unrelated reason (the code doesn't recognize `polity` at all yet, not
because it correctly validates a genuinely-missing `polity`). It is kept
here anyway because it is a real, spec-named clause of this slice's
Gherkin ("unchanged hard error") and a genuine regression guard once
`polity` parsing exists: the acceptance-and-logging test (seam decisions 1-3
above) and the vault round-trip test (seam decision 6 below) are this file's
actual red-for-the-right-reason proof of the new behavior; this scenario
guards that the pre-existing hard-error contract survives the rename.

Seam decision 5 -- `polities_touched` is asserted as an exact list, never
validated against a closed vocabulary
-----------------------------------------------------------------------
Appendix C/G: `polities_touched` is `cardinality: many`, `values: free_text`
-- there is no controlled vocabulary to check membership against (unlike
every other tagged axis in this pipeline). This test asserts the parsed
value is a `list` of non-empty strings equal, verbatim, to the two-element
list this test's own fixture payload injected -- proving the facet round-
trips faithfully, without inventing a vocabulary check the spec explicitly
says does not apply.

Seam decision 6 -- vault round-trip via `isolated_vault_root`
-----------------------------------------------------------------------
Mirrors tests/ingestion/test_vault_tag_frontmatter.py and tests/ingestion/
test_tag_shape_coercion.py exactly: every `axial` subprocess this test
spawns runs with `cwd` set to `isolated_vault_root` (tests/conftest.py), a
fresh per-test staging directory outside this repo entirely, so this test
never collides with (or is polluted by) the real `data/vault/` a concurrent
ingestion run also writes into.

Test hygiene: `isolated_vault_root` (opt-in, tests/conftest.py) gives each
test its own private staging directory, torn down with `tmp_path`; the real
`data/vault/`, `data/trees/`, and `data/envelopes/` directories a concurrent
ingestion run depends on are never read, moved, or written by this test.
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
from axial.schema import Schema, load_schema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
STUB_TAG_RESPONSE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE"

COUNTRY_CASE_SCOPE_VALUE = "scope:country-case"

# A historical, supra-national referent -- deliberately never a nation-state
# example (Appendix C's own illustration: "an empire, a mandate, a former
# union"), so the examples-not-menu acceptance path is genuinely exercised,
# not accidentally satisfied by an in-list value.
OFFENDING_POLITY = "Ottoman Empire"
SECOND_ENGAGED_POLITY = "France"
POLITIES_TOUCHED = [OFFENDING_POLITY, SECOND_ENGAGED_POLITY]

# argparse's fallback error for an as-yet-nonexistent subcommand/flag. Any of
# these substrings in the combined output means the target subcommand's
# logic was never actually exercised. Mirrors every other test in this
# family (tests/ingestion/test_tag.py, test_tag_shape_coercion.py, etc.).
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
    """Temporarily change the process cwd to `path` -- `run_chunk_recursive`
    resolves its persisted-tree read as a plain, cwd-relative path with no
    override parameter. Calling it in-process instead of shelling out to
    `axial chunk` needs this to reproduce the exact resolution a
    `cwd=`-scoped subprocess would get (mirrors tests/ingestion/
    test_tag_shape_coercion.py's helper of the same name)."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _run_envelope(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["envelope", *args], provider, cwd=cwd)


def _run_tag(
    provider: str,
    *args: str,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return _run_axial(["tag", *args], provider, cwd=cwd, extra_env=extra_env)


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
    verbatim instead of running docling (mirrors tests/ingestion/
    test_vault_tag_frontmatter.py)."""
    source_id = compute_source_id(source_pdf)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _arrange_stored_envelope(root: Path) -> Path:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope exists on disk before tagging/vault
    write, and write the real, on-disk chunk artifact for this fixture.
    Asserts the arrange step itself succeeded and produced exactly one new
    envelope file (mirrors tests/ingestion/test_tag_shape_coercion.py's
    helper of the same name)."""
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


def _parse_records(stdout: str, container_keys: tuple[str, ...]) -> list[dict]:
    """Parse output records from an axial subcommand's stdout, tolerating a
    bare JSON array, a JSON object with one of `container_keys` as a
    top-level array, or newline-delimited JSON (one record per line).
    Mirrors tests/ingestion/test_tag.py's `_parse_records`."""
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


def _split_frontmatter(text: str, note_path: Path) -> tuple[dict, str]:
    """Split a note's text into its parsed YAML frontmatter mapping and its
    body string (mirrors tests/ingestion/test_vault_tag_frontmatter.py's
    helper of the same name)."""
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
    (asserts at least one exists, mirrors tests/ingestion/
    test_tag_shape_coercion.py's helper of the same name)."""
    prose_dir = _prose_dir(root)
    assert prose_dir.exists(), (
        f"expected {prose_dir} to exist after `axial vault write` ran, but it does not"
    )
    note_paths = [p for p in prose_dir.iterdir() if p.is_file()]
    assert note_paths, f"expected at least one prose note under {prose_dir}, got none"
    return [_split_frontmatter(p.read_text(encoding="utf-8"), p)[0] for p in note_paths]


def _baseline_country_case_payload(schema: Schema) -> dict:
    """A complete, schema-valid multi-axis tag-pass payload whose
    empirical_scope is fixed to scope:country-case and every OTHER axis is a
    genuine, in-schema, properly-shaped value read from the schema at test
    time -- never hardcoded (mirrors tests/ingestion/
    test_tag_shape_coercion.py's `_baseline_tag_payload`). Callers override
    only `polity`/`polities_touched`, the two fields this slice is about."""
    role_in_argument = next(iter(schema.axes["role_in_argument"].tag_ids))
    field_primary = next(iter(schema.axes["field"].tag_ids))
    claim_type_primary = next(iter(schema.axes["claim_type"].tag_ids))
    theory_school_primary = next(iter(schema.axes["theory_school"].tag_ids))
    return {
        "role_in_argument": role_in_argument,
        "empirical_scope": COUNTRY_CASE_SCOPE_VALUE,
        "field": {"primary": field_primary, "secondary": []},
        "claim_type": {"primary": claim_type_primary, "secondary": None, "subtags": []},
        "theory_school": {"primary": theory_school_primary},
    }


def _assert_offending_polity_is_out_of_examples(schema: Schema) -> None:
    """Verify this test's own fixture literal against the REAL schema at
    test time (seam decision 2): `OFFENDING_POLITY` must genuinely be
    outside the schema's example list, and the schema must expose that list
    under its Appendix-G-renamed name, `polity_examples` (not the legacy
    `country_list`)."""
    assert hasattr(schema, "polity_examples"), (
        "expected the loaded Schema to expose a 'polity_examples' attribute "
        "(PRD Appendix C/G: the placeholder 'country_list' is renamed to "
        "'polity_examples' -- illustrative examples, not a closed menu), "
        "but the schema loader does not yet expose it -- see "
        "plans/tag/05-polity-capture.md item 2"
    )
    assert OFFENDING_POLITY not in schema.polity_examples, (
        f"test setup invariant broken: {OFFENDING_POLITY!r} must NOT already "
        f"be a member of the schema's polity_examples {schema.polity_examples!r}, "
        f"or this test would not actually be exercising the examples-not-menu "
        f"acceptance path"
    )


def test_tag_polity_renamed_examples_not_menu_and_polities_touched(isolated_vault_root):
    """Slice 05 happy path (issue #194). Given a tag-pass response carrying
    empirical_scope=scope:country-case with polity=<a non-example, historical
    polity> and polities_touched=[<two engaged polities>], `axial tag
    <fixture>` must: exit 0; carry a free-text `polity` on every
    scope:country-case record and NEVER a `country` key on any record;
    accept and log the out-of-examples polity as a candidate (never fatal,
    #77); and carry the many-valued `polities_touched` list verbatim on
    every record."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    _assert_offending_polity_is_out_of_examples(schema)

    payload = _baseline_country_case_payload(schema)
    payload["polity"] = OFFENDING_POLITY
    payload["polities_touched"] = POLITIES_TOUCHED

    result = _run_tag(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "tag")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial tag` when the tag-pass response "
        f"declares polity={OFFENDING_POLITY!r} -- outside the schema's "
        f"polity_examples but the intended, faithfully-named referent "
        f"(Appendix C: 'the tagger is instructed to name the true polity "
        f"faithfully even when it is absent from the examples, historical, "
        f"defunct, or supra-national') -- got exit code {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    records = _parse_tag_records(result.stdout)
    assert records, (
        f"expected at least one tagged record on stdout, got none; stdout: {result.stdout!r}"
    )

    country_case_seen = False
    for record in records:
        assert isinstance(record, dict), (
            f"expected each tagged record to be a JSON object, got "
            f"{type(record).__name__}: {record!r}"
        )

        # -- never a 'country' key, on ANY record (seam decision 3) --
        assert "country" not in record, (
            f"expected a tagged record to never carry a legacy 'country' "
            f"key (Appendix C/G: the field is renamed 'polity', not "
            f"'country' -- 'a country field is a category error for an "
            f"empire, a mandate, or a supra-national referent'), got "
            f"'country'={record.get('country')!r} in record {record!r}"
        )

        # -- polities_touched: many-valued free text, no vocabulary check
        # (seam decision 5), present on every record --
        polities_touched = record.get("polities_touched")
        assert polities_touched == POLITIES_TOUCHED, (
            f"expected tagged record's 'polities_touched' to equal the "
            f"injected many-valued free-text list {POLITIES_TOUCHED!r} "
            f"verbatim (Appendix C 'Polities-touched facet': 'a separate, "
            f"many-valued free-text list of every polity the chunk "
            f"substantively engages'; Appendix G: 'cardinality: many, "
            f"values: free_text' -- no closed-vocabulary check), got "
            f"{polities_touched!r} (full record: {record!r})"
        )

        if record.get("empirical_scope") == COUNTRY_CASE_SCOPE_VALUE:
            country_case_seen = True
            polity = record.get("polity")
            assert isinstance(polity, str) and polity.strip(), (
                f"expected a scope:country-case tagged record to carry a "
                f"non-empty string 'polity' (Appendix C/G, Gherkin: 'each "
                f"scope:country-case record carries a free-text polity'), "
                f"got {polity!r} (full record: {record!r})"
            )
            assert polity == OFFENDING_POLITY, (
                f"expected the scope:country-case record's 'polity' to "
                f"equal the injected out-of-examples value "
                f"{OFFENDING_POLITY!r} verbatim (never rejected or "
                f"substituted -- Appendix C: 'accepted and logged as "
                f"candidate additions, never fatal'), got {polity!r} (full "
                f"record: {record!r})"
            )

    assert country_case_seen, (
        f"expected at least one tagged record with empirical_scope == "
        f"{COUNTRY_CASE_SCOPE_VALUE!r} given this test's fixture payload, "
        f"got none among: {records!r}"
    )

    # -- the out-of-examples polity must still be surfaced as a non-fatal
    # diagnostic on stderr, naming both the offending value and the
    # renamed 'polity_examples' list it fell outside of (Appendix C: "such
    # values are accepted and logged as candidate additions") --
    assert OFFENDING_POLITY in result.stderr, (
        f"expected `axial tag`'s stderr to name the out-of-examples polity "
        f"value {OFFENDING_POLITY!r} as a candidate addition (Appendix C: "
        f"'accepted and logged as candidate additions, never fatal in "
        f"v0'), got stderr: {result.stderr!r}"
    )
    assert "polity_examples" in result.stderr, (
        f"expected `axial tag`'s stderr diagnostic for the out-of-examples "
        f"polity to name the schema's renamed 'polity_examples' list "
        f"(Appendix G renames 'country_list' -> 'polity_examples'), not the "
        f"legacy 'country_list' name, got stderr: {result.stderr!r}"
    )


def test_tag_country_case_missing_polity_still_errors(isolated_vault_root):
    """Slice 05 error path (issue #194), unchanged hard error. A
    scope:country-case tag response with no 'polity' value at all must still
    exit non-zero with a clear error -- the rename from 'country' to
    'polity' must not weaken the missing-value hard error (Appendix C:
    'a missing or empty value stays the hard error it is today')."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    payload = _baseline_country_case_payload(schema)
    # Deliberately no 'polity' key at all, and never the legacy 'country'
    # key either -- proving the hard error fires on the RENAMED field, not
    # merely on the absence of the old one.
    payload["polities_touched"] = []

    result = _run_tag(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "tag")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial tag` when the tag-pass "
        f"response declares empirical_scope=scope:country-case with no "
        f"'polity' key at all (Gherkin: 'a scope:country-case record with a "
        f"missing/empty polity exits non-zero with a clear error -- "
        f"unchanged hard error'), got exit code 0\nstdout: "
        f"{result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert result.stderr.strip(), (
        f"expected `axial tag` to report a clear, non-empty error on "
        f"stderr for a missing-polity country-case record, got empty "
        f"stderr\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real polity-validation error path, not a generic "
            f"argparse fallback (found {marker!r}) masquerading as the "
            f"missing-polity error\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


def test_vault_write_round_trips_polity_and_polities_touched(isolated_vault_root):
    """Slice 05 vault round-trip (issue #194). `axial vault write` must
    persist both `empirical_scope.polity` (never `empirical_scope.country`)
    and the `polities_touched` list into the prose note frontmatter,
    matching Appendix H's illustrated shape (`empirical_scope: { value:
    scope:country-case, polity: Syria }`, `polities_touched: [Syria,
    Iraq]`)."""
    root = isolated_vault_root
    _arrange_stored_envelope(root)

    schema = load_schema(str(DOMAIN_DIR))
    _assert_offending_polity_is_out_of_examples(schema)

    payload = _baseline_country_case_payload(schema)
    payload["polity"] = OFFENDING_POLITY
    payload["polities_touched"] = POLITIES_TOUCHED

    result = _run_vault_write(
        "stub",
        str(THESIS_PAPER_PDF),
        cwd=root,
        extra_env={STUB_TAG_RESPONSE_ENV_VAR: json.dumps(payload)},
    )
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` when the tag-pass "
        f"response declares polity={OFFENDING_POLITY!r} and "
        f"polities_touched={POLITIES_TOUCHED!r}, got exit code "
        f"{result.returncode}\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    frontmatters = _all_prose_note_frontmatters(root)
    for frontmatter in frontmatters:
        empirical_scope = frontmatter.get("empirical_scope")
        assert isinstance(empirical_scope, dict), (
            f"expected every note's frontmatter 'empirical_scope' to be a "
            f"mapping (Appendix H: 'empirical_scope: { {'value': ..., 'polity': ...} }'), "
            f"got {type(empirical_scope).__name__}: {empirical_scope!r}"
        )
        assert empirical_scope.get("value") == COUNTRY_CASE_SCOPE_VALUE, (
            f"expected every note's frontmatter 'empirical_scope.value' to "
            f"equal {COUNTRY_CASE_SCOPE_VALUE!r}, got "
            f"{empirical_scope.get('value')!r} (full block: {empirical_scope!r})"
        )
        assert "country" not in empirical_scope, (
            f"expected the frontmatter's 'empirical_scope' block to never "
            f"carry a legacy 'country' key (Appendix H renames it to "
            f"'polity'), got {empirical_scope!r}"
        )
        assert empirical_scope.get("polity") == OFFENDING_POLITY, (
            f"expected every note's frontmatter 'empirical_scope.polity' to "
            f"equal the tagged out-of-examples value {OFFENDING_POLITY!r} "
            f"verbatim (Gherkin: 'axial vault write round-trips ... "
            f"empirical_scope.polity ... into the prose note frontmatter'), "
            f"got {empirical_scope.get('polity')!r} (full block: {empirical_scope!r})"
        )

        polities_touched = frontmatter.get("polities_touched")
        assert polities_touched == POLITIES_TOUCHED, (
            f"expected every note's frontmatter 'polities_touched' to equal "
            f"the tagged many-valued list {POLITIES_TOUCHED!r} verbatim "
            f"(Gherkin: 'axial vault write round-trips ... the "
            f"polities_touched list into the prose note frontmatter'; "
            f"Appendix H: 'polities_touched: [Syria, Iraq]'), got "
            f"{polities_touched!r}"
        )
