"""Inner unit tests for the axial vault module (issue #18 slice 06 -- vault
write)."""

from __future__ import annotations

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
    "text": "This is the chunk's own prose text.",
}


# --- frontmatter assembly ----------------------------------------------------


def test_build_frontmatter_carries_chunk_id_section_chunk_text():
    from axial.vault import build_frontmatter

    frontmatter = build_frontmatter(_RECORD, _ENVELOPE)

    assert frontmatter["chunk_id"] == _RECORD["chunk_id"]
    assert frontmatter["section"] == _RECORD["section"]
    assert frontmatter["chunk_text"] == _RECORD["text"]


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
        "chunk_id": "paper-abc123_1_introduction_001",
        "section": "Introduction",
        "text": "First line of the chunk.\n---\nSecond line after a bare rule.",
    }

    frontmatter = build_frontmatter(record, _ENVELOPE)
    note_text = render_note(frontmatter, record["text"])

    parsed_frontmatter, body = _split_frontmatter_like_outer_test(note_text)

    assert parsed_frontmatter == frontmatter
    assert parsed_frontmatter["chunk_text"] == record["text"]
    assert record["text"] in body


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
