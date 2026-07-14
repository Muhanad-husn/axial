"""Inner unit tests for the per-source embedding cache (issue #152, PRD §5
stage 4 / §7.7 -- "cheap band sweeps", memory [[chunk-experiment-caching]]).
Complements tests/test_chunk_cache.py (the LOCKED outer acceptance test,
which exercises the whole `run_chunk_embedding` critical path with a
counting stub embedder) with individual-mechanism unit tests of
`_CachingEmbedder`, `_default_chunk_cache_dir`, `_safe_cache_key_component`,
and `HashingEmbedder`'s new `model_id` attribute -- the seams this slice
adds to `src/axial/chunk.py`.
"""

from __future__ import annotations

import json

import axial.chunk as chunk_mod
from axial.chunk import (
    HashingEmbedder,
    MissingSourceError,
    MissingTreeError,
    _CachingEmbedder,
    _default_chunk_cache_dir,
    _safe_cache_key_component,
    run_chunk_embedding,
)


class _CountingEmbedder:
    """A minimal counting stub, local to this file (mirrors
    tests/test_chunk_cache.py's own `CountingEmbedder`, kept independent so
    this unit-test file has no dependency on the locked outer test file)."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.calls = 0

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(len(text)), float(sum(map(ord, text)) % 997)] for text in texts]


# --- HashingEmbedder.model_id -------------------------------------------------


def test_hashing_embedder_default_model_id_reflects_dim():
    assert HashingEmbedder(dim=64).model_id == "hashing-v1-64"
    assert HashingEmbedder(dim=256).model_id == "hashing-v1-256"


def test_hashing_embedder_explicit_model_id_is_honored():
    embedder = HashingEmbedder(dim=64, model_id="custom-model")
    assert embedder.model_id == "custom-model"


# --- _default_chunk_cache_dir -------------------------------------------------


def test_default_chunk_cache_dir_reads_the_module_global(monkeypatch, tmp_path):
    monkeypatch.setattr(chunk_mod, "CHUNK_CACHE_DIR", tmp_path / "custom_cache")
    assert _default_chunk_cache_dir() == tmp_path / "custom_cache"


def test_default_chunk_cache_dir_falls_back_to_module_constant():
    # This module's own conftest.py autouse fixture already redirects
    # CHUNK_CACHE_DIR to an isolated tmp dir for every in-process test (see
    # src/axial/conftest.py) -- so this only proves the function reads
    # whatever CHUNK_CACHE_DIR currently is, not the real cwd-relative
    # "data/chunk_cache" literal.
    assert _default_chunk_cache_dir() == chunk_mod.CHUNK_CACHE_DIR


# --- _safe_cache_key_component -------------------------------------------------


def test_safe_cache_key_component_sanitizes_unsafe_characters():
    assert _safe_cache_key_component("plain-safe_id.123") == "plain-safe_id.123"
    assert _safe_cache_key_component("weird/model:id with spaces") == "weird_model_id_with_spaces"


# --- _CachingEmbedder: key, cold write, warm read, invalidation --------------


def test_caching_embedder_cache_key_is_source_id_plus_model_id(tmp_path):
    inner = _CountingEmbedder(model_id="model-x")
    cache = _CachingEmbedder(inner, source_id="source-a", cache_dir=tmp_path)
    assert cache._path == tmp_path / "source-a__model-x.json"


def test_caching_embedder_two_sources_never_collide(tmp_path):
    inner_a = _CountingEmbedder(model_id="model-x")
    inner_b = _CountingEmbedder(model_id="model-x")
    cache_a = _CachingEmbedder(inner_a, source_id="source-a", cache_dir=tmp_path)
    cache_b = _CachingEmbedder(inner_b, source_id="source-b", cache_dir=tmp_path)

    cache_a.encode(["shared sentence text"])
    cache_a.flush()
    cache_b.encode(["shared sentence text"])
    cache_b.flush()

    # Both cold: each inner embedder was called once, despite sharing a
    # sentence text -- source_id is part of the cache key, so source B's
    # cache file is entirely separate from source A's.
    assert inner_a.calls == 1
    assert inner_b.calls == 1
    assert {p.name for p in tmp_path.iterdir()} == {
        "source-a__model-x.json",
        "source-b__model-x.json",
    }


def test_caching_embedder_cold_write_then_warm_read_skips_inner_encode(tmp_path):
    inner_cold = _CountingEmbedder(model_id="model-x")
    cache_cold = _CachingEmbedder(inner_cold, source_id="source-a", cache_dir=tmp_path)
    cold_vectors = cache_cold.encode(["one", "two", "three"])
    cache_cold.flush()
    assert inner_cold.calls == 1

    # A fresh _CachingEmbedder instance (as a separate run/process would
    # construct) backed by a fresh inner embedder, same source_id/model_id,
    # same cache_dir: it must load the flushed file at construction and
    # never touch its own inner embedder.
    inner_warm = _CountingEmbedder(model_id="model-x")
    cache_warm = _CachingEmbedder(inner_warm, source_id="source-a", cache_dir=tmp_path)
    warm_vectors = cache_warm.encode(["one", "two", "three"])

    assert inner_warm.calls == 0
    assert warm_vectors == cold_vectors


def test_caching_embedder_flush_is_a_noop_when_nothing_changed(tmp_path):
    inner = _CountingEmbedder(model_id="model-x")
    cache = _CachingEmbedder(inner, source_id="source-a", cache_dir=tmp_path)
    cache.encode(["one"])
    cache.flush()
    written = json.loads((tmp_path / "source-a__model-x.json").read_text(encoding="utf-8"))

    # A second flush with no intervening cache-miss encode() call must not
    # rewrite the file with different content (idempotent no-op).
    cache.flush()
    still_written = json.loads((tmp_path / "source-a__model-x.json").read_text(encoding="utf-8"))
    assert still_written == written


def test_caching_embedder_partial_hit_only_calls_inner_for_misses(tmp_path):
    inner = _CountingEmbedder(model_id="model-x")
    cache = _CachingEmbedder(inner, source_id="source-a", cache_dir=tmp_path)
    cache.encode(["one", "two"])
    assert inner.calls == 1

    # "two" is already cached; only "three" is a genuine miss.
    cache.encode(["two", "three"])
    assert inner.calls == 2


def test_caching_embedder_different_model_id_is_a_cache_miss(tmp_path):
    inner_x = _CountingEmbedder(model_id="model-x")
    cache_x = _CachingEmbedder(inner_x, source_id="source-a", cache_dir=tmp_path)
    cache_x.encode(["one"])
    cache_x.flush()

    inner_y = _CountingEmbedder(model_id="model-y")
    cache_y = _CachingEmbedder(inner_y, source_id="source-a", cache_dir=tmp_path)
    cache_y.encode(["one"])

    assert inner_y.calls == 1  # different model_id -> different cache file -> miss


# --- Review finding 1: a filename collision must never commingle vectors -----


class _ModelSaltedEmbedder:
    """A counting stub whose returned vector depends on its OWN model_id
    (unlike `_CountingEmbedder` above, which ignores model_id entirely) --
    needed so a test can prove two distinct model ids never read back each
    other's vector for the same sentence text, rather than merely both
    happening to compute an identical-looking vector."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.calls = 0

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(len(text)), float(hash((self.model_id, text)) % 997)] for text in texts]


def test_safe_cache_key_component_can_collide_across_distinct_model_ids():
    # Sanity check pinning the exact collision review finding 1 identified:
    # `_` survives sanitization, so two distinct raw model ids can sanitize
    # to the identical filename component.
    assert _safe_cache_key_component("model_1") == _safe_cache_key_component("model!1")
    assert _safe_cache_key_component("model_1") == _safe_cache_key_component("model 1")


def test_caching_embedder_colliding_model_ids_never_commingle_vectors(tmp_path):
    inner_a = _ModelSaltedEmbedder(model_id="model_1")
    cache_a = _CachingEmbedder(inner_a, source_id="source-a", cache_dir=tmp_path)
    vectors_a = cache_a.encode(["shared sentence text"])
    cache_a.flush()

    inner_b = _ModelSaltedEmbedder(model_id="model!1")
    cache_b = _CachingEmbedder(inner_b, source_id="source-a", cache_dir=tmp_path)
    # Both instances resolve to the SAME on-disk filename -- the collision
    # `_safe_cache_key_component` alone cannot rule out.
    assert cache_b._path == cache_a._path

    vectors_b = cache_b.encode(["shared sentence text"])

    # Model B must never read model A's vector back for the shared
    # sentence text: it must call its own inner embedder instead, and the
    # vector it gets back must be model B's own (not model A's).
    assert inner_b.calls == 1
    assert vectors_b != vectors_a

    # The on-disk artifact, once B flushes, reflects B's own run (the
    # integrity check invalidated A's stale file rather than serving it).
    cache_b.flush()
    on_disk = json.loads(cache_a._path.read_text(encoding="utf-8"))
    assert on_disk["model_id"] == "model!1"
    assert on_disk["vectors"]["shared sentence text"] == vectors_b[0]


# --- Review finding 2: a corrupt cache file must never crash a run -----------


def test_caching_embedder_truncated_json_file_does_not_raise_and_recomputes(tmp_path):
    path = tmp_path / "source-a__model-x.json"
    path.write_text(
        '{"source_id": "source-a", "model_id": "model-x", "vectors": {"one": [0.1',
        encoding="utf-8",
    )

    inner = _CountingEmbedder(model_id="model-x")
    cache = _CachingEmbedder(inner, source_id="source-a", cache_dir=tmp_path)  # must not raise
    vectors = cache.encode(["one"])

    assert inner.calls == 1  # treated as cold -- genuinely re-embedded, not crashed
    assert vectors == [[3.0, float(sum(map(ord, "one")) % 997)]]


def test_caching_embedder_wrong_shape_json_file_does_not_raise_and_recomputes(tmp_path):
    path = tmp_path / "source-a__model-x.json"
    path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

    inner = _CountingEmbedder(model_id="model-x")
    cache = _CachingEmbedder(inner, source_id="source-a", cache_dir=tmp_path)  # must not raise
    vectors = cache.encode(["one"])

    assert inner.calls == 1
    assert vectors == [[3.0, float(sum(map(ord, "one")) % 997)]]


def test_caching_embedder_flush_after_healing_corrupt_file_produces_a_readable_file(tmp_path):
    path = tmp_path / "source-a__model-x.json"
    path.write_text("not json at all {{{", encoding="utf-8")

    inner = _CountingEmbedder(model_id="model-x")
    cache = _CachingEmbedder(inner, source_id="source-a", cache_dir=tmp_path)
    cache.encode(["one"])
    cache.flush()

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["source_id"] == "source-a"
    assert on_disk["model_id"] == "model-x"
    assert on_disk["vectors"]["one"]


def test_run_chunk_embedding_survives_a_corrupt_cache_file(monkeypatch, tmp_path):
    """End-to-end (issue #152 review finding 2): a torn/corrupt cache file
    pre-placed at the exact path a run resolves to must not abort the run
    -- it degrades to a cold re-embed and the pass completes normally."""
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes for corrupt-cache unit test")
    _patch_tree(monkeypatch, tmp_path, _tree_with_one_section("Findings", _BODY))
    cache_dir = tmp_path / "cache"
    chunks_dir = tmp_path / "chunks"

    source_id = chunk_mod.compute_source_id(source)
    cache_dir.mkdir(parents=True)
    (cache_dir / f"{source_id}__model-x.json").write_text(
        '{"source_id": "' + source_id + '", "model_id": "model-x", "vectors": {"broken',
        encoding="utf-8",
    )

    embedder = _CountingEmbedder(model_id="model-x")
    records = run_chunk_embedding(
        source,
        embedder=embedder,
        chunks_dir=chunks_dir,
        chunk_cache_dir=cache_dir,
    )  # must not raise despite the corrupt cache file

    assert embedder.calls > 0
    assert records


# --- run_chunk_embedding: band-param change reuses the embedding cache -------


def _tree_with_one_section(heading: str, body: str) -> dict:
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": heading,
                "children": [{"type": "prose", "order": "1.1", "text": body}],
            }
        ]
    }


def _patch_tree(monkeypatch, tmp_path, tree: dict):
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(json.dumps(tree), encoding="utf-8")
    monkeypatch.setattr(chunk_mod, "tree_path", lambda source_id: tree_file)
    monkeypatch.setattr(chunk_mod, "load_persisted_tree", lambda path: tree)


_BODY = (
    "The river flooded the lowland fields early each spring season. "
    "Farmers built new levees to hold back the rising flood water. "
    "The election commission published new voting rules this month. "
    "Candidates campaigned across every district in the province. "
    "The observatory installed a new infrared telescope array recently. "
    "Astronomers began mapping distant galaxies with far more precision."
)


def test_run_chunk_embedding_band_change_reuses_cache_and_reshapes(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes for band-reuse unit test")
    _patch_tree(monkeypatch, tmp_path, _tree_with_one_section("Findings", _BODY))
    cache_dir = tmp_path / "cache"
    chunks_dir = tmp_path / "chunks"

    cold = _CountingEmbedder(model_id="model-x")
    tight_records = run_chunk_embedding(
        source,
        embedder=cold,
        chunks_dir=chunks_dir,
        chunk_min=10,
        chunk_max=90,
        chunk_cache_dir=cache_dir,
    )
    assert cold.calls > 0

    warm = _CountingEmbedder(model_id="model-x")
    loose_records = run_chunk_embedding(
        source,
        embedder=warm,
        chunks_dir=chunks_dir,
        chunk_min=10,
        chunk_max=10_000,
        chunk_cache_dir=cache_dir,
    )
    assert warm.calls == 0
    assert [r["text"] for r in loose_records] != [r["text"] for r in tight_records]


def test_run_chunk_embedding_missing_source_still_raises_before_touching_cache(tmp_path):
    missing = tmp_path / "does_not_exist.pdf"
    try:
        run_chunk_embedding(
            missing,
            embedder=HashingEmbedder(),
            chunks_dir=tmp_path / "chunks",
            chunk_cache_dir=tmp_path / "cache",
        )
    except MissingSourceError:
        pass
    else:
        raise AssertionError("expected MissingSourceError")
    assert not (tmp_path / "cache").exists()


def test_run_chunk_embedding_missing_tree_still_raises(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    monkeypatch.setattr(chunk_mod, "tree_path", lambda source_id: tmp_path / "no_such_tree.json")
    try:
        run_chunk_embedding(
            source,
            embedder=HashingEmbedder(),
            chunks_dir=tmp_path / "chunks",
            chunk_cache_dir=tmp_path / "cache",
        )
    except MissingTreeError:
        pass
    else:
        raise AssertionError("expected MissingTreeError")
