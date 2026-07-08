"""Outer acceptance test for issue #18, slice 06 (vault write).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given an extracted fixture source with a stored envelope and its chunk
      records, stub LLM provider
When  the user runs `axial vault write <fixture>`
Then  it exits 0 and writes one prose note per chunk under
      data/vault/prose/
And   each note has valid YAML frontmatter carrying source-level metadata,
      the section label, chunk_id, and chunk_text
And   the prose pool is a separate surface from data/vault/artifacts/
      (which stays empty this phase)

See specs/PRODUCT.md §5 stage 7 ("Cross-reference pass... Then write
everything to the Obsidian vault. Output: vault notes (prose pool +
artifact pool) with backlinks." -- this slice covers only the prose half,
without backlinks, per plans/minimal-ingestion/06-vault-write.md's scope),
§7.2 ("Every prose note carries three metadata levels... Source-level:
author, title, date, fields..., author's stated thesis, scope. Reused from
the envelope. Section-level: the author's own section/chapter labels, kept
verbatim... Chunk-level: claim-type tag(s)... [deferred to phase-3 tagging,
per the slice plan's out-of-scope list -- this slice locks only the
non-axis chunk-level fields, chunk_id/chunk_text/section provenance]"),
§8 P0-8 ("Prose pool and artifact pool are separate, independently
queryable surfaces sharing metadata conventions." / "Notes carry valid
three-level frontmatter and backlinks." -- backlinks are P0-7, out of
scope for this slice per the plan), and Appendix H (example prose-chunk
frontmatter shape: a `source_meta` mapping nesting author/date/thesis
alongside a top-level `chunk_id` and `section`) for the source of truth.

Fixture reuse: tests/fixtures/envelope/thesis_paper.pdf (see
tests/test_envelope.py, tests/test_chunk.py, and its _generate.py) has
three top-level sections -- Introduction, Comparative Cases, Conclusion.
No new fixture is needed: this slice only needs a source that already has
a stored envelope and produces at least one chunk per section, which this
fixture already exercises end-to-end in tests/test_chunk.py.

Seam decision 1 -- command shape
-----------------------------------------------------------------------
The issue and plan both name `axial vault write <file>`, a two-word
subcommand taking a source file path exactly like `axial chunk <file>` and
`axial envelope <file>` (not a chunk-records path -- there is no persisted
chunk store yet; src/axial/chunk.py's own module docstring says "this
slice emits chunk records to stdout only; vault persistence is slice 06",
i.e. this slice's `vault write` is expected to invoke the chunking pass
itself, internally, exactly as `axial chunk` does, given the same
`AXIAL_LLM_PROVIDER` selection). This test locks that `vault write` is a
nested subcommand under a `vault` top-level command, mirroring the
`schema show`/`schema validate` nesting pattern already established in
src/axial/cli.py -- run as `uv run axial vault write <path>`.

Seam decision 2 -- deriving the expected chunk set independently, not
hardcoding it
-----------------------------------------------------------------------
This test never hardcodes chunk_id values, section labels, chunk counts,
or chunk text. Instead it ALSO runs `axial chunk <fixture>` (stub
provider, same fixture) to obtain the real chunk records the pipeline
produces, and treats that as the expected set for `vault write`'s output.
This is safe because tests/test_chunk.py already locks (and this test
relies on) chunk_id/section/text being deterministic and stable across
repeat stub runs over the same fixture+envelope -- so an independent
`axial chunk` invocation and the chunking `axial vault write` performs
internally must agree, as long as both consume the same stored envelope
with the same stub provider. This keeps the acceptance test about
behavior (does one note exist per real chunk, with the real chunk's own
data faithfully carried), not about implementation-internal record shapes.

Seam decision 3 -- frontmatter key names locked by this test
-----------------------------------------------------------------------
Neither the PRD nor the slice plan names exact frontmatter keys beyond
"source-level metadata, the section label, chunk_id, and chunk_text"
(the Gherkin) and the illustrative (not literal-contract) Appendix H
example, so this test locks the minimum needed to make the acceptance
criterion executable, choosing the smallest, least implementation-committal
names consistent with both:

  - top-level `chunk_id` (string): the chunk-level id, mirroring
    `axial chunk`'s own field name (tests/test_chunk.py already locks
    `chunk_id` as the emitted field name for this exact concept -- reusing
    it here avoids inventing a second name for the same thing).
  - top-level `section` (string): the section-level verbatim label,
    mirroring `axial chunk`'s own `section` field name for the same
    reason.
  - top-level `chunk_text` (string): the chunk-level prose text, named
    `chunk_text` per the Gherkin's own wording ("chunk_id, and
    chunk_text") and Appendix I's label-sheet column of the same name --
    this is the one field name the acceptance criterion states literally,
    so it is locked verbatim.
  - top-level `source_meta` (a nested YAML mapping): the source-level
    metadata block reused from the envelope, per §7.2 ("Reused from the
    envelope") and Appendix H (which nests source-level fields under a
    `source_meta` key). This test locks that `source_meta` carries the
    keys `author`, `title`, `date`, `thesis`, and `scope` -- the four
    source-level fields §7.2 names (author, title, date, thesis, scope)
    that also exist verbatim on the stored envelope (§7.3); §7.2's
    `fields` (primary+secondary) is a schema-driven axis tag, deferred to
    phase-3 tagging per the slice plan's out-of-scope list, and is
    deliberately NOT asserted here.

  This test does NOT lock: exact frontmatter key ordering, exact YAML
  serialization style (block vs. flow, quoting), a `source` display-string
  key (Appendix H's illustrative `source: "Hinnebusch -- ..."` line), or
  any axis-tag field (`claim_type`, `field`, `empirical_scope`,
  `theory_school`, `role_in_argument`, `artifact_refs`, `schema_version`)
  -- all out of scope for this slice per the plan's "Out of scope" list.

Seam decision 4 -- frontmatter block delimiters and note naming
-----------------------------------------------------------------------
This test locks the standard Obsidian/Jekyll frontmatter convention: a
note file opens with a line that is exactly `---`, followed by a YAML
mapping, followed by a line that is exactly `---`, followed by the note
body. This is parsed with PyYAML (already a project dependency, used by
src/axial/envelope.py) rather than any bespoke format.

Note filenames are locked only to the extent the plan itself commits to:
"one file is written per chunk under data/vault/prose/, named by
chunk_id" (plan inner-loop list). This test asserts each note's filename
STEM (the name without extension) equals the chunk's `chunk_id` exactly
once under data/vault/prose/, without dictating the file extension
(`.md` is conventional for Obsidian but not asserted here, since no
source of truth pins it down).

Seam decision 5 -- source-level values read from disk, never hardcoded
-----------------------------------------------------------------------
Exactly as tests/test_chunk.py's seam decision 3(a) and
tests/test_envelope.py's seam decision 3, this test never hardcodes stub
wording. It reads the stored envelope's own `author`/`title`/`date`/
`thesis`/`scope` values back from the envelope JSON file on disk at test
time and asserts each note's `source_meta` block carries the SAME values
(including possibly-null `author`/`date`, since the current stub's canned
envelope response supplies neither -- see src/axial/llm.py's
`StubLLMClient._CANNED_RESPONSE`, which has no "author"/"date" keys, so
`axial envelope`'s own fallback logic in src/axial/envelope.py leaves
those two null). Asserting exact value equality against whatever the
envelope itself holds -- rather than asserting non-null or hardcoding
stub prose -- proves the metadata was faithfully carried through without
baking any particular stub response into the locked contract.

Seam decision 6 -- artifact-pool separation, minimally
-----------------------------------------------------------------------
The Gherkin's third clause ("the prose pool is a separate surface from
data/vault/artifacts/, which stays empty this phase") is checked two
ways: (a) no note file for any chunk is ever found under
data/vault/artifacts/ (only under data/vault/prose/), and (b)
data/vault/artifacts/ contains no files at all after the run -- it may or
may not exist as an empty directory (the plan explicitly permits "This
slice may create the empty artifact directory but writes nothing into
it"), so this test does not require its existence, only its emptiness.

Test hygiene: any envelope file this test creates under data/envelopes/
is removed in fixture teardown (mirrors tests/test_chunk.py's
clean_envelopes). Any file or directory this test causes to newly appear
under data/vault/ is likewise removed in teardown (clean_vault, below),
so runs stay idempotent and the repo is never polluted by a real e2e-run
artifact.

Arrange-mechanism change (issue #45, tree-cache) -- no behavioral assertion
changed
-----------------------------------------------------------------------
This test's PURPOSE is vault-write's own behavior -- it CONSUMES the stored
envelope and this fixture's chunk records, never asserting anything about
extraction/tree shape itself (that is tests/test_extract.py's contract). The
arrange step's `axial envelope` call internally calls `axial.extract.
extract`, which -- per the now-locked tree-persist contract
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
ARTIFACTS_DIR = VAULT_DIR / "artifacts"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

KNOWN_SECTION_LABELS = {"Introduction", "Comparative Cases", "Conclusion"}

# Source-level fields §7.2 names as "reused from the envelope" (excluding
# `fields`, a schema-driven axis tag deferred to phase-3 tagging).
SOURCE_META_FIELDS = ("author", "title", "date", "thesis", "scope")

# argparse's fallback error for an as-yet-nonexistent subcommand, e.g.
# "axial: error: argument command: invalid choice: 'vault' (choose from
# 'schema', 'intake', 'extract', 'envelope', 'chunk')". Any of these
# substrings in the combined output means the target subcommand's logic
# was never actually exercised -- the process failed before real behavior
# ran. Reject that generic failure mode explicitly so this test can only
# pass once real `vault write` behavior exists.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_axial(
    args: list[str],
    provider: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["uv", "run", "axial", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_envelope(provider: str, *args: str) -> subprocess.CompletedProcess:
    return _run_axial(["envelope", *args], provider)


def _run_chunk(provider: str, *args: str) -> subprocess.CompletedProcess:
    return _run_axial(["chunk", *args], provider)


def _run_vault_write(provider: str, *args: str) -> subprocess.CompletedProcess:
    return _run_axial(["vault", "write", *args], provider)


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
    stub provider so a stored envelope exists on disk before vault write,
    and return its path. Asserts the arrange step itself succeeded and
    produced exactly one new envelope file. (Mirrors tests/test_chunk.py's
    helper of the same name.)"""
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


def _parse_chunk_records(stdout: str) -> list[dict]:
    """Parse chunk records from `axial chunk`'s stdout, tolerating any of
    the shapes tests/test_chunk.py's own parsing helper accepts: a bare
    JSON array, a JSON object with a "chunks" array, or newline-delimited
    JSON (one record per line)."""
    stripped = stdout.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None

    if data is not None:
        if isinstance(data, dict):
            assert "chunks" in data, (
                f"expected a top-level 'chunks' key when chunk stdout is a "
                f"JSON object, got keys: {sorted(data.keys())}; stdout: {stdout!r}"
            )
            records = data["chunks"]
        else:
            records = data
        assert isinstance(records, list), (
            f"expected chunk records to be a JSON array (bare, or under a "
            f"'chunks' key), got {type(records).__name__}: {records!r}"
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
                f"expected chunk stdout to be either one parseable JSON "
                f"document (a bare array, or an object with a top-level "
                f"'chunks' array) or newline-delimited JSON (one chunk "
                f"record object per line); line {line!r} failed to parse "
                f"({exc}). Full stdout: {stdout!r}"
            ) from None
    assert records, (
        f"expected at least one parseable chunk record in stdout, got none. stdout: {stdout!r}"
    )
    return records


def _arrange_expected_chunk_records() -> list[dict]:
    """Independently run `axial chunk` (stub) to obtain the real chunk
    records for the fixture, used as the expected set `vault write` must
    match one-for-one (see module docstring, seam decision 2). Requires a
    stored envelope to already exist."""
    result = _run_chunk("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(result, "chunk")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial chunk` on "
        f"the fixture with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    records = _parse_chunk_records(result.stdout)
    assert len(records) >= 1, (
        f"arrange step failed: expected at least one chunk record from "
        f"`axial chunk`, got {len(records)}; stdout: {result.stdout!r}"
    )
    for record in records:
        assert isinstance(record.get("chunk_id"), str) and record["chunk_id"].strip(), (
            f"arrange step failed: expected every chunk record to carry a "
            f"non-empty 'chunk_id', got {record!r}"
        )
        assert record.get("section") in KNOWN_SECTION_LABELS, (
            f"arrange step failed: expected every chunk record to carry a "
            f"'section' field naming one of this fixture's verbatim section "
            f"headings {sorted(KNOWN_SECTION_LABELS)}, got {record!r}"
        )
        assert isinstance(record.get("text"), str) and record["text"].strip(), (
            f"arrange step failed: expected every chunk record to carry "
            f"non-empty 'text', got {record!r}"
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
    the test caused to appear, so runs stay idempotent and the repo is
    never polluted by a real e2e-run artifact. (Mirrors
    tests/test_chunk.py's fixture of the same name.)"""
    before = _existing_envelope_files()
    yield
    after = _existing_envelope_files()
    for created in after - before:
        created.unlink()


@pytest.fixture
def clean_vault():
    """Snapshot data/vault/ (files and directories) before the test and
    remove anything the test caused to newly appear -- files first, then
    now-empty directories deepest-first, then the data/vault/ root itself
    if the whole tree was newly created -- so runs stay idempotent and the
    repo is never polluted by a real e2e-run artifact."""
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
    body string, per the standard `---`-delimited convention this test
    locks (module docstring, seam decision 4)."""
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
        f"stem equals chunk_id {chunk_id!r} (plan inner-loop: 'one file is "
        f"written per chunk under data/vault/prose/, named by chunk_id'), "
        f"got {len(matches)}: {sorted(matches)}"
    )
    return matches[0]


def test_vault_write_creates_one_prose_note_per_chunk_with_three_level_frontmatter(
    clean_envelopes, clean_vault
):
    envelope_path = _arrange_stored_envelope()
    envelope = json.loads(envelope_path.read_bytes())

    expected_records = _arrange_expected_chunk_records()

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
        f"expected exactly one prose note per chunk under {PROSE_DIR} "
        f"(Gherkin: 'writes one prose note per chunk'), got "
        f"{len(prose_files)} file(s) for {len(expected_records)} chunk "
        f"record(s). Files: {sorted(p.name for p in prose_files)}; expected "
        f"chunk_ids: {sorted(r['chunk_id'] for r in expected_records)}"
    )

    for expected in expected_records:
        chunk_id = expected["chunk_id"]
        note_path = _find_note_for_chunk(chunk_id)
        frontmatter, body = _split_frontmatter(note_path.read_text(encoding="utf-8"), note_path)

        assert frontmatter.get("chunk_id") == chunk_id, (
            f"expected {note_path}'s frontmatter 'chunk_id' to equal "
            f"{chunk_id!r} (the chunk it was written for), got "
            f"{frontmatter.get('chunk_id')!r}"
        )

        assert frontmatter.get("section") == expected["section"], (
            f"expected {note_path}'s frontmatter 'section' to equal this "
            f"chunk's own verbatim section label {expected['section']!r} "
            f"(PRD §7.2 'section-level: kept verbatim'), got "
            f"{frontmatter.get('section')!r}"
        )

        assert frontmatter.get("chunk_text") == expected["text"], (
            f"expected {note_path}'s frontmatter 'chunk_text' to equal "
            f"this chunk's own text as produced by `axial chunk` on the "
            f"same fixture+envelope+stub provider (Gherkin: '...chunk_id, "
            f"and chunk_text'), got {frontmatter.get('chunk_text')!r} vs. "
            f"expected {expected['text']!r}"
        )

        assert expected["text"] in body, (
            f"expected {note_path}'s body (below the frontmatter block) to "
            f"contain the chunk's own text, making it a readable Obsidian "
            f"note (plan inner-loop: 'the note body contains the chunk "
            f"text below the frontmatter'); body (truncated): {body[:1000]!r}"
        )

        source_meta = frontmatter.get("source_meta")
        assert isinstance(source_meta, dict), (
            f"expected {note_path}'s frontmatter to carry a 'source_meta' "
            f"mapping with the source-level fields reused from the "
            f"envelope (PRD §7.2 'source-level:... Reused from the "
            f"envelope'; Appendix H nests these under 'source_meta'), got "
            f"{source_meta!r}"
        )
        for field in SOURCE_META_FIELDS:
            assert field in source_meta, (
                f"expected {note_path}'s frontmatter 'source_meta' to "
                f"carry a {field!r} key (PRD §7.2 source-level fields), "
                f"got keys: {sorted(source_meta.keys())}"
            )
            assert source_meta[field] == envelope.get(field), (
                f"expected {note_path}'s frontmatter 'source_meta.{field}' "
                f"to equal the stored envelope's own {field!r} value "
                f"(read from {envelope_path} on disk, never hardcoded -- "
                f"see module docstring, seam decision 5), got "
                f"{source_meta[field]!r} vs. envelope's {envelope.get(field)!r}"
            )

    # the envelope itself must be untouched by vault write, same "read not
    # recomputed" discipline as tests/test_chunk.py locks for the chunk pass.
    envelope_bytes_after = envelope_path.read_bytes()
    assert json.loads(envelope_bytes_after) == envelope, (
        f"expected {envelope_path} to be unchanged after `axial vault write` "
        f"ran (the envelope must be read, not recomputed/rewritten -- PRD "
        f"§10 'no recompute')"
    )


def test_vault_write_prose_pool_is_separate_from_empty_artifact_pool(clean_envelopes, clean_vault):
    _arrange_stored_envelope()
    expected_records = _arrange_expected_chunk_records()
    expected_chunk_ids = {record["chunk_id"] for record in expected_records}

    result = _run_vault_write("stub", str(THESIS_PAPER_PDF))
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` on a fixture source "
        f"with a stored envelope and the stub LLM provider configured, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # every expected chunk's note must land under prose/, not artifacts/.
    for chunk_id in expected_chunk_ids:
        _find_note_for_chunk(chunk_id)

    if ARTIFACTS_DIR.exists():
        artifact_files = [p for p in ARTIFACTS_DIR.rglob("*") if p.is_file()]
        assert artifact_files == [], (
            f"expected {ARTIFACTS_DIR} to stay empty this phase (Gherkin: "
            f"'the prose pool is a separate surface from "
            f"data/vault/artifacts/, which stays empty this phase'; plan: "
            f"'This slice may create the empty artifact directory but "
            f"writes nothing into it'), got file(s): "
            f"{sorted(p.name for p in artifact_files)}"
        )

    for chunk_id in expected_chunk_ids:
        artifact_matches = (
            [p for p in ARTIFACTS_DIR.iterdir() if p.is_file() and p.stem == chunk_id]
            if ARTIFACTS_DIR.exists()
            else []
        )
        assert artifact_matches == [], (
            f"expected no prose note for chunk {chunk_id!r} to be written "
            f"under {ARTIFACTS_DIR} -- the prose pool "
            f"({PROSE_DIR}) and the artifact pool ({ARTIFACTS_DIR}) must "
            f"be separate surfaces (PRD §8 P0-8), got: {artifact_matches}"
        )
