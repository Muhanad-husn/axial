"""Inner-test fixtures for src/axial/test_*.py (issue #81).

The chunk-artifact and tag-pass checkpoints (`axial.chunk.run_chunk_embedding`
/ `read_chunks` and `axial.tag.run_tag`) persist source-keyed files under the
cwd-relative `data/chunks/` and `data/tags/` directories by default. Inner
unit tests run in-process with cwd at the repo root and frequently reuse the
same fixture bytes (hence the same content-hashed source_id), so without
isolation those tests would write into the real `data/` tree and read each
other's (or a previous run's) checkpoints -- making call-count assertions
order- and run-dependent.

This autouse fixture redirects both checkpoint directories to a fresh temp
location per test (the module-global defaults `_default_chunks_dir` /
`_default_tags_dir` fall back to, since `config/pipeline.yaml` declares no
`chunks_dir`/`tags_dir` key), so every in-process test that exercises the
real `run_chunk_embedding`/`read_chunks`/`run_tag` is isolated with no
per-test edits. It only affects in-process tests; the acceptance tests under
tests/ spawn `axial` as a subprocess with cwd set to their own isolated
staging root and are unaffected.
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
