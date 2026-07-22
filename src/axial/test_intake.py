"""Inner unit tests for the axial intake module (issue #13, slice 01)."""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "intake"

TEXT_LAYER_PDF = FIXTURES_DIR / "text_layer.pdf"
NO_TEXT_LAYER_PDF = FIXTURES_DIR / "no_text_layer.pdf"
TEXT_DOCX = FIXTURES_DIR / "text.docx"
UNSUPPORTED_TXT = FIXTURES_DIR / "unsupported.txt"
UNSUPPORTED_PNG = FIXTURES_DIR / "unsupported.png"


def test_check_extension_accepts_pdf_case_insensitively():
    from axial.intake import check_extension

    check_extension(Path("some/file.PDF"))
    check_extension(Path("some/file.pdf"))


def test_check_extension_accepts_docx_case_insensitively():
    from axial.intake import check_extension

    check_extension(Path("some/file.DOCX"))
    check_extension(Path("some/file.docx"))


def test_check_extension_rejects_unsupported_extension_naming_it():
    from axial.intake import IntakeError, check_extension

    with pytest.raises(IntakeError) as exc_info:
        check_extension(Path("some/file.txt"))

    assert ".txt" in str(exc_info.value)


def test_has_text_layer_true_for_text_pdf():
    from axial.intake import has_text_layer

    assert has_text_layer(TEXT_LAYER_PDF, "pdf") is True


def test_has_text_layer_false_for_no_text_pdf():
    from axial.intake import has_text_layer

    assert has_text_layer(NO_TEXT_LAYER_PDF, "pdf") is False


def test_has_text_layer_true_for_docx_with_body_text():
    from axial.intake import has_text_layer

    assert has_text_layer(TEXT_DOCX, "docx") is True


def test_intake_missing_path_raises_intake_error():
    from axial.intake import IntakeError, intake

    with pytest.raises(IntakeError):
        intake(FIXTURES_DIR / "no-such-file.pdf")


def test_intake_returns_source_metadata_stub_for_text_pdf():
    from axial.intake import intake

    source = intake(TEXT_LAYER_PDF)

    assert source.path == TEXT_LAYER_PDF
    assert source.format == "pdf"
    assert source.text_layer_ok is True


def test_intake_returns_source_metadata_stub_for_text_docx():
    from axial.intake import intake

    source = intake(TEXT_DOCX)

    assert source.path == TEXT_DOCX
    assert source.format == "docx"
    assert source.text_layer_ok is True


def test_intake_rejects_no_text_layer_pdf():
    from axial.intake import IntakeError, intake

    with pytest.raises(IntakeError) as exc_info:
        intake(NO_TEXT_LAYER_PDF)

    message = str(exc_info.value).lower()
    assert "text layer" in message or "no text" in message


def test_intake_rejects_unsupported_extension():
    from axial.intake import IntakeError, intake

    with pytest.raises(IntakeError) as exc_info:
        intake(UNSUPPORTED_PNG)

    assert ".png" in str(exc_info.value)


# =============================================================================
# Holdings-completeness check wiring (issue #284, §7.11 / §8 P0-1b): how
# `intake()` attaches `Source.holdings_flag`. The check's own cleaning,
# prompt and flag shape live in `axial.holdings` and are tested in
# `test_holdings.py`.
# =============================================================================


class _StubHoldingsClient:
    def __init__(self, verdict: str = "complete"):
        self.verdict = verdict
        self.calls = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        import json

        self.calls += 1
        return json.dumps(
            {
                "document_kind": "book",
                "claimed_extent": None,
                "claimed_extent_stated_by": None,
                "verdict": self.verdict,
                "reason": "stub",
            }
        )


def test_pdf_page_texts_returns_one_string_per_physical_page():
    from axial.intake import _pdf_page_texts

    page_texts = _pdf_page_texts(TEXT_LAYER_PDF)

    assert isinstance(page_texts, list)
    assert len(page_texts) == 1
    assert "text layer" in page_texts[0].lower()


def test_source_defaults_holdings_flag_to_none():
    from axial.intake import Source

    source = Source(path=TEXT_LAYER_PDF, format="pdf", text_layer_ok=True)

    assert source.holdings_flag is None


def test_intake_populates_holdings_flag_for_pdf_source():
    from axial.intake import intake

    client = _StubHoldingsClient(verdict="partial")

    source = intake(TEXT_LAYER_PDF, client=client)

    assert source.format == "pdf"
    assert source.text_layer_ok is True
    assert client.calls == 1
    assert source.holdings_flag["source"] == TEXT_LAYER_PDF.name
    assert source.holdings_flag["observed_pages"] == 1


def test_intake_checks_a_docx_source_too_with_no_page_count():
    """§7.11 retires the blanket DOCX exemption: the check runs, and the
    absent page count is unobtainable evidence, not a flag."""
    from axial.intake import intake

    client = _StubHoldingsClient()

    source = intake(TEXT_DOCX, client=client)

    assert source.format == "docx"
    assert client.calls == 1
    assert source.holdings_flag is None


def test_intake_without_a_client_makes_no_model_call_and_raises_no_flag():
    """The judgment is a model call, so it runs only for a caller that
    supplies a client -- `extract()` validates a file without paying for a
    judgment it never reads."""
    from axial.intake import intake

    source = intake(TEXT_LAYER_PDF)

    assert source.text_layer_ok is True
    assert source.holdings_flag is None


# =============================================================================
# Persisted source-metadata record (issue #285, §7.12/§7.13, §8 P0-1c/P0-1d).
# Outer, end-to-end coverage lives in
# tests/ingestion/test_source_metadata_record.py; these are pure/unit-level
# checks of the individual helpers plus a couple of shape-level integration
# checks against the existing shared fixtures. `axial.intake.SOURCE_META_DIR`
# is redirected to an isolated tmp dir for every test in this file by the
# autouse `_isolate_checkpoint_dirs` fixture in src/axial/conftest.py, so a
# call to `intake()` below with no explicit `source_meta_dir` never touches
# the real repo's `data/source_meta/`.
# =============================================================================


def test_source_meta_path_is_keyed_by_source_id_under_the_given_dir(tmp_path):
    from axial.intake import source_meta_path

    path = source_meta_path("some-source-abc123456789", tmp_path)

    assert path == tmp_path / "some-source-abc123456789.json"


class TestPlausibleMetadataValue:
    def test_passes_through_a_real_value(self):
        from axial.intake import _plausible_metadata_value

        assert _plausible_metadata_value("Jane Q. Historian", "pdfTeX", "LaTeX") == (
            "Jane Q. Historian"
        )

    def test_rejects_empty_and_whitespace_only(self):
        from axial.intake import _plausible_metadata_value

        assert _plausible_metadata_value("") is None
        assert _plausible_metadata_value("   ") is None
        assert _plausible_metadata_value(None) is None

    def test_rejects_a_value_equal_to_a_junk_candidate_case_and_whitespace_insensitively(self):
        from axial.intake import _plausible_metadata_value

        assert _plausible_metadata_value("Adobe Acrobat Pro DC", "Adobe Acrobat Pro DC") is None
        assert (
            _plausible_metadata_value("  adobe   acrobat pro dc  ", "Adobe Acrobat Pro DC") is None
        )

    def test_only_rejects_an_exact_junk_match_not_a_mere_substring(self):
        from axial.intake import _plausible_metadata_value

        # A real author whose name happens to contain a producer-ish
        # substring must still pass through -- the comparison is exact,
        # never a substring/fuzzy match.
        assert _plausible_metadata_value("Adobe Acrobat Historian", "Adobe Acrobat Pro DC") == (
            "Adobe Acrobat Historian"
        )


class TestCleanGuardsNonStringPypdfSentinels:
    """§307 finding 1: pypdf can hand back a raw `NullObject` (or any other
    non-string sentinel) for a malformed metadata field instead of a plain
    `None`. `_clean` -- and therefore `_plausible_metadata_value`, which
    every embedded-metadata read routes through -- must treat that as
    absent rather than crash on `.split()`."""

    def test_a_null_object_is_treated_as_absent_not_a_crash(self):
        from pypdf.generic import NullObject

        from axial.intake import _clean

        assert _clean(NullObject()) is None

    def test_plausible_metadata_value_survives_a_null_object_value(self):
        from pypdf.generic import NullObject

        from axial.intake import _plausible_metadata_value

        assert _plausible_metadata_value(NullObject()) is None

    def test_plausible_metadata_value_survives_a_null_object_junk_candidate(self):
        from pypdf.generic import NullObject

        from axial.intake import _plausible_metadata_value

        # A real value must still pass through even when a junk candidate
        # (producer/creator) is itself an unreadable sentinel.
        assert _plausible_metadata_value("Jane Q. Historian", NullObject()) == ("Jane Q. Historian")


class TestResolveBibliographicValue:
    """§307 findings 2/3: the title-page cross-check that replaces the
    retired deterministic fallback (`_resolve_bibliographic_value`)."""

    def test_no_embedded_value_falls_back_to_the_title_page_reading(self):
        from axial.intake import PROVENANCE_TITLE_PAGE, _resolve_bibliographic_value

        resolved = _resolve_bibliographic_value(None, "Sinisa Malesevic", None)

        assert resolved == {"value": "Sinisa Malesevic", "provenance": PROVENANCE_TITLE_PAGE}

    def test_no_embedded_value_and_no_title_page_reading_is_unavailable(self):
        from axial.intake import UNAVAILABLE, _resolve_bibliographic_value

        assert _resolve_bibliographic_value(None, None, None) == UNAVAILABLE

    def test_an_embedded_value_the_model_flags_as_a_mismatch_is_unavailable(self):
        """The required outcome for a recycled-metadata PDF (#285 finding 2,
        `heydemann-war-institutions-social-change`): a wrong value with
        provenance is worse than an honest blank."""
        from axial.intake import UNAVAILABLE, _resolve_bibliographic_value

        resolved = _resolve_bibliographic_value("Michael Hanby", "Steven Heydemann", False)

        assert resolved == UNAVAILABLE

    def test_an_embedded_value_the_model_confirms_stands(self):
        from axial.intake import PROVENANCE_EMBEDDED_METADATA, _resolve_bibliographic_value

        resolved = _resolve_bibliographic_value("Jane Q. Historian", "Jane Q. Historian", True)

        assert resolved == {
            "value": "Jane Q. Historian",
            "provenance": PROVENANCE_EMBEDDED_METADATA,
        }

    def test_an_embedded_value_with_no_matches_verdict_still_stands(self):
        """A `None` match (no comparison was made -- e.g. an older-shaped
        canned response in a test, or a model that skipped the judgment)
        trusts the embedded value: only an explicit `false` downgrades it."""
        from axial.intake import PROVENANCE_EMBEDDED_METADATA, _resolve_bibliographic_value

        resolved = _resolve_bibliographic_value("Jane Q. Historian", None, None)

        assert resolved == {
            "value": "Jane Q. Historian",
            "provenance": PROVENANCE_EMBEDDED_METADATA,
        }


class TestBibliographicField:
    def test_a_found_value_carries_its_provenance(self):
        from axial.intake import _bibliographic_field

        assert _bibliographic_field("Jane Q. Historian", "embedded metadata") == {
            "value": "Jane Q. Historian",
            "provenance": "embedded metadata",
        }

    def test_no_value_is_the_unavailable_sentinel(self):
        from axial.intake import UNAVAILABLE, _bibliographic_field

        assert _bibliographic_field(None, "embedded metadata") == UNAVAILABLE


class TestResolveHoldingsFlag:
    def test_a_supplied_client_always_wins_even_when_it_computed_none(self, tmp_path):
        from axial.intake import _resolve_holdings_flag

        meta_path = tmp_path / "some-id.json"
        meta_path.write_text('{"holdings_flag": {"document_kind": "book"}}', encoding="utf-8")

        resolved = _resolve_holdings_flag(None, object(), meta_path)

        assert resolved is None

    def test_no_client_and_no_existing_record_resolves_to_none(self, tmp_path):
        from axial.intake import _resolve_holdings_flag

        resolved = _resolve_holdings_flag(None, None, tmp_path / "absent.json")

        assert resolved is None

    def test_no_client_preserves_the_existing_records_flag(self, tmp_path):
        from axial.intake import _resolve_holdings_flag

        meta_path = tmp_path / "some-id.json"
        meta_path.write_text('{"holdings_flag": {"document_kind": "book"}}', encoding="utf-8")

        resolved = _resolve_holdings_flag(None, None, meta_path)

        assert resolved == {"document_kind": "book"}


class TestResolveBibliographicFields:
    """`author`/`title`/`date`/`publisher` preserved the same way as
    `holdings_flag` (`_resolve_recorded_field`, generalized): a client-less
    call (every `extract()` validation call) must never regress an
    already-recorded, model-informed answer back to a client-less-only
    guess."""

    def test_no_client_and_no_existing_record_uses_the_computed_fields(self, tmp_path):
        from axial.intake import UNAVAILABLE, _resolve_bibliographic_fields

        computed = {
            "author": UNAVAILABLE,
            "title": {"value": "A Title", "provenance": "embedded metadata"},
            "date": UNAVAILABLE,
            "publisher": UNAVAILABLE,
        }

        resolved = _resolve_bibliographic_fields(computed, None, tmp_path / "absent.json")

        assert resolved == computed

    def test_no_client_preserves_the_existing_records_fields(self, tmp_path):
        import json

        from axial.intake import _resolve_bibliographic_fields

        meta_path = tmp_path / "some-id.json"
        meta_path.write_text(
            json.dumps(
                {
                    "author": {"value": "Steven Heydemann", "provenance": "title page"},
                    "title": {
                        "value": "War, Institutions, and Social Change",
                        "provenance": "title page",
                    },
                    "date": "unavailable",
                    "publisher": {"value": "A Publisher", "provenance": "open_library"},
                }
            ),
            encoding="utf-8",
        )
        computed = {
            "author": "unavailable",
            "title": "unavailable",
            "date": "unavailable",
            "publisher": "unavailable",
        }

        resolved = _resolve_bibliographic_fields(computed, None, meta_path)

        assert resolved["author"] == {"value": "Steven Heydemann", "provenance": "title page"}
        assert resolved["title"] == {
            "value": "War, Institutions, and Social Change",
            "provenance": "title page",
        }
        assert resolved["publisher"] == {"value": "A Publisher", "provenance": "open_library"}

    def test_a_supplied_client_always_overwrites_with_the_computed_fields(self, tmp_path):
        import json

        from axial.intake import _resolve_bibliographic_fields

        meta_path = tmp_path / "some-id.json"
        meta_path.write_text(
            json.dumps(
                {
                    "author": {"value": "Stale Prior Answer", "provenance": "title page"},
                    "title": "unavailable",
                    "date": "unavailable",
                    "publisher": "unavailable",
                }
            ),
            encoding="utf-8",
        )
        computed = {
            "author": "unavailable",
            "title": "unavailable",
            "date": "unavailable",
            "publisher": "unavailable",
        }

        resolved = _resolve_bibliographic_fields(computed, object(), meta_path)

        assert resolved == computed


def test_intake_writes_a_source_meta_record_for_a_pdf(tmp_path):
    import json

    from axial.envelope import compute_source_id
    from axial.intake import intake, source_meta_path

    intake(TEXT_LAYER_PDF, source_meta_dir=tmp_path)

    record_path = source_meta_path(compute_source_id(TEXT_LAYER_PDF), tmp_path)
    assert record_path.exists()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["source_id"] == compute_source_id(TEXT_LAYER_PDF)
    assert isinstance(record["physical_page_count"], int)
    assert "holdings_flag" in record
    for field in ("author", "title", "date"):
        assert field in record


def test_intake_writes_a_source_meta_record_for_a_docx_with_no_page_count(tmp_path):
    import json

    from axial.envelope import compute_source_id
    from axial.intake import NOT_ATTEMPTED, intake, source_meta_path

    intake(TEXT_DOCX, source_meta_dir=tmp_path)

    record_path = source_meta_path(compute_source_id(TEXT_DOCX), tmp_path)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["physical_page_count"] is None
    # No mechanism exists for a DOCX's publication date in this slice.
    assert record["date"] == NOT_ATTEMPTED


def test_intake_default_source_meta_dir_is_isolated_by_the_autouse_fixture(tmp_path):
    """Sanity check on this file's own isolation seam: `SOURCE_META_DIR` is
    redirected away from the real repo `data/source_meta/` for every test
    here, so a call with no explicit `source_meta_dir` still lands under an
    isolated tmp location, never the real cwd-relative default."""
    import axial.intake as intake_mod

    REPO_DEFAULT = Path("data/source_meta")
    assert intake_mod.SOURCE_META_DIR != REPO_DEFAULT


# =============================================================================
# The once-per-source judgment marker (issue #303, §7.12): the record says
# whether the §7.11/§7.13 model judgment has been made, so the ingest path
# pays for it once and reads it back afterwards.
# =============================================================================


class TestHoldingsJudged:
    def test_a_record_marked_checked_is_judged(self, tmp_path):
        from axial.intake import HOLDINGS_CHECKED, holdings_judged

        (tmp_path / "some-id.json").write_text(
            json.dumps({HOLDINGS_CHECKED: True}), encoding="utf-8"
        )

        assert holdings_judged("some-id", tmp_path) is True

    def test_a_record_from_before_the_marker_existed_is_not_judged(self, tmp_path):
        """A record written before this slice carries a `holdings_flag` of
        null and no marker at all. That is "never judged", not "judged
        complete" -- the whole distinction the marker exists to make."""
        from axial.intake import holdings_judged

        (tmp_path / "some-id.json").write_text(
            json.dumps({"holdings_flag": None}), encoding="utf-8"
        )

        assert holdings_judged("some-id", tmp_path) is False

    def test_no_record_is_not_judged(self, tmp_path):
        from axial.intake import holdings_judged

        assert holdings_judged("some-id", tmp_path) is False

    def test_an_unreadable_record_is_not_judged(self, tmp_path):
        from axial.intake import holdings_judged

        (tmp_path / "some-id.json").write_text("{not json", encoding="utf-8")

        assert holdings_judged("some-id", tmp_path) is False


def test_intake_with_a_client_records_the_judgment_as_made(tmp_path):
    from axial.intake import HOLDINGS_CHECKED, intake, source_meta_path
    from axial.envelope import compute_source_id

    intake(TEXT_LAYER_PDF, client=_StubHoldingsClient(), source_meta_dir=tmp_path)

    record_path = source_meta_path(compute_source_id(TEXT_LAYER_PDF), tmp_path)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record[HOLDINGS_CHECKED] is True


def test_intake_without_a_client_records_the_judgment_as_not_made(tmp_path):
    from axial.intake import HOLDINGS_CHECKED, intake, source_meta_path
    from axial.envelope import compute_source_id

    intake(TEXT_LAYER_PDF, source_meta_dir=tmp_path)

    record_path = source_meta_path(compute_source_id(TEXT_LAYER_PDF), tmp_path)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record[HOLDINGS_CHECKED] is False


def test_a_client_less_intake_never_unmarks_an_existing_judgment(tmp_path):
    """`extract()` re-validates a source on every pass. A pass that does not
    re-run the judgment must not erase the record of one already made, or
    the source would be re-judged forever (§7.12, the same preservation rule
    `holdings_flag` follows)."""
    from axial.intake import HOLDINGS_CHECKED, intake, source_meta_path
    from axial.envelope import compute_source_id

    intake(TEXT_LAYER_PDF, client=_StubHoldingsClient(), source_meta_dir=tmp_path)
    intake(TEXT_LAYER_PDF, source_meta_dir=tmp_path)

    record_path = source_meta_path(compute_source_id(TEXT_LAYER_PDF), tmp_path)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record[HOLDINGS_CHECKED] is True


def test_intake_with_a_client_that_cannot_answer_records_no_judgment(tmp_path):
    """A model call that fails is not a judgment: caching it as one would
    leave the source unchecked forever (issue #303)."""
    from axial.llm import LLMError
    from axial.intake import HOLDINGS_CHECKED, intake, source_meta_path
    from axial.envelope import compute_source_id

    class _FailingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            raise LLMError("provider unavailable")

    intake(TEXT_LAYER_PDF, client=_FailingClient(), source_meta_dir=tmp_path)

    record_path = source_meta_path(compute_source_id(TEXT_LAYER_PDF), tmp_path)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record[HOLDINGS_CHECKED] is False


# =============================================================================
# Identifier capture + lookup merge (issue #326, §7.12/§7.13): the same-work
# identity guard and the publisher/identifier field wiring. Full end-to-end
# coverage (intake() over a fixture PDF, a mocked lookup transport) lives in
# tests/ingestion/test_identifier_metadata.py; these are unit-level checks of
# the guard and the merge helper in isolation.
# =============================================================================


class TestAuthorsPlausiblyOverlap:
    def test_no_known_author_passes_by_default(self):
        """Nothing to contradict -- the real gap this slice fixes
        (`ayubi-over-stating-the-arab-state`'s `None` title) has no prior
        author reading to compare against either."""
        from axial.intake import authors_plausibly_overlap

        assert authors_plausibly_overlap(None, "Nazih N. M. Ayubi") is True

    def test_a_known_author_with_no_fetched_author_fails(self):
        from axial.intake import authors_plausibly_overlap

        assert authors_plausibly_overlap("Michael Mann", None) is False

    def test_diacritics_and_last_first_order_are_treated_as_a_match(self):
        """The spike's own false-mismatch case: `Malesevic, Sinisa` vs
        `Siniša Malešević`."""
        from axial.intake import authors_plausibly_overlap

        assert authors_plausibly_overlap("Malesevic, Sinisa", "Siniša Malešević") is True

    def test_a_fetch_naming_a_genuinely_different_person_fails(self):
        """What this guard actually catches: a single, unambiguous
        identifier whose fetch names an entirely different person (a
        mistyped or recycled identifier) -- not a same-author wrong-volume
        mismatch, see the next test."""
        from axial.intake import authors_plausibly_overlap

        assert authors_plausibly_overlap("Michael Mann", "A Totally Different Editor") is False

    def test_the_real_mann_volumes_pair_passes_the_guard_alone_does_not_catch_it(self):
        """Post-review correction (issue #326): the reviewer measured, via a
        live Open Library call, that the wrong-volume ISBN shared by
        `mann-sources-of-social-power-v1`/`v3`/`v4` resolves to author
        `"Mann, Michael"` -- which plausibly overlaps each volume's own
        known author `"Michael Mann"`. This function correctly returns
        `True` for that pair: an author-overlap guard structurally cannot
        separate same-author volumes from each other. What actually
        protects this source is ambiguity abstention on the capture itself
        (`identifiers.capture`'s `abstained` shape, applied in
        `_merge_identifier_fields` before any lookup runs) -- see
        `tests/ingestion/test_identifier_metadata.py`'s own ambiguity test
        for the end-to-end proof."""
        from axial.intake import authors_plausibly_overlap

        assert authors_plausibly_overlap("Michael Mann", "Mann, Michael") is True


class TestMergeIdentifierFields:
    def _biblio(self, author=None):
        from axial.intake import UNAVAILABLE as _UNAVAILABLE

        return {
            "author": author if author is not None else _UNAVAILABLE,
            "title": _UNAVAILABLE,
            "date": _UNAVAILABLE,
        }

    def test_no_identifier_leaves_fields_unchanged_and_publisher_unavailable_for_pdf(self):
        from axial.intake import UNAVAILABLE, _merge_identifier_fields

        biblio = self._biblio()
        merged = _merge_identifier_fields(biblio, None, "pdf", None, None)

        assert merged["author"] == UNAVAILABLE
        assert merged["title"] == UNAVAILABLE
        assert merged["date"] == UNAVAILABLE
        assert merged["publisher"] == UNAVAILABLE

    def test_no_identifier_scan_for_docx_leaves_publisher_not_attempted(self):
        from axial.intake import NOT_ATTEMPTED, _merge_identifier_fields

        merged = _merge_identifier_fields(self._biblio(), None, "docx", None, None)

        assert merged["publisher"] == NOT_ATTEMPTED

    def test_an_unresolved_lookup_leaves_the_four_fields_unchanged(self, monkeypatch, tmp_path):
        import axial.bib_lookup as bib_lookup_mod
        from axial.intake import UNAVAILABLE, _merge_identifier_fields

        monkeypatch.setattr(
            bib_lookup_mod,
            "resolve_isbn",
            lambda value, **kwargs: {"resolved": False, "error": None},
        )

        identifier = {"type": "isbn", "value": "9780262033848"}
        merged = _merge_identifier_fields(self._biblio(), identifier, "pdf", None, tmp_path)

        assert merged["author"] == UNAVAILABLE
        assert merged["title"] == UNAVAILABLE
        assert merged["publisher"] == UNAVAILABLE

    def test_a_passing_guard_overrides_all_four_fields_with_provenance(self, monkeypatch, tmp_path):
        import axial.bib_lookup as bib_lookup_mod
        from axial.intake import _merge_identifier_fields

        def _resolved(value, **kwargs):
            return {
                "resolved": True,
                "title": "A Fetched Title",
                "author": "Jane Q. Historian",
                "date": "1985",
                "publisher": "A Publisher",
                "source": "open_library",
            }

        monkeypatch.setattr(bib_lookup_mod, "resolve_isbn", _resolved)

        biblio = self._biblio(
            author={"value": "Jane Q. Historian", "provenance": "embedded metadata"}
        )
        identifier = {"type": "isbn", "value": "9780262033848"}
        merged = _merge_identifier_fields(biblio, identifier, "pdf", None, tmp_path)

        assert merged["title"] == {"value": "A Fetched Title", "provenance": "open_library"}
        assert merged["author"] == {"value": "Jane Q. Historian", "provenance": "open_library"}
        assert merged["date"] == {"value": "1985", "provenance": "open_library"}
        assert merged["publisher"] == {"value": "A Publisher", "provenance": "open_library"}

    def test_a_failing_guard_leaves_the_four_fields_unchanged_but_lookup_still_ran(
        self, monkeypatch, tmp_path
    ):
        """A single, unambiguous identifier whose fetch names an entirely
        different person -- not the Mann-volumes case (a same-author
        wrong-volume mismatch, which this guard does NOT catch; see
        `test_an_ambiguous_identifier_never_reaches_the_lookup_at_all`
        below for what actually protects that one)."""
        import axial.bib_lookup as bib_lookup_mod
        from axial.intake import _merge_identifier_fields

        def _resolved(value, **kwargs):
            return {
                "resolved": True,
                "title": "An Entirely Unrelated Book",
                "author": "A Completely Different Person",
                "date": "2001",
                "publisher": "Some Other Press",
                "source": "open_library",
            }

        monkeypatch.setattr(bib_lookup_mod, "resolve_isbn", _resolved)

        biblio = self._biblio(
            author={"value": "Jane Q. Historian", "provenance": "embedded metadata"}
        )
        identifier = {"type": "isbn", "value": "9780000000000"}
        merged = _merge_identifier_fields(biblio, identifier, "pdf", None, tmp_path)

        assert merged["author"] == {"value": "Jane Q. Historian", "provenance": "embedded metadata"}

    def test_an_ambiguous_identifier_never_reaches_the_lookup_at_all(self, monkeypatch, tmp_path):
        """The real Mann-volumes protection: an `abstained` capture (more
        than one distinct identifier found) short-circuits before
        `_lookup_identifier` is ever called -- proven here by monkeypatching
        `resolve_isbn` to raise if it is invoked at all."""
        import axial.bib_lookup as bib_lookup_mod
        from axial.intake import UNAVAILABLE, _merge_identifier_fields

        def _must_not_be_called(value, **kwargs):
            raise AssertionError("resolve_isbn must not be called for an ambiguous identifier")

        monkeypatch.setattr(bib_lookup_mod, "resolve_isbn", _must_not_be_called)

        biblio = self._biblio(author={"value": "Michael Mann", "provenance": "embedded metadata"})
        identifier = {
            "type": "isbn",
            "value": None,
            "abstained": True,
            "candidates": ["9780262033848", "9781107028654"],
        }
        merged = _merge_identifier_fields(biblio, identifier, "pdf", None, tmp_path)

        assert merged["author"] == {"value": "Michael Mann", "provenance": "embedded metadata"}
        assert merged["publisher"] == UNAVAILABLE
