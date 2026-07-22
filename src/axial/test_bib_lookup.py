"""Inner unit tests for `axial.bib_lookup` (issue #326, §7.12/§7.13).

Every test uses `httpx.MockTransport` (the same seam `axial.llm.OpenRouterClient`
already relies on) and an explicit `cache_dir` under `tmp_path` -- no live
network, and no writes into the real repo's `data/bib_lookup_cache/`.
"""

from __future__ import annotations

import json

import httpx
import pytest

from axial.bib_lookup import resolve_doi, resolve_isbn


def _transport(handler):
    return httpx.MockTransport(handler)


def _json_response(status_code: int, body) -> httpx.Response:
    return httpx.Response(status_code, json=body)


class TestResolveIsbn:
    def test_a_successful_response_maps_title_author_date_publisher(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "ISBN:9780262033848" in str(request.url)
            return _json_response(
                200,
                {
                    "ISBN:9780262033848": {
                        "title": "Introduction to Algorithms",
                        "authors": [{"name": "Thomas H. Cormen"}, {"name": "Charles E. Leiserson"}],
                        "publish_date": "2009",
                        "publishers": [{"name": "MIT Press"}],
                    }
                },
            )

        result = resolve_isbn("9780262033848", transport=_transport(handler), cache_dir=tmp_path)

        assert result == {
            "resolved": True,
            "title": "Introduction to Algorithms",
            "author": "Thomas H. Cormen, Charles E. Leiserson",
            "date": "2009",
            "publisher": "MIT Press",
            "source": "open_library",
        }

    def test_near_duplicate_author_variants_are_not_duplicated(self, tmp_path):
        """The spike's own bug, found on `ayubi-over-stating-the-arab-state`:
        Open Library listed `"Nazih N. M. Ayubi"` and the truncated variant
        `"Nazih N."` for the same edition."""

        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                200,
                {
                    "ISBN:9780415054865": {
                        "title": "Over-Stating the Arab State",
                        "authors": [{"name": "Nazih N. M. Ayubi"}, {"name": "Nazih N."}],
                    }
                },
            )

        result = resolve_isbn("9780415054865", transport=_transport(handler), cache_dir=tmp_path)

        assert result["author"] == "Nazih N. M. Ayubi"

    def test_a_cached_response_short_circuits_with_zero_network_requests(self, tmp_path):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return _json_response(
                200, {"ISBN:9780262033848": {"title": "Introduction to Algorithms"}}
            )

        resolve_isbn("9780262033848", transport=_transport(handler), cache_dir=tmp_path)
        assert len(calls) == 1

        result = resolve_isbn("9780262033848", transport=_transport(handler), cache_dir=tmp_path)

        assert len(calls) == 1, "a second call for the same identifier must make no request"
        assert result["title"] == "Introduction to Algorithms"

    def test_a_genuine_not_found_bibkey_is_resolved_false_with_no_error(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(200, {})

        result = resolve_isbn("9999999999999", transport=_transport(handler), cache_dir=tmp_path)

        assert result == {"resolved": False, "error": None}

    def test_a_timeout_returns_not_resolved_with_an_error_never_raises(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        result = resolve_isbn("9780262033848", transport=_transport(handler), cache_dir=tmp_path)

        assert result["resolved"] is False
        assert result["error"] is not None

    def test_a_transport_error_is_distinguishable_from_a_genuine_not_found(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        transport_result = resolve_isbn(
            "9780262033848", transport=_transport(handler), cache_dir=tmp_path
        )

        def not_found_handler(request: httpx.Request) -> httpx.Response:
            return _json_response(200, {})

        not_found_result = resolve_isbn(
            "9780262033849", transport=_transport(not_found_handler), cache_dir=tmp_path
        )

        assert transport_result["error"] is not None
        assert not_found_result["error"] is None

    def test_a_non_json_body_returns_not_resolved_never_raises(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json at all")

        result = resolve_isbn("9780262033848", transport=_transport(handler), cache_dir=tmp_path)

        assert result == {"resolved": False, "error": "non-JSON response body"}

    def test_the_cache_file_lands_under_the_given_cache_dir(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(200, {"ISBN:9780262033848": {"title": "A Title"}})

        resolve_isbn("9780262033848", transport=_transport(handler), cache_dir=tmp_path)

        cached_files = list(tmp_path.glob("*.json"))
        assert len(cached_files) == 1
        assert json.loads(cached_files[0].read_text(encoding="utf-8"))

    def test_requests_carry_a_descriptive_user_agent_with_contact_info(self, tmp_path):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["user_agent"] = request.headers.get("user-agent")
            return _json_response(200, {})

        resolve_isbn("9780262033848", transport=_transport(handler), cache_dir=tmp_path)

        assert seen["user_agent"] is not None
        assert "@" in seen["user_agent"], "expected contact info in the User-Agent"


class TestResolveDoi:
    def test_a_successful_response_maps_the_same_fields(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "10.1145%2F3292500.3330701" in str(request.url) or (
                "10.1145/3292500.3330701" in str(request.url)
            )
            return _json_response(
                200,
                {
                    "message": {
                        "title": ["A Distributed Systems Paper"],
                        "author": [{"given": "Ada", "family": "Lovelace"}],
                        "published": {"date-parts": [[2019]]},
                        "publisher": "ACM",
                    }
                },
            )

        result = resolve_doi(
            "10.1145/3292500.3330701", transport=_transport(handler), cache_dir=tmp_path
        )

        assert result == {
            "resolved": True,
            "title": "A Distributed Systems Paper",
            "author": "Ada Lovelace",
            "date": "2019",
            "publisher": "ACM",
            "source": "crossref",
        }

    def test_an_edited_volume_uses_editor_when_author_is_empty(self, tmp_path):
        """The edited-volume case,
        `decentralization-local-governance-inequality-mena`, whose current
        record correctly has `"Kristen Kao (Editor)"`."""

        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                200,
                {
                    "message": {
                        "title": ["Decentralization, Local Governance, and Inequality"],
                        "author": [],
                        "editor": [{"given": "Kristen", "family": "Kao"}],
                    }
                },
            )

        result = resolve_doi(
            "10.1234/example.doi", transport=_transport(handler), cache_dir=tmp_path
        )

        assert result["author"] == "Kristen Kao"

    def test_a_404_is_a_genuine_not_found_and_is_cached(self, tmp_path):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(404)

        first = resolve_doi("10.9999/nope", transport=_transport(handler), cache_dir=tmp_path)
        second = resolve_doi("10.9999/nope", transport=_transport(handler), cache_dir=tmp_path)

        assert first == {"resolved": False, "error": None}
        assert second == {"resolved": False, "error": None}
        assert len(calls) == 1, "a cached not-found must make no second request"

    def test_a_5xx_is_a_transport_error_not_a_cached_not_found(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        result = resolve_doi("10.9999/flaky", transport=_transport(handler), cache_dir=tmp_path)

        assert result["resolved"] is False
        assert result["error"] is not None


@pytest.fixture(autouse=True)
def _no_real_cache_dir_by_default(monkeypatch, tmp_path):
    """Every test above passes an explicit `cache_dir`, but redirect the
    module default too as a second line of defense against ever writing
    into the real repo's `data/bib_lookup_cache/` from this file."""
    import axial.bib_lookup as bib_lookup_mod

    monkeypatch.setattr(bib_lookup_mod, "CACHE_DIR", tmp_path / "unused_default_cache")
