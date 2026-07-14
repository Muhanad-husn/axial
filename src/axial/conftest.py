"""Inner-test fixtures for src/axial/test_*.py (issue #81).

The chunk-pass and tag-pass checkpoints (`axial.chunk.run_chunk` /
`axial.tag.run_tag`) persist source-keyed files under the cwd-relative
`data/chunks/` and `data/tags/` directories by default. Inner unit tests run
in-process with cwd at the repo root and frequently reuse the same fixture
bytes (hence the same content-hashed source_id), so without isolation those
tests would write into the real `data/` tree and read each other's (or a
previous run's) checkpoints -- making call-count assertions order- and
run-dependent.

This autouse fixture redirects both checkpoint directories to a fresh temp
location per test (the module-global defaults `_default_chunks_dir` /
`_default_tags_dir` fall back to, since `config/pipeline.yaml` declares no
`chunks_dir`/`tags_dir` key), so every in-process test that exercises the
real `run_chunk`/`run_tag` is isolated with no per-test edits. It only
affects in-process tests; the acceptance tests under tests/ spawn `axial` as
a subprocess with cwd set to their own isolated staging root and are
unaffected.

`CHUNK_CACHE_DIR` (issue #152, `axial.chunk`'s per-source embedding cache)
is redirected the same way, for the same reason: any in-process test that
calls `run_chunk_embedding` without an explicit `chunk_cache_dir` would
otherwise write real, cwd-relative `data/chunk_cache/` cache files during
the test suite, and (worse) a fixture whose content-hashed source_id
happens to repeat across tests would silently read back another test's
cached embeddings, making its `encode`-call-count assertions order- and
run-dependent -- the exact same failure mode `CHUNKS_DIR`/`TAGS_DIR`'s
isolation above already guards against.
"""

from __future__ import annotations

import pytest

import axial.chunk as _chunk_mod
import axial.tag as _tag_mod


@pytest.fixture(autouse=True)
def _isolate_checkpoint_dirs(tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("checkpoints")
    monkeypatch.setattr(_chunk_mod, "CHUNKS_DIR", base / "chunks")
    monkeypatch.setattr(_tag_mod, "TAGS_DIR", base / "tags")
    monkeypatch.setattr(_chunk_mod, "CHUNK_CACHE_DIR", base / "chunk_cache")
