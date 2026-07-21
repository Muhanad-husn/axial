"""Outer acceptance test for issue #303 (intake-metadata, slice 04): the
holdings-completeness check and the title-page bibliographic read are wired
into the real ingest path (PRD §7.11/§7.12/§7.13, §8 P0-1b/P0-1c).

Given a source ingested through the real pipeline path (`extract()`, which
      every ingest entry point funnels through)
When  it is extracted for the first time
Then  intake makes the §7.11/§7.13 model judgment exactly once and persists
      it in the §7.12 source-metadata record
And   a later pass over the same source makes no new model call and builds
      no client at all -- it reads the record
And   a source whose check could not land (no provider, no client) is not
      recorded as judged, and still extracts normally
And   a flagged source completes extraction exactly as an unflagged one
      does (flag-only, §7.11)

Before this slice, `extract()` called `intake(path)` with no client, so the
check ran nowhere in the pipeline: P0-1b's "runs at intake on every accepted
source" was true of `intake()` and false of the pipeline.

Seam decisions
-----------------------------------------------------------------------
1. `axial.extract.extract()` is driven in-process rather than through the
   CLI: the assertions are about how many model calls and client
   constructions happen, which no CLI text scrape can observe.
2. A structural tree is pre-placed at a `tmp_path`-redirected
   `axial.extract.TREES_DIR` so `extract()` cache-hits and real docling
   never runs (the same convention tests/ingestion/test_envelope.py and
   test_source_metadata_record.py already use). The cache hit is also the
   case this slice most has to get right: it is the common one in a real
   corpus pass, and it must still get its holdings judgment.
3. `axial.extract.get_client` is monkeypatched with a factory that counts
   constructions and hands back a recorded holdings client that counts
   calls. Counting the *factory* is what pins "no client is even built for
   an already-judged source"; the repo's stub provider cannot answer a
   holdings prompt, so it cannot stand in here.
4. `axial.intake.SOURCE_META_DIR` is redirected to `tmp_path` for every
   test, so the real `data/source_meta/` is never read or written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import axial.extract as extract_mod
import axial.intake as intake_mod
from axial.envelope import compute_source_id
from axial.llm import LLMConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE_PDF = REPO_ROOT / "tests" / "fixtures" / "extract" / "prose_and_table.pdf"

PARTIAL_VERDICT = {
    "document_kind": "book",
    "claimed_extent": "volume 2 of 4",
    "claimed_extent_stated_by": "title page",
    "verdict": "partial",
    "reason": "The title page names volume 2 of a four-volume set.",
    "title_page_title": "A Stated Title",
    "title_page_author": "A Stated Author",
    "title_page_date": "1971",
    "author_metadata_matches": None,
    "title_metadata_matches": None,
}

PRE_PLACED_TREE = {
    "children": [
        {
            "type": "prose",
            "order": "1",
            "text": "A pre-placed section",
            "children": [{"type": "prose", "order": "1.1", "text": "Body text."}],
        }
    ]
}


class _RecordedHoldingsClient:
    """Replays one recorded holdings/title-page answer and counts calls."""

    def __init__(self, verdict: dict):
        self._response = json.dumps(verdict)
        self.calls = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls += 1
        return self._response


class _CountingClientFactory:
    """Stands in for `axial.extract.get_client`: counts how many times the
    ingest path asks for a client at all, and hands back one shared recorded
    client so call counts accumulate across `extract()` calls."""

    def __init__(self, client=None, error: Exception | None = None):
        self.client = client
        self.error = error
        self.constructions = 0

    def __call__(self, *args, **kwargs):
        self.constructions += 1
        if self.error is not None:
            raise self.error
        return self.client


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Redirect both persisted-state directories and pre-place the source's
    structural tree, so `extract()` runs its real intake path with no docling
    and no shared state."""
    trees_dir = tmp_path / "trees"
    trees_dir.mkdir()
    monkeypatch.setattr(extract_mod, "TREES_DIR", trees_dir)
    monkeypatch.setattr(intake_mod, "SOURCE_META_DIR", tmp_path / "source_meta")

    source_id = compute_source_id(SOURCE_PDF)
    (trees_dir / f"{source_id}.json").write_text(json.dumps(PRE_PLACED_TREE), encoding="utf-8")
    return source_id


def _record(source_id: str) -> dict:
    path = intake_mod.source_meta_path(source_id, intake_mod.SOURCE_META_DIR)
    assert path.exists(), f"expected a source-metadata record at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_extract_makes_the_holdings_judgment_once_and_persists_it(wired, monkeypatch):
    """P0-1b end to end: the pipeline's own extract call pays for the check,
    once, and the flag lands in the §7.12 record where a reader can find it."""
    client = _RecordedHoldingsClient(PARTIAL_VERDICT)
    factory = _CountingClientFactory(client)
    monkeypatch.setattr(extract_mod, "get_client", factory)

    tree = extract_mod.extract(SOURCE_PDF)

    assert client.calls == 1, (
        f"expected exactly one holdings/title-page model call from the ingest "
        f"path, got {client.calls}"
    )
    record = _record(wired)
    assert record["holdings_flag"] is not None, (
        f"expected the §7.11 flag in the persisted record after a real extract; record was {record}"
    )
    assert record["holdings_flag"]["claimed_extent"] == "volume 2 of 4"
    assert record["holdings_flag"]["reason"]
    # The same call carries the §7.13 title-page read (§7.12/#285).
    assert record["date"] == {"value": "1971", "provenance": "title page"}
    # Flag-only (§7.11): a flagged source extracts exactly as a clean one does.
    assert tree == PRE_PLACED_TREE


def test_a_second_pass_over_a_judged_source_makes_no_new_model_call(wired, monkeypatch):
    """The §7.12 record is the once-per-source cache: re-running the pipeline
    over an already-judged source neither calls the model nor builds a
    client."""
    client = _RecordedHoldingsClient(PARTIAL_VERDICT)
    factory = _CountingClientFactory(client)
    monkeypatch.setattr(extract_mod, "get_client", factory)

    extract_mod.extract(SOURCE_PDF)
    first_record = _record(wired)

    extract_mod.extract(SOURCE_PDF)

    assert client.calls == 1, (
        f"expected no second holdings call for an already-judged source, got {client.calls}"
    )
    assert factory.constructions == 1, (
        f"expected no client to be constructed on the second pass, got "
        f"{factory.constructions} constructions"
    )
    assert _record(wired) == first_record, "the persisted judgment must survive a second pass"


def test_a_check_that_could_not_land_is_not_cached_as_judged(wired, monkeypatch):
    """A source whose check never produced an answer -- no client available
    (offline, no API key) -- still extracts, and is judged on the next pass
    rather than being silently recorded as checked forever."""
    unavailable = _CountingClientFactory(error=LLMConfigError("no API key configured"))
    monkeypatch.setattr(extract_mod, "get_client", unavailable)

    tree = extract_mod.extract(SOURCE_PDF)

    assert tree == PRE_PLACED_TREE, "an unavailable model must never halt extraction (P0-1b)"
    assert _record(wired)["holdings_flag"] is None

    client = _RecordedHoldingsClient(PARTIAL_VERDICT)
    monkeypatch.setattr(extract_mod, "get_client", _CountingClientFactory(client))

    extract_mod.extract(SOURCE_PDF)

    assert client.calls == 1, (
        "a source whose check never landed must be judged on the next pass, "
        f"got {client.calls} calls"
    )
    assert _record(wired)["holdings_flag"] is not None
