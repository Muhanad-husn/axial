"""Inner unit tests for the corpus-pin manifest module (issue #248, slice
02, specs/PHASE-B.md §7.12; extended for issue #486, slice 01, D6 --
the vault-snapshot hash now covers the name layer, not a struck tag
projection).

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

from axial.argmap.build import compute_corpus_pin
from axial.envelope import compute_source_id
from axial.eval.corpus_pin import (
    AmbiguousCorpusPinError,
    AmbiguousSourceFileError,
    GitShaUnavailableError,
    MalformedAliasMapError,
    MalformedDisagreementsError,
    MalformedEnvelopeError,
    MalformedNameIndexError,
    MalformedNoteError,
    MissingAliasMapError,
    MissingCorpusPinError,
    MissingDisagreementsError,
    MissingEnvelopesDirError,
    MissingNameIndexError,
    MissingNamesDirError,
    MissingSourceFileError,
    MissingVaultDirError,
    UnresolvableSourceIdError,
    _build_sources,
    _build_vault_snapshot_hash,
    _collect_chunk_ids,
    _count_non_null_disagreements,
    _default_sources_dir,
    _load_alias_map_version,
    _load_canonical_names,
    ingest_code_sha,
    resolve_pin_id,
    unresolvable_sources,
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
    ever catch a missing/removed sort). `**axis_overrides` still lets a
    caller set the schema tag axes (`field`, `role_in_argument`, etc.) even
    though the pin no longer reads them (D6) -- real vault notes carry them
    regardless, and `test_snapshot_hash_unchanged_when_tag_axes_change`
    below depends on being able to vary them."""
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


def _stage_names_dir(
    names_dir: Path,
    *,
    names: tuple[str, ...] = ("United States",),
    alias_map_version: int = 1,
    disagreements: tuple[tuple[str, str | None], ...] = (),
    index_generated_at: str = "2026-01-01T00:00:00Z",
    alias_map_generated_at: str = "2026-01-01T00:00:00Z",
) -> None:
    """A minimal, well-formed name layer under `names_dir`: `index.json`
    (the canonical name set), `alias_map.json` (the version Reconcile
    stamped), and `disagreements.jsonl` (one line per `(name_key,
    disagreement)` pair -- `disagreement=None` mirrors the real "these
    authors do not disagree" record). Every field this module's own
    `write_index`/`write_pin` never reads (`generated_at` on both JSON
    files) is included anyway, so a test that varies it can prove the pin
    ignores it."""
    names_dir.mkdir(parents=True, exist_ok=True)
    (names_dir / "index.json").write_text(
        json.dumps(
            {"version": alias_map_version, "generated_at": index_generated_at, "names": list(names)}
        ),
        encoding="utf-8",
    )
    (names_dir / "alias_map.json").write_text(
        json.dumps(
            {"version": alias_map_version, "generated_at": alias_map_generated_at, "nodes": []}
        ),
        encoding="utf-8",
    )
    lines = [
        json.dumps({"name_key": name_key, "disagreement": disagreement})
        for name_key, disagreement in disagreements
    ]
    (names_dir / "disagreements.jsonl").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
    )


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
        _collect_chunk_ids(vault_dir)

    assert str(note_path) in str(excinfo.value)


def test_split_frontmatter_non_mapping_raises_malformed_note_naming_the_path(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True)
    note_path = prose_dir / "c1.md"
    # A bare YAML list, not a mapping.
    note_path.write_text("---\n- one\n- two\n---\nbody\n", encoding="utf-8")

    with pytest.raises(MalformedNoteError) as excinfo:
        _collect_chunk_ids(vault_dir)

    assert str(note_path) in str(excinfo.value)


# --- F4: the missing-closing-delimiter guard has its own coverage ---------


def test_split_frontmatter_missing_closing_delimiter_raises_malformed_note(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True)
    note_path = prose_dir / "c1.md"
    note_path.write_text("---\nchunk_id: c1\nno closing delimiter here\n", encoding="utf-8")

    with pytest.raises(MalformedNoteError) as excinfo:
        _collect_chunk_ids(vault_dir)

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


# --- Vault chunk-id list (plan inner tests 3-6; F3: sort order asserted directly) --


def test_collect_chunk_ids_is_sorted_regardless_of_write_order(tmp_path: Path):
    """F3 (re-review, issue #248): assert the sort DIRECTLY on the canonical
    id list, with the on-disk FILENAME deliberately decoupled from
    `chunk_id` (via `_write_note`'s `filename=` param) -- when filename ==
    chunk_id (the prior version of this test), `Path.glob`'s own
    alphabetical-by-filename order is textually identical to chunk_id sort
    order, so the test cannot distinguish "sorted" from "glob order,
    whatever that happens to be" and would still pass with the `sort` call
    at `_collect_chunk_ids` deleted entirely. Here, glob visits
    `01_note.md/02_note.md/03_note.md` in that filename order, whose
    frontmatter `chunk_id`s are `zzz_chunk/aaa_chunk/mmm_chunk` -- NOT
    already sorted -- so only a real sort produces the asserted ascending
    result."""
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "zzz_chunk", filename="01_note.md")
    _write_note(prose_dir, "aaa_chunk", filename="02_note.md")
    _write_note(prose_dir, "mmm_chunk", filename="03_note.md")

    chunk_ids = _collect_chunk_ids(vault_dir)

    assert chunk_ids == ["aaa_chunk", "mmm_chunk", "zzz_chunk"]


def test_snapshot_hash_sorted_by_chunk_id_independent_of_enumeration_order(tmp_path: Path):
    """Companion to the test above at the hash level: two vaults whose notes
    are enumerated in different filename order (again decoupled from
    `chunk_id` via `filename=`, for the same reason) must still hash equal,
    since the hash is computed over the sorted chunk-id list, never raw
    glob order. Both vaults share the identical (stable) name layer, so
    only the vault side of the hash is under test."""
    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir)

    vault_a = tmp_path / "vault_a"
    prose_a = vault_a / "prose"
    _write_note(prose_a, "zzz_chunk", filename="01_note.md")
    _write_note(prose_a, "aaa_chunk", filename="02_note.md")

    vault_b = tmp_path / "vault_b"
    prose_b = vault_b / "prose"
    # same two chunk_ids, but visited in the OPPOSITE filename order
    _write_note(prose_b, "aaa_chunk", filename="01_note.md")
    _write_note(prose_b, "zzz_chunk", filename="02_note.md")

    assert _build_vault_snapshot_hash(vault_a, names_dir) == _build_vault_snapshot_hash(
        vault_b, names_dir
    )


def test_snapshot_hash_unchanged_when_only_chunk_text_changes(tmp_path: Path):
    """DEC-23: the pin tracks ids and the name layer, not prose -- editing
    chunk_text alone (chunk_id held fixed) must not move the hash."""
    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir)
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "c1")
    baseline = _build_vault_snapshot_hash(vault_dir, names_dir)

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
    mutated = _build_vault_snapshot_hash(vault_dir, names_dir)

    assert baseline == mutated


def test_snapshot_hash_unchanged_when_tag_axes_change(tmp_path: Path):
    """D6/STRUCK: Phase A v1 deleted every `TAG_AXES` tag axis, so the
    vault-snapshot hash no longer projects onto them at all -- changing
    `field.primary` (the old projection's own regression case) must NOT
    move the hash any more, the mirror image of the pre-#486 contract."""
    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir)
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "c1", field={"primary": "state", "secondary": []})
    baseline = _build_vault_snapshot_hash(vault_dir, names_dir)

    _write_note(prose_dir, "c1", field={"primary": "violence", "secondary": []})
    mutated = _build_vault_snapshot_hash(vault_dir, names_dir)

    assert baseline == mutated


def test_snapshot_hash_changes_when_a_note_is_added(tmp_path: Path):
    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir)
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "c1")
    baseline = _build_vault_snapshot_hash(vault_dir, names_dir)

    _write_note(prose_dir, "c2")
    widened = _build_vault_snapshot_hash(vault_dir, names_dir)

    assert baseline != widened


def test_snapshot_hash_changes_when_a_note_is_removed(tmp_path: Path):
    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir)
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "c1")
    _write_note(prose_dir, "c2")
    baseline = _build_vault_snapshot_hash(vault_dir, names_dir)

    (prose_dir / "c2.md").unlink()
    narrowed = _build_vault_snapshot_hash(vault_dir, names_dir)

    assert baseline != narrowed


def test_snapshot_hash_changes_when_a_note_id_changes(tmp_path: Path):
    """A note whose `chunk_id` itself changes (e.g. a re-chunk under D16)
    is neither purely an add nor purely a remove -- assert it directly
    rather than relying on the add/remove tests to imply it."""
    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir)
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    note_path = _write_note(prose_dir, "c1_old")
    baseline = _build_vault_snapshot_hash(vault_dir, names_dir)

    note_path.unlink()
    _write_note(prose_dir, "c1_new")
    renamed = _build_vault_snapshot_hash(vault_dir, names_dir)

    assert baseline != renamed


def test_snapshot_hash_missing_vault_dir_raises_naming_the_path(tmp_path: Path):
    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir)
    missing = tmp_path / "no-such-vault"
    with pytest.raises(MissingVaultDirError) as excinfo:
        _build_vault_snapshot_hash(missing, names_dir)
    assert str(missing) in str(excinfo.value)


def test_snapshot_hash_empty_prose_dir_is_a_stable_deterministic_value(tmp_path: Path):
    """A vault dir that exists but has no prose subdir yet (e.g. only
    artifacts so far) hashes the empty chunk-id list rather than
    erroring."""
    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir)
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    first = _build_vault_snapshot_hash(vault_dir, names_dir)
    second = _build_vault_snapshot_hash(vault_dir, names_dir)
    assert first == second


# --- The name layer (issue #486, D6) ---------------------------------------


def test_load_canonical_names_returns_sorted_deduplicated_set(tmp_path: Path):
    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir, names=("Zebra", "Aardvark", "Zebra"))

    assert _load_canonical_names(names_dir) == ["Aardvark", "Zebra"]


def test_load_canonical_names_missing_names_dir_raises(tmp_path: Path):
    missing = tmp_path / "no-such-names"
    with pytest.raises(MissingNamesDirError) as excinfo:
        _load_canonical_names(missing)
    assert str(missing) in str(excinfo.value)


def test_load_canonical_names_missing_index_file_raises_naming_the_path(tmp_path: Path):
    names_dir = tmp_path / "names"
    names_dir.mkdir()
    (names_dir / "alias_map.json").write_text(
        json.dumps({"version": 1, "nodes": []}), encoding="utf-8"
    )
    (names_dir / "disagreements.jsonl").write_text("", encoding="utf-8")

    index_path = names_dir / "index.json"
    with pytest.raises(MissingNameIndexError) as excinfo:
        _load_canonical_names(names_dir)
    assert str(index_path) in str(excinfo.value)


def test_load_canonical_names_malformed_json_raises(tmp_path: Path):
    names_dir = tmp_path / "names"
    names_dir.mkdir()
    (names_dir / "index.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(MalformedNameIndexError):
        _load_canonical_names(names_dir)


def test_load_canonical_names_missing_names_key_raises(tmp_path: Path):
    names_dir = tmp_path / "names"
    names_dir.mkdir()
    (names_dir / "index.json").write_text(json.dumps({"version": 1}), encoding="utf-8")

    with pytest.raises(MalformedNameIndexError):
        _load_canonical_names(names_dir)


def test_load_canonical_names_non_mapping_index_raises(tmp_path: Path):
    """Mirrors `_build_sources`'s own F2 non-mapping guard: valid JSON that
    isn't a mapping (e.g. a bare top-level list) must not escape as a bare
    `AttributeError` from `index.get(...)`."""
    names_dir = tmp_path / "names"
    names_dir.mkdir()
    (names_dir / "index.json").write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")

    with pytest.raises(MalformedNameIndexError):
        _load_canonical_names(names_dir)


def test_load_alias_map_version_returns_the_version_field(tmp_path: Path):
    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir, alias_map_version=7)

    assert _load_alias_map_version(names_dir) == 7


def test_load_alias_map_version_missing_file_raises_naming_the_path(tmp_path: Path):
    names_dir = tmp_path / "names"
    names_dir.mkdir()
    (names_dir / "index.json").write_text(json.dumps({"version": 1, "names": []}), encoding="utf-8")
    (names_dir / "disagreements.jsonl").write_text("", encoding="utf-8")

    alias_map_path = names_dir / "alias_map.json"
    with pytest.raises(MissingAliasMapError) as excinfo:
        _load_alias_map_version(names_dir)
    assert str(alias_map_path) in str(excinfo.value)


def test_load_alias_map_version_malformed_json_raises(tmp_path: Path):
    names_dir = tmp_path / "names"
    names_dir.mkdir()
    (names_dir / "alias_map.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(MalformedAliasMapError):
        _load_alias_map_version(names_dir)


def test_load_alias_map_version_non_mapping_raises(tmp_path: Path):
    names_dir = tmp_path / "names"
    names_dir.mkdir()
    (names_dir / "alias_map.json").write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")

    with pytest.raises(MalformedAliasMapError):
        _load_alias_map_version(names_dir)


def test_count_non_null_disagreements_counts_only_non_null_records(tmp_path: Path):
    names_dir = tmp_path / "names"
    _stage_names_dir(
        names_dir,
        disagreements=(
            ("name-a", "Author X says Y, author Z says not-Y"),
            ("name-b", None),
            ("name-c", "Another real disagreement"),
        ),
    )

    assert _count_non_null_disagreements(names_dir) == 2


def test_count_non_null_disagreements_missing_file_raises_naming_the_path(tmp_path: Path):
    names_dir = tmp_path / "names"
    names_dir.mkdir()
    (names_dir / "index.json").write_text(json.dumps({"version": 1, "names": []}), encoding="utf-8")
    (names_dir / "alias_map.json").write_text(
        json.dumps({"version": 1, "nodes": []}), encoding="utf-8"
    )

    disagreements_path = names_dir / "disagreements.jsonl"
    with pytest.raises(MissingDisagreementsError) as excinfo:
        _count_non_null_disagreements(names_dir)
    assert str(disagreements_path) in str(excinfo.value)


def test_count_non_null_disagreements_malformed_line_raises(tmp_path: Path):
    """A torn/corrupt line that is NOT the checkpoint's last line is genuine
    corruption (`axial.checkpoint.load_checkpoint_records`'s own healing
    rule only forgives a torn FINAL line, the signature of a hard kill
    mid-append) -- raises naming the file and the 1-indexed line number."""
    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir)
    (names_dir / "disagreements.jsonl").write_text(
        'not json at all\n{"name_key": "a", "disagreement": null}\n',
        encoding="utf-8",
    )

    with pytest.raises(MalformedDisagreementsError):
        _count_non_null_disagreements(names_dir)


# --- The vault-snapshot hash covers the name layer (issue #486, D6) --------


def test_snapshot_hash_changes_when_the_disagreement_count_changes(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    _write_note(vault_dir / "prose", "c1")

    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir, disagreements=(("name-a", None),))
    baseline = _build_vault_snapshot_hash(vault_dir, names_dir)

    _stage_names_dir(names_dir, disagreements=(("name-a", "a real disagreement now"),))
    mutated = _build_vault_snapshot_hash(vault_dir, names_dir)

    assert baseline != mutated


def test_snapshot_hash_changes_when_the_alias_map_version_changes(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    _write_note(vault_dir / "prose", "c1")

    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir, alias_map_version=1)
    baseline = _build_vault_snapshot_hash(vault_dir, names_dir)

    _stage_names_dir(names_dir, alias_map_version=2)
    mutated = _build_vault_snapshot_hash(vault_dir, names_dir)

    assert baseline != mutated


def test_snapshot_hash_changes_when_the_canonical_name_set_changes(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    _write_note(vault_dir / "prose", "c1")

    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir, names=("United States",))
    baseline = _build_vault_snapshot_hash(vault_dir, names_dir)

    _stage_names_dir(names_dir, names=("United States", "Syria"))
    mutated = _build_vault_snapshot_hash(vault_dir, names_dir)

    assert baseline != mutated


def test_snapshot_hash_unchanged_when_index_generated_at_moves(tmp_path: Path):
    """`index.json`'s own `generated_at` moves on every rebuild whether or
    not `names` changed -- it must never enter the hash."""
    vault_dir = tmp_path / "vault"
    _write_note(vault_dir / "prose", "c1")

    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir, index_generated_at="2026-01-01T00:00:00Z")
    baseline = _build_vault_snapshot_hash(vault_dir, names_dir)

    _stage_names_dir(names_dir, index_generated_at="2099-12-31T23:59:59Z")
    mutated = _build_vault_snapshot_hash(vault_dir, names_dir)

    assert baseline == mutated


def test_snapshot_hash_unchanged_when_alias_map_generated_at_moves(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    _write_note(vault_dir / "prose", "c1")

    names_dir = tmp_path / "names"
    _stage_names_dir(names_dir, alias_map_generated_at="2026-01-01T00:00:00Z")
    baseline = _build_vault_snapshot_hash(vault_dir, names_dir)

    _stage_names_dir(names_dir, alias_map_generated_at="2099-12-31T23:59:59Z")
    mutated = _build_vault_snapshot_hash(vault_dir, names_dir)

    assert baseline == mutated


def test_snapshot_hash_missing_names_dir_raises(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    _write_note(vault_dir / "prose", "c1")
    missing_names_dir = tmp_path / "no-such-names"

    with pytest.raises(MissingNamesDirError) as excinfo:
        _build_vault_snapshot_hash(vault_dir, missing_names_dir)
    assert str(missing_names_dir) in str(excinfo.value)


def test_snapshot_hash_vault_error_raised_before_names_dir_is_ever_read(tmp_path: Path):
    """A malformed vault fails loudly on its own terms even when the name
    layer is entirely missing -- `_collect_chunk_ids` runs first."""
    vault_dir = tmp_path / "no-such-vault"
    missing_names_dir = tmp_path / "also-no-such-names"

    with pytest.raises(MissingVaultDirError):
        _build_vault_snapshot_hash(vault_dir, missing_names_dir)


# --- write_pin: field equality, diff-stable serialization (plan test 7) ----


def _stage_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    envelopes_dir = root / "data" / "envelopes"
    vault_dir = root / "data" / "vault"
    sources_dir = root / "data" / "sources"
    names_dir = root / "data" / "names"
    envelope_path, source_id = _write_envelope_for_source(envelopes_dir, sources_dir, "book-a")
    _write_note(vault_dir / "prose", f"{source_id}_000_intro_001")
    _stage_names_dir(names_dir)
    return vault_dir, envelopes_dir, sources_dir, names_dir


def test_write_pin_two_runs_compare_equal_field_by_field_and_sorted_keys(tmp_path: Path):
    vault_dir, envelopes_dir, sources_dir, names_dir = _stage_fixture(tmp_path)
    evals_dir = tmp_path / "evals" / "corpus_pin"

    first_path = write_pin(
        "baseline",
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        sources_dir=sources_dir,
        names_dir=names_dir,
        evals_dir=evals_dir,
    )
    first = json.loads(first_path.read_text(encoding="utf-8"))

    second_path = write_pin(
        "baseline",
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        sources_dir=sources_dir,
        names_dir=names_dir,
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
    vault_dir, envelopes_dir, sources_dir, names_dir = _stage_fixture(tmp_path)
    evals_dir = tmp_path / "brand" / "new" / "evals" / "corpus_pin"
    assert not evals_dir.exists()

    path = write_pin(
        "baseline",
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        sources_dir=sources_dir,
        names_dir=names_dir,
        evals_dir=evals_dir,
    )

    assert path.is_file()
    assert path.parent == evals_dir


def test_write_pin_regenerating_the_envelope_does_not_move_content_hash(tmp_path: Path):
    """End-to-end F1 regression at the write_pin level: rewriting the
    envelope (simulating a routine LLM regen) with the raw source held
    fixed must not move that source's content_hash in the written pin."""
    vault_dir, envelopes_dir, sources_dir, names_dir = _stage_fixture(tmp_path)
    evals_dir = tmp_path / "evals" / "corpus_pin"

    first_path = write_pin(
        "baseline",
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        sources_dir=sources_dir,
        names_dir=names_dir,
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
        names_dir=names_dir,
        evals_dir=evals_dir,
    )
    second = json.loads(second_path.read_text(encoding="utf-8"))

    assert first["sources"] == second["sources"]


def test_write_pin_manifest_never_contains_a_canonical_name(tmp_path: Path):
    """§7.12/D6: the hash COVERS the canonical name set; the written
    manifest must never carry the names themselves (DEC-23 extended to the
    name layer -- a canonical name is a surface form a source wrote)."""
    vault_dir, envelopes_dir, sources_dir, names_dir = _stage_fixture(tmp_path)
    sentinel_name = "SENTINEL_CANONICAL_NAME_9f3a21_Muhanad_Test_Surface_Form"
    _stage_names_dir(names_dir, names=(sentinel_name,))
    evals_dir = tmp_path / "evals" / "corpus_pin"

    path = write_pin(
        "baseline",
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        sources_dir=sources_dir,
        names_dir=names_dir,
        evals_dir=evals_dir,
    )

    raw = path.read_text(encoding="utf-8")
    assert sentinel_name not in raw


def test_write_pin_missing_names_dir_raises_and_writes_nothing(tmp_path: Path):
    vault_dir, envelopes_dir, sources_dir, names_dir = _stage_fixture(tmp_path)
    evals_dir = tmp_path / "evals" / "corpus_pin"
    missing_names_dir = tmp_path / "no-such-names"

    with pytest.raises(MissingNamesDirError):
        write_pin(
            "baseline",
            vault_dir=vault_dir,
            envelopes_dir=envelopes_dir,
            sources_dir=sources_dir,
            names_dir=missing_names_dir,
            evals_dir=evals_dir,
        )

    assert not (evals_dir / "baseline.json").exists()


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


# --- resolve_pin_id: archived pins stay invisible (DEC-42) ------------------


def test_resolve_pin_id_ignores_an_archive_subdirectory(tmp_path: Path):
    """DEC-42: after a corpus rebuild the old pin is kept as history rather
    than rewritten, and a fresh pin is generated alongside it. The archive
    convention keeps `resolve_pin_id`'s "exactly one live manifest"
    invariant intact by relocating history out of its (non-recursive) glob
    rather than weakening the invariant: a live pin plus one or more
    superseded pins filed under `archive/` resolves cleanly to the live
    pin's stem, with the archived files neither ambiguating nor resolving."""
    pin_dir = tmp_path / "corpus_pin"
    pin_dir.mkdir()
    (pin_dir / "sim-2026-08-01.json").write_text("{}", encoding="utf-8")
    archive_dir = pin_dir / "archive"
    archive_dir.mkdir()
    (archive_dir / "sim-2026-07-23.json").write_text("{}", encoding="utf-8")

    assert resolve_pin_id(pin_dir) == "sim-2026-08-01"


def test_resolve_pin_id_ignores_multiple_archived_pins(tmp_path: Path):
    """Several superseded pins accumulating under `archive/` over successive
    rebuilds must never trip the ambiguity check -- only files directly
    under `evals_dir` count."""
    pin_dir = tmp_path / "corpus_pin"
    pin_dir.mkdir()
    (pin_dir / "sim-2026-08-01.json").write_text("{}", encoding="utf-8")
    archive_dir = pin_dir / "archive"
    archive_dir.mkdir()
    (archive_dir / "sim-2026-07-23.json").write_text("{}", encoding="utf-8")
    (archive_dir / "sim-2026-06-01.json").write_text("{}", encoding="utf-8")

    assert resolve_pin_id(pin_dir) == "sim-2026-08-01"


def test_resolve_pin_id_still_ambiguous_for_two_live_pins(tmp_path: Path):
    """We are relocating history, not weakening the invariant: two `*.json`
    manifests directly under `evals_dir` (no archiving) still raise
    `AmbiguousCorpusPinError`, exactly as before this change."""
    pin_dir = tmp_path / "corpus_pin"
    pin_dir.mkdir()
    (pin_dir / "a.json").write_text("{}", encoding="utf-8")
    (pin_dir / "b.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AmbiguousCorpusPinError):
        resolve_pin_id(pin_dir)


def test_resolve_pin_id_missing_when_only_archived_pins_exist(tmp_path: Path):
    """A pin directory holding nothing but an `archive/` subdirectory (e.g.
    right after the old pin was archived and before a fresh one is written)
    is correctly reported as missing, not silently satisfied by history."""
    pin_dir = tmp_path / "corpus_pin"
    pin_dir.mkdir()
    archive_dir = pin_dir / "archive"
    archive_dir.mkdir()
    (archive_dir / "sim-2026-07-23.json").write_text("{}", encoding="utf-8")

    with pytest.raises(MissingCorpusPinError):
        resolve_pin_id(pin_dir)


# --- unresolvable_sources ----------------------------------------------------
#
# The pin's own precondition, asked without raising (issue #819): every
# envelope `_build_sources` could not resolve a raw source file for. It is
# what `axial sources` reports as `missing`, so it must agree with
# `compute_corpus_pin` on the same corpus in every case below.


def test_unresolvable_sources_is_empty_when_the_pin_can_be_computed(tmp_path: Path):
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    _write_envelope_for_source(envelopes_dir, sources_dir, "book-a")
    _write_envelope_for_source(envelopes_dir, sources_dir, "book-b")

    assert unresolvable_sources(envelopes_dir, sources_dir) == []
    # And the pin really does compute, so the empty answer was not a false
    # all-clear.
    assert compute_corpus_pin(envelopes_dir, sources_dir)


def test_unresolvable_sources_names_an_envelope_whose_raw_file_is_gone(tmp_path: Path):
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    _write_envelope_for_source(envelopes_dir, sources_dir, "book-a")
    _, source_id = _write_envelope_for_source(envelopes_dir, sources_dir, "gone")
    (sources_dir / "gone.pdf").unlink()

    unresolved = unresolvable_sources(envelopes_dir, sources_dir)

    assert [entry[0] for entry in unresolved] == [source_id]
    assert "no raw source file" in unresolved[0][1]
    # The pin agrees: this is exactly the state that kills it.
    with pytest.raises(MissingSourceFileError):
        compute_corpus_pin(envelopes_dir, sources_dir)


def test_unresolvable_sources_names_every_one_not_only_the_first(tmp_path: Path):
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    _, kept = _write_envelope_for_source(envelopes_dir, sources_dir, "book-a")
    for stem in ("gone-one", "gone-two"):
        _write_envelope_for_source(envelopes_dir, sources_dir, stem)
        (sources_dir / f"{stem}.pdf").unlink()

    unresolved = unresolvable_sources(envelopes_dir, sources_dir)

    # The pin raises on the first it reaches; this reports both, which is
    # the whole point -- restoring one file at a time and re-running a paid
    # draw to find the next is the expensive version of this answer.
    assert len(unresolved) == 2
    assert kept not in {entry[0] for entry in unresolved}


def test_unresolvable_sources_does_not_fire_on_a_re_sourced_file(tmp_path: Path):
    """A file replaced with different bytes gets a NEW source_id, leaving the
    old envelope behind under the same stem. The pin resolves BY STEM, so it
    still computes -- and a check that reported that stale envelope
    `missing` would fail an operator's command forever over a state the pin
    does not care about."""
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    _write_envelope_for_source(envelopes_dir, sources_dir, "book-a")
    _write_envelope_raw(envelopes_dir, "book-a-000000000000")

    assert unresolvable_sources(envelopes_dir, sources_dir) == []
    assert compute_corpus_pin(envelopes_dir, sources_dir)


def test_unresolvable_sources_names_an_ambiguous_stem(tmp_path: Path):
    """Both a .pdf and a .docx under one stem: the pin refuses rather than
    picking, and the forward walk cannot see it either -- it reports two
    perfectly ordinary sources."""
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    _, source_id = _write_envelope_for_source(envelopes_dir, sources_dir, "book-a")
    (sources_dir / "book-a.docx").write_bytes(b"a second file under the same stem")

    unresolved = unresolvable_sources(envelopes_dir, sources_dir)

    assert [entry[0] for entry in unresolved] == [source_id]
    assert "ambiguous" in unresolved[0][1].lower()
    with pytest.raises(AmbiguousSourceFileError):
        compute_corpus_pin(envelopes_dir, sources_dir)


def test_unresolvable_sources_names_a_source_id_of_a_retired_shape(tmp_path: Path):
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    _write_envelope_raw(envelopes_dir, "a-long-retired-identifier-with-no-digest")

    unresolved = unresolvable_sources(envelopes_dir, sources_dir)

    assert [entry[0] for entry in unresolved] == ["a-long-retired-identifier-with-no-digest"]
    with pytest.raises(UnresolvableSourceIdError):
        compute_corpus_pin(envelopes_dir, sources_dir)


def test_unresolvable_sources_names_a_malformed_envelope_rather_than_raising(tmp_path: Path):
    envelopes_dir = tmp_path / "envelopes"
    sources_dir = tmp_path / "sources"
    _write_envelope_for_source(envelopes_dir, sources_dir, "book-a")
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    (envelopes_dir / "broken-2001-abcdefabcdef.json").write_text("{ not json", encoding="utf-8")

    unresolved = unresolvable_sources(envelopes_dir, sources_dir)

    assert [entry[0] for entry in unresolved] == ["broken-2001-abcdefabcdef"]
    with pytest.raises(MalformedEnvelopeError):
        compute_corpus_pin(envelopes_dir, sources_dir)


def test_unresolvable_sources_returns_empty_list_for_an_absent_envelopes_dir(tmp_path: Path):
    """Nothing ingested, so nothing can be unresolvable -- `compute_corpus_pin`
    raises here, but the check is asked on corpora that may not exist yet."""
    assert unresolvable_sources(tmp_path / "nowhere", tmp_path / "sources") == []
