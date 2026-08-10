"""Unit tests for the content-keyed paper cache (issue #686):
`PaperCache.store`/`.lookup` and the materialised-copy design that lets a
hit survive the originating analyst's own working set changing later
(module docstring)."""

from __future__ import annotations

import json
from pathlib import Path

from axial.service.cache import PaperCache


def test_lookup_is_none_on_a_miss(paper_cache: PaperCache):
    assert paper_cache.lookup("brief-1", "pin-1") is None


def test_store_then_lookup_finds_the_materialised_copy(paper_cache: PaperCache, tmp_path: Path):
    source = tmp_path / "original" / "brief-1.json"
    source.parent.mkdir()
    source.write_text(json.dumps({"claims": ["x"]}), encoding="utf-8")
    cache_dir = tmp_path / "cache"

    stored_path = paper_cache.store("brief-1", "pin-1", source, cache_dir)

    # A distinct, materialised copy -- not the original path.
    assert stored_path != source
    assert stored_path.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert paper_cache.lookup("brief-1", "pin-1") == str(stored_path)


def test_a_hit_survives_the_originating_analysts_directory_being_deleted(
    paper_cache: PaperCache, tmp_path: Path
):
    """The decision this cache is built on (module docstring): pointing at
    the original path would break the moment that analyst's own working set
    is gone. It must not."""
    source = tmp_path / "analyses" / "analyst-a" / "brief-1.json"
    source.parent.mkdir(parents=True)
    body = json.dumps({"claims": ["a claim"]})
    source.write_text(body, encoding="utf-8")
    paper_cache.store("brief-1", "pin-1", source, tmp_path / "cache")

    # Analyst A's own working set is pruned, moved, or scoped away.
    source.unlink()
    source.parent.rmdir()

    cached_ref = paper_cache.lookup("brief-1", "pin-1")
    assert cached_ref is not None
    assert Path(cached_ref).read_text(encoding="utf-8") == body


def test_a_different_corpus_pin_is_a_miss(paper_cache: PaperCache, tmp_path: Path):
    source = tmp_path / "brief-1.json"
    source.write_text("{}", encoding="utf-8")
    paper_cache.store("brief-1", "pin-1", source, tmp_path / "cache")

    assert paper_cache.lookup("brief-1", "pin-2") is None


def test_a_second_store_for_the_same_key_does_not_error(paper_cache: PaperCache, tmp_path: Path):
    """Two racing workers can both generate the same miss and both call
    `store` (module docstring: `ON CONFLICT DO NOTHING`) -- the loser's
    write must not raise, and the table keeps its first winner."""
    source = tmp_path / "brief-1.json"
    source.write_text(json.dumps({"claims": ["first"]}), encoding="utf-8")
    first_path = paper_cache.store("brief-1", "pin-1", source, tmp_path / "cache")

    other_source = tmp_path / "brief-1-again.json"
    other_source.write_text(json.dumps({"claims": ["second"]}), encoding="utf-8")
    paper_cache.store("brief-1", "pin-1", other_source, tmp_path / "cache")

    assert paper_cache.lookup("brief-1", "pin-1") == str(first_path)
