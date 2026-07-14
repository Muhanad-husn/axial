"""Inner unit tests for the axial vault module (issue #18 slice 06 -- vault
write)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

_ENVELOPE = {
    "source_id": "paper-abc123",
    "author": None,
    "title": "Some Paper",
    "date": None,
    "thesis": "Envelope thesis text.",
    "scope": "Envelope scope text.",
    "stated_argument": "Envelope stated_argument text.",
}

_RECORD = {
    "chunk_id": "paper-abc123_1_introduction_001",
    "section": "Introduction",
    "chunk_text": "This is the chunk's own prose text.",
    "role_in_argument": "role:claim",
    "schema_version": "1.0.0",
    "empirical_scope": "scope:country-case",
    "country": "Syria",
    "field": {"primary": "field:political-science", "secondary": ["field:history"]},
    "claim_type": {
        "primary": "claim:causal",
        "secondary": None,
        "subtags": ["claim:causal:mechanism"],
    },
    "theory_school": {"primary": "school:realism", "secondary": None, "status": "candidate"},
}

_NON_COUNTRY_RECORD = {
    **_RECORD,
    "empirical_scope": "scope:national",
}
del _NON_COUNTRY_RECORD["country"]

# issue #32 slice 02 -- artifact record shape (mirrors
# `axial.artifacts.build_artifact_record`'s output).
_ARTIFACT_RECORD = {
    "artifact_id": "paper-abc123_art_1.2",
    "artifact_role": "case-study",
    "field": {"primary": "state", "secondary": ["ideology"]},
    "source_id": "paper-abc123",
    "section": "Introduction",
}

_DISCARD_ARTIFACT_RECORD = {
    "artifact_id": "paper-abc123_art_1.3",
    "artifact_role": "discard",
    "field": {"primary": "state", "secondary": []},
    "source_id": "paper-abc123",
    "section": "Introduction",
}


# --- frontmatter assembly ----------------------------------------------------


def test_build_frontmatter_carries_chunk_id_section_chunk_text():
    from axial.vault import build_frontmatter

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE)

    assert frontmatter["chunk_id"] == _RECORD["chunk_id"]
    assert frontmatter["section"] == _RECORD["section"]
    assert frontmatter["chunk_text"] == _RECORD["chunk_text"]


def test_build_frontmatter_source_meta_carries_five_fields_from_envelope():
    from axial.vault import build_frontmatter

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE)
    source_meta = frontmatter["source_meta"]

    assert source_meta == {
        "author": None,
        "title": "Some Paper",
        "date": None,
        "thesis": "Envelope thesis text.",
        "scope": "Envelope scope text.",
    }


# --- axis block (issue #31 slice 04) -----------------------------------------


def test_build_frontmatter_carries_schema_version():
    from axial.vault import build_frontmatter

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE)

    assert frontmatter["schema_version"] == _RECORD["schema_version"]


def test_build_frontmatter_role_in_argument_is_a_flat_scalar():
    from axial.vault import build_frontmatter

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE)

    assert frontmatter["role_in_argument"] == _RECORD["role_in_argument"]


def test_build_frontmatter_field_and_claim_type_carried_through_verbatim():
    from axial.vault import build_frontmatter

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE)

    assert frontmatter["field"] == _RECORD["field"]
    assert frontmatter["claim_type"] == _RECORD["claim_type"]


def test_build_frontmatter_theory_school_carries_primary_and_status():
    from axial.vault import build_frontmatter

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE)

    assert frontmatter["theory_school"]["primary"] == _RECORD["theory_school"]["primary"]
    assert frontmatter["theory_school"]["status"] == _RECORD["theory_school"]["status"]


def test_build_frontmatter_empirical_scope_nests_value_and_country():
    from axial.vault import build_frontmatter

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE)

    assert frontmatter["empirical_scope"] == {
        "value": _RECORD["empirical_scope"],
        "country": _RECORD["country"],
    }


def test_build_frontmatter_empirical_scope_omits_country_when_record_has_none():
    from axial.vault import build_frontmatter

    frontmatter = build_frontmatter(_NON_COUNTRY_RECORD, _ENVELOPE)

    assert frontmatter["empirical_scope"] == {"value": _NON_COUNTRY_RECORD["empirical_scope"]}
    assert "country" not in frontmatter["empirical_scope"]


# --- note rendering -----------------------------------------------------------


def test_render_note_has_delimited_yaml_frontmatter_parseable_by_pyyaml():
    from axial.vault import build_frontmatter, render_note

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE)
    note_text = render_note(frontmatter, "body text here")

    lines = note_text.splitlines()
    assert lines[0] == "---"
    closing_index = lines.index("---", 1)
    parsed = yaml.safe_load("\n".join(lines[1:closing_index]))
    assert parsed["chunk_id"] == _RECORD["chunk_id"]


def test_render_note_body_contains_chunk_text_below_frontmatter():
    from axial.vault import build_frontmatter, render_note

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE)
    note_text = render_note(frontmatter, "This is the chunk's own prose text.")

    lines = note_text.splitlines()
    closing_index = lines.index("---", 1)
    body = "\n".join(lines[closing_index + 1 :])
    assert "This is the chunk's own prose text." in body


def _split_frontmatter_like_outer_test(text: str) -> tuple[dict, str]:
    """Mirror tests/test_vault_write.py's `_split_frontmatter`: scan for the
    first line (after the opening '---') whose stripped value is exactly
    '---' and treat it as the closing delimiter."""
    lines = text.splitlines()
    assert lines[0].strip() == "---"
    closing_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing_index = index
            break
    assert closing_index is not None
    frontmatter_text = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1 :])
    return yaml.safe_load(frontmatter_text), body


def test_render_note_survives_chunk_text_containing_a_bare_triple_dash_line():
    """A chunk's text (or section) may itself contain a line that is exactly
    '---' (e.g. a Markdown horizontal rule from docling/Unstructured output).
    yaml.safe_dump's default folded scalar style would emit that embedded
    '---' on its own indented line inside the chunk_text value, which a
    frontmatter splitter scanning for the first bare '---' line (exactly
    what the locked outer test's `_split_frontmatter` does) would mistake
    for the closing delimiter, truncating/corrupting the frontmatter."""
    from axial.vault import build_frontmatter, render_note

    record = {
        **_RECORD,
        "chunk_text": "First line of the chunk.\n---\nSecond line after a bare rule.",
    }

    frontmatter = build_frontmatter(record, _ENVELOPE)
    note_text = render_note(frontmatter, record["chunk_text"])

    parsed_frontmatter, body = _split_frontmatter_like_outer_test(note_text)

    assert parsed_frontmatter == frontmatter
    assert parsed_frontmatter["chunk_text"] == record["chunk_text"]
    assert record["chunk_text"] in body


# --- note writing --------------------------------------------------------------


def test_write_chunk_note_writes_under_prose_dir_named_by_chunk_id(tmp_path):
    from axial.vault import write_chunk_note

    vault_dir = tmp_path / "vault"
    note_path = write_chunk_note(_RECORD, _ENVELOPE, vault_dir)

    assert note_path == vault_dir / "prose" / f"{_RECORD['chunk_id']}.md"
    assert note_path.is_file()


def test_write_chunk_note_creates_parent_dirs(tmp_path):
    from axial.vault import write_chunk_note

    vault_dir = tmp_path / "nested" / "vault"
    note_path = write_chunk_note(_RECORD, _ENVELOPE, vault_dir)

    assert note_path.is_file()


def test_write_chunk_note_does_not_touch_artifacts_dir(tmp_path):
    from axial.vault import write_chunk_note

    vault_dir = tmp_path / "vault"
    write_chunk_note(_RECORD, _ENVELOPE, vault_dir)

    assert not (vault_dir / "artifacts").exists()


def test_write_chunk_note_rerun_overwrites_in_place_without_duplicating(tmp_path):
    """Re-running vault write on the same chunk must update its note
    idempotently, not create a second file (plan seeded behavior)."""
    from axial.vault import write_chunk_note

    vault_dir = tmp_path / "vault"

    first_path = write_chunk_note(_RECORD, _ENVELOPE, vault_dir)
    second_path = write_chunk_note(_RECORD, _ENVELOPE, vault_dir)

    assert first_path == second_path
    prose_files = [p for p in (vault_dir / "prose").iterdir() if p.is_file()]
    assert len(prose_files) == 1
    assert prose_files[0] == first_path


# --- artifact frontmatter/note (issue #32 slice 02) --------------------------


def test_build_artifact_frontmatter_carries_role_field_and_provenance():
    from axial.vault import build_artifact_frontmatter

    frontmatter = build_artifact_frontmatter(_ARTIFACT_RECORD)

    assert frontmatter["artifact_id"] == _ARTIFACT_RECORD["artifact_id"]
    assert frontmatter["artifact_role"] == _ARTIFACT_RECORD["artifact_role"]
    assert frontmatter["field"] == _ARTIFACT_RECORD["field"]
    assert frontmatter["source_id"] == _ARTIFACT_RECORD["source_id"]
    assert frontmatter["section"] == _ARTIFACT_RECORD["section"]


def test_build_artifact_frontmatter_retrievable_true_for_non_discard_role():
    from axial.vault import build_artifact_frontmatter

    frontmatter = build_artifact_frontmatter(_ARTIFACT_RECORD)

    assert frontmatter["retrievable"] is True


def test_build_artifact_frontmatter_retrievable_false_for_discard_role():
    from axial.vault import build_artifact_frontmatter

    frontmatter = build_artifact_frontmatter(_DISCARD_ARTIFACT_RECORD)

    assert frontmatter["retrievable"] is False


def test_build_artifact_frontmatter_carries_caption_when_the_record_has_one():
    """Issue #168: a caption attached to its figure/table by
    `axial.artifacts.run_artifacts` must reach the persisted artifact note's
    own frontmatter, not be dropped at the vault-write boundary."""
    from axial.vault import build_artifact_frontmatter

    record = {**_ARTIFACT_RECORD, "caption": "A caption describing the figure."}
    frontmatter = build_artifact_frontmatter(record)

    assert frontmatter["caption"] == "A caption describing the figure."


def test_build_artifact_frontmatter_omits_caption_key_when_the_record_has_none():
    """Pre-#168 artifact records (no `caption` key at all) must produce a
    byte-for-byte unchanged frontmatter -- never a `caption: null` key that
    didn't exist before."""
    from axial.vault import build_artifact_frontmatter

    assert "caption" not in _ARTIFACT_RECORD
    frontmatter = build_artifact_frontmatter(_ARTIFACT_RECORD)

    assert "caption" not in frontmatter


def test_write_artifact_note_writes_under_artifacts_dir_named_by_artifact_id(tmp_path):
    from axial.vault import write_artifact_note

    vault_dir = tmp_path / "vault"
    note_path = write_artifact_note(_ARTIFACT_RECORD, vault_dir)

    assert note_path == vault_dir / "artifacts" / f"{_ARTIFACT_RECORD['artifact_id']}.md"
    assert note_path.is_file()


def test_write_artifact_note_does_not_touch_prose_dir(tmp_path):
    from axial.vault import write_artifact_note

    vault_dir = tmp_path / "vault"
    write_artifact_note(_ARTIFACT_RECORD, vault_dir)

    assert not (vault_dir / "prose").exists()


def test_write_artifact_note_rerun_overwrites_in_place_without_duplicating(tmp_path):
    from axial.vault import write_artifact_note

    vault_dir = tmp_path / "vault"

    first_path = write_artifact_note(_ARTIFACT_RECORD, vault_dir)
    second_path = write_artifact_note(_ARTIFACT_RECORD, vault_dir)

    assert first_path == second_path
    artifact_files = [p for p in (vault_dir / "artifacts").iterdir() if p.is_file()]
    assert len(artifact_files) == 1


def test_write_artifact_note_frontmatter_is_yaml_parseable_with_real_boolean(tmp_path):
    from axial.vault import write_artifact_note

    vault_dir = tmp_path / "vault"
    note_path = write_artifact_note(_DISCARD_ARTIFACT_RECORD, vault_dir)

    text = note_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    closing_index = lines.index("---", 1)
    frontmatter = yaml.safe_load("\n".join(lines[1:closing_index]))

    assert frontmatter["retrievable"] is False
    assert isinstance(frontmatter["retrievable"], bool)


# --- orchestration -------------------------------------------------------------


def test_run_vault_write_raises_missing_envelope_error_when_none_stored(tmp_path):
    from axial.vault import MissingEnvelopeError, run_vault_write

    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF-1.4 fake")

    with pytest.raises(MissingEnvelopeError):
        run_vault_write(
            source_path,
            envelopes_dir=tmp_path / "envelopes",
            vault_dir=tmp_path / "vault",
        )


def test_run_vault_write_raises_missing_source_error_for_nonexistent_file(tmp_path):
    from axial.vault import MissingSourceError, run_vault_write

    with pytest.raises(MissingSourceError):
        run_vault_write(
            tmp_path / "does-not-exist.pdf",
            envelopes_dir=tmp_path / "envelopes",
            vault_dir=tmp_path / "vault",
        )


def _write_stored_envelope(envelopes_dir: Path, source_path: Path) -> None:
    from axial.envelope import compute_source_id, envelope_path

    envelopes_dir.mkdir(parents=True, exist_ok=True)
    source_id = compute_source_id(source_path)
    envelope = {**_ENVELOPE, "source_id": source_id}
    envelope_path(source_id, envelopes_dir).write_text(json.dumps(envelope), encoding="utf-8")


def test_run_vault_write_composes_the_tagger_not_the_chunker_directly(monkeypatch, tmp_path):
    """`run_vault_write` must run one thread from source to tagged prose
    notes -- via `axial.tag.run_tag` (which itself reads the on-disk chunk
    artifact) -- rather than reading chunk records itself directly."""
    import axial.vault as vault_mod

    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF-1.4 fake")
    _write_stored_envelope(tmp_path / "envelopes", source_path)

    tagged_records = [dict(_RECORD)]
    calls = []

    def _fake_run_tag(*args, **kwargs):
        calls.append(kwargs)
        return tagged_records

    def _fail_read_chunks(*args, **kwargs):
        raise AssertionError("run_vault_write must not call read_chunks directly")

    monkeypatch.setattr(vault_mod, "run_tag", _fake_run_tag)
    monkeypatch.setattr(vault_mod, "read_chunks", _fail_read_chunks, raising=False)
    # issue #32 slice 02: run_vault_write now also runs the artifact pass;
    # stub it to [] so this prose-composition test stays hermetic (no real
    # docling on the fake PDF) and still asserts exactly one prose note.
    monkeypatch.setattr(vault_mod, "run_artifacts", lambda *a, **k: [])
    # issue #34 slice 02: run_vault_write now also runs the backlink pass;
    # stub it to [] so this test stays hermetic (no real chunking/xref on
    # the fake PDF).
    monkeypatch.setattr(vault_mod, "run_xref", lambda *a, **k: [])

    written = vault_mod.run_vault_write(
        source_path,
        envelopes_dir=tmp_path / "envelopes",
        vault_dir=tmp_path / "vault",
    )

    assert len(calls) == 1
    assert len(written) == 1
    assert written[0].stem == _RECORD["chunk_id"]


def test_run_vault_write_wraps_tag_error_as_a_vault_error(monkeypatch, tmp_path):
    import axial.vault as vault_mod
    from axial.tag import TagError

    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF-1.4 fake")
    _write_stored_envelope(tmp_path / "envelopes", source_path)

    def _failing_run_tag(*args, **kwargs):
        raise TagError("boom")

    monkeypatch.setattr(vault_mod, "run_tag", _failing_run_tag)

    with pytest.raises(vault_mod.VaultError):
        vault_mod.run_vault_write(
            source_path,
            envelopes_dir=tmp_path / "envelopes",
            vault_dir=tmp_path / "vault",
        )


def _arrange_stored_envelope(tmp_path):
    """Shared arrange step for the artifact-routing orchestration tests
    below: a real source file plus a pre-written stored envelope, so
    `run_vault_write` gets past its envelope-existence check."""
    import json as _json

    from axial.envelope import compute_source_id, envelope_path

    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF-1.4 fake")

    envelopes_dir = tmp_path / "envelopes"
    source_id = compute_source_id(source_path)
    env_path = envelope_path(source_id, envelopes_dir)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(_json.dumps(_ENVELOPE), encoding="utf-8")

    return source_path, envelopes_dir


def test_run_vault_write_writes_both_prose_and_artifact_notes(monkeypatch, tmp_path):
    import axial.vault as vault_mod

    source_path, envelopes_dir = _arrange_stored_envelope(tmp_path)
    vault_dir = tmp_path / "vault"

    # run_vault_write now composes run_tag (which reads the on-disk chunk
    # artifact, not a chunker call -- slice 04) for the prose half plus
    # run_artifacts for the artifact half (issue #32 slice 02) plus run_xref
    # for the backlink half (issue #34 slice 02).
    monkeypatch.setattr(vault_mod, "run_tag", lambda *a, **k: [_RECORD])
    monkeypatch.setattr(vault_mod, "run_artifacts", lambda *a, **k: [_ARTIFACT_RECORD])
    monkeypatch.setattr(vault_mod, "run_xref", lambda *a, **k: [])

    written = vault_mod.run_vault_write(
        source_path, envelopes_dir=envelopes_dir, vault_dir=vault_dir
    )

    prose_note = vault_dir / "prose" / f"{_RECORD['chunk_id']}.md"
    artifact_note = vault_dir / "artifacts" / f"{_ARTIFACT_RECORD['artifact_id']}.md"
    assert prose_note.is_file()
    assert artifact_note.is_file()
    assert set(written) == {prose_note, artifact_note}


def test_run_vault_write_wraps_artifacts_error_into_vault_error(monkeypatch, tmp_path):
    import axial.vault as vault_mod
    from axial.artifacts import ArtifactsError

    source_path, envelopes_dir = _arrange_stored_envelope(tmp_path)
    vault_dir = tmp_path / "vault"

    monkeypatch.setattr(vault_mod, "run_tag", lambda *a, **k: [_RECORD])

    def _raise_artifacts_error(*a, **k):
        raise ArtifactsError("boom")

    monkeypatch.setattr(vault_mod, "run_artifacts", _raise_artifacts_error)

    with pytest.raises(vault_mod.VaultError):
        vault_mod.run_vault_write(source_path, envelopes_dir=envelopes_dir, vault_dir=vault_dir)


def test_run_vault_write_wraps_tag_not_in_schema_error_into_vault_error(monkeypatch, tmp_path):
    """Issue #32 slice 02 carry-in: `axial.artifacts.run_artifacts` can now
    raise `axial.tag.TagNotInSchemaError` (a `TagError`, not an
    `ArtifactsError`) directly for an out-of-schema `artifact_role`/`field`
    value -- `run_vault_write` must still wrap it into a `VaultError`
    subclass rather than letting a bare `TagError` escape to the CLI."""
    import axial.vault as vault_mod
    from axial.tag import TagNotInSchemaError

    source_path, envelopes_dir = _arrange_stored_envelope(tmp_path)
    vault_dir = tmp_path / "vault"

    monkeypatch.setattr(vault_mod, "run_tag", lambda *a, **k: [_RECORD])

    def _raise_tag_error(*a, **k):
        raise TagNotInSchemaError("artifact_role", "not-a-real-role")

    monkeypatch.setattr(vault_mod, "run_artifacts", _raise_tag_error)

    with pytest.raises(vault_mod.VaultError):
        vault_mod.run_vault_write(source_path, envelopes_dir=envelopes_dir, vault_dir=vault_dir)


# --- backlinks (issue #34 slice 02 -- xref-backlinks) -------------------------

_XREF_PAIRS = [
    {"chunk_id": "chunk-1", "artifact_id": "art-1"},
    {"chunk_id": "chunk-1", "artifact_id": "art-2"},
    {"chunk_id": "chunk-2", "artifact_id": "art-1"},
]


def test_build_backlink_maps_groups_pairs_by_chunk_and_by_artifact():
    from axial.vault import build_backlink_maps

    chunk_to_artifacts, artifact_to_chunks = build_backlink_maps(_XREF_PAIRS)

    assert chunk_to_artifacts == {"chunk-1": ["art-1", "art-2"], "chunk-2": ["art-1"]}
    assert artifact_to_chunks == {"art-1": ["chunk-1", "chunk-2"], "art-2": ["chunk-1"]}


def test_build_backlink_maps_dedupes_repeated_pairs():
    from axial.vault import build_backlink_maps

    pairs = [{"chunk_id": "chunk-1", "artifact_id": "art-1"}] * 3
    chunk_to_artifacts, artifact_to_chunks = build_backlink_maps(pairs)

    assert chunk_to_artifacts == {"chunk-1": ["art-1"]}
    assert artifact_to_chunks == {"art-1": ["chunk-1"]}


def test_build_backlink_maps_empty_pairs_yields_empty_maps():
    from axial.vault import build_backlink_maps

    chunk_to_artifacts, artifact_to_chunks = build_backlink_maps([])

    assert chunk_to_artifacts == {}
    assert artifact_to_chunks == {}


def test_build_frontmatter_defaults_artifact_refs_to_empty_list():
    from axial.vault import build_frontmatter

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE)

    assert frontmatter["artifact_refs"] == []


def test_build_frontmatter_carries_given_artifact_refs():
    from axial.vault import build_frontmatter

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE, artifact_refs=["art-1", "art-2"])

    assert frontmatter["artifact_refs"] == ["art-1", "art-2"]


def test_build_artifact_frontmatter_defaults_cited_by_to_empty_list():
    from axial.vault import build_artifact_frontmatter

    frontmatter = build_artifact_frontmatter(_ARTIFACT_RECORD)

    assert frontmatter["cited_by"] == []


def test_build_artifact_frontmatter_carries_given_cited_by():
    from axial.vault import build_artifact_frontmatter

    frontmatter = build_artifact_frontmatter(_ARTIFACT_RECORD, cited_by=["chunk-1", "chunk-2"])

    assert frontmatter["cited_by"] == ["chunk-1", "chunk-2"]


def test_write_chunk_note_writes_given_artifact_refs_into_frontmatter(tmp_path):
    from axial.vault import write_chunk_note

    vault_dir = tmp_path / "vault"
    note_path = write_chunk_note(_RECORD, _ENVELOPE, vault_dir, artifact_refs=["art-1"])

    frontmatter, _ = _split_frontmatter_like_outer_test(note_path.read_text(encoding="utf-8"))
    assert frontmatter["artifact_refs"] == ["art-1"]


def test_write_artifact_note_writes_given_cited_by_into_frontmatter(tmp_path):
    from axial.vault import write_artifact_note

    vault_dir = tmp_path / "vault"
    note_path = write_artifact_note(_ARTIFACT_RECORD, vault_dir, cited_by=["chunk-1"])

    frontmatter, _ = _split_frontmatter_like_outer_test(note_path.read_text(encoding="utf-8"))
    assert frontmatter["cited_by"] == ["chunk-1"]


def test_write_artifact_note_persists_caption_when_the_record_has_one(tmp_path):
    """Issue #168: the persisted artifact note (the real §5 stage-5 output)
    must carry an attached caption's text, not silently drop it."""
    from axial.vault import write_artifact_note

    vault_dir = tmp_path / "vault"
    record = {**_ARTIFACT_RECORD, "caption": "A caption describing the figure."}
    note_path = write_artifact_note(record, vault_dir)

    frontmatter, _ = _split_frontmatter_like_outer_test(note_path.read_text(encoding="utf-8"))
    assert frontmatter["caption"] == "A caption describing the figure."


def test_write_artifact_note_omits_caption_key_when_the_record_has_none(tmp_path):
    from axial.vault import write_artifact_note

    vault_dir = tmp_path / "vault"
    note_path = write_artifact_note(_ARTIFACT_RECORD, vault_dir)

    frontmatter, _ = _split_frontmatter_like_outer_test(note_path.read_text(encoding="utf-8"))
    assert "caption" not in frontmatter


def test_run_vault_write_backlink_pass_writes_bidirectional_frontmatter(monkeypatch, tmp_path):
    """`run_vault_write` runs `axial.xref.run_xref` after both prose and
    artifact notes are computed and materializes each pair as bidirectional
    frontmatter (issue #34 slice 02)."""
    import axial.vault as vault_mod

    source_path, envelopes_dir = _arrange_stored_envelope(tmp_path)
    vault_dir = tmp_path / "vault"

    monkeypatch.setattr(vault_mod, "run_tag", lambda *a, **k: [_RECORD])
    monkeypatch.setattr(vault_mod, "run_artifacts", lambda *a, **k: [_ARTIFACT_RECORD])
    monkeypatch.setattr(
        vault_mod,
        "run_xref",
        lambda *a, **k: [
            {"chunk_id": _RECORD["chunk_id"], "artifact_id": _ARTIFACT_RECORD["artifact_id"]}
        ],
    )

    vault_mod.run_vault_write(source_path, envelopes_dir=envelopes_dir, vault_dir=vault_dir)

    prose_note = vault_dir / "prose" / f"{_RECORD['chunk_id']}.md"
    artifact_note = vault_dir / "artifacts" / f"{_ARTIFACT_RECORD['artifact_id']}.md"

    prose_frontmatter, _ = _split_frontmatter_like_outer_test(
        prose_note.read_text(encoding="utf-8")
    )
    artifact_frontmatter, _ = _split_frontmatter_like_outer_test(
        artifact_note.read_text(encoding="utf-8")
    )

    assert prose_frontmatter["artifact_refs"] == [_ARTIFACT_RECORD["artifact_id"]]
    assert artifact_frontmatter["cited_by"] == [_RECORD["chunk_id"]]


def test_run_vault_write_backlink_pass_leaves_unreferenced_notes_with_empty_lists(
    monkeypatch, tmp_path
):
    import axial.vault as vault_mod

    source_path, envelopes_dir = _arrange_stored_envelope(tmp_path)
    vault_dir = tmp_path / "vault"

    monkeypatch.setattr(vault_mod, "run_tag", lambda *a, **k: [_RECORD])
    monkeypatch.setattr(vault_mod, "run_artifacts", lambda *a, **k: [_ARTIFACT_RECORD])
    monkeypatch.setattr(vault_mod, "run_xref", lambda *a, **k: [])

    vault_mod.run_vault_write(source_path, envelopes_dir=envelopes_dir, vault_dir=vault_dir)

    prose_note = vault_dir / "prose" / f"{_RECORD['chunk_id']}.md"
    artifact_note = vault_dir / "artifacts" / f"{_ARTIFACT_RECORD['artifact_id']}.md"

    prose_frontmatter, _ = _split_frontmatter_like_outer_test(
        prose_note.read_text(encoding="utf-8")
    )
    artifact_frontmatter, _ = _split_frontmatter_like_outer_test(
        artifact_note.read_text(encoding="utf-8")
    )

    assert prose_frontmatter["artifact_refs"] == []
    assert artifact_frontmatter["cited_by"] == []


def test_run_vault_write_backlink_pass_rerun_does_not_duplicate(monkeypatch, tmp_path):
    import axial.vault as vault_mod

    source_path, envelopes_dir = _arrange_stored_envelope(tmp_path)
    vault_dir = tmp_path / "vault"

    monkeypatch.setattr(vault_mod, "run_tag", lambda *a, **k: [_RECORD])
    monkeypatch.setattr(vault_mod, "run_artifacts", lambda *a, **k: [_ARTIFACT_RECORD])
    monkeypatch.setattr(
        vault_mod,
        "run_xref",
        lambda *a, **k: [
            {"chunk_id": _RECORD["chunk_id"], "artifact_id": _ARTIFACT_RECORD["artifact_id"]}
        ],
    )

    vault_mod.run_vault_write(source_path, envelopes_dir=envelopes_dir, vault_dir=vault_dir)
    vault_mod.run_vault_write(source_path, envelopes_dir=envelopes_dir, vault_dir=vault_dir)

    prose_note = vault_dir / "prose" / f"{_RECORD['chunk_id']}.md"
    artifact_note = vault_dir / "artifacts" / f"{_ARTIFACT_RECORD['artifact_id']}.md"

    prose_frontmatter, _ = _split_frontmatter_like_outer_test(
        prose_note.read_text(encoding="utf-8")
    )
    artifact_frontmatter, _ = _split_frontmatter_like_outer_test(
        artifact_note.read_text(encoding="utf-8")
    )

    assert prose_frontmatter["artifact_refs"] == [_ARTIFACT_RECORD["artifact_id"]]
    assert artifact_frontmatter["cited_by"] == [_RECORD["chunk_id"]]


def test_run_vault_write_wraps_tag_error_raised_inside_run_xref_into_vault_error(
    monkeypatch, tmp_path
):
    """Live-failure regression (issue #90): the wimmer traceback showed
    `TagNotInSchemaError` escaping raw all the way through
    `run_vault_write -> run_xref -> run_artifacts` -- distinct from
    `test_run_vault_write_wraps_tag_not_in_schema_error_into_vault_error`
    above, which only covers `run_vault_write`'s own DIRECT `run_artifacts`
    call (for artifact notes), not the SEPARATE `run_artifacts` reference
    `axial.xref.run_xref` uses internally (for xref pairs) -- the exact
    module/call site the live failure died inside. `run_vault_write`'s own
    `run_artifacts` call is left succeeding here so execution actually
    reaches the xref pass."""
    import axial.vault as vault_mod
    import axial.xref as xref_mod
    from axial.tag import TagNotInSchemaError

    source_path, envelopes_dir = _arrange_stored_envelope(tmp_path)
    vault_dir = tmp_path / "vault"

    monkeypatch.setattr(vault_mod, "run_tag", lambda *a, **k: [_RECORD])
    monkeypatch.setattr(vault_mod, "run_artifacts", lambda *a, **k: [_ARTIFACT_RECORD])
    # `run_xref` itself is left real (not monkeypatched on vault_mod) so this
    # test exercises the actual composition -- only its OWN internal
    # collaborators (xref_mod's read_chunks/run_artifacts) are stubbed.
    monkeypatch.setattr(xref_mod, "read_chunks", lambda *a, **k: [])

    def _raise_tag_error(*a, **k):
        raise TagNotInSchemaError("field", "")

    monkeypatch.setattr(xref_mod, "run_artifacts", _raise_tag_error)

    with pytest.raises(vault_mod.VaultError):
        vault_mod.run_vault_write(source_path, envelopes_dir=envelopes_dir, vault_dir=vault_dir)


def test_run_vault_write_wraps_xref_error_into_vault_error(monkeypatch, tmp_path):
    import axial.vault as vault_mod
    from axial.xref import XrefError

    source_path, envelopes_dir = _arrange_stored_envelope(tmp_path)
    vault_dir = tmp_path / "vault"

    monkeypatch.setattr(vault_mod, "run_tag", lambda *a, **k: [_RECORD])
    monkeypatch.setattr(vault_mod, "run_artifacts", lambda *a, **k: [_ARTIFACT_RECORD])

    def _raise_xref_error(*a, **k):
        raise XrefError("boom")

    monkeypatch.setattr(vault_mod, "run_xref", _raise_xref_error)

    with pytest.raises(vault_mod.VaultError):
        vault_mod.run_vault_write(source_path, envelopes_dir=envelopes_dir, vault_dir=vault_dir)
