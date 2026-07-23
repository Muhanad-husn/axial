"""Inner unit tests for the corpus-pin manifest module (issue #248, slice
02, specs/PHASE-B.md §7.12).

Co-located under src/axial/eval/ per the repo's existing test layout
(mirrors src/axial/brief/test_intake.py for the sibling brief package).
The outer acceptance test (tests/analysis/test_corpus_pin.py, locked,
DEC-1) drives `axial pin write` end to end through a subprocess and pins
the CLI-level contract; these unit tests exercise the pieces underneath it
directly -- the plan's own inner unit test list
(plans/analysis-foundation/02-corpus-pin-manifest.md), plus the stage-1
review findings on issue #248 (F1-F4): `content_hash` is a digest of the
raw ingested source file (not the envelope), malformed inputs raise a
named `CorpusPinError` instead of a bare traceback, and the snapshot-hash
sort order is directly asserted rather than incidentally matched by
filesystem enumeration order.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from axial.envelope import compute_source_id
from axial.eval.corpus_pin import (
    AmbiguousSourceFileError,
    GitShaUnavailableError,
    MalformedEnvelopeError,
    MalformedNoteError,
    MissingEnvelopesDirError,
    MissingSourceFileError,
    MissingVaultDirError,
    TAG_AXES,
    UnresolvableSourceIdError,
    _build_sources,
    _build_vault_snapshot_hash,
    _collect_snapshot_pairs,
    _default_sources_dir,
    _tag_projection,
    ingest_code_sha,
    write_pin,
)
from axial.vault import render_note


def _write_source_file(sources_dir: Path, stem: str, extension: str = ".pdf") -> Path:
    """A throwaway raw-source stand-in under `sources_dir` -- never real
    book text (repo copyright policy)."""
    sources_dir.mkdir(parents=True, exist_ok=True)
    path = sources_dir / f"{stem}{extension}"
    path.write_bytes(f"synthetic raw source bytes for {stem}".encode("utf-8"))
    return path


def _write_envelope_for_source(
    envelopes_dir: Path, sources_dir: Path, stem: str, extension: str = ".pdf"
) -> tuple[Path, str]:
    """Write a real raw source file under `sources_dir` and an envelope
    whose `source_id` is genuinely content-derived from it
    (`compute_source_id`, mirroring how a real envelope is produced) --
    returns (envelope_path, source_id)."""
    source_path = _write_source_file(sources_dir, stem, extension)
    source_id = compute_source_id(source_path)
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    envelope_path = envelopes_dir / f"{source_id}.json"
    envelope_path.write_text(json.dumps({"source_id": source_id, "thesis": "t"}), encoding="utf-8")
    return envelope_path, source_id


def _write_envelope_raw(envelopes_dir: Path, source_id: str, body: str | None = None) -> Path:
    """Write an envelope file directly under a given (possibly malformed or
    unresolvable) `source_id`/body, without also staging a raw source
    file -- for the error-path tests below."""
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    path = envelopes_dir / f"{source_id}.json"
    path.write_text(
        body if body is not None else json.dumps({"source_id": source_id, "thesis": "t"}),
        encoding="utf-8",
    )
    return path


def _write_note(
    prose_dir: Path, chunk_id: str, filename: str | None = None, **axis_overrides
) -> Path:
    """Write a prose note whose frontmatter `chunk_id` is `chunk_id`. The
    on-disk filename defaults to `f"{chunk_id}.md"` (most call sites), but a
    caller may pass an explicit `filename` to deliberately DECOUPLE the
    filesystem name from the `chunk_id` -- required by any test that means
    to distinguish filesystem enumeration ("glob") order from `chunk_id`
    sort order (see the F3 finding on issue #248: when filename == chunk_id,
    the two orders are textually identical and no test built on them can
    ever catch a missing/removed sort)."""
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "Introduction",
        "chunk_text": f"body text for {chunk_id}",
        "source_meta": {"author": "A", "title": "T"},
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "state", "secondary": []},
        **axis_overrides,
    }
    path = prose_dir / (filename or f"{chunk_id}.md")
    path.write_text(render_note(frontmatter, "# Introduction\n\nbody\n"), encoding="utf-8")
    return path


# --- Source list (plan inner test 1; F1: raw-source-file digest) -----------


def test_build_sources_one_entry_per_envelope_with_source_id_and_content_hash(tmp_path: Path):
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    _write_envelope_for_source(envelopes_dir, sources_dir, "book-a")
    _write_envelope_for_source(envelopes_dir, sources_dir, "book-b")

    sources = _build_sources(envelopes_dir, sources_dir)

    assert len(sources) == 2
    assert sources == sorted(sources, key=lambda entry: entry["source_id"])
    for entry in sources:
        assert isinstance(entry["content_hash"], str) and entry["content_hash"]


def test_build_sources_content_hash_is_a_digest_of_the_raw_source_not_the_envelope(
    tmp_path: Path,
):
    """F1 (founder-adjudicated, issue #248): `content_hash` must be a digest
    of the raw ingested source file -- regenerating the envelope (routine,
    #235/#241) must never move it. Reuses `axial.envelope.content_digest`,
    the same primitive `compute_source_id` hashes source bytes with, so it
    is never a second hashing convention."""
    from axial.envelope import content_digest

    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    envelope_path, source_id = _write_envelope_for_source(envelopes_dir, sources_dir, "book-a")
    source_path = sources_dir / "book-a.pdf"

    (entry,) = _build_sources(envelopes_dir, sources_dir)

    assert entry["content_hash"] == content_digest(source_path)
    assert entry["content_hash"] != content_digest(envelope_path)


def test_build_sources_content_hash_unmoved_by_regenerating_the_envelope(tmp_path: Path):
    """The core F1 regression: rewriting the envelope file (simulating an
    LLM regen with different prose but the SAME underlying source) must not
    change content_hash."""
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    envelope_path, source_id = _write_envelope_for_source(envelopes_dir, sources_dir, "book-a")

    (before,) = _build_sources(envelopes_dir, sources_dir)

    envelope_path.write_text(
        json.dumps({"source_id": source_id, "thesis": "a totally different regenerated thesis"}),
        encoding="utf-8",
    )
    (after,) = _build_sources(envelopes_dir, sources_dir)

    assert before["content_hash"] == after["content_hash"]


def test_build_sources_missing_envelopes_dir_raises_naming_the_path(tmp_path: Path):
    missing = tmp_path / "no-such-envelopes"
    with pytest.raises(MissingEnvelopesDirError) as excinfo:
        _build_sources(missing, tmp_path / "sources")
    assert str(missing) in str(excinfo.value)


def test_build_sources_missing_raw_source_file_fails_loudly_naming_source_id_and_dir(
    tmp_path: Path,
):
    """F1: a source_id with no matching raw file under sources_dir must
    raise -- never silently fall back to the envelope hash or the
    source_id digest, never skip the entry."""
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    source_id = "book-a-aaaaaaaaaaaa"
    _write_envelope_raw(envelopes_dir, source_id)

    with pytest.raises(MissingSourceFileError) as excinfo:
        _build_sources(envelopes_dir, sources_dir)

    assert source_id in str(excinfo.value)
    assert str(sources_dir) in str(excinfo.value)


def test_build_sources_ambiguous_raw_source_file_fails_loudly(tmp_path: Path):
    """F1: two raw files sharing the same stem (e.g. a .pdf AND a .docx)
    under sources_dir is an unresolvable ambiguity, never silently
    resolved by picking one."""
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    pdf_path = _write_source_file(sources_dir, "book-a", ".pdf")
    source_id = compute_source_id(pdf_path)
    _write_source_file(sources_dir, "book-a", ".docx")
    _write_envelope_raw(envelopes_dir, source_id)

    with pytest.raises(AmbiguousSourceFileError) as excinfo:
        _build_sources(envelopes_dir, sources_dir)

    assert source_id in str(excinfo.value)


def test_build_sources_unresolvable_source_id_shape_fails_loudly(tmp_path: Path):
    """A source_id that doesn't match compute_source_id's own
    '<stem>-<12 hex digits>' shape can't be resolved to a filename stem at
    all -- fails loudly rather than guessing."""
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    _write_envelope_raw(envelopes_dir, "not-a-real-source-id-shape")

    with pytest.raises(UnresolvableSourceIdError):
        _build_sources(envelopes_dir, sources_dir)


def test_build_sources_stem_with_embedded_hyphens_is_recovered_whole(tmp_path: Path):
    """A real source stem routinely contains hyphens (e.g.
    'tilly-from-mobilization-to-revolution') -- the stem-recovery regex
    must not truncate at the first/last hyphen."""
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    _write_envelope_for_source(envelopes_dir, sources_dir, "tilly-from-mobilization-to-revolution")

    (entry,) = _build_sources(envelopes_dir, sources_dir)
    assert entry["source_id"].startswith("tilly-from-mobilization-to-revolution-")


# --- F2: malformed inputs raise a named CorpusPinError, not a traceback ----


def test_build_sources_malformed_envelope_json_raises_naming_the_path(tmp_path: Path):
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    envelopes_dir.mkdir(parents=True)
    bad_path = envelopes_dir / "broken.json"
    bad_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(MalformedEnvelopeError) as excinfo:
        _build_sources(envelopes_dir, sources_dir)

    assert str(bad_path) in str(excinfo.value)


def test_build_sources_non_mapping_envelope_raises_naming_the_path(tmp_path: Path):
    """F2 re-review finding: valid JSON that isn't a mapping (e.g. a
    top-level list) must not escape as a bare `AttributeError` from
    `envelope.get(...)` -- mirrors `_split_frontmatter`'s identical
    non-mapping guard on the note path (`test_split_frontmatter_non_mapping_
    raises_malformed_note_naming_the_path` below)."""
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    envelopes_dir.mkdir(parents=True)
    bad_path = envelopes_dir / "not-a-mapping.json"
    bad_path.write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")

    with pytest.raises(MalformedEnvelopeError) as excinfo:
        _build_sources(envelopes_dir, sources_dir)

    assert str(bad_path) in str(excinfo.value)


def test_split_frontmatter_invalid_yaml_raises_malformed_note_naming_the_path(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True)
    note_path = prose_dir / "c1.md"
    # An unterminated flow mapping is invalid YAML.
    note_path.write_text("---\nchunk_id: c1\nfield: [unterminated\n---\nbody\n", encoding="utf-8")

    with pytest.raises(MalformedNoteError) as excinfo:
        _build_vault_snapshot_hash(vault_dir)

    assert str(note_path) in str(excinfo.value)


def test_split_frontmatter_non_mapping_raises_malformed_note_naming_the_path(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True)
    note_path = prose_dir / "c1.md"
    # A bare YAML list, not a mapping.
    note_path.write_text("---\n- one\n- two\n---\nbody\n", encoding="utf-8")

    with pytest.raises(MalformedNoteError) as excinfo:
        _build_vault_snapshot_hash(vault_dir)

    assert str(note_path) in str(excinfo.value)


# --- F4: the missing-closing-delimiter guard has its own coverage ---------


def test_split_frontmatter_missing_closing_delimiter_raises_malformed_note(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True)
    note_path = prose_dir / "c1.md"
    note_path.write_text("---\nchunk_id: c1\nno closing delimiter here\n", encoding="utf-8")

    with pytest.raises(MalformedNoteError) as excinfo:
        _build_vault_snapshot_hash(vault_dir)

    assert str(note_path) in str(excinfo.value)


# --- ingest_code_sha (plan inner test 2) ------------------------------------


def test_ingest_code_sha_reads_current_git_head(tmp_path: Path):
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert ingest_code_sha(repo_root) == expected


def test_ingest_code_sha_unreadable_repo_fails_loudly_not_a_placeholder(tmp_path: Path):
    """A directory that is not a git checkout at all must raise, never
    silently produce a null/placeholder SHA."""
    with pytest.raises(GitShaUnavailableError):
        ingest_code_sha(tmp_path)


# --- Vault snapshot hash (plan inner tests 3-6; F3: sort order asserted directly) --


def test_collect_snapshot_pairs_is_sorted_by_chunk_id_regardless_of_write_order(tmp_path: Path):
    """F3 (re-review, issue #248): assert the sort DIRECTLY on the canonical
    pair list, with the on-disk FILENAME deliberately decoupled from
    `chunk_id` (via `_write_note`'s `filename=` param) -- when filename ==
    chunk_id (the prior version of this test), `Path.glob`'s own
    alphabetical-by-filename order is textually identical to chunk_id sort
    order, so the test cannot distinguish "sorted" from "glob order,
    whatever that happens to be" and would still pass with the `sort` call
    at `_collect_snapshot_pairs` deleted entirely. Here, glob visits
    `01_note.md/02_note.md/03_note.md` in that filename order, whose
    frontmatter `chunk_id`s are `zzz_chunk/aaa_chunk/mmm_chunk` -- NOT
    already sorted -- so only a real sort produces the asserted ascending
    result."""
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "zzz_chunk", filename="01_note.md")
    _write_note(prose_dir, "aaa_chunk", filename="02_note.md")
    _write_note(prose_dir, "mmm_chunk", filename="03_note.md")

    pairs = _collect_snapshot_pairs(vault_dir)

    chunk_ids = [pair[0] for pair in pairs]
    assert chunk_ids == ["aaa_chunk", "mmm_chunk", "zzz_chunk"]


def test_snapshot_hash_sorted_by_chunk_id_independent_of_enumeration_order(tmp_path: Path):
    """Companion to the test above at the hash level: two vaults whose notes
    are enumerated in different filename order (again decoupled from
    `chunk_id` via `filename=`, for the same reason) must still hash equal,
    since the hash is computed over the sorted pair list, never raw glob
    order."""
    vault_a = tmp_path / "vault_a"
    prose_a = vault_a / "prose"
    _write_note(prose_a, "zzz_chunk", filename="01_note.md")
    _write_note(prose_a, "aaa_chunk", filename="02_note.md")

    vault_b = tmp_path / "vault_b"
    prose_b = vault_b / "prose"
    # same two chunk_ids, but visited in the OPPOSITE filename order
    _write_note(prose_b, "aaa_chunk", filename="01_note.md")
    _write_note(prose_b, "zzz_chunk", filename="02_note.md")

    assert _build_vault_snapshot_hash(vault_a) == _build_vault_snapshot_hash(vault_b)


def test_tag_projection_covers_only_the_named_tag_axes(tmp_path: Path):
    frontmatter = {
        "chunk_id": "c1",
        "chunk_text": "SENTINEL should never appear in the projection",
        "source_meta": {"author": "A"},
        "role_in_argument": "role:claim",
        "field": {"primary": "state", "secondary": []},
        "claim_type": {"primary": "x", "secondary": None, "subtags": []},
        "theory_school": {"primary": "y", "secondary": None, "status": "candidate"},
        "empirical_scope": {"value": "scope:country-case", "polity": "Syria"},
        "polities_touched": ["Syria"],
        "artifact_refs": [],
        "schema_version": "0.1",
        "some_future_key": "must not leak in either",
    }
    projection = _tag_projection(frontmatter)

    assert set(projection) == set(TAG_AXES) & set(frontmatter)
    assert "chunk_text" not in projection
    assert "source_meta" not in projection
    assert "artifact_refs" not in projection
    assert "schema_version" not in projection
    assert "some_future_key" not in projection


def test_snapshot_hash_changes_when_a_tag_changes(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "c1", field={"primary": "state", "secondary": []})
    baseline = _build_vault_snapshot_hash(vault_dir)

    _write_note(prose_dir, "c1", field={"primary": "violence", "secondary": []})
    mutated = _build_vault_snapshot_hash(vault_dir)

    assert baseline != mutated


def test_snapshot_hash_unchanged_when_only_chunk_text_changes(tmp_path: Path):
    """DEC-23: the pin tracks tagging, not prose -- editing chunk_text alone
    (tags held fixed) must not move the hash."""
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "c1")
    baseline = _build_vault_snapshot_hash(vault_dir)

    prose_dir_path = prose_dir / "c1.md"
    frontmatter = {
        "chunk_id": "c1",
        "section": "Introduction",
        "chunk_text": "a totally different sentence than before",
        "source_meta": {"author": "A", "title": "T"},
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "state", "secondary": []},
    }
    prose_dir_path.write_text(
        render_note(frontmatter, "# Introduction\n\nbody\n"), encoding="utf-8"
    )
    mutated = _build_vault_snapshot_hash(vault_dir)

    assert baseline == mutated


def test_snapshot_hash_changes_when_a_note_is_added(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "c1")
    baseline = _build_vault_snapshot_hash(vault_dir)

    _write_note(prose_dir, "c2")
    widened = _build_vault_snapshot_hash(vault_dir)

    assert baseline != widened


def test_snapshot_hash_changes_when_a_note_is_removed(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "c1")
    _write_note(prose_dir, "c2")
    baseline = _build_vault_snapshot_hash(vault_dir)

    (prose_dir / "c2.md").unlink()
    narrowed = _build_vault_snapshot_hash(vault_dir)

    assert baseline != narrowed


def test_snapshot_hash_missing_vault_dir_raises_naming_the_path(tmp_path: Path):
    missing = tmp_path / "no-such-vault"
    with pytest.raises(MissingVaultDirError) as excinfo:
        _build_vault_snapshot_hash(missing)
    assert str(missing) in str(excinfo.value)


def test_snapshot_hash_empty_prose_dir_is_a_stable_deterministic_value(tmp_path: Path):
    """A vault dir that exists but has no prose subdir yet (e.g. only
    artifacts so far) hashes the empty projection rather than erroring."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    first = _build_vault_snapshot_hash(vault_dir)
    second = _build_vault_snapshot_hash(vault_dir)
    assert first == second


# --- write_pin: field equality, diff-stable serialization (plan test 7) ----


def _stage_fixture(root: Path) -> tuple[Path, Path, Path]:
    envelopes_dir = root / "data" / "envelopes"
    vault_dir = root / "data" / "vault"
    sources_dir = root / "data" / "sources"
    envelope_path, source_id = _write_envelope_for_source(envelopes_dir, sources_dir, "book-a")
    _write_note(vault_dir / "prose", f"{source_id}_000_intro_001")
    return vault_dir, envelopes_dir, sources_dir


def test_write_pin_two_runs_compare_equal_field_by_field_and_sorted_keys(tmp_path: Path):
    vault_dir, envelopes_dir, sources_dir = _stage_fixture(tmp_path)
    evals_dir = tmp_path / "evals" / "corpus_pin"

    first_path = write_pin(
        "baseline",
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        sources_dir=sources_dir,
        evals_dir=evals_dir,
    )
    first = json.loads(first_path.read_text(encoding="utf-8"))

    second_path = write_pin(
        "baseline",
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        sources_dir=sources_dir,
        evals_dir=evals_dir,
    )
    second = json.loads(second_path.read_text(encoding="utf-8"))

    assert first == second
    assert first_path == second_path

    raw = first_path.read_text(encoding="utf-8")
    # sorted-keys, indent=2 serialization -- the top-level keys appear in
    # lexicographic order in the raw text, so the file is diff-stable.
    assert (
        raw.index('"ingest_code_sha"') < raw.index('"sources"') < raw.index('"vault_snapshot_hash"')
    )
    assert raw.endswith("}\n")


def test_write_pin_creates_evals_dir_when_absent(tmp_path: Path):
    vault_dir, envelopes_dir, sources_dir = _stage_fixture(tmp_path)
    evals_dir = tmp_path / "brand" / "new" / "evals" / "corpus_pin"
    assert not evals_dir.exists()

    path = write_pin(
        "baseline",
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        sources_dir=sources_dir,
        evals_dir=evals_dir,
    )

    assert path.is_file()
    assert path.parent == evals_dir


def test_write_pin_regenerating_the_envelope_does_not_move_content_hash(tmp_path: Path):
    """End-to-end F1 regression at the write_pin level: rewriting the
    envelope (simulating a routine LLM regen) with the raw source held
    fixed must not move that source's content_hash in the written pin."""
    vault_dir, envelopes_dir, sources_dir = _stage_fixture(tmp_path)
    evals_dir = tmp_path / "evals" / "corpus_pin"

    first_path = write_pin(
        "baseline",
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        sources_dir=sources_dir,
        evals_dir=evals_dir,
    )
    first = json.loads(first_path.read_text(encoding="utf-8"))

    (envelope_path,) = envelopes_dir.glob("*.json")
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    envelope["thesis"] = "a completely different regenerated thesis"
    envelope_path.write_text(json.dumps(envelope), encoding="utf-8")

    second_path = write_pin(
        "baseline",
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        sources_dir=sources_dir,
        evals_dir=evals_dir,
    )
    second = json.loads(second_path.read_text(encoding="utf-8"))

    assert first["sources"] == second["sources"]


# --- Sources-dir resolution delegates to axial.paths (issue #281) ----------


def test_default_sources_dir_is_the_same_function_object_as_axial_paths():
    """`corpus_pin._default_sources_dir` must be `axial.paths.
    default_sources_dir` itself, not a second, independent implementation
    -- issue #281: #248 added `_default_sources_dir` as its own
    config-then-fallback resolver, duplicating the one `axial.paths` was
    built (#249) to be the sole owner of. An identity check (rather than a
    behavioral comparison of two implementations that might simply happen
    to agree today) is what actually rules out a reintroduced duplicate:
    two independent functions can return equal paths on every input and
    still silently diverge the moment one of them is edited."""
    import axial.paths as paths_module

    assert _default_sources_dir is paths_module.default_sources_dir


def test_default_sources_dir_honors_a_configured_sources_dir(tmp_path: Path):
    """End-to-end proof that the delegation is live: a `paths.sources_dir`
    key in the pipeline config is honored by `corpus_pin._default_sources_dir`
    exactly as `axial.paths.default_sources_dir` resolves it (the
    acceptance criterion's own example config)."""
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        "paths:\n  sources_dir: data/a_totally_different_dir\n", encoding="utf-8"
    )

    assert _default_sources_dir(config_path) == Path("data/a_totally_different_dir")
