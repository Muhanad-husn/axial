"""Outer acceptance test for issue #326, slice 01
(book-metadata-open-library/identifier-lookup-and-merge):

Given the text of a source's front matter (title page + copyright/ISBN block)
When  identifier capture runs over that text
Then  it returns every checksum-valid ISBN-10/ISBN-13 and syntactically valid
      DOI found
And   a corrupted check digit or an all-same-digit placeholder is rejected,
      not returned
And   a source whose front matter carries neither yields no identifier --
      not an error

Given a checksum-valid ISBN or DOI
When  the corresponding resolver is called and the API has a matching record
Then  it returns title, author(s), date, and publisher for every field the
      source provides
And   the raw response is cached to disk keyed by the identifier; a second
      call makes no network request
And   a not-found, network-error, or timeout result is explicit and never
      raises

Given intake has already produced its existing embedded-metadata/title-page
      reading for a source
And   a validated identifier resolves
When  the fetched author plausibly overlaps intake's already-known author
      (the identity guard passes)
Then  the persisted record's title/author/date/publisher are the fetched
      values, each with provenance "open_library" or "crossref"
And   the record's `identifier` field carries `{type, value}`

Given the fetched author does not plausibly overlap intake's already-known
      author (a single, unambiguous identifier resolving to an entirely
      different person's work)
When  the record is built
Then  intake falls back to its existing embedded-metadata/title-page values
      unchanged
And   `identifier` still records what was found, for audit, but is not used
      for the four fields

Given a source's front matter carries MORE THAN ONE distinct checksum-valid
      identifier (e.g. a multi-volume work's own "also available in this
      series" ISBN block -- the real, measured case:
      `mann-sources-of-social-power-v1`/`v3`/`v4` all carry the identical
      ISBN `9781107028654`)
When  the record is built
Then  the capture ABSTAINS -- no lookup is attempted at all -- because an
      author-overlap guard cannot separate same-author volumes (the fetch
      for the shared ISBN resolves to "Mann, Michael", which overlaps every
      volume's own known author, so the guard alone would pass a
      wrong-volume fetch through)
And   intake falls back to its existing embedded-metadata/title-page values
      unchanged, and `identifier` records the candidates found, for audit

Given no identifier is found, or it fails to resolve
When  the record is built
Then  the record is produced exactly as intake does today, with
      `identifier: null`

See plans/book-metadata-open-library/01-identifier-lookup-and-merge.md for
the full slice contract and specs/PRODUCT.md §7.12/§7.13 for the source of
truth this test pins. The ambiguous-capture criterion above is the
founder's post-review correction (issue #326): the reviewer measured that
the author-overlap guard alone does NOT catch the Mann case (a live Open
Library call resolves the shared ISBN to an author that plausibly overlaps
every volume), so ambiguity abstention -- not the guard -- is what protects
it. `test_guard_rejects_a_fetch_for_a_genuinely_different_persons_work`
below is what the guard actually does catch.

Seam decisions
-----------------------------------------------------------------------
1. Fixture PDFs are hand-built in-module by the same minimal from-scratch
   writer `tests/ingestion/test_source_metadata_record.py` already uses
   (`_make_pdf`, with an optional `/Info` metadata dictionary) -- carried
   over rather than committing a binary fixture (DEC-23 forbids committing
   source text).
2. `axial.intake.intake()` is called directly, with an explicit
   `source_meta_dir` (a `tmp_path` subdirectory) so this file never touches
   the real repo's `data/source_meta/`, and an explicit `bib_cache_dir` (also
   under `tmp_path`) so it never touches the real repo's
   `data/bib_lookup_cache/` either.
3. The identifier lookup is stubbed via `httpx.MockTransport` passed as
   `bib_transport` -- no live network anywhere in this file, and CI has no
   egress dependency.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from axial.envelope import compute_source_id
from axial.intake import intake

# =============================================================================
# Minimal from-scratch PDF writer (adapted from
# test_source_metadata_record.py's own `_make_pdf`/`_write_pdf`)
# =============================================================================


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream_for_page(lines: list[str]) -> bytes:
    parts = ["BT", "/F1 10 Tf", "72 750 Td"]
    for index, line in enumerate(lines):
        if index > 0:
            parts.append("0 -14 Td")
        parts.append(f"({_escape_pdf_text(line)}) Tj")
    parts.append("ET")
    stream = "\n".join(parts).encode("latin-1")
    header = f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
    return header + stream + b"\nendstream"


def _info_dict_bytes(info: dict[str, str]) -> bytes:
    parts = " ".join(f"/{key} ({_escape_pdf_text(value)})" for key, value in info.items())
    return f"<< {parts} >>".encode("latin-1")


def _make_pdf(pages_lines: list[list[str]], info: dict[str, str] | None = None) -> bytes:
    n = len(pages_lines)
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{4 + i} 0 R' for i in range(n))}] "
        f"/Count {n} >>".encode("ascii"),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i, lines in enumerate(pages_lines):
        page_obj_num = 4 + i
        content_obj_num = 4 + n + i
        objects[page_obj_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_obj_num} 0 R >>"
        ).encode("ascii")
        objects[content_obj_num] = _content_stream_for_page(lines)

    max_obj = 3 + 2 * n
    info_obj_num = None
    if info:
        max_obj += 1
        info_obj_num = max_obj
        objects[info_obj_num] = _info_dict_bytes(info)

    buf = bytearray(header)
    offsets: dict[int, int] = {}
    for obj_num in range(1, max_obj + 1):
        offsets[obj_num] = len(buf)
        buf.extend(f"{obj_num} 0 obj\n".encode("ascii"))
        buf.extend(objects[obj_num])
        buf.extend(b"\nendobj\n")

    xref_offset = len(buf)
    buf.extend(f"xref\n0 {max_obj + 1}\n".encode("ascii"))
    buf.extend(b"0000000000 65535 f \n")
    for obj_num in range(1, max_obj + 1):
        buf.extend(f"{offsets[obj_num]:010d} 00000 n \n".encode("ascii"))
    trailer = f"<< /Size {max_obj + 1} /Root 1 0 R"
    if info_obj_num is not None:
        trailer += f" /Info {info_obj_num} 0 R"
    trailer += " >>"
    buf.extend(f"trailer\n{trailer}\nstartxref\n{xref_offset}\n%%EOF".encode("ascii"))
    return bytes(buf)


def _write_pdf(
    tmp_path: Path, name: str, pages_lines: list[list[str]], info: dict[str, str] | None = None
) -> Path:
    path = tmp_path / name
    path.write_bytes(_make_pdf(pages_lines, info=info))
    return path


def _body(index: int) -> list[str]:
    return [f"Ordinary body prose on page {index}, discussing the case in general terms."]


# =============================================================================
# Mock transports (no live network)
# =============================================================================


def _open_library_transport(isbn: str, record: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert f"ISBN:{isbn}" in str(request.url)
        return httpx.Response(200, json={f"ISBN:{isbn}": record})

    return httpx.MockTransport(handler)


def _crossref_transport(message: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": message})

    return httpx.MockTransport(handler)


def _counting_transport(record: dict) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=record)

    return httpx.MockTransport(handler), calls


# =============================================================================
# Corpus-shaped fixtures
# =============================================================================

REAL_ISBN = "9780262033848"
CORRUPTED_ISBN = "9780262033849"  # bad EAN-13 check digit
PLACEHOLDER_ISBN = "0-000-00000-0"
REAL_DOI = "10.1145/3292500.3330701"

FRONT_MATTER_WITH_ISBN = [
    ["State Legitimacy and Civil Conflict", "An Institutional History"],
    [f"ISBN: {REAL_ISBN[:3]}-{REAL_ISBN[3]}-{REAL_ISBN[4:7]}-{REAL_ISBN[7:12]}-{REAL_ISBN[12]}"],
] + [_body(i) for i in range(1, 4)]

FRONT_MATTER_NO_IDENTIFIER = [
    ["A Perfectly Ordinary Book", "Some front matter with no identifier at all."],
] + [_body(i) for i in range(1, 4)]

FRONT_MATTER_CORRUPTED_ISBN = [
    [
        f"ISBN: {CORRUPTED_ISBN[:3]}-{CORRUPTED_ISBN[3]}-{CORRUPTED_ISBN[4:7]}-"
        f"{CORRUPTED_ISBN[7:12]}-{CORRUPTED_ISBN[12]}"
    ],
] + [_body(i) for i in range(1, 3)]

FRONT_MATTER_PLACEHOLDER_ISBN = [
    [f"ISBN: {PLACEHOLDER_ISBN}"],
] + [_body(i) for i in range(1, 3)]

FRONT_MATTER_WITH_DOI = [
    ["A Distributed Systems Paper"],
    [f"https://doi.org/{REAL_DOI}"],
] + [_body(i) for i in range(1, 3)]


# =============================================================================
# Capture: front matter -> validated identifiers (no network)
# =============================================================================


class TestCapture:
    def test_a_checksum_valid_isbn_is_captured(self):
        from axial.identifiers import capture

        assert capture("ISBN: 978-0-262-03384-8") == {"type": "isbn", "value": REAL_ISBN}

    def test_a_syntactically_valid_doi_is_captured(self):
        from axial.identifiers import capture

        assert capture(f"https://doi.org/{REAL_DOI}") == {"type": "doi", "value": REAL_DOI}

    def test_a_corrupted_check_digit_is_rejected_not_returned(self):
        from axial.identifiers import capture

        assert capture("ISBN: 978-0-262-03384-9") is None

    def test_an_all_same_digit_placeholder_is_rejected(self):
        from axial.identifiers import capture

        assert capture(f"ISBN: {PLACEHOLDER_ISBN}") is None

    def test_front_matter_with_neither_yields_no_identifier_not_an_error(self):
        from axial.identifiers import capture

        assert capture("Ordinary front matter with no identifier.") is None


# =============================================================================
# Resolve: identifier -> Open Library/Crossref fields, cache, error shapes
# =============================================================================


class TestResolve:
    def test_a_resolved_isbn_returns_every_field_the_source_provides(self, tmp_path):
        from axial.bib_lookup import resolve_isbn

        transport = _open_library_transport(
            REAL_ISBN,
            {
                "title": "State Legitimacy and Civil Conflict",
                "authors": [{"name": "Jane Q. Historian"}],
                "publish_date": "1985",
                "publishers": [{"name": "A University Press"}],
            },
        )

        result = resolve_isbn(REAL_ISBN, transport=transport, cache_dir=tmp_path)

        assert result["resolved"] is True
        assert result["title"] == "State Legitimacy and Civil Conflict"
        assert result["author"] == "Jane Q. Historian"
        assert result["date"] == "1985"
        assert result["publisher"] == "A University Press"
        assert result["source"] == "open_library"

    def test_a_second_call_for_the_same_identifier_makes_no_network_request(self, tmp_path):
        from axial.bib_lookup import resolve_isbn

        transport, calls = _counting_transport({f"ISBN:{REAL_ISBN}": {"title": "A Title"}})

        resolve_isbn(REAL_ISBN, transport=transport, cache_dir=tmp_path)
        resolve_isbn(REAL_ISBN, transport=transport, cache_dir=tmp_path)

        assert len(calls) == 1

    def test_a_not_found_result_is_explicit_and_never_raises(self, tmp_path):
        from axial.bib_lookup import resolve_isbn

        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))

        result = resolve_isbn("9999999999999", transport=transport, cache_dir=tmp_path)

        assert result == {"resolved": False, "error": None}

    def test_a_network_error_is_explicit_never_raises_and_distinguishable_from_not_found(
        self, tmp_path
    ):
        from axial.bib_lookup import resolve_isbn

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out", request=request)

        transport = httpx.MockTransport(handler)

        result = resolve_isbn(REAL_ISBN, transport=transport, cache_dir=tmp_path)

        assert result["resolved"] is False
        assert result["error"] is not None  # distinguishable from a genuine not-found (error=None)


# =============================================================================
# Merge: intake() end to end, behind the same-work identity guard
# =============================================================================


class TestMergeIntoIntake:
    def test_guard_passes_fetched_fields_win_with_provenance_and_identifier_recorded(
        self, tmp_path
    ):
        """Guard passes because the fetched author overlaps the file's own
        embedded-metadata author."""
        path = _write_pdf(
            tmp_path,
            "book.pdf",
            FRONT_MATTER_WITH_ISBN,
            info={"Author": "Jane Q. Historian", "Title": "An Unrelated Embedded Title"},
        )
        meta_dir = tmp_path / "source_meta"
        cache_dir = tmp_path / "bib_cache"
        transport = _open_library_transport(
            REAL_ISBN,
            {
                "title": "State Legitimacy and Civil Conflict",
                "authors": [{"name": "Jane Q. Historian"}],
                "publish_date": "1985",
                "publishers": [{"name": "A University Press"}],
            },
        )

        intake(path, source_meta_dir=meta_dir, bib_transport=transport, bib_cache_dir=cache_dir)

        record = json.loads(
            (meta_dir / f"{compute_source_id(path)}.json").read_text(encoding="utf-8")
        )
        assert record["title"] == {
            "value": "State Legitimacy and Civil Conflict",
            "provenance": "open_library",
        }
        assert record["author"] == {"value": "Jane Q. Historian", "provenance": "open_library"}
        assert record["date"] == {"value": "1985", "provenance": "open_library"}
        assert record["publisher"] == {"value": "A University Press", "provenance": "open_library"}
        assert record["identifier"] == {"type": "isbn", "value": REAL_ISBN}

    def test_ambiguous_multi_volume_isbn_block_abstains_lookup_never_attempted(self, tmp_path):
        """The REAL case (post-review correction, issue #326): a live Open
        Library call resolves `mann-sources-of-social-power-v1`/`v3`/`v4`'s
        shared ISBN `9781107028654` to author `"Mann, Michael"` -- which
        DOES plausibly overlap each volume's own known author `"Michael
        Mann"` (`authors_plausibly_overlap` returns `True` for that pair,
        see `test_intake.py::TestAuthorsPlausiblyOverlap`). The guard alone
        would therefore pass a wrong-volume fetch straight through. What
        actually protects this source is that its front matter carries MORE
        THAN ONE distinct ISBN (its own volume-specific one, plus the
        series' shared one in an "also available" block) -- capture
        abstains before any lookup is attempted, so the guard is never even
        reached. The transport below fails the test outright if it receives
        any request at all."""
        mann_front_matter = [
            ["The Sources of Social Power", "Volume 4: Globalizations, 1945-2011"],
            [
                f"ISBN: {REAL_ISBN[:3]}-{REAL_ISBN[3]}-{REAL_ISBN[4:7]}-{REAL_ISBN[7:12]}-"
                f"{REAL_ISBN[12]}",
                "Also available in this series:",
                # The real corpus finding: v1/v3/v4 all share this ISBN.
                "ISBN: 978-1-107-02865-4",
            ],
        ] + [_body(i) for i in range(1, 4)]
        path = _write_pdf(
            tmp_path,
            "mann-sources-of-social-power-v4.pdf",
            mann_front_matter,
            info={"Author": "Michael Mann", "Title": "The Sources of Social Power, Vol. IV"},
        )
        meta_dir = tmp_path / "source_meta"
        cache_dir = tmp_path / "bib_cache"

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError(
                f"no lookup should ever be attempted for an ambiguous capture, got: {request.url}"
            )

        never_called_transport = httpx.MockTransport(handler)

        intake(
            path,
            source_meta_dir=meta_dir,
            bib_transport=never_called_transport,
            bib_cache_dir=cache_dir,
        )

        record = json.loads(
            (meta_dir / f"{compute_source_id(path)}.json").read_text(encoding="utf-8")
        )
        assert record["author"] == {"value": "Michael Mann", "provenance": "embedded metadata"}
        assert record["title"] == {
            "value": "The Sources of Social Power, Vol. IV",
            "provenance": "embedded metadata",
        }
        assert record["publisher"] == "unavailable"
        assert record["identifier"] == {
            "type": "isbn",
            "value": None,
            "abstained": True,
            "candidates": sorted([REAL_ISBN, "9781107028654"]),
        }

    def test_guard_rejects_a_fetch_for_a_genuinely_different_persons_work(self, tmp_path):
        """What the author-overlap guard actually does catch: a single,
        unambiguous identifier whose fetch names an entirely different
        person -- a mistyped or recycled identifier, not a same-author
        wrong-volume mismatch (see the ambiguity test above for that case)."""
        path = _write_pdf(
            tmp_path,
            "book.pdf",
            FRONT_MATTER_WITH_ISBN,
            info={"Author": "Jane Q. Historian", "Title": "State Legitimacy and Civil Conflict"},
        )
        meta_dir = tmp_path / "source_meta"
        cache_dir = tmp_path / "bib_cache"
        transport = _open_library_transport(
            REAL_ISBN,
            {
                "title": "An Entirely Unrelated Book",
                "authors": [{"name": "A Completely Different Person"}],
                "publish_date": "2001",
                "publishers": [{"name": "Some Other Press"}],
            },
        )

        intake(path, source_meta_dir=meta_dir, bib_transport=transport, bib_cache_dir=cache_dir)

        record = json.loads(
            (meta_dir / f"{compute_source_id(path)}.json").read_text(encoding="utf-8")
        )
        assert record["author"] == {"value": "Jane Q. Historian", "provenance": "embedded metadata"}
        assert record["title"] == {
            "value": "State Legitimacy and Civil Conflict",
            "provenance": "embedded metadata",
        }
        assert record["publisher"] == "unavailable"
        assert record["identifier"] == {"type": "isbn", "value": REAL_ISBN}

    def test_guard_treats_diacritics_and_name_order_as_a_match(self, tmp_path):
        """The spike's own false-mismatch case: `Malesevic, Sinisa` (the
        file's own embedded metadata) vs `Siniša Malešević` (the fetch)."""
        path = _write_pdf(
            tmp_path,
            "book.pdf",
            FRONT_MATTER_WITH_ISBN,
            info={"Author": "Malesevic, Sinisa", "Title": "An Unrelated Embedded Title"},
        )
        meta_dir = tmp_path / "source_meta"
        cache_dir = tmp_path / "bib_cache"
        transport = _open_library_transport(
            REAL_ISBN,
            {
                "title": "Nation-States and Nationalism in Europe",
                "authors": [{"name": "Siniša Malešević"}],
                "publish_date": "2013",
            },
        )

        intake(path, source_meta_dir=meta_dir, bib_transport=transport, bib_cache_dir=cache_dir)

        record = json.loads(
            (meta_dir / f"{compute_source_id(path)}.json").read_text(encoding="utf-8")
        )
        assert record["author"] == {"value": "Siniša Malešević", "provenance": "open_library"}
        assert record["title"] == {
            "value": "Nation-States and Nationalism in Europe",
            "provenance": "open_library",
        }

    def test_the_ayubi_gap_case_a_null_title_read_gets_a_real_title_when_the_guard_passes(
        self, tmp_path
    ):
        """The real gap the spike found: `ayubi-over-stating-the-arab-state`'s
        pre-feature title read is `None` (no embedded metadata, no client so
        no title-page read either). No known author exists to contradict the
        fetch, so the guard passes by default."""
        path = _write_pdf(tmp_path, "ayubi-over-stating-the-arab-state.pdf", FRONT_MATTER_WITH_ISBN)
        meta_dir = tmp_path / "source_meta"
        cache_dir = tmp_path / "bib_cache"
        transport = _open_library_transport(
            REAL_ISBN,
            {
                "title": "Over-Stating the Arab State",
                "authors": [{"name": "Nazih N. M. Ayubi"}, {"name": "Nazih N."}],
                "publish_date": "1995",
            },
        )

        # Sanity check on the "gap": no client, no embedded metadata -> the
        # pre-feature title read would have been unavailable/None.
        intake_no_lookup = intake(path, source_meta_dir=tmp_path / "no_lookup_meta")
        pre_feature_record = json.loads(
            (tmp_path / "no_lookup_meta" / f"{compute_source_id(path)}.json").read_text(
                encoding="utf-8"
            )
        )
        assert pre_feature_record["title"] != {
            "value": "Over-Stating the Arab State",
            "provenance": "embedded metadata",
        }
        del intake_no_lookup

        intake(path, source_meta_dir=meta_dir, bib_transport=transport, bib_cache_dir=cache_dir)

        record = json.loads(
            (meta_dir / f"{compute_source_id(path)}.json").read_text(encoding="utf-8")
        )
        assert record["title"] == {
            "value": "Over-Stating the Arab State",
            "provenance": "open_library",
        }
        # The spike's own author-join bug must not resurface here either.
        assert record["author"] == {"value": "Nazih N. M. Ayubi", "provenance": "open_library"}

    def test_a_doi_only_source_resolves_via_crossref_editor_used_when_author_is_empty(
        self, tmp_path
    ):
        path = _write_pdf(tmp_path, "decentralization-local-governance.pdf", FRONT_MATTER_WITH_DOI)
        meta_dir = tmp_path / "source_meta"
        cache_dir = tmp_path / "bib_cache"
        transport = _crossref_transport(
            {
                "title": ["Decentralization, Local Governance, and Inequality"],
                "author": [],
                "editor": [{"given": "Kristen", "family": "Kao"}],
                "published": {"date-parts": [[2021]]},
                "publisher": "A Publisher",
            }
        )

        intake(path, source_meta_dir=meta_dir, bib_transport=transport, bib_cache_dir=cache_dir)

        record = json.loads(
            (meta_dir / f"{compute_source_id(path)}.json").read_text(encoding="utf-8")
        )
        assert record["identifier"] == {"type": "doi", "value": REAL_DOI}
        assert record["author"] == {"value": "Kristen Kao", "provenance": "crossref"}
        assert record["title"] == {
            "value": "Decentralization, Local Governance, and Inequality",
            "provenance": "crossref",
        }

    def test_no_identifier_found_record_matches_pre_feature_behavior_except_identifier_null(
        self, tmp_path
    ):
        path = _write_pdf(tmp_path, "book.pdf", FRONT_MATTER_NO_IDENTIFIER)
        meta_dir = tmp_path / "source_meta"

        intake(path, source_meta_dir=meta_dir)

        record = json.loads(
            (meta_dir / f"{compute_source_id(path)}.json").read_text(encoding="utf-8")
        )
        assert record["identifier"] is None
        assert record["publisher"] == "unavailable"
        # No embedded metadata (info=None) and no client: pre-feature
        # title/author/date behavior (unavailable) is unchanged.
        assert record["author"] == "unavailable"
        assert record["title"] == "unavailable"

    def test_a_corrupted_isbn_yields_no_identifier_not_a_false_win(self, tmp_path):
        path = _write_pdf(tmp_path, "book.pdf", FRONT_MATTER_CORRUPTED_ISBN)
        meta_dir = tmp_path / "source_meta"

        intake(path, source_meta_dir=meta_dir)

        record = json.loads(
            (meta_dir / f"{compute_source_id(path)}.json").read_text(encoding="utf-8")
        )
        assert record["identifier"] is None

    def test_a_placeholder_isbn_yields_no_identifier(self, tmp_path):
        path = _write_pdf(tmp_path, "book.pdf", FRONT_MATTER_PLACEHOLDER_ISBN)
        meta_dir = tmp_path / "source_meta"

        intake(path, source_meta_dir=meta_dir)

        record = json.loads(
            (meta_dir / f"{compute_source_id(path)}.json").read_text(encoding="utf-8")
        )
        assert record["identifier"] is None

    def test_an_unresolved_lookup_leaves_the_four_fields_at_pre_feature_behavior(self, tmp_path):
        path = _write_pdf(
            tmp_path,
            "book.pdf",
            FRONT_MATTER_WITH_ISBN,
            info={"Author": "Jane Q. Historian", "Title": "An Embedded Title"},
        )
        meta_dir = tmp_path / "source_meta"
        cache_dir = tmp_path / "bib_cache"
        # A definitive not-found: Open Library carries no matching bibkey.
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))

        intake(path, source_meta_dir=meta_dir, bib_transport=transport, bib_cache_dir=cache_dir)

        record = json.loads(
            (meta_dir / f"{compute_source_id(path)}.json").read_text(encoding="utf-8")
        )
        assert record["author"] == {"value": "Jane Q. Historian", "provenance": "embedded metadata"}
        assert record["title"] == {"value": "An Embedded Title", "provenance": "embedded metadata"}
        assert record["publisher"] == "unavailable"
        assert record["identifier"] == {"type": "isbn", "value": REAL_ISBN}

    def test_publisher_three_state_shape_matches_author_title_date(self, tmp_path):
        no_id_path = _write_pdf(tmp_path, "no_identifier.pdf", FRONT_MATTER_NO_IDENTIFIER)
        with_id_path = _write_pdf(
            tmp_path,
            "with_identifier.pdf",
            FRONT_MATTER_WITH_ISBN,
            info={"Author": "Jane Q. Historian"},
        )
        meta_dir = tmp_path / "source_meta"
        cache_dir = tmp_path / "bib_cache"
        transport = _open_library_transport(
            REAL_ISBN,
            {
                "title": "State Legitimacy and Civil Conflict",
                "authors": [{"name": "Jane Q. Historian"}],
                "publishers": [{"name": "A Press"}],
            },
        )

        intake(no_id_path, source_meta_dir=meta_dir)
        intake(
            with_id_path, source_meta_dir=meta_dir, bib_transport=transport, bib_cache_dir=cache_dir
        )

        no_id_record = json.loads(
            (meta_dir / f"{compute_source_id(no_id_path)}.json").read_text(encoding="utf-8")
        )
        with_id_record = json.loads(
            (meta_dir / f"{compute_source_id(with_id_path)}.json").read_text(encoding="utf-8")
        )
        assert no_id_record["publisher"] == "unavailable"
        assert isinstance(with_id_record["publisher"], dict)
        assert with_id_record["publisher"]["provenance"] == "open_library"

    def test_the_record_stays_byte_unchanged_across_a_client_less_revalidation(self, tmp_path):
        """The same durability guard `test_source_metadata_record.py`
        established: a later client-less call (mirroring `extract()`'s own
        internal validation-only `intake()` call) must not disturb the
        identifier-merged fields already on disk."""
        path = _write_pdf(
            tmp_path,
            "book.pdf",
            FRONT_MATTER_WITH_ISBN,
            info={"Author": "Jane Q. Historian"},
        )
        meta_dir = tmp_path / "source_meta"
        cache_dir = tmp_path / "bib_cache"
        transport = _open_library_transport(
            REAL_ISBN,
            {
                "title": "State Legitimacy and Civil Conflict",
                "authors": [{"name": "Jane Q. Historian"}],
                "publish_date": "1985",
                "publishers": [{"name": "A University Press"}],
            },
        )

        intake(path, source_meta_dir=meta_dir, bib_transport=transport, bib_cache_dir=cache_dir)
        record_path = meta_dir / f"{compute_source_id(path)}.json"
        first_bytes = record_path.read_bytes()

        # A later, client-less call with NO bib_transport override at all --
        # it must read the disk cache (no live network) and still preserve
        # the already-recorded fields rather than recompute-and-regress them.
        intake(path, source_meta_dir=meta_dir, bib_cache_dir=cache_dir)

        assert record_path.read_bytes() == first_bytes
