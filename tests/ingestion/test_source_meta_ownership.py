"""Outer acceptance test for issue #278, slice 03 (author/title/date
ownership: the source-metadata record is the sole origin, the envelope drops
them).

Given a source with a source-metadata record (slice 02) carrying
      author/title/date and an envelope carrying thesis/scope
When  the envelope is built and a chunk is written to the vault
Then  the envelope's locked shape is `{source_id, thesis, toc[], scope,
      stated_argument}` with no author, title, or date key, and it still
      validates
And   the vault note's `source_meta` block keeps its five keys `author`,
      `title`, `date`, `thesis`, `scope`
And   `author`, `title` and `date` are composed from the source-metadata
      record, and `thesis`, `scope` from the envelope
And   a source whose printed title differs from its filename slug yields the
      printed title, never the slug
And   a bibliographic field the record marks unavailable is written as
      unavailable, distinguishable from an empty value

Source of truth: specs/PRODUCT.md §7.3 (the locked envelope shape, now
`{source_id, thesis, toc[], scope, stated_argument}`), §7.12 (the persisted
source-metadata record), §7.13 ("the source-metadata record is the sole
origin of author, title and date"; "the envelope no longer carries them";
"the vault's source_meta frontmatter block keeps its five keys ... composed
from two places"), and §8 P0-1d ("the filename is never a source ...
Observable: a source whose filename slug differs from its printed title
yields the printed title, or `unavailable` -- never the slug").

Seam decisions
-----------------------------------------------------------------------
1. **In-process, not a subprocess.** The slice plan names a "pytest
   integration test (stub LLM client for the envelope build; no network)".
   The envelope half calls `axial.envelope.run_envelope` with
   `StubLLMClient` over a monkeypatched `extract`, exactly as
   src/axial/test_envelope.py's own run_envelope tests do; the vault half
   calls `axial.vault.run_vault_write` with the internal tag/artifacts/xref
   passes stubbed out, exactly as src/axial/test_vault.py's own
   run_vault_write tests do. Those three passes are not what this slice
   changed -- the frontmatter composition is.

2. **The filename slug is chosen to be conspicuously wrong.** The source
   file is named `ugur-paramilitarism.pdf` after the real corpus source
   whose title-cased slug (`Ugur Paramilitarism`) is precisely what §7.13
   records as today's fabricated envelope `title`. The record's printed
   title is a different string, so "the printed title, never the slug" is
   an observable assertion rather than a tautology.

3. **The record is written through slice 02's own writer.**
   `axial.intake.build_source_meta`/`write_source_meta`/`source_meta_path`
   produce the on-disk record, so this test can never drift from the shape
   slice 02 actually persists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from axial.intake import (
    NOT_ATTEMPTED,
    PROVENANCE_EMBEDDED_METADATA,
    PROVENANCE_TITLE_PAGE,
    UNAVAILABLE,
    build_source_meta,
    source_meta_path,
    write_source_meta,
)
from axial.llm import StubLLMClient

# The real corpus source §7.13 names: its filename slug title-cases to
# `Ugur Paramilitarism`, which is what the envelope fabricates today, and
# its printed title is nothing like it.
SOURCE_FILENAME = "ugur-paramilitarism.pdf"
FILENAME_SLUG_TITLE = "Ugur Paramilitarism"
PRINTED_TITLE = "Paramilitarism: Mass Violence in the Shadow of the State"
PRINTED_AUTHOR = "Ugur Ümit Üngör"
PRINTED_DATE = "2020"

_TAGGED_RECORD = {
    "chunk_id": "ugur-paramilitarism-abc123_1_introduction_001",
    "section": "Introduction",
    "chunk_text": "The chunk's own prose text.",
    "role_in_argument": "role:claim",
    "schema_version": "1.0.0",
    "field": {"primary": "field:history", "secondary": []},
}


def _tree() -> dict:
    body = (
        "This book argues that paramilitary violence is not a breakdown of "
        "state authority but one of its instruments, delegated outward so "
        "that the state can disclaim what it directs, a claim developed "
        "across the comparative chapters that follow."
    )
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "label": "section_header",
                "children": [{"type": "prose", "order": "1.1", "text": body}],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Conclusion",
                "label": "section_header",
                "children": [{"type": "prose", "order": "2.1", "text": body}],
            },
        ]
    }


def _write_source(tmp_path: Path) -> Path:
    source = tmp_path / SOURCE_FILENAME
    source.write_bytes(b"not a real pdf; only its bytes' hash is read here")
    return source


def _build_envelope(monkeypatch, tmp_path: Path, source: Path) -> dict:
    import axial.envelope as envelope_mod

    monkeypatch.setattr(envelope_mod, "extract", lambda path: _tree())
    return envelope_mod.run_envelope(
        source, client=StubLLMClient(), envelopes_dir=tmp_path / "envelopes"
    )


def _write_record(source: Path, meta_dir: Path, source_id: str, *, date_state) -> None:
    record = build_source_meta(
        source_id,
        source,
        "pdf",
        216,
        None,
        {
            "author": {"value": PRINTED_AUTHOR, "provenance": PROVENANCE_TITLE_PAGE},
            "title": {"value": PRINTED_TITLE, "provenance": PROVENANCE_EMBEDDED_METADATA},
            "date": date_state,
        },
        True,
    )
    write_source_meta(record, source_meta_path(source_id, meta_dir))


def _run_vault_write(monkeypatch, source: Path, tmp_path: Path, meta_dir: Path) -> dict:
    """Run the real `run_vault_write` with the three internal passes it
    composes stubbed out (they are unchanged by this slice), and return the
    written prose note's parsed frontmatter."""
    import axial.vault as vault_mod

    monkeypatch.setattr(vault_mod, "run_tag", lambda *a, **k: [_TAGGED_RECORD])
    monkeypatch.setattr(vault_mod, "run_artifacts", lambda *a, **k: [])
    monkeypatch.setattr(vault_mod, "run_xref", lambda *a, **k: [])

    vault_dir = tmp_path / "vault"
    vault_mod.run_vault_write(
        source,
        envelopes_dir=tmp_path / "envelopes",
        vault_dir=vault_dir,
        source_meta_dir=meta_dir,
    )

    note_path = vault_dir / "prose" / f"{_TAGGED_RECORD['chunk_id']}.md"
    text = note_path.read_text(encoding="utf-8")
    frontmatter_text = text.split("---\n", 2)[1]
    return yaml.safe_load(frontmatter_text)


def test_envelope_locked_shape_no_longer_carries_author_title_or_date(monkeypatch, tmp_path):
    """§7.3/§7.13: the locked shape becomes `{source_id, thesis, toc[],
    scope, stated_argument}`, and it still validates."""
    from axial.envelope import validate_envelope_fields

    source = _write_source(tmp_path)
    envelope = _build_envelope(monkeypatch, tmp_path, source)

    assert set(envelope) == {"source_id", "thesis", "toc", "scope", "stated_argument"}, (
        f"expected the envelope's locked shape to be exactly "
        f"{{source_id, thesis, toc, scope, stated_argument}} (PRD §7.3, "
        f"§7.13 'the envelope no longer carries them'), got keys "
        f"{sorted(envelope)}"
    )
    validate_envelope_fields(envelope)

    on_disk = json.loads(
        (tmp_path / "envelopes" / f"{envelope['source_id']}.json").read_text(encoding="utf-8")
    )
    assert on_disk == envelope

    # The fabricated filename-slug title is gone from every value, not just
    # from the `title` key (§7.13: "the filename is never a source").
    assert FILENAME_SLUG_TITLE not in json.dumps(envelope)


def test_vault_source_meta_composes_the_record_and_the_envelope(monkeypatch, tmp_path):
    """§7.13: the five-key block survives; author/title/date come from the
    record, thesis/scope from the envelope, and the printed title wins over
    the filename slug (P0-1d)."""
    from axial.envelope import compute_source_id

    source = _write_source(tmp_path)
    envelope = _build_envelope(monkeypatch, tmp_path, source)
    meta_dir = tmp_path / "source_meta"
    _write_record(
        source,
        meta_dir,
        compute_source_id(source),
        date_state={"value": PRINTED_DATE, "provenance": PROVENANCE_TITLE_PAGE},
    )

    frontmatter = _run_vault_write(monkeypatch, source, tmp_path, meta_dir)
    source_meta = frontmatter["source_meta"]

    assert list(source_meta) == ["author", "title", "date", "thesis", "scope"], (
        f"expected the note's `source_meta` block to keep its five keys "
        f"(§7.13: 'no downstream reader or note shape changes'), got "
        f"{list(source_meta)}"
    )
    assert source_meta["author"] == PRINTED_AUTHOR
    assert source_meta["title"] == PRINTED_TITLE
    assert source_meta["date"] == PRINTED_DATE
    assert source_meta["thesis"] == envelope["thesis"]
    assert source_meta["scope"] == envelope["scope"]

    assert source_meta["title"] != FILENAME_SLUG_TITLE, (
        "P0-1d: a source whose filename slug differs from its printed title "
        "must yield the printed title, never the slug"
    )


def test_an_unavailable_bibliographic_field_is_written_as_unavailable(monkeypatch, tmp_path):
    """§7.13: unavailable is recorded as unavailable in the note -- never as
    an empty value indistinguishable from an unattempted read."""
    from axial.envelope import compute_source_id

    source = _write_source(tmp_path)
    _build_envelope(monkeypatch, tmp_path, source)
    meta_dir = tmp_path / "source_meta"
    _write_record(source, meta_dir, compute_source_id(source), date_state=UNAVAILABLE)

    source_meta = _run_vault_write(monkeypatch, source, tmp_path, meta_dir)["source_meta"]

    assert source_meta["date"] == UNAVAILABLE, (
        f"expected an unavailable `date` to be written as {UNAVAILABLE!r}, "
        f"distinguishable from an empty/unattempted value, got "
        f"{source_meta['date']!r}"
    )
    assert source_meta["date"] not in (None, ""), (
        "§7.13: today's failure mode is exactly that the hard case and the "
        "easy case produce identical output"
    )
    assert source_meta["date"] != NOT_ATTEMPTED


def test_a_source_with_no_record_fails_loudly_rather_than_emitting_nulls(monkeypatch, tmp_path):
    """§7.13: the record is the sole origin. With no record on disk the pass
    must say so, never silently re-emit the nulls this slice retires."""
    import axial.vault as vault_mod

    source = _write_source(tmp_path)
    _build_envelope(monkeypatch, tmp_path, source)

    monkeypatch.setattr(vault_mod, "run_tag", lambda *a, **k: [_TAGGED_RECORD])
    monkeypatch.setattr(vault_mod, "run_artifacts", lambda *a, **k: [])
    monkeypatch.setattr(vault_mod, "run_xref", lambda *a, **k: [])

    with pytest.raises(vault_mod.MissingSourceMetaError):
        vault_mod.run_vault_write(
            source,
            envelopes_dir=tmp_path / "envelopes",
            vault_dir=tmp_path / "vault",
            source_meta_dir=tmp_path / "empty_source_meta",
        )
