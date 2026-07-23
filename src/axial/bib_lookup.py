"""Identifier resolution against Open Library and Crossref (PRD §7.12/§7.13,
issue #326).

Two free, keyless lookups -- ISBN against Open Library's `/api/books` and
DOI against Crossref's `/works/{doi}` -- each a **single attempt with a
disk cache**, mirroring `axial.holdings.probe`'s own never-halts contract
(`holdings.py:437-442`): a transport failure, a timeout, a non-JSON body, or
a genuine not-found never raises, and the two are returned distinguishably
so a caller can tell "nothing to find" from "could not ask". No retry, no
backoff, no rate-limit pacing -- the corpus is ~30 sources.

The raw JSON response is cached to disk keyed by the identifier, under
`data/` (gitignored wholesale, DEC-23), so a second call for the same
identifier makes no network request. Built for a mockable transport
(`httpx.MockTransport`), the same seam `axial.llm.OpenRouterClient` already
uses, so this is unit-tested without ever making a live call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

# Gitignored scratch location for cached raw API responses -- `data/` is
# ignored wholesale (see .gitignore's DEC-23 block), so this needs no entry
# of its own. Plain, cwd-relative, no config override, mirroring
# `axial.intake.SOURCE_META_DIR`'s own convention: no caller of this module
# needs a redirect other than a test's explicit `cache_dir`.
CACHE_DIR = Path("data/bib_lookup_cache")

# Descriptive User-Agent with contact info, per both APIs' own request.
USER_AGENT = "axial-bib-lookup/0.1 (mailto:muhanad.a.husn@gmail.com)"

_TIMEOUT_SECONDS = 15.0

PROVENANCE_OPEN_LIBRARY = "open_library"
PROVENANCE_CROSSREF = "crossref"


def _cache_path(cache_dir: Path, cache_key: str) -> Path:
    return cache_dir / f"{cache_key}.json"


def _write_cache(cache_dir: Path, cache_file: Path, payload: dict[str, Any]) -> None:
    """Best-effort cache write -- mirrors the cache-READ path's own
    tolerance (`_fetch_json` below already degrades a corrupt/unreadable
    cache file to a cache miss rather than raising). A disk-full,
    permission-denied, or read-only-mount failure here must not propagate
    out of a resolver that promises never to raise: the caller still gets
    its correct, freshly-fetched answer, just uncached -- the next call
    tries the network again instead of reading a cache that was never
    written."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        print(f"bib_lookup: failed to cache {cache_file.name}: {exc}", file=sys.stderr)


def _fetch_json(
    url: str,
    cache_key: str,
    *,
    transport: httpx.BaseTransport | None,
    cache_dir: Path,
    timeout: float,
) -> dict[str, Any]:
    """One GET, cache-first, never raising. Returns one of:
    - `{"ok": True, "body": <parsed JSON>}` -- from cache or a fresh 2xx;
    - `{"ok": False, "not_found": True}` -- a definitive not-found (an HTTP
      404), cached like a real answer so a repeat call need not re-ask;
    - `{"ok": False, "error": <message>}` -- a transport failure, a timeout,
      a non-2xx/non-404 status, or a non-JSON body. Never cached: the
      failure may be transient and a later call should get another try.
    """
    cache_file = _cache_path(cache_dir, cache_key)
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = None
        if isinstance(cached, dict):
            if cached.get("__not_found__"):
                return {"ok": False, "not_found": True}
            return {"ok": True, "body": cached}

    client = httpx.Client(transport=transport, timeout=timeout)
    try:
        with client:
            response = client.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc)}

    if response.status_code == 404:
        _write_cache(cache_dir, cache_file, {"__not_found__": True})
        return {"ok": False, "not_found": True}
    if response.status_code >= 400:
        return {"ok": False, "error": f"HTTP {response.status_code}"}

    try:
        body = response.json()
    except ValueError:
        return {"ok": False, "error": "non-JSON response body"}

    _write_cache(cache_dir, cache_file, body)
    return {"ok": True, "body": body}


def _not_resolved(error: str | None = None) -> dict[str, Any]:
    return {"resolved": False, "error": error}


def _names_are_variants(a: str, b: str) -> bool:
    """True when one name's tokens are a leading prefix of the other's
    (casefolded) -- the shape of Open Library's own near-duplicate author
    listing (`"Nazih N. M. Ayubi"` / `"Nazih N."`), not a general fuzzy
    match."""
    a_tokens = a.casefold().split()
    b_tokens = b.casefold().split()
    shorter, longer = (
        (a_tokens, b_tokens) if len(a_tokens) <= len(b_tokens) else (b_tokens, a_tokens)
    )
    return bool(shorter) and shorter == longer[: len(shorter)]


def _crossref_date(msg: dict[str, Any]) -> str | None:
    """The publication year from Crossref's `published`/`issued` date-parts
    shape, or `None` -- tolerant of a malformed-but-valid response (a
    non-dict `published`/`issued`, a non-list `date-parts`), one of the
    failure modes this module's own never-raises contract names."""
    for key in ("published", "issued"):
        value = msg.get(key)
        if not isinstance(value, dict):
            continue
        date_parts = value.get("date-parts")
        if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list):
            year = date_parts[0][0] if date_parts[0] else None
            if year:
                return str(year)
    return None


def _dedupe_similar_authors(names: list[str]) -> list[str]:
    """`names` with near-duplicate variants of the same person collapsed to
    the longest (most complete) form -- the spike's own bug (see module
    docstring), found on `ayubi-over-stating-the-arab-state`."""
    kept: list[str] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        matched = False
        for i, existing in enumerate(kept):
            if _names_are_variants(name, existing):
                if len(name) > len(existing):
                    kept[i] = name
                matched = True
                break
        if not matched:
            kept.append(name)
    return kept


def resolve_isbn(
    isbn: str,
    *,
    transport: httpx.BaseTransport | None = None,
    cache_dir: Path | None = None,
    timeout: float = _TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Resolve `isbn` against Open Library. Returns `{"resolved": True,
    "title", "author", "date", "publisher", "source": "open_library"}` on a
    match (any field the record does not carry is `None`); otherwise
    `{"resolved": False, "error": None | <message>}` -- `error` is `None`
    for a genuine not-found bibkey and a message for a transport failure."""
    cache_dir = cache_dir if cache_dir is not None else CACHE_DIR
    url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
    fetched = _fetch_json(
        url, f"isbn_{isbn}", transport=transport, cache_dir=cache_dir, timeout=timeout
    )
    if not fetched["ok"]:
        return _not_resolved(fetched.get("error"))

    rec = fetched["body"].get(f"ISBN:{isbn}") if isinstance(fetched["body"], dict) else None
    if not rec:
        return _not_resolved(None)

    authors = _dedupe_similar_authors(
        [a.get("name", "") for a in rec.get("authors", []) if isinstance(a, dict) and a.get("name")]
    )
    publishers = [
        p.get("name", "")
        for p in rec.get("publishers", [])
        if isinstance(p, dict) and p.get("name")
    ]
    return {
        "resolved": True,
        "title": rec.get("title") or None,
        "author": ", ".join(authors) or None,
        "date": rec.get("publish_date") or None,
        "publisher": ", ".join(publishers) or None,
        "source": PROVENANCE_OPEN_LIBRARY,
    }


def resolve_doi(
    doi: str,
    *,
    transport: httpx.BaseTransport | None = None,
    cache_dir: Path | None = None,
    timeout: float = _TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Resolve `doi` against Crossref. Returns the same shape as
    `resolve_isbn`, provenance `"crossref"`. When Crossref's own `author` is
    empty and `editor` is present, `editor` is used -- the edited-volume
    case (`decentralization-local-governance-inequality-mena`)."""
    cache_dir = cache_dir if cache_dir is not None else CACHE_DIR
    cache_key = f"doi_{doi.replace('/', '_')}"
    fetched = _fetch_json(
        f"https://api.crossref.org/works/{doi}",
        cache_key,
        transport=transport,
        cache_dir=cache_dir,
        timeout=timeout,
    )
    if not fetched["ok"]:
        if fetched.get("not_found"):
            return _not_resolved(None)
        return _not_resolved(fetched.get("error"))

    msg = fetched["body"].get("message") if isinstance(fetched["body"], dict) else None
    if not msg:
        return _not_resolved(None)

    title = "; ".join(msg.get("title") or []) or None
    contributors = msg.get("author") or msg.get("editor") or []
    author = (
        ", ".join(
            f"{c.get('given', '')} {c.get('family', '')}".strip()
            for c in contributors
            if isinstance(c, dict) and (c.get("given") or c.get("family"))
        )
        or None
    )
    return {
        "resolved": True,
        "title": title,
        "author": author,
        "date": _crossref_date(msg),
        "publisher": msg.get("publisher") or None,
        "source": PROVENANCE_CROSSREF,
    }
