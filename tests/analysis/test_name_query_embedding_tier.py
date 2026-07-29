"""Outer acceptance test for issue #487's fourth resolution tier: nearest
neighbours over the name vectors Reconcile already persisted
(`data/names/embeddings.lance`, table `names`).

Locked behavioral contract -- do not edit once committed green without a
one-line justification in the PR body.

Given a persisted name vector table and a name layer whose index holds
      "Uğur Ümit Üngör", "Charles Tilly" (alias "Tilly") and "Rojava"
  And a stub encoder standing in for the local sentence-transformer
When  find_names("Ungor") is called and tiers 1-3 all miss
Then  "Uğur Ümit Üngör" comes back at tier "embedding", carrying the surface
      form that matched
  And the model name is read from the store's own similarity_manifest.json,
      never a hardcoded string

Given the same store
When  a query's nearest neighbour is an ALIAS surface form
Then  the hit is mapped back through the alias map to its canonical and
      de-duplicated, so one canonical appears once

Given the same store
When  a query no vector is near enough to is called
Then  [] is returned -- the honest resolution failure, never the nearest
      scholar to hand

Given the same store
When  two canonicals are both near enough
Then  they come back by score descending, ties broken by canonical
      ascending, truncated at `limit`, identically on every repeat call

See specs/PHASE-B.md §7.5 (tier 4 and its determinism clause) and §8 P0-2
(the D10 relaxation: "tier 4 is exercised against a stub encoder") for the
source of truth, and plans/phase-b-v1/README.md D10.

Seam decisions
--------------
This module is separate from tests/analysis/test_name_query.py because it is
the only part of the tool set that needs the optional `distill` dependency
group: `lancedb` writes the persisted vector table, so `importorskip` below
skips this whole module when it is absent (`uv sync --group distill`; CI
installs it). Tiers 1-3 need none of it and are pinned there instead.

The encoder is injected, never loaded: `sentence-transformers` is what §7.5
names for the real path and it makes no network call and no LLM call, but a
test does not need a real 384-dim model to pin what tier 4 must DO with the
vectors. The stub returns fixed 4-dim vectors whose cosine geometry is
stated in `_STUB_VECTORS` -- no tuned numbers, just orthogonal axes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

lancedb = pytest.importorskip("lancedb")

UNGOR = "Uğur Ümit Üngör"
TILLY = "Charles Tilly"
ROJAVA = "Rojava"
# A query the corpus genuinely does not hold, and the one the live-vault run
# measured (2026-07-30): cut at cosine 0.4518. NOT "AANES" -- that entity is in
# the real index under its full name, and the acronym failing to reach it is a
# name-layer gap filed against Phase A (specs/PHASE-B.md §7.5).
UNHELD_QUERY = "zzqqx nonexistent scholar"

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
TABLE_NAME = "names"

NODES: list[dict[str, Any]] = [
    {"canonical": UNGOR, "kind": "person", "aliases": []},
    {"canonical": TILLY, "kind": "person", "aliases": ["Tilly"]},
    {"canonical": ROJAVA, "kind": "country/state/place", "aliases": []},
]

# One row per inventory surface form, exactly as `axial.names.run_names`
# persists them. "Tilly" is an ALIAS surface: a hit on it must come back as
# the canonical "Charles Tilly", de-duplicated against the canonical's own
# row.
_ROW_VECTORS: dict[str, list[float]] = {
    UNGOR: [1.0, 0.0, 0.0, 0.0],
    TILLY: [0.0, 1.0, 0.0, 0.0],
    "Tilly": [0.0, 1.0, 0.0, 0.0],
    ROJAVA: [0.0, 0.0, 1.0, 0.0],
}

# What the stub encoder returns per query string. Orthogonal axes, so the
# cosine similarity with each row is just that row's own component: "Ungor"
# sits almost exactly on Üngör's axis, "Chas Tilly" exactly on Tilly's,
# "Rojava border" on both Rojava (0.8) and Üngör (0.6) so the two are ranked,
# and the unheld query on a fourth axis nothing else occupies -- similarity 0
# with every row, so nothing clears the floor.
_STUB_VECTORS: dict[str, list[float]] = {
    "Ungor": [0.99, 0.01, 0.0, 0.0],
    "Chas Tilly": [0.0, 1.0, 0.0, 0.0],
    "Rojava border": [0.6, 0.0, 0.8, 0.0],
    UNHELD_QUERY: [0.0, 0.0, 0.0, 1.0],
}


def _stub_encoder(texts: list[str]) -> list[list[float]]:
    return [_STUB_VECTORS[text] for text in texts]


def _exploding_encoder(_texts: list[str]) -> list[list[float]]:
    raise AssertionError("tiers 1-3 must resolve without ever loading an encoder")


@pytest.fixture(autouse=True)
def _no_real_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")


def _write_name_layer(names_dir: Path) -> None:
    names_dir.mkdir(parents=True, exist_ok=True)
    (names_dir / "index.json").write_text(
        json.dumps({"version": 1, "names": [node["canonical"] for node in NODES]}),
        encoding="utf-8",
    )
    (names_dir / "alias_map.json").write_text(
        json.dumps({"version": 1, "nodes": NODES}, ensure_ascii=False), encoding="utf-8"
    )
    (names_dir / "similarity_manifest.json").write_text(
        json.dumps(
            {
                "model_name": MODEL_NAME,
                "embedding_dim": 4,
                "entry_count": len(_ROW_VECTORS),
                "table_name": TABLE_NAME,
            }
        ),
        encoding="utf-8",
    )
    db = lancedb.connect(names_dir / "embeddings.lance")
    db.create_table(
        TABLE_NAME,
        data=[
            {
                "surface_form": surface_form,
                "kind": "person",
                "count": 1,
                "chunk_ids_json": "[]",
                "cluster_label": -1,
                "vector": vector,
            }
            for surface_form, vector in sorted(_ROW_VECTORS.items())
        ],
        mode="overwrite",
    )


@pytest.fixture
def names_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "names"
    _write_name_layer(directory)
    return directory


def test_tier_four_reaches_a_name_no_exact_or_folded_lookup_can(names_dir: Path):
    """The measured case D10 exists for: the index holds "Uğur Ümit Üngör",
    briefs say Ungor, and diacritics are deliberately outside Phase A's fold
    so tier 3 cannot bridge them."""
    from axial.query import find_names

    hits = find_names("Ungor", 5, names_dir=names_dir, encoder=_stub_encoder)

    assert [hit.canonical for hit in hits] == [UNGOR], (
        f"expected the embedding tier to reach {UNGOR!r}, got {hits!r}"
    )
    assert hits[0].tier == "embedding"
    assert hits[0].matched_on == UNGOR, "the surface form that matched is reported"
    assert hits[0].kind == "person"


def test_tier_four_maps_an_alias_surface_back_to_its_canonical_and_dedupes(names_dir: Path):
    """Two rows ("Charles Tilly" and its alias "Tilly") are equally near.
    One canonical, one hit -- and `matched_on` names a real surface form."""
    from axial.query import find_names

    hits = find_names("Chas Tilly", 5, names_dir=names_dir, encoder=_stub_encoder)

    assert [hit.canonical for hit in hits] == [TILLY]
    assert hits[0].matched_on in (TILLY, "Tilly")


def test_tier_four_returns_empty_rather_than_the_nearest_wrong_name(names_dir: Path):
    """`[]` comes back even with the vector store present and readable: a
    nearest neighbour that is not near enough is not an answer. Handing back
    the closest scholar instead is the failure mode the issue names
    explicitly, and the live-vault run measured this exact cut at 0.4518."""
    from axial.query import find_names

    assert find_names(UNHELD_QUERY, 5, names_dir=names_dir, encoder=_stub_encoder) == []


def test_tier_four_orders_by_score_descending_and_is_deterministic(names_dir: Path):
    from axial.query import find_names

    first = find_names("Rojava border", 5, names_dir=names_dir, encoder=_stub_encoder)
    second = find_names("Rojava border", 5, names_dir=names_dir, encoder=_stub_encoder)

    assert [hit.canonical for hit in first] == [ROJAVA, UNGOR], (
        f"expected score-descending order, got {[hit.canonical for hit in first]!r}"
    )
    assert first == second, "§7.5's determinism contract holds for the ranked tier too"

    truncated = find_names("Rojava border", 1, names_dir=names_dir, encoder=_stub_encoder)
    assert [hit.canonical for hit in truncated] == [ROJAVA]


def test_tiers_one_to_three_never_touch_the_store_even_when_it_exists(names_dir: Path):
    """The tiers are exhausted in order: an exact canonical answers without
    the encoder ever being called, store present or not."""
    from axial.query import find_names

    hits = find_names(ROJAVA, 5, names_dir=names_dir, encoder=_exploding_encoder)

    assert [(hit.canonical, hit.tier) for hit in hits] == [(ROJAVA, "exact")]


def test_the_model_name_comes_from_the_stores_own_manifest(names_dir: Path):
    """§7.5: "the same local sentence-transformer the store names in its own
    `similarity_manifest.json` (`model_name`)" -- never a string hardcoded in
    `src/`. Proven by asking for the model the default encoder factory would
    be built with, without building it."""
    from axial.query.names import resolve_encoder_model_name

    assert resolve_encoder_model_name(names_dir) == MODEL_NAME

    (names_dir / "similarity_manifest.json").write_text(
        json.dumps({"model_name": "some-other/encoder", "table_name": TABLE_NAME}),
        encoding="utf-8",
    )
    assert resolve_encoder_model_name(names_dir) == "some-other/encoder", (
        "the manifest is the source of truth; a hardcoded default would not move"
    )
