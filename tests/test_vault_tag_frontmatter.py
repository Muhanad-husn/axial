"""Outer acceptance test for issue #31, slice 04 (tag -> vault frontmatter).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given an extracted fixture source with a stored envelope and chunks,
      AXIAL_LLM_PROVIDER=stub
When  the user runs `axial vault write <fixture>`
Then  each prose note's frontmatter carries `schema_version` and a
      chunk-level axis block (claim_type, field, empirical_scope,
      theory_school, role_in_argument) matching Appendix H
And   the phase-2 source-level (`source_meta`) and section-level metadata
      are unchanged
And   re-running is idempotent (no duplicate or conflicting frontmatter)

See specs/PRODUCT.md §7.2 (three-level metadata: "Chunk-level: claim-type
tag(s), empirical-scope value (+ `country` where applicable), theory-school
tag(s) `[candidate]`, `role_in_argument`, and `artifact_refs`.") and
Appendix H (example prose-chunk frontmatter). Plan:
plans/tag/04-tag-vault-frontmatter.md.

Fixture reuse: exactly tests/test_vault_write.py's fixture
(tests/fixtures/envelope/thesis_paper.pdf + its committed real tree fixture
tests/fixtures/envelope/thesis_paper_tree.json) -- this slice only extends
what `axial vault write` writes into frontmatter for the SAME source, so no
new fixture is needed.

Seam decision 1 -- deriving expected axis values from the tagger itself,
never hardcoding stub wording
-----------------------------------------------------------------------
Exactly like tests/test_vault_write.py's seam decision 2 (which independently
runs `axial chunk` to get the expected chunk set), this test independently
runs `axial tag <fixture>` (stub, same fixture, same default domain
`config/domains/syria` that `axial vault write` uses internally per the slice
plan) to obtain the real tagged records the pipeline produces, and treats
those as the expected axis values `vault write`'s frontmatter must carry.
This test never hardcodes a tag id, a schema version string, or a country
name -- if the domain schema or the stub's canned tag response ever changes,
this test's expectations move with it, because both `axial tag` and `axial
vault write` read the same schema/stub at test time.

Seam decision 2 -- the empirical_scope reshaping
-----------------------------------------------------------------------
`axial tag`'s own record shape (src/axial/tag.py's `build_tagged_record`)
emits `empirical_scope` as a FLAT scalar string plus a SEPARATE top-level
`country` field. Appendix H nests both under one `empirical_scope` mapping:
`empirical_scope: { value: scope:country-case, country: Syria }`. This is
the one genuine reshaping the vault-write pass must perform (per the slice's
brief: "the tagger emits `empirical_scope` as a FLAT string plus a SEPARATE
top-level `country`, but Appendix H nests them"). This test locks the
Appendix-H nested shape: `frontmatter["empirical_scope"]` is a mapping
carrying `value` (equal to the tagged record's own `empirical_scope` string)
and, when the tagged record itself carries a non-null `country` (as the
stub's canned tag response always does for this fixture), a `country` key
equal to that same value.

Seam decision 3 -- claim_type and field: lock the tagger's own nested shape
verbatim, which already matches Appendix H's illustrated keys
-----------------------------------------------------------------------
`field`'s tagged-record shape (`{"primary": ..., "secondary": [...]}`) and
`claim_type`'s (`{"primary": ..., "secondary": ..., "subtags": [...]}`, when
the axis declares subtags) already match Appendix H's illustrated nesting
keys exactly (`field: { primary, secondary }`, `claim_type: { primary,
secondary, subtags }`). So this test locks full-dict equality between each
note's `field`/`claim_type` frontmatter block and the corresponding tagged
record's own `field`/`claim_type` value -- proving the vault-write pass
carries the tagger's nested axis object through faithfully, without
reinventing its shape.

Seam decision 4 -- theory_school: lock only the keys Appendix H names,
deliberately NOT over-constraining `secondary`
-----------------------------------------------------------------------
Appendix H's illustrated theory_school block is `{ primary, status:
candidate }` -- no `secondary` key. But `axial tag`'s own multi-value parser
(`parse_multi_value_tag_response` in src/axial/tag.py) always includes a
`secondary` key in its parsed dict for a `primary_plus_optional_secondary`
axis (defaulting to `None` when the model's response omits it), so the
tagged record's own `theory_school` value structurally carries a `secondary`
key Appendix H's illustrative example doesn't show. Per the task brief
("let common sense govern: lock the nesting keys the AC names and the
values that must come through, and document any field you deliberately do
NOT over-constrain"), this test locks exactly the two keys Appendix H names
-- `theory_school.primary` and `theory_school.status`, each checked against
the tagged record's own values -- and does NOT assert anything about
whether/how a `secondary` key appears on the frontmatter's `theory_school`
block. This keeps the contract anchored to Appendix H's illustrated shape
without accidentally locking an implementation detail of the tagger's
parser that Appendix H never claimed to fix.

Seam decision 5 -- role_in_argument: a flat top-level scalar, not nested
-----------------------------------------------------------------------
Appendix H shows `role_in_argument: role:claim` as a bare top-level scalar
(unlike the other four axes, which are nested mappings) -- this matches
`axial tag`'s own record shape exactly (`role_in_argument` is a plain
string on the tagged record, per `build_tagged_record`). This test locks
`frontmatter["role_in_argument"]` as a flat string equal to the tagged
record's own `role_in_argument` value -- no nesting.

Seam decision 6 -- phase-2 fields (source_meta / section / chunk_id /
chunk_text) unchanged: reusing tests/test_vault_write.py's own assertions
-----------------------------------------------------------------------
This test carries forward the exact assertions tests/test_vault_write.py
locks for the non-axis frontmatter fields (`chunk_id`, `section`,
`chunk_text`, and `source_meta`'s five reused-from-the-envelope fields --
`author`, `title`, `date`, `thesis`, `scope` -- each read from the stored
envelope on disk, never hardcoded), so this test doubles as a regression
guard on that slice's contract while this slice's own pass composes the
tagger internally instead of the chunker directly. Provenance
(chunk_id/section/chunk_text) is read off the independently-run tagged
records rather than a separate `axial chunk` run, because `axial tag`'s own
record shape already carries those three fields verbatim from its internal
chunking call (`build_tagged_record`), and tests/test_chunk.py already locks
chunk_id/section/text as deterministic and stable across repeat stub runs
over the same fixture+envelope -- so an independently-run `axial tag` and
the tagging `axial vault write` performs internally must agree, exactly as
tests/test_vault_write.py's seam decision 2 argues for the chunker.

Seam decision 7 -- idempotency: compare parsed frontmatter, not file bytes
-----------------------------------------------------------------------
This test re-runs `axial vault write` a second time over the same source
and asserts (a) the note count per chunk stays exactly one (no duplicate
files), and (b) each note's PARSED frontmatter mapping is unchanged between
the two runs. Comparing parsed YAML rather than raw bytes tolerates
non-semantic serialization differences (key order, quoting style) while
still catching any conflicting or duplicated key/value the Gherkin's
idempotency clause rules out.

Test hygiene: mirrors tests/test_vault_write.py's `clean_envelopes` and
`clean_vault` fixtures (data/envelopes/ is additionally isolated repo-wide
by tests/conftest.py's autouse content-snapshot fixture); nothing else is
written to the repo.

Arrange-mechanism change (issue #45, tree-cache) -- no behavioral assertion
changed
-----------------------------------------------------------------------
Exactly as tests/test_vault_write.py and tests/test_tag.py already document:
the arrange step pre-places the committed REAL tree fixture
(tests/fixtures/envelope/thesis_paper_tree.json) at
data/trees/<source_id>.json before calling `axial envelope`, so `axial
extract` reuses it verbatim instead of re-running docling. This test's
purpose is vault-write's axis-frontmatter behavior, not extraction/tree
shape (tests/test_extract.py's contract).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
ENVELOPES_DIR = REPO_ROOT / "data" / "envelopes"
TREES_DIR = REPO_ROOT / "data" / "trees"
VAULT_DIR = REPO_ROOT / "data" / "vault"
PROSE_DIR = VAULT_DIR / "prose"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

KNOWN_SECTION_LABELS = {"Introduction", "Comparative Cases", "Conclusion"}

# Source-level fields §7.2 names as "reused from the envelope" (excluding
# `fields`, a schema-driven axis tag -- mirrors tests/test_vault_write.py.
SOURCE_META_FIELDS = ("author", "title", "date", "thesis", "scope")

# argparse's fallback error for an as-yet-nonexistent subcommand/flag. Any of
# these substrings in the combined output means the target subcommand's
# logic was never actually exercised. Mirrors tests/test_vault_write.py and
# tests/test_tag.py.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_axial(args: list[str], provider: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    return subprocess.run(
        ["uv", "run", "axial", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_envelope(provider: str, *args: str) -> subprocess.CompletedProcess:
    return _run_axial(["envelope", *args], provider)


def _run_tag(provider: str, *args: str) -> subprocess.CompletedProcess:
    return _run_axial(["tag", *args], provider)


def _run_vault_write(provider: str, *args: str) -> subprocess.CompletedProcess:
    return _run_axial(["vault", "write", *args], provider)


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess, command: str) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `{command}` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `{command}` "
            f"subcommand/flag does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _existing_envelope_files() -> set[Path]:
    if not ENVELOPES_DIR.exists():
        return set()
    return set(ENVELOPES_DIR.glob("*.json"))


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    data/trees/<source_id>.json so `axial.extract.extract` reuses it
    verbatim instead of running docling (see module docstring). Returns the
    tree path."""
    source_id = compute_source_id(source_pdf)
    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _arrange_stored_envelope() -> Path:
    """Pre-place the real tree fixture, then run `axial envelope` with the
    stub provider so a stored envelope exists on disk before vault write,
    and return its path. Asserts the arrange step itself succeeded and
    produced exactly one new envelope file. (Mirrors
    tests/test_vault_write.py's helper of the same name.)"""
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


def _parse_records(stdout: str, container_keys: tuple[str, ...]) -> list[dict]:
    """Parse output records from an axial subcommand's stdout, tolerating a
    bare JSON array, a JSON object with one of `container_keys` as a
    top-level array, or newline-delimited JSON (one record per line).
    Mirrors tests/test_tag.py's `_parse_records`."""
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


def _arrange_expected_tagged_records() -> list[dict]:
    """Independently run `axial tag` (stub, default domain) to obtain the
    real tagged records for the fixture -- the expected axis values `axial
    vault write`'s frontmatter must carry (see module docstring, seam
    decision 1). Requires a stored envelope to already exist. Asserts the
    arrange step itself succeeded and produced well-formed tagged records,
    so a later failure in this test is never mistaken for an arrange
    problem."""
    result = _run_tag("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(result, "tag")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial tag` on the "
        f"fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    records = _parse_tag_records(result.stdout)
    assert len(records) >= 1, (
        f"arrange step failed: expected at least one tagged record from "
        f"`axial tag`, got {len(records)}; stdout: {result.stdout!r}"
    )
    for record in records:
        assert isinstance(record.get("chunk_id"), str) and record["chunk_id"].strip(), (
            f"arrange step failed: expected every tagged record to carry a "
            f"non-empty 'chunk_id', got {record!r}"
        )
        assert record.get("section") in KNOWN_SECTION_LABELS, (
            f"arrange step failed: expected every tagged record to carry a "
            f"'section' field naming one of this fixture's verbatim section "
            f"headings {sorted(KNOWN_SECTION_LABELS)}, got {record!r}"
        )
        assert isinstance(record.get("chunk_text"), str) and record["chunk_text"].strip(), (
            f"arrange step failed: expected every tagged record to carry "
            f"non-empty 'chunk_text', got {record!r}"
        )
        assert isinstance(record.get("schema_version"), str) and record["schema_version"], (
            f"arrange step failed: expected every tagged record to carry a "
            f"non-empty 'schema_version', got {record!r}"
        )
        assert isinstance(record.get("role_in_argument"), str) and record["role_in_argument"], (
            f"arrange step failed: expected every tagged record to carry a "
            f"non-empty 'role_in_argument', got {record!r}"
        )
        assert "empirical_scope" in record, (
            f"arrange step failed: expected every tagged record to carry an "
            f"'empirical_scope' value, got {record!r}"
        )
        for axis_name in ("field", "claim_type", "theory_school"):
            axis_value = record.get(axis_name)
            assert isinstance(axis_value, dict) and "primary" in axis_value, (
                f"arrange step failed: expected every tagged record's "
                f"{axis_name!r} to be an object with a 'primary' key, got "
                f"{axis_value!r}; full record: {record!r}"
            )
    return records


def _vault_files() -> set[Path]:
    if not VAULT_DIR.exists():
        return set()
    return {p for p in VAULT_DIR.rglob("*") if p.is_file()}


def _vault_dirs() -> set[Path]:
    if not VAULT_DIR.exists():
        return set()
    return {p for p in VAULT_DIR.rglob("*") if p.is_dir()}


@pytest.fixture
def clean_envelopes():
    """Snapshot data/envelopes/*.json before the test and delete any file
    the test caused to appear. (Mirrors tests/test_vault_write.py's fixture
    of the same name; belt-and-suspenders alongside tests/conftest.py's
    autouse isolation fixture.)"""
    before = _existing_envelope_files()
    yield
    after = _existing_envelope_files()
    for created in after - before:
        created.unlink()


@pytest.fixture
def clean_vault():
    """Snapshot data/vault/ (files and directories) before the test and
    remove anything the test caused to newly appear, so runs stay idempotent
    and the repo is never polluted by a real e2e-run artifact. (Mirrors
    tests/test_vault_write.py's fixture of the same name.)"""
    vault_existed_before = VAULT_DIR.exists()
    before_files = _vault_files()
    before_dirs = _vault_dirs()
    yield
    after_files = _vault_files()
    for created in after_files - before_files:
        created.unlink()

    after_dirs = _vault_dirs()
    new_dirs = after_dirs - before_dirs
    for created_dir in sorted(new_dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            created_dir.rmdir()
        except OSError:
            pass  # not empty -- holds content that predates this test's run

    if not vault_existed_before and VAULT_DIR.exists():
        try:
            VAULT_DIR.rmdir()
        except OSError:
            pass


def _split_frontmatter(text: str, note_path: Path) -> tuple[dict, str]:
    """Split a note's text into its parsed YAML frontmatter mapping and its
    body string, per the standard `---`-delimited convention (mirrors
    tests/test_vault_write.py's helper of the same name)."""
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


def _find_note_for_chunk(chunk_id: str) -> Path:
    assert PROSE_DIR.exists(), (
        f"expected {PROSE_DIR} to exist after `axial vault write` ran, but it does not"
    )
    matches = [p for p in PROSE_DIR.iterdir() if p.is_file() and p.stem == chunk_id]
    assert len(matches) == 1, (
        f"expected exactly one note file under {PROSE_DIR} whose filename "
        f"stem equals chunk_id {chunk_id!r}, got {len(matches)}: {sorted(matches)}"
    )
    return matches[0]


def _assert_phase2_fields_unchanged(
    frontmatter: dict, note_path: Path, expected: dict, envelope: dict, envelope_path: Path
) -> None:
    """The phase-2 (chunk_id/section/chunk_text/source_meta) assertions this
    test carries forward verbatim from tests/test_vault_write.py, so this
    test also regression-guards that slice's own contract (module docstring,
    seam decision 6)."""
    assert frontmatter.get("chunk_id") == expected["chunk_id"], (
        f"expected {note_path}'s frontmatter 'chunk_id' to equal "
        f"{expected['chunk_id']!r} (the chunk it was written for), got "
        f"{frontmatter.get('chunk_id')!r}"
    )
    assert frontmatter.get("section") == expected["section"], (
        f"expected {note_path}'s frontmatter 'section' to equal this "
        f"chunk's own verbatim section label {expected['section']!r} "
        f"(PRD §7.2 'section-level: kept verbatim'), got "
        f"{frontmatter.get('section')!r}"
    )
    assert frontmatter.get("chunk_text") == expected["chunk_text"], (
        f"expected {note_path}'s frontmatter 'chunk_text' to equal this "
        f"chunk's own text, got {frontmatter.get('chunk_text')!r} vs. "
        f"expected {expected['chunk_text']!r}"
    )

    source_meta = frontmatter.get("source_meta")
    assert isinstance(source_meta, dict), (
        f"expected {note_path}'s frontmatter to carry a 'source_meta' "
        f"mapping with the source-level fields reused from the envelope "
        f"(PRD §7.2 'source-level:... Reused from the envelope'; Appendix H "
        f"nests these under 'source_meta'), got {source_meta!r}"
    )
    for field in SOURCE_META_FIELDS:
        assert field in source_meta, (
            f"expected {note_path}'s frontmatter 'source_meta' to carry a "
            f"{field!r} key (PRD §7.2 source-level fields), got keys: "
            f"{sorted(source_meta.keys())}"
        )
        assert source_meta[field] == envelope.get(field), (
            f"expected {note_path}'s frontmatter 'source_meta.{field}' to "
            f"equal the stored envelope's own {field!r} value (read from "
            f"{envelope_path} on disk, never hardcoded), got "
            f"{source_meta[field]!r} vs. envelope's {envelope.get(field)!r}"
        )


def _assert_axis_block_matches_appendix_h(
    frontmatter: dict, note_path: Path, expected: dict
) -> None:
    """The chunk-level axis-block assertions this test's acceptance
    criterion is actually about: `schema_version` plus the five-axis block
    in Appendix H's nesting, every value sourced from the independently-run
    `axial tag` record (module docstring, seam decisions 1-5)."""
    assert frontmatter.get("schema_version") == expected["schema_version"], (
        f"expected {note_path}'s frontmatter 'schema_version' to equal the "
        f"tagged record's own schema_version {expected['schema_version']!r} "
        f"(PRD §7.1: 'every note written records the schema version it was "
        f"tagged under'), got {frontmatter.get('schema_version')!r}"
    )

    # role_in_argument: flat top-level scalar (seam decision 5), not nested.
    assert frontmatter.get("role_in_argument") == expected["role_in_argument"], (
        f"expected {note_path}'s frontmatter 'role_in_argument' to equal "
        f"the tagged record's own role_in_argument value "
        f"{expected['role_in_argument']!r} as a flat top-level scalar "
        f"(Appendix H: 'role_in_argument: role:claim'), got "
        f"{frontmatter.get('role_in_argument')!r}"
    )

    # field: nested {primary, secondary}, full-dict equality with the
    # tagger's own value (seam decision 3).
    assert frontmatter.get("field") == expected["field"], (
        f"expected {note_path}'s frontmatter 'field' block to equal the "
        f"tagged record's own field value {expected['field']!r} verbatim "
        f"(Appendix H: 'field: {{ primary, secondary }}'), got "
        f"{frontmatter.get('field')!r}"
    )

    # claim_type: nested {primary, secondary, subtags}, full-dict equality
    # with the tagger's own value (seam decision 3).
    assert frontmatter.get("claim_type") == expected["claim_type"], (
        f"expected {note_path}'s frontmatter 'claim_type' block to equal "
        f"the tagged record's own claim_type value {expected['claim_type']!r} "
        f"verbatim (Appendix H: 'claim_type: {{ primary, secondary, "
        f"subtags }}'), got {frontmatter.get('claim_type')!r}"
    )

    # theory_school: lock only the keys Appendix H names (primary, status);
    # deliberately do NOT constrain 'secondary' (seam decision 4).
    theory_school = frontmatter.get("theory_school")
    assert isinstance(theory_school, dict), (
        f"expected {note_path}'s frontmatter 'theory_school' to be a "
        f"mapping (Appendix H: 'theory_school: {{ primary, status }}'), got "
        f"{theory_school!r}"
    )
    expected_theory_school = expected["theory_school"]
    assert theory_school.get("primary") == expected_theory_school.get("primary"), (
        f"expected {note_path}'s frontmatter 'theory_school.primary' to "
        f"equal the tagged record's own theory_school primary "
        f"{expected_theory_school.get('primary')!r}, got "
        f"{theory_school.get('primary')!r}"
    )
    assert theory_school.get("status") == expected_theory_school.get("status"), (
        f"expected {note_path}'s frontmatter 'theory_school.status' to "
        f"equal the tagged record's own theory_school status "
        f"{expected_theory_school.get('status')!r} (Appendix E: '[candidate]'), "
        f"got {theory_school.get('status')!r}"
    )

    # empirical_scope: the one genuine reshape -- nested {value, country}
    # (seam decision 2), values sourced from the tagger's own flat
    # empirical_scope + separate top-level country.
    empirical_scope = frontmatter.get("empirical_scope")
    assert isinstance(empirical_scope, dict), (
        f"expected {note_path}'s frontmatter 'empirical_scope' to be a "
        f"mapping nesting 'value' (+ 'country' where applicable) (Appendix "
        f"H: 'empirical_scope: {{ value: scope:country-case, country: "
        f"Syria }}'), got {empirical_scope!r}"
    )
    assert empirical_scope.get("value") == expected.get("empirical_scope"), (
        f"expected {note_path}'s frontmatter 'empirical_scope.value' to "
        f"equal the tagged record's own flat empirical_scope value "
        f"{expected.get('empirical_scope')!r}, got {empirical_scope.get('value')!r}"
    )
    expected_country = expected.get("country")
    if expected_country is not None:
        assert empirical_scope.get("country") == expected_country, (
            f"expected {note_path}'s frontmatter 'empirical_scope.country' "
            f"to equal the tagged record's own top-level country value "
            f"{expected_country!r} (Appendix C/G: scope:country-case carries "
            f"an additional country field), got "
            f"{empirical_scope.get('country')!r}"
        )


def test_vault_write_persists_axis_frontmatter_matching_appendix_h(clean_envelopes, clean_vault):
    envelope_path = _arrange_stored_envelope()
    envelope = json.loads(envelope_path.read_bytes())

    expected_records = _arrange_expected_tagged_records()

    result = _run_vault_write("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` on a fixture source "
        f"with a stored envelope and the stub LLM provider configured, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    assert PROSE_DIR.exists(), (
        f"expected `axial vault write` to create {PROSE_DIR} and write "
        f"prose notes into it, but it does not exist after a successful run"
    )

    prose_files = [p for p in PROSE_DIR.iterdir() if p.is_file()]
    assert len(prose_files) == len(expected_records), (
        f"expected exactly one prose note per tagged chunk under "
        f"{PROSE_DIR}, got {len(prose_files)} file(s) for "
        f"{len(expected_records)} tagged record(s). Files: "
        f"{sorted(p.name for p in prose_files)}; expected chunk_ids: "
        f"{sorted(r['chunk_id'] for r in expected_records)}"
    )

    for expected in expected_records:
        chunk_id = expected["chunk_id"]
        note_path = _find_note_for_chunk(chunk_id)
        frontmatter, body = _split_frontmatter(note_path.read_text(encoding="utf-8"), note_path)

        assert expected["chunk_text"] in body, (
            f"expected {note_path}'s body (below the frontmatter block) to "
            f"contain the chunk's own text, making it a readable Obsidian "
            f"note; body (truncated): {body[:1000]!r}"
        )

        _assert_phase2_fields_unchanged(frontmatter, note_path, expected, envelope, envelope_path)
        _assert_axis_block_matches_appendix_h(frontmatter, note_path, expected)

    # the envelope itself must be untouched by vault write (PRD §10 "no
    # recompute") -- mirrors tests/test_vault_write.py's own assertion.
    envelope_bytes_after = envelope_path.read_bytes()
    assert json.loads(envelope_bytes_after) == envelope, (
        f"expected {envelope_path} to be unchanged after `axial vault write` "
        f"ran (the envelope must be read, not recomputed/rewritten -- PRD "
        f"§10 'no recompute')"
    )


def test_vault_write_axis_frontmatter_is_idempotent(clean_envelopes, clean_vault):
    _arrange_stored_envelope()
    expected_records = _arrange_expected_tagged_records()
    chunk_ids = [record["chunk_id"] for record in expected_records]

    first_result = _run_vault_write("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(first_result, "vault write")
    assert first_result.returncode == 0, (
        f"expected exit code 0 for the first `axial vault write` run, got "
        f"{first_result.returncode}\nstdout: {first_result.stdout!r}\n"
        f"stderr: {first_result.stderr!r}"
    )

    first_frontmatters = {}
    for chunk_id in chunk_ids:
        note_path = _find_note_for_chunk(chunk_id)
        frontmatter, _ = _split_frontmatter(note_path.read_text(encoding="utf-8"), note_path)
        first_frontmatters[chunk_id] = frontmatter

    second_result = _run_vault_write("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(second_result, "vault write")
    assert second_result.returncode == 0, (
        f"expected exit code 0 for the second (re-run) `axial vault write` "
        f"run, got {second_result.returncode}\nstdout: {second_result.stdout!r}\n"
        f"stderr: {second_result.stderr!r}"
    )

    prose_files_after_rerun = [p for p in PROSE_DIR.iterdir() if p.is_file()]
    assert len(prose_files_after_rerun) == len(expected_records), (
        f"expected re-running `axial vault write` to leave exactly one note "
        f"per chunk under {PROSE_DIR} (Gherkin: 'no duplicate ... "
        f"frontmatter'), got {len(prose_files_after_rerun)} file(s) for "
        f"{len(expected_records)} chunk(s) after the second run. Files: "
        f"{sorted(p.name for p in prose_files_after_rerun)}"
    )

    for chunk_id in chunk_ids:
        note_path = _find_note_for_chunk(chunk_id)
        second_frontmatter, _ = _split_frontmatter(note_path.read_text(encoding="utf-8"), note_path)
        assert second_frontmatter == first_frontmatters[chunk_id], (
            f"expected {note_path}'s parsed frontmatter to be unchanged "
            f"across a re-run of `axial vault write` (Gherkin: "
            f"'re-running is idempotent (no duplicate or conflicting "
            f"frontmatter)'), got a different mapping the second time.\n"
            f"first run:  {first_frontmatters[chunk_id]!r}\n"
            f"second run: {second_frontmatter!r}"
        )
