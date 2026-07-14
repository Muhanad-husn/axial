"""Outer acceptance test for issue #152, slice 02 of the chunk-redesign
subproject (charter #148): per-source sentence-embedding caching for the
embedding-based chunk stage (`axial.chunk.run_chunk_embedding`, issue #151 /
slice 01, already merged).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source chunked once with a counting stub embedder (cache cold)
When  the chunk stage runs again on the same source bytes with a
      different [min, max] band
Then  it makes zero new embedding calls (reads data/chunk_cache/), and the
      re-run's chunks match what a from-scratch run with that band would
      produce
And   running again after changing the embedding-model id re-embeds (cache
      key differs)
And   an edited source (a new content-hashed source_id) never reuses
      another source's cache

See plans/chunk-redesign/02-embedding-cache.md (the slice plan this test
encodes) and specs/PRODUCT.md §5 stage 4 / §7.7 / §8 P0-4 for the source of
truth on the underlying chunk stage this caching layer wraps.

Seam decisions this test locks (none of these interfaces exist in
src/axial/chunk.py today -- verified by reading it in full before writing
this test)
-----------------------------------------------------------------------
1. Band parameterization: `run_chunk_embedding` gains two new keyword
   parameters, `chunk_min: int` and `chunk_max: int` (mirroring the band
   guard's existing internal parameters on `_chunk_section_text`, which
   `run_chunk_embedding` today calls with no override -- always the module
   defaults `CHUNK_MIN`/`CHUNK_MAX`). Without a caller-supplied band, "the
   same source, a different band, reshaped from cache" (this slice's whole
   point -- cheap band sweeps, per founder direction, memory
   [[chunk-experiment-caching]]) has no way to be expressed at all. A test
   in this file that passes `chunk_min=`/`chunk_max=` to
   `run_chunk_embedding` is expected to raise `TypeError` (unexpected
   keyword argument) until the implementer adds this seam -- that is an
   intended, correct-reason RED, not a fixture bug.
2. Model-id seam on `Embedder`: every embedder the chunk stage accepts
   (including this file's own `CountingEmbedder` stub) carries a `model_id:
   str` attribute. Per the slice plan ("keyed by source_id + embedding-model
   id"), the cache key must be a function of `(source_id, embedder.model_id)`
   -- reading the model id off the injected embedder itself, since that is
   the object whose identity actually determines what "the embedding model"
   is, mirrors how the real `axial.llm` client selection already works
   (config/provider selects the object; nothing separately re-declares its
   identity to callers). No `model_id` concept exists anywhere in
   `axial.chunk` today.
3. On-disk cache location and behavior: `run_chunk_embedding` persists each
   source's sentence embeddings under `data/chunk_cache/` (gitignored per
   the plan; a cwd-relative default path, mirroring `axial.extract.TREES_DIR`
   / `axial.chunk.CHUNKS_DIR`'s own convention exactly), and on a later call
   for the SAME `(source_id, model_id)` pair, reads that cache back instead
   of calling `embedder.encode` at ALL -- not just at the primary per-section
   embed site in `_chunk_section_text`, but also at the MAX-side re-embed
   site inside `_split_group_to_max` (today `encode` is called at BOTH
   sites; a sentence's embedding is the same value no matter which call site
   asks for it, so a correct cache hit must short-circuit both). This test's
   `CountingEmbedder.calls` must therefore be EXACTLY 0 across an entire warm
   run, not merely lower than the cold run's.
4. This test does not dictate the cache's on-disk file naming/format inside
   `data/chunk_cache/` -- only that (a) at least one file appears there after
   a cold run, and (b) a warm run at a different band, same source bytes,
   same model id, makes zero embedding calls, and its resulting chunk
   records are identical to an independent from-scratch run computed
   directly at that band in a brand-new, never-before-populated cache
   directory (proving the cache stores genuinely reusable embeddings, not
   merely that re-embedding was skipped).

Why this is an in-process test, not a subprocess CLI test
-----------------------------------------------------------------------
The slice plan's own outer test type is "pytest integration test (counting
stub embedder; no network)". Counting embedding calls across a CLI
subprocess invocation is not observable from the test process, so (unlike
tests/test_chunk.py's slice-01 outer test, which shells out to `axial
chunk`) this test calls `axial.chunk.run_chunk_embedding` directly with an
injected `CountingEmbedder`.

Isolation
-----------------------------------------------------------------------
`run_chunk_embedding` resolves `data/trees/`, `data/chunks/`, and
(per this slice) presumably `data/chunk_cache/` as plain, cwd-relative
paths (verified: `axial.extract.TREES_DIR = Path("data/trees")`,
`axial.chunk.CHUNKS_DIR = Path("data/chunks")`, and
`axial.llm.DEFAULT_PIPELINE_CONFIG_PATH = Path("config/pipeline.yaml")`,
all resolved against the process's current working directory, not the repo
root). Every test in this file therefore runs from a freshly created,
empty `tmp_path` directory (via the local `_chdir` context manager, restored
on exit) instead of the real repo root -- the real `data/` tree is never
read from or written to, so tests/conftest.py's directory-snapshot fixture
is not needed here (nothing under the real repo's `data/` is ever touched).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
from pathlib import Path

from axial.chunk import run_chunk_embedding
from axial.envelope import compute_source_id

# Band pair chosen (and verified against today's already-merged slice-01
# band-guard logic, `axial.chunk._chunk_section_text`, before this file was
# written) to force a DIFFERENT chunk split on `SECTION_A_TEXT` below: a
# tight band (BAND1) forces extra MAX-side splits that a loose band (BAND2)
# does not need, so "warm re-run at BAND2 differs from the BAND1 cold run"
# is a meaningful, non-degenerate assertion, not a coincidence of band
# choice.
BAND1 = (100, 300)
BAND2 = (100, 2000)


@contextlib.contextmanager
def _chdir(path: Path):
    """Temporarily change the process's current working directory to
    `path`, restoring the original cwd on exit -- the isolation seam this
    whole file relies on (see module docstring)."""
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


class CountingEmbedder:
    """A deterministic, offline embedder that counts every `encode` call
    (and every text embedded across those calls), so this test can assert
    "zero NEW embedding calls" on a warm, cache-hit run -- across every call
    site `run_chunk_embedding`'s critical path reaches, per seam decision 3
    above.

    Carries its own `model_id`, the seam this slice's cache key is locked to
    (seam decision 2). Embeddings are a bag-of-words hash salted by
    `model_id`, mirroring `axial.chunk.HashingEmbedder`'s own hashing-trick
    technique: two `CountingEmbedder`s sharing a `model_id` produce
    IDENTICAL vectors for the same text (needed for the "warm run matches an
    independent from-scratch run" equality assertion below), while two
    different `model_id`s produce different vectors for the same text -- a
    stand-in for swapping to a genuinely different embedding model.
    """

    def __init__(self, model_id: str, dim: int = 64) -> None:
        self.model_id = model_id
        self._dim = dim
        self.calls = 0
        self.texts_embedded = 0

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.texts_embedded += len(texts)
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            salted = f"{self.model_id}:{token}"
            index = int(hashlib.sha256(salted.encode("utf-8")).hexdigest(), 16) % self._dim
            vector[index] += 1.0
        norm = math.sqrt(sum(component * component for component in vector))
        return [component / norm for component in vector] if norm else vector


# A 12-sentence, three-topic (flood / election / observatory) section body,
# ~765 characters. Verified (via a throwaway script against the already-
# merged slice-01 band guard, before this band pair was locked in) to yield
# 4 chunks under BAND1 and 3 chunks under BAND2 -- different shapes, so a
# band change on this fixture provably reshapes the output.
_SECTION_A_SENTENCES = [
    "The river flooded the lowland fields early each spring season.",
    "Farmers built new levees to hold back the rising flood water.",
    "The flood plain supported rich agricultural yields for decades.",
    "Engineers reinforced the riverbank against future flood damage.",
    "The election commission published new voting rules this month.",
    "Candidates campaigned across every district in the province.",
    "Turnout was expected to exceed prior years by a wide margin.",
    "Poll workers received fresh training on the updated procedures.",
    "The observatory installed a new infrared telescope array recently.",
    "Astronomers began mapping distant galaxies with far more precision.",
    "The data helped refine models of early galaxy formation greatly.",
    "Researchers published their first results in a leading journal.",
]
SECTION_A_TEXT = " ".join(_SECTION_A_SENTENCES)

# A distinct-topic section body used for the "edited source" fixture (issue
# #152's fourth Gherkin clause) -- content unrelated to SECTION_A_TEXT, so a
# records-equality check anywhere in this file can never accidentally pass
# by the two sections coincidentally producing the same chunk text.
_SECTION_B_SENTENCES = [
    "Regional markets reopened gradually as security conditions improved.",
    "Traders reported steadier supply chains across the border crossings.",
    "Local currency exchange rates stabilized after months of volatility.",
]
SECTION_B_TEXT = " ".join(_SECTION_B_SENTENCES)


def _write_source_file(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def _leaf(order: str, text: str) -> dict:
    return {"type": "prose", "order": order, "text": text}


def _section(order: str, heading: str, body_texts: list[str]) -> dict:
    return {
        "type": "prose",
        "order": order,
        "text": heading,
        "label": "section_header",
        "children": [_leaf(f"{order}.{i + 1}", body) for i, body in enumerate(body_texts)],
    }


def _single_section_tree(heading: str, body_text: str) -> dict:
    """A minimal persisted-tree fixture with exactly one top-level prose
    section, matching the node shape `axial.extract`'s tree-builder produces
    (mirrored from tests/test_chunk.py's identical fixture-tree pattern,
    slice 01)."""
    return {"children": [_section("1", heading, [body_text])]}


def _place_tree(source_id: str, tree: dict) -> Path:
    """Write `tree` to the cwd-relative `data/trees/<source_id>.json`, so
    `run_chunk_embedding` (via `axial.extract.tree_path`/`load_persisted_tree`)
    reads it verbatim instead of requiring a real docling conversion."""
    path = Path("data/trees") / f"{source_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tree), encoding="utf-8")
    return path


def test_cold_run_populates_cache_and_warm_rerun_same_key_makes_zero_calls(tmp_path):
    with _chdir(tmp_path):
        source_path = _write_source_file(
            tmp_path / "source.txt", b"chunk-cache fixture source, base case\n"
        )
        source_id = compute_source_id(source_path)
        _place_tree(source_id, _single_section_tree("Findings", SECTION_A_TEXT))

        cold_embedder = CountingEmbedder(model_id="model-x")
        cold_records = run_chunk_embedding(source_path, embedder=cold_embedder)
        assert cold_embedder.calls > 0, (
            "expected the cold run (no cache yet) to call the embedder at "
            "least once -- this is a fixture sanity check, not the feature "
            "under test"
        )
        assert cold_records, "expected at least one chunk record from the cold run"

        cache_dir = Path("data/chunk_cache")
        assert cache_dir.exists() and any(cache_dir.rglob("*")), (
            f"expected the cold run to populate a per-source embedding cache "
            f"under {cache_dir} (plan: 'data/chunk_cache/', gitignored, keyed "
            f"by source_id + embedding-model id), but found nothing there "
            f"after the cold run -- this is exactly the not-yet-built caching "
            f"seam this test pins (see module docstring, seam decision 3)"
        )

        warm_embedder = CountingEmbedder(model_id="model-x")
        warm_records = run_chunk_embedding(source_path, embedder=warm_embedder)
        assert warm_embedder.calls == 0, (
            f"expected a warm re-run on the SAME source bytes with the SAME "
            f"embedding-model id to make ZERO new embedding calls (reads the "
            f"on-disk cache instead of calling embedder.encode again -- issue "
            f"#152's acceptance criterion), got {warm_embedder.calls} calls "
            f"({warm_embedder.texts_embedded} texts embedded)"
        )
        assert warm_records == cold_records, (
            "expected the warm re-run's chunk records to be byte-identical to "
            "the cold run's (identical inputs, identical band) -- caching "
            "must never change chunk output"
        )


def test_band_change_reuses_cached_embeddings_and_reshapes_matching_from_scratch_run(
    tmp_path,
):
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    root_a.mkdir()
    root_b.mkdir()
    source_bytes = b"chunk-cache fixture source, band-reshape case\n"

    with _chdir(root_a):
        source_path = _write_source_file(root_a / "source.txt", source_bytes)
        source_id = compute_source_id(source_path)
        _place_tree(source_id, _single_section_tree("Findings", SECTION_A_TEXT))

        cold_embedder = CountingEmbedder(model_id="model-x")
        band1_records = run_chunk_embedding(
            source_path, embedder=cold_embedder, chunk_min=BAND1[0], chunk_max=BAND1[1]
        )
        assert cold_embedder.calls > 0, (
            "expected the cold run at BAND1 to call the embedder at least "
            "once -- fixture sanity check"
        )

        warm_embedder = CountingEmbedder(model_id="model-x")
        band2_warm_records = run_chunk_embedding(
            source_path, embedder=warm_embedder, chunk_min=BAND2[0], chunk_max=BAND2[1]
        )
        assert warm_embedder.calls == 0, (
            f"expected re-running on the SAME source bytes with the SAME "
            f"embedding-model id but a DIFFERENT [min, max] band ({BAND1} -> "
            f"{BAND2}) to make ZERO new embedding calls -- issue #152's "
            f"central acceptance criterion: a band sweep reshapes cached "
            f"embeddings without re-embedding. Got {warm_embedder.calls} "
            f"calls ({warm_embedder.texts_embedded} texts embedded). This "
            f"requires BOTH the band-parameterization seam (run_chunk_embedding "
            f"accepting chunk_min/chunk_max) AND the cache seam (see module "
            f"docstring, seam decisions 1 and 3)"
        )

        band1_texts = [r["text"] for r in band1_records]
        band2_texts = [r["text"] for r in band2_warm_records]
        assert band2_texts != band1_texts, (
            f"expected BAND2 {BAND2} to reshape the chunk output relative to "
            f"BAND1 {BAND1} on this fixture (chosen to force a different "
            f"split) -- got identical text regardless of band, which would "
            f"mean the re-run never actually reshaped from the cached "
            f"embeddings at all"
        )

    with _chdir(root_b):
        # Same filename + identical bytes -> the SAME content-hashed
        # source_id (axial.envelope.compute_source_id), but a brand-new,
        # never-before-populated cache directory: an independent
        # from-scratch computation at BAND2, to compare against the warm
        # re-run above.
        source_path_b = _write_source_file(root_b / "source.txt", source_bytes)
        source_id_b = compute_source_id(source_path_b)
        assert source_id_b == source_id, (
            "expected identical source bytes + filename to produce the same "
            "source_id in a fresh root -- fixture sanity check"
        )
        _place_tree(source_id_b, _single_section_tree("Findings", SECTION_A_TEXT))

        fresh_embedder = CountingEmbedder(model_id="model-x")
        fresh_band2_records = run_chunk_embedding(
            source_path_b, embedder=fresh_embedder, chunk_min=BAND2[0], chunk_max=BAND2[1]
        )
        assert fresh_embedder.calls > 0, (
            "expected a truly from-scratch run (fresh cache directory) at "
            "BAND2 to call the embedder at least once -- fixture sanity check"
        )

    assert band2_warm_records == fresh_band2_records, (
        "expected the warm re-run's BAND2 chunk records (reshaped from cached "
        "embeddings, zero new embed calls) to be IDENTICAL to an independent "
        "from-scratch run computed directly at BAND2 in a brand-new cache "
        "directory -- proves the cache stores genuinely reusable embeddings, "
        "not merely that re-embedding was skipped"
    )


def test_model_id_change_forces_reembed(tmp_path):
    with _chdir(tmp_path):
        source_path = _write_source_file(
            tmp_path / "source.txt", b"chunk-cache fixture source, model-id case\n"
        )
        source_id = compute_source_id(source_path)
        _place_tree(source_id, _single_section_tree("Findings", SECTION_A_TEXT))

        cold_embedder = CountingEmbedder(model_id="model-x")
        run_chunk_embedding(source_path, embedder=cold_embedder)
        assert cold_embedder.calls > 0, (
            "expected the cold run to call the embedder at least once -- fixture sanity check"
        )

        same_model_embedder = CountingEmbedder(model_id="model-x")
        run_chunk_embedding(source_path, embedder=same_model_embedder)
        assert same_model_embedder.calls == 0, (
            "expected a warm re-run with the SAME embedding-model id to make "
            "zero embedding calls -- this is the cache-exists precondition "
            "that makes this test's real assertion below meaningful (without "
            "a cache at all, changing the model id would trivially always "
            "re-embed, proving nothing about the cache key)"
        )

        different_model_embedder = CountingEmbedder(model_id="model-y")
        run_chunk_embedding(source_path, embedder=different_model_embedder)
        assert different_model_embedder.calls > 0, (
            "expected changing the embedding-model id to invalidate the "
            "cache (cache key = source_id + model id, per the slice plan) "
            "and force a re-embed, got zero calls -- this means the cache "
            "key does not actually include the embedding-model id"
        )


def test_edited_source_never_reuses_another_sources_cache(tmp_path):
    with _chdir(tmp_path):
        source_path = tmp_path / "source.txt"
        _write_source_file(source_path, b"chunk-cache fixture source A, version 1\n")
        source_id_a = compute_source_id(source_path)
        _place_tree(source_id_a, _single_section_tree("Findings", SECTION_A_TEXT))

        embedder_a_cold = CountingEmbedder(model_id="model-x")
        records_a_cold = run_chunk_embedding(source_path, embedder=embedder_a_cold)
        assert embedder_a_cold.calls > 0, (
            "expected source A's cold run to call the embedder at least "
            "once -- fixture sanity check"
        )

        # "Edit" the source in place: SAME filename/stem as source A, but
        # DIFFERENT bytes -> a different content-hashed source_id
        # (axial.envelope.compute_source_id hashes the file's own bytes).
        # Deliberately reusing the same filename stresses a cache
        # implementation that might (incorrectly) key on filename/path alone
        # rather than the full source_id.
        _write_source_file(source_path, b"chunk-cache fixture source A, version 1, edited\n")
        source_id_b = compute_source_id(source_path)
        assert source_id_b != source_id_a, (
            "expected editing the source's bytes to produce a different "
            "content-hashed source_id -- fixture sanity check (if this "
            "fails, the fixture itself is broken, not the implementation "
            "under test)"
        )
        _place_tree(source_id_b, _single_section_tree("Notes", SECTION_B_TEXT))

        embedder_b_cold = CountingEmbedder(model_id="model-x")
        run_chunk_embedding(source_path, embedder=embedder_b_cold)
        assert embedder_b_cold.calls > 0, (
            "expected the edited source (a new source_id, but the SAME "
            "filename stem as the original) to be embedded fresh rather "
            "than incorrectly reusing the original source's cache entry"
        )

        # Restore the original bytes so a re-run against source_id_a can be
        # driven again, and prove source B's cold run did not clobber A's
        # cache entry.
        _write_source_file(source_path, b"chunk-cache fixture source A, version 1\n")
        assert compute_source_id(source_path) == source_id_a, (
            "expected restoring the original bytes to reproduce source A's "
            "original source_id -- fixture sanity check"
        )

        embedder_a_warm = CountingEmbedder(model_id="model-x")
        records_a_warm = run_chunk_embedding(source_path, embedder=embedder_a_warm)
        assert embedder_a_warm.calls == 0, (
            "expected source A's cache entry to remain intact and reusable "
            "after a DIFFERENT source (B, same filename stem) was cached "
            "under the same embedding-model id -- a cache keyed only on "
            "filename/stem (rather than the full content-hashed source_id) "
            "would make this re-run collide with B's cache entry and "
            "re-embed (or worse, silently reuse B's embeddings)"
        )
        assert records_a_warm == records_a_cold, (
            "expected source A's re-run to reproduce its original cold-run "
            "chunk records exactly, proving source B's cache write did not "
            "corrupt or overwrite source A's cache entry"
        )
