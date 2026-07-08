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
    notes -- via `axial.tag.run_tag` (which itself runs the chunker
    internally) -- rather than calling `axial.chunk.run_chunk` directly."""
    import axial.vault as vault_mod

    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF-1.4 fake")
    _write_stored_envelope(tmp_path / "envelopes", source_path)

    tagged_records = [dict(_RECORD)]
    calls = []

    def _fake_run_tag(*args, **kwargs):
        calls.append(kwargs)
        return tagged_records

    def _fail_run_chunk(*args, **kwargs):
        raise AssertionError("run_vault_write must not call run_chunk directly")

    monkeypatch.setattr(vault_mod, "run_tag", _fake_run_tag)
    monkeypatch.setattr(vault_mod, "run_chunk", _fail_run_chunk, raising=False)

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
