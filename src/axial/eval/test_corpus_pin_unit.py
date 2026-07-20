"""Inner unit tests for the corpus-pin manifest module (issue #248, slice
02, specs/PHASE-B.md §7.12).

Co-located under src/axial/eval/ per the repo's existing test layout
(mirrors src/axial/brief/test_intake.py for the sibling brief package).
The outer acceptance test (tests/analysis/test_corpus_pin.py, locked,
DEC-1) drives `axial pin write` end to end through a subprocess and pins
the CLI-level contract; these unit tests exercise the pieces underneath it
directly -- the plan's own inner unit test list
(plans/analysis-foundation/02-corpus-pin-manifest.md).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from axial.envelope import compute_source_id
from axial.eval.corpus_pin import (
    GitShaUnavailableError,
    MissingEnvelopesDirError,
    MissingVaultDirError,
    TAG_AXES,
    _build_sources,
    _build_vault_snapshot_hash,
    _tag_projection,
    ingest_code_sha,
    write_pin,
)
from axial.vault import render_note


def _write_envelope(envelopes_dir: Path, source_id: str) -> Path:
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    path = envelopes_dir / f"{source_id}.json"
    path.write_text(json.dumps({"source_id": source_id, "thesis": "t"}), encoding="utf-8")
    return path


def _write_note(prose_dir: Path, chunk_id: str, **axis_overrides) -> Path:
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
    path = prose_dir / f"{chunk_id}.md"
    path.write_text(render_note(frontmatter, "# Introduction\n\nbody\n"), encoding="utf-8")
    return path


# --- Source list (plan inner test 1) ----------------------------------------


def test_build_sources_one_entry_per_envelope_with_source_id_and_content_hash(tmp_path: Path):
    envelopes_dir = tmp_path / "envelopes"
    _write_envelope(envelopes_dir, "book-a-111111111111")
    _write_envelope(envelopes_dir, "book-b-222222222222")

    sources = _build_sources(envelopes_dir)

    assert [entry["source_id"] for entry in sources] == [
        "book-a-111111111111",
        "book-b-222222222222",
    ]
    for entry in sources:
        assert isinstance(entry["content_hash"], str) and entry["content_hash"]


def test_build_sources_content_hash_reuses_compute_source_id_hashing_path(tmp_path: Path):
    """The pin's content_hash must not invent a second hashing convention:
    it is the same sha256-over-bytes primitive `compute_source_id` already
    uses, applied here to the envelope file itself (the only content
    available at pin-write time)."""
    envelopes_dir = tmp_path / "envelopes"
    path = _write_envelope(envelopes_dir, "book-a-111111111111")

    (entry,) = _build_sources(envelopes_dir)

    # compute_source_id's own suffix is the first 12 hex chars of the exact
    # same sha256 digest this module reuses in full.
    expected_source_id = compute_source_id(path)
    assert expected_source_id.endswith(entry["content_hash"][:12])


def test_build_sources_missing_envelopes_dir_raises_naming_the_path(tmp_path: Path):
    missing = tmp_path / "no-such-envelopes"
    with pytest.raises(MissingEnvelopesDirError) as excinfo:
        _build_sources(missing)
    assert str(missing) in str(excinfo.value)


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


# --- Vault snapshot hash (plan inner tests 3-6) -----------------------------


def test_snapshot_hash_sorted_by_chunk_id_independent_of_enumeration_order(tmp_path: Path):
    vault_a = tmp_path / "vault_a"
    prose_a = vault_a / "prose"
    _write_note(prose_a, "zzz_chunk")
    _write_note(prose_a, "aaa_chunk")

    vault_b = tmp_path / "vault_b"
    prose_b = vault_b / "prose"
    # written in the opposite order on disk
    _write_note(prose_b, "aaa_chunk")
    _write_note(prose_b, "zzz_chunk")

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


def _stage_fixture(root: Path) -> tuple[Path, Path]:
    envelopes_dir = root / "data" / "envelopes"
    vault_dir = root / "data" / "vault"
    _write_envelope(envelopes_dir, "book-a-111111111111")
    _write_note(vault_dir / "prose", "book-a-111111111111_000_intro_001")
    return vault_dir, envelopes_dir


def test_write_pin_two_runs_compare_equal_field_by_field_and_sorted_keys(tmp_path: Path):
    vault_dir, envelopes_dir = _stage_fixture(tmp_path)
    evals_dir = tmp_path / "evals" / "corpus_pin"

    first_path = write_pin(
        "baseline", vault_dir=vault_dir, envelopes_dir=envelopes_dir, evals_dir=evals_dir
    )
    first = json.loads(first_path.read_text(encoding="utf-8"))

    second_path = write_pin(
        "baseline", vault_dir=vault_dir, envelopes_dir=envelopes_dir, evals_dir=evals_dir
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
    vault_dir, envelopes_dir = _stage_fixture(tmp_path)
    evals_dir = tmp_path / "brand" / "new" / "evals" / "corpus_pin"
    assert not evals_dir.exists()

    path = write_pin(
        "baseline", vault_dir=vault_dir, envelopes_dir=envelopes_dir, evals_dir=evals_dir
    )

    assert path.is_file()
    assert path.parent == evals_dir
