"""Outer acceptance test for issue #159, part of the chunk-redesign
subproject (charter #148): wiring a REAL sentence-embedding model behind the
existing `Embedder` seam (`axial.chunk.get_embedder` / `AXIAL_EMBEDDER`,
issue #151/slice 01, already merged) as the production default.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given the `AXIAL_EMBEDDER` env var
When  it is unset (the production default)
Then  `get_embedder()` selects a REAL sentence-embedding model -- not the
      deterministic `HashingEmbedder` stub -- identified by its `model_id`
And   when it is `"stub"`, `get_embedder()` still selects the deterministic,
      offline `HashingEmbedder` (the pytest/CI seam is unchanged)
And   merely SELECTING the real embedder (constructing it and reading its
      `model_id`) never imports the heavy embedding dependency (`fastembed`)
      -- the model is loaded/downloaded lazily, only on first `encode`,
      mirroring `axial.extract`'s lazy docling/Unstructured imports
And   (marked `slow`, excluded from the acceptance tier) the real embedder,
      once actually asked to `encode`, returns one real fixed-length vector
      per input text

See plans/chunk-redesign/ (the slice plan for #159, sequenced behind #151's
already-merged `Embedder` seam) and specs/PRODUCT.md §5 stage 4 / §7.7 / §8
P0-4 for the source of truth on the chunk stage this embedder plugs into.
`src/axial/chunk.py`'s `get_embedder` currently returns `HashingEmbedder()`
on BOTH the `stub` and the unset/default branch -- this test's primary red
is exactly that: the default branch must stop being the stub.

Seam decisions this test locks
-----------------------------------------------------------------------
1. Altitude: this test asserts on OBSERVABLE selection behavior --
   `get_embedder().model_id` and `sys.modules` membership -- never on the
   implementer's internal class name. Any real embedder implementation is
   acceptable as long as (a) its `model_id` identifies the real model
   (`"bge-small-en-v1.5"`, the model this issue's context names, must appear
   in it) and (b) constructing/selecting it and reading `model_id` does not
   pull `fastembed` into `sys.modules`.
2. Lazy import: mirroring `axial.extract._build_converter`'s "Local import:
   defers docling's (torch-backed) load until a conversion is actually
   requested" convention, `fastembed` (an ONNX-backed, no-torch dependency)
   must not be imported merely by calling `get_embedder()` and reading
   `model_id` off the result -- only by an actual `encode` call. This is
   what keeps every offline, non-slow acceptance test in this file fast and
   network-free even though `fastembed` is not installed in this
   environment at the time this test is written.
3. Stub path is unchanged: `AXIAL_EMBEDDER=stub` must keep resolving to
   `HashingEmbedder` exactly as before -- this issue only changes the
   unset/default branch, never the explicit stub seam pytest/CI already
   depends on.
4. The `slow` end-to-end test is the ONLY place in this file allowed to
   actually load/download the real model and call `encode`; it is excluded
   from this subproject's acceptance tier (`uv run pytest tests/chunk -q -m
   "not slow"`) and from CI's default run, exactly like
   `test_extract.py::test_extract_runs_docling_end_to_end_on_the_fixture_and_normalizes_it`.
"""

from __future__ import annotations

import sys

import pytest

from axial.chunk import EMBEDDER_ENV_VAR, HashingEmbedder, get_embedder

# The real model this issue's context names as the production default
# (BAAI/bge-small-en-v1.5, 384-dim). This test does not lock the exact
# `model_id` string, only that this substring identifies the model family --
# so an implementer prefixing/suffixing it (e.g. "fastembed:bge-small-en-v1.5")
# still passes.
REAL_MODEL_ID_MARKER = "bge-small-en-v1.5"
REAL_MODEL_DIM = 384

# The heavy dependency that must NOT be imported merely by selecting the
# real embedder -- only by actually calling `encode` on it.
HEAVY_MODULE_NAME = "fastembed"


def test_default_unset_env_selects_the_real_embedding_model(monkeypatch):
    """PRD §5 stage 4 / this issue: with AXIAL_EMBEDDER unset, the
    production default is a REAL sentence-embedding model, not the
    deterministic stub. Today `get_embedder()` returns `HashingEmbedder`
    (model_id starting with "hashing-v1-") on this branch too -- this is the
    primary red this test locks."""
    monkeypatch.delenv(EMBEDDER_ENV_VAR, raising=False)

    embedder = get_embedder()

    assert REAL_MODEL_ID_MARKER in embedder.model_id, (
        f"expected the default (AXIAL_EMBEDDER unset) embedder's model_id to "
        f"identify the real model ({REAL_MODEL_ID_MARKER!r} as a substring), "
        f"got {embedder.model_id!r} -- the unset/default branch of "
        f"get_embedder() must select a real sentence-embedding model, not "
        f"the deterministic HashingEmbedder stub"
    )
    assert not isinstance(embedder, HashingEmbedder), (
        f"expected get_embedder() with AXIAL_EMBEDDER unset to return a real "
        f"embedder, not HashingEmbedder (model_id={embedder.model_id!r})"
    )


def test_stub_env_value_still_selects_the_deterministic_offline_stub(monkeypatch):
    """The pytest/CI seam (AXIAL_EMBEDDER=stub) is unchanged by this issue:
    it must keep resolving to HashingEmbedder, exactly as slice 01 (#151)
    already locked."""
    monkeypatch.setenv(EMBEDDER_ENV_VAR, "stub")

    embedder = get_embedder()

    assert isinstance(embedder, HashingEmbedder), (
        f"expected AXIAL_EMBEDDER=stub to still select HashingEmbedder, got "
        f"{type(embedder).__name__} (model_id={embedder.model_id!r})"
    )
    assert embedder.model_id.startswith("hashing"), (
        f"expected the stub embedder's model_id to start with 'hashing', got {embedder.model_id!r}"
    )


def test_selecting_the_default_embedder_does_not_import_the_heavy_dependency(monkeypatch):
    """Lazy import (mirroring axial.extract's docling/Unstructured lazy
    accessors): merely selecting the real embedder and reading its
    `model_id` must not pull `fastembed` (the ONNX-backed, no-torch heavy
    dependency) into sys.modules -- only an actual `encode` call may load
    the model. This is what lets every offline test in this file run fast,
    with zero network access and zero model download, even before
    `fastembed` is installed at all."""
    if HEAVY_MODULE_NAME in sys.modules:
        pytest.skip(
            f"{HEAVY_MODULE_NAME!r} was already imported earlier in this test "
            f"process (by an unrelated test) -- this test cannot meaningfully "
            f"prove lazy-import behavior in that state"
        )

    monkeypatch.delenv(EMBEDDER_ENV_VAR, raising=False)

    embedder = get_embedder()
    _ = embedder.model_id  # reading model_id alone must never trigger a load

    assert HEAVY_MODULE_NAME not in sys.modules, (
        f"expected selecting the default embedder (get_embedder()) and "
        f"reading its model_id to NOT import {HEAVY_MODULE_NAME!r} -- the "
        f"real model must be lazy-imported/loaded only on first `encode` "
        f"call, mirroring axial.extract's lazy docling/Unstructured "
        f"accessors, so selection alone never triggers a model download"
    )


@pytest.mark.slow
def test_real_embedder_encodes_texts_into_real_fixed_length_vectors(monkeypatch):
    """End-to-end proof the real model actually works (excluded from the
    acceptance tier and CI's default `-m "not slow"` run, exactly like
    test_extract.py's real-docling test): constructing the default embedder
    and calling `encode` returns one real 384-dim vector per input text."""
    monkeypatch.delenv(EMBEDDER_ENV_VAR, raising=False)

    embedder = get_embedder()
    assert REAL_MODEL_ID_MARKER in embedder.model_id

    vectors = embedder.encode(["Some sentence.", "Another sentence."])

    assert len(vectors) == 2, f"expected one vector per input text, got {len(vectors)}"
    for vector in vectors:
        assert len(vector) == REAL_MODEL_DIM, (
            f"expected each vector to have {REAL_MODEL_DIM} dimensions "
            f"(bge-small-en-v1.5), got {len(vector)}"
        )
        assert any(component != 0.0 for component in vector), (
            "expected a real, non-all-zero embedding vector"
        )
