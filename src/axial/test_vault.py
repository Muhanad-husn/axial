"""Inner unit tests for the axial vault module.

`run_vault_write` is retired pending issue #411 (module docstring of
`axial.vault`): the tag pass and the cross-reference pass it used to drive
internally are gone (issue #414, `plans/phase-a-v1/README.md` D4/D5), and
its replacement -- prose notes carrying interrogation answers, plus name
pages -- is issue #411's job, gated behind slices 04/05. The 1217-line test
suite this file used to carry (issue #18 slice 06, tag axis frontmatter,
xref backlinks, per-note fault isolation, note-count reconciliation) tested
exactly that retired pipeline and goes with it; what remains is the new
stubbed-call contract plus a smoke test of the note-writing primitives that
survive for issue #411 to build on.
"""

from __future__ import annotations

import pytest

from axial.vault import (
    VaultError,
    VaultWriteRetiredError,
    build_frontmatter,
    render_note,
    run_vault_write,
)

_ENVELOPE = {"thesis": "Envelope thesis.", "scope": "Envelope scope."}
_SOURCE_META = {
    "author": {"value": "Some Author", "provenance": "title page"},
    "title": {"value": "Some Paper", "provenance": "embedded metadata"},
    "date": "unavailable",
}
_RECORD = {
    "chunk_id": "paper-abc123_1_introduction_001",
    "section": "Introduction",
    "chunk_text": "Some prose.",
}


def test_run_vault_write_always_raises_naming_issue_411():
    with pytest.raises(VaultWriteRetiredError) as exc_info:
        run_vault_write("some/source.pdf")

    assert "#411" in str(exc_info.value)


def test_run_vault_write_retired_error_is_a_vault_error():
    """Existing callers (`axial.ingest.run_ingest`, `axial.drive`) catch the
    base `VaultError` per source and continue -- the stub must still be
    catchable that way, not a bare new exception type."""
    with pytest.raises(VaultError):
        run_vault_write("some/source.pdf")


def test_run_vault_write_accepts_every_existing_caller_kwarg():
    """Every kwarg `axial.ingest`/`axial.drive`/`axial.run` pass survives on
    the stubbed signature -- the point is a clean, typed error, not an
    `AttributeError`/`TypeError` from a caller passing a now-unknown kwarg."""
    with pytest.raises(VaultWriteRetiredError):
        run_vault_write(
            "some/source.pdf",
            client=None,
            envelopes_dir=None,
            vault_dir=None,
            domain_dir="config/domains/syria",
            chunks_dir=None,
            artifacts_dir=None,
            source_meta_dir=None,
        )


def test_build_frontmatter_carries_the_note_identity_and_source_meta_block():
    """The note-writing primitives survive `run_vault_write`'s retirement
    (module docstring) -- `build_frontmatter` still composes chunk_id/
    section/chunk_text plus the five-key source_meta block, with no axis
    block or backlink field (both retired, issue #414 D4/D5)."""
    frontmatter = build_frontmatter(_RECORD, _ENVELOPE, _SOURCE_META)

    assert frontmatter["chunk_id"] == _RECORD["chunk_id"]
    assert frontmatter["section"] == "Introduction"
    assert frontmatter["chunk_text"] == "Some prose."
    assert list(frontmatter["source_meta"]) == ["author", "title", "date", "thesis", "scope"]
    assert "artifact_refs" not in frontmatter
    assert "schema_version" not in frontmatter
    assert "role_in_argument" not in frontmatter


def test_render_note_round_trips_frontmatter_and_body():
    text = render_note({"chunk_id": "c1"}, "Body text.\n")

    assert text.startswith("---\n")
    assert '"chunk_id"' in text
    assert text.endswith("Body text.\n")
