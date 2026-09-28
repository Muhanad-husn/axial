"""Inner unit tests for the name-layer query API (issue #487,
specs/PHASE-B.md §7.5): the properties underneath
tests/analysis/test_name_query.py's scenarios, each in isolation --
resolution-tier edges and the alias-fold matching every caller shares.

DEC-75 (issue #853) retired the name pages, the embedding tier, and the
`name_neighbors`/`who_cites`/`who_argues_against`/`where_names_meet` walk
tools: `find_names`/`get_name` now answer purely from the store (`notes.db`,
`axial.query.store`), never a page or a nearest-neighbour vector search.
Every fixture below that used to write a name page now writes a `notes.db`
instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.query import store as note_store
from axial.query.names import (
    NameNotFoundError,
    as_string_list,
    canonical_for_surface,
    coverage_count,
    find_names,
    get_name,
)

# -- fixture helpers ----------------------------------------------------------


def _write_layer(names_dir: Path, nodes: list[dict[str, Any]], *, index_extra=()) -> None:
    names_dir.mkdir(parents=True, exist_ok=True)
    names = [node["canonical"] for node in nodes] + list(index_extra)
    (names_dir / "index.json").write_text(
        json.dumps({"version": 1, "names": names}, ensure_ascii=False), encoding="utf-8"
    )
    (names_dir / "alias_map.json").write_text(
        json.dumps({"version": 1, "nodes": nodes}, ensure_ascii=False), encoding="utf-8"
    )


def _source_of(chunk_id: str) -> str:
    """The bare source-id prefix a fixture `chunk_id` carries, or `""` for
    one deliberately shaped not to parse -- `note_names.source_id` is a
    plain column now (DEC-75), never derived by the reader from the id, so a
    fixture states it directly rather than needing a real parseable id."""
    return chunk_id.split("_", 1)[0] if "_" in chunk_id else ""


def _write_store(
    vault_dir: Path,
    doors: dict[str, tuple[str | None, list[str]]],
) -> None:
    """A `notes.db` carrying one door per `canonical -> (kind, member_
    chunk_ids)` entry -- the store-based replacement for the retired name
    page fixture (DEC-75, issue #853): `find_names`/`get_name`/
    `coverage_count` all answer from this store now, never a page."""
    from axial.query.names import fold_surface_form

    sources_seen: dict[str, None] = {}
    notes_by_chunk: dict[str, tuple] = {}
    note_names: list[tuple] = []
    names: list[tuple] = []
    for canonical, (kind, member_ids) in doors.items():
        names.append((canonical, kind, fold_surface_form(canonical)))
        for chunk_id in member_ids:
            source_id = _source_of(chunk_id)
            if source_id:
                sources_seen.setdefault(source_id, None)
            notes_by_chunk.setdefault(
                chunk_id, (chunk_id, source_id or None, "Section", None, "A claim.", None)
            )
            note_names.append((chunk_id, source_id, canonical, kind))
    note_store.write_store(
        note_store.store_path(vault_dir),
        sources=[(source_id, "Author", "Title", "2000", 2000) for source_id in sources_seen],
        notes=list(notes_by_chunk.values()),
        names=names,
        note_names=note_names,
        note_arguing_against=[],
        note_citations=[],
    )


def _write_prose_note(vault_dir: Path, chunk_id: str, answers: dict[str, Any]) -> None:
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "A Section",
        "chunk_text": f"{chunk_id} text.",
        "source_meta": {"author": "A", "title": "T", "date": 2020},
        "answers": answers,
    }
    rendered = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    (prose_dir / f"{chunk_id}.md").write_text(f"---\n{rendered}---\nBody.\n", encoding="utf-8")


# -- the surface fold is Phase A's own, not a second copy ----------------------


def test_the_fold_is_reused_from_phase_a_not_re_derived():
    """§7.16/issue #463's fold: case, whitespace and punctuation, with a
    hyphen to a SPACE and everything else to nothing, and diacritics
    deliberately untouched. Asserted through this module's own import so a
    future local re-implementation of the rule fails here."""
    from axial.name_candidates import _normalize_form
    from axial.query.names import fold_surface_form

    assert fold_surface_form is _normalize_form
    assert fold_surface_form("Charles-Tilly") == fold_surface_form("charles  tilly")
    assert fold_surface_form("#MeToo") == "metoo"
    assert fold_surface_form("Üngör") != fold_surface_form("Ungor"), (
        "diacritics are out of scope for the fold -- that is what tier 4 used to be for"
    )


# -- resolution tiers ---------------------------------------------------------


def test_tier_two_alias_hit_resolves_to_every_node_claiming_that_alias(tmp_path):
    """One alias string can sit under two nodes in a dirty map. Both come
    back, in ascending-canonical order -- never whichever the file happened
    to list last."""
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {"canonical": "Zed Tilly", "kind": "person", "aliases": ["Tilly"]},
            {"canonical": "Charles Tilly", "kind": "person", "aliases": ["Tilly"]},
        ],
    )

    hits = find_names("Tilly", 10, names_dir=names_dir, vault_dir=tmp_path / "vault")

    assert [hit.canonical for hit in hits] == ["Charles Tilly", "Zed Tilly"]
    assert {hit.tier for hit in hits} == {"alias"}


def test_a_name_in_the_index_with_no_alias_map_node_still_resolves(tmp_path):
    """§7.16's closing rule -- nothing is dropped: a surface no cluster
    reached survives as its own canonical with no aliases."""
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [], index_extra=["lonely concept"])

    hits = find_names("lonely concept", 10, names_dir=names_dir, vault_dir=tmp_path / "vault")

    assert [(hit.canonical, hit.tier, hit.kind, hit.aliases) for hit in hits] == [
        ("lonely concept", "exact", None, [])
    ]


def test_member_count_is_none_when_this_vault_holds_no_door_for_the_name(tmp_path):
    """Reported, not filled in with a 0 that would read like real, thin
    coverage."""
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "orphan", "kind": "concept", "aliases": []}])

    hits = find_names("orphan", 10, names_dir=names_dir, vault_dir=tmp_path / "vault")

    assert hits[0].member_count is None


def test_no_name_layer_at_all_resolves_nothing_rather_than_raising(tmp_path):
    assert find_names("anything", 10, names_dir=tmp_path / "absent", vault_dir=tmp_path) == []


def test_limit_of_zero_returns_empty(tmp_path):
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "a concept", "kind": "concept", "aliases": []}])

    assert find_names("a concept", 0, names_dir=names_dir, vault_dir=tmp_path) == []


# -- the door slate (issue #632) -----------------------------------------------


def test_find_names_exact_hit_does_not_suppress_a_bigger_same_family_page(tmp_path):
    """Issue #632's own motivating case: `Mandate` used to return only
    itself because an exact hit stopped every other tier. The new
    `contains` route now also surfaces `French Mandate`, a bigger
    same-family door, and ranks it AHEAD of the exact hit by its own
    (source_count, member_count) -- an exact hit is no longer a ceiling on
    what the slate offers."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {"canonical": "Mandate", "kind": "concept", "aliases": []},
            {"canonical": "French Mandate", "kind": "concept", "aliases": []},
        ],
    )
    _write_store(
        vault_dir,
        {
            "Mandate": (
                "concept",
                ["srcA_000_intro_001", "srcA_000_intro_002", "srcB_000_intro_001"],
            ),
            "French Mandate": (
                "concept",
                [
                    "srcD_000_intro_001",
                    "srcE_000_intro_001",
                    "srcF_000_intro_001",
                    "srcD_000_intro_002",
                    "srcE_000_intro_002",
                ],
            ),
        },
    )

    hits = find_names("Mandate", 10, names_dir=names_dir, vault_dir=vault_dir)

    assert [(hit.canonical, hit.tier, hit.member_count, hit.source_count) for hit in hits] == [
        ("French Mandate", "contains", 5, 3),
        ("Mandate", "exact", 3, 2),
    ]


def test_find_names_ranks_a_work_kind_page_last_regardless_of_size(tmp_path):
    """Issue #632: 8,583 of the real vault's names used to be book/article
    titles; a concept query's `contains` scan turns up work-titled doors
    sharing its words, and those must rank LAST even when they are the
    bigger door -- a work is a citation target, not an argument page."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {"canonical": "Culture of Sectarianism", "kind": "work", "aliases": []},
            {"canonical": "sectarianism", "kind": "concept", "aliases": []},
        ],
    )
    _write_store(
        vault_dir,
        {
            "Culture of Sectarianism": (
                "work",
                [f"srcBig{i}_000_intro_001" for i in range(5)],
            ),
            "sectarianism": ("concept", ["srcSmall_000_intro_001"]),
        },
    )

    hits = find_names("sectarianism", 10, names_dir=names_dir, vault_dir=vault_dir)

    assert [hit.canonical for hit in hits] == ["sectarianism", "Culture of Sectarianism"], (
        "the work-kind door ranks last even though it spans five sources against one"
    )


def test_compound_query_fallback_offers_the_best_door_per_content_word(tmp_path):
    """Issue #632's own motivating compound case: no name literally carries
    "mandate-era institutions Syria" as a phrase, so each content word is
    resolved separately and the best door per word stands in for group 1,
    marked `tier="word"` so a caller can tell "your phrase matched no name;
    this word did" from a real phrase resolution -- and `matched_on` names
    the query WORD, not the name, for the same reason."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {"canonical": "French Mandate", "kind": "concept", "aliases": []},
            {"canonical": "Syria", "kind": "country/state/place", "aliases": []},
        ],
    )
    _write_store(
        vault_dir,
        {
            "French Mandate": (
                "concept",
                ["srcD_000_intro_001", "srcE_000_intro_001", "srcF_000_intro_001"],
            ),
            "Syria": ("country/state/place", [f"src{i}_000_intro_001" for i in range(4)]),
        },
    )

    hits = find_names(
        "mandate-era institutions Syria", 10, names_dir=names_dir, vault_dir=vault_dir
    )

    by_canonical = {hit.canonical: hit for hit in hits}
    assert by_canonical["French Mandate"].tier == "word"
    assert by_canonical["French Mandate"].matched_on == "mandate"
    assert by_canonical["Syria"].tier == "word"
    assert by_canonical["Syria"].matched_on == "Syria"
    assert "institutions" not in by_canonical and "era" not in by_canonical, (
        "a content word with no door in this fixture adds none"
    )


def test_compound_query_fallback_orders_words_by_page_name_rarity_not_query_order(tmp_path):
    """Issue #632, second round: a generic word that names hundreds of pages
    (`Syrian`, `de`, `state`) used to lead the fallback slate ahead of the
    word that actually names the query's topic, bumping an
    already-correct door out of first place. The per-word doors are now
    ordered by how many page names each word appears in -- rarest first --
    never by query order and never by door size: `common` appears in four
    of this fixture's names, `rare` in one, and `rare` leads even though it
    comes SECOND in the query text."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    canonicals = ["Rare Concept", "Common Era", "Common Ground", "Common Law", "Common Sense"]
    _write_layer(
        names_dir, [{"canonical": c, "kind": "concept", "aliases": []} for c in canonicals]
    )
    _write_store(
        vault_dir, {c: ("concept", [f"{c.replace(' ', '')}_000_a_001"]) for c in canonicals}
    )

    # Neither word, nor the two-word phrase, is any name's own name, so
    # this exercises the fallback rather than group 1's literal routes.
    hits = find_names("common rare", 10, names_dir=names_dir, vault_dir=vault_dir)

    word_hits = [hit for hit in hits if hit.tier == "word"]
    assert [hit.matched_on for hit in word_hits] == ["rare", "common"], (
        "the rarer word's door leads even though 'common' comes first in the query text"
    )
    assert word_hits[0].canonical == "Rare Concept"
    assert word_hits[1].canonical == "Common Era", (
        "among the four 'common' names the usual group-1 ranking still decides which one wins"
    )


def test_find_names_ordering_is_deterministic_including_group_one_ties(tmp_path):
    """Issue #632: two names tied on kind/source_count/member_count break by
    canonical ascending, and the same query returns the same slate on every
    call -- the determinism contract §7.5 requires, extended to the slate."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {"canonical": "Zeta Mandate", "kind": "concept", "aliases": []},
            {"canonical": "Alpha Mandate", "kind": "concept", "aliases": []},
        ],
    )
    _write_store(
        vault_dir,
        {
            "Zeta Mandate": ("concept", ["srcX_000_intro_001"]),
            "Alpha Mandate": ("concept", ["srcY_000_intro_001"]),
        },
    )

    first = find_names("Mandate", 10, names_dir=names_dir, vault_dir=vault_dir)
    second = find_names("Mandate", 10, names_dir=names_dir, vault_dir=vault_dir)

    assert [hit.canonical for hit in first] == ["Alpha Mandate", "Zeta Mandate"], (
        "a tie on kind/source_count/member_count breaks by canonical ascending"
    )
    assert first == second, "the same query over the same vault returns the same slate every call"


def test_canonical_for_surface_prefers_exact_then_alias_then_fold(tmp_path):
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {"canonical": "Rojava", "kind": "country/state/place", "aliases": ["North-East Syria"]},
            {"canonical": "PYD", "kind": "institution/group", "aliases": []},
        ],
    )
    from axial.query.names import _name_layer

    layer = _name_layer(names_dir)

    assert canonical_for_surface("Rojava", layer) == "Rojava"
    assert canonical_for_surface("North-East Syria", layer) == "Rojava"
    assert canonical_for_surface("north east syria", layer) == "Rojava"
    assert canonical_for_surface("a surface the layer never saw", layer) is None


# -- get_name (answered from the store, DEC-75) --------------------------------


def test_get_name_on_a_member_whose_chunk_id_does_not_parse_reports_no_source_id(tmp_path):
    vault_dir = tmp_path / "vault"
    _write_store(vault_dir, {"a concept": ("concept", ["not-a-real-chunk-id"])})

    page = get_name("a concept", vault_dir=vault_dir)

    assert page.members[0].source_id is None
    assert page.members[0].chunk_id == "not-a-real-chunk-id"


def test_get_name_raises_naming_the_canonical_when_no_door_exists(tmp_path):
    _write_store(tmp_path / "vault", {})

    with pytest.raises(NameNotFoundError) as exc_info:
        get_name("absent name", vault_dir=tmp_path / "vault")
    assert "absent name" in str(exc_info.value)


def test_get_name_raises_when_the_vault_carries_no_store_at_all(tmp_path):
    (tmp_path / "vault").mkdir(parents=True)

    with pytest.raises(NameNotFoundError):
        get_name("absent name", vault_dir=tmp_path / "vault")


def test_get_name_truncates_members_at_limit_but_not_member_count(tmp_path):
    """issue #505: `Syria` returns 962 members with no `limit` at all, and
    re-sending that list on every later turn flooded a real retrieval-loop
    prompt to ~72,000 characters. `members` is capped; `member_count` is the
    door's own total and must stay the true count regardless, so a caller
    can see both the window and the whole it is a window onto."""
    vault_dir = tmp_path / "vault"
    chunk_ids = [f"m{i}" for i in range(1, 5)]
    _write_store(vault_dir, {"a concept": ("concept", chunk_ids)})

    capped = get_name("a concept", 2, vault_dir=vault_dir)
    assert [m.chunk_id for m in capped.members] == ["m1", "m2"], (
        "these chunk_ids carry no parseable source_id (issue #562's round-robin "
        "groups every one of them under the same empty-string bucket), so the "
        "spread degenerates to `chunk_id` order here -- see the round-robin-"
        "specific tests below for a fixture with real source spread"
    )
    assert capped.member_count == 4, "member_count is the true total, never capped"

    uncapped = get_name("a concept", 10, vault_dir=vault_dir)
    assert [m.chunk_id for m in uncapped.members] == chunk_ids
    assert uncapped.member_count == 4

    default = get_name("a concept", vault_dir=vault_dir)
    assert [m.chunk_id for m in default.members] == chunk_ids, (
        "DEFAULT_LIMIT (10) does not truncate a 4-member door"
    )


def test_get_name_truncated_window_reaches_a_primary_source_deep_in_chunk_id_order(tmp_path):
    """issue #562: `Charles Tilly`'s own door groups members by `source_id`
    alphabetically, and two secondary sources (`malesevic-2004`,
    `mann-2012`) hold far more members between them than the primary source
    (`tilly-1978`) -- the exact hub shape measured on the real vault, where
    Tilly's own book sat at member 108 of 154. A plain prefix truncation at
    any limit under 74 never reaches it; the round-robin spread reaches it
    as soon as every distinct source has contributed once, which for a
    4-source door is limit=4."""
    vault_dir = tmp_path / "vault"
    chunk_ids = (
        ["bayat-1997_1_a_001"]
        + [f"malesevic-2004_1_a_{i:03d}" for i in range(1, 31)]
        + [f"mann-2012_1_a_{i:03d}" for i in range(1, 41)]
        + [f"tilly-1978_1_a_{i:03d}" for i in range(1, 4)]
    )
    _write_store(vault_dir, {"Charles Tilly": ("person", chunk_ids)})
    assert not any(cid.startswith("tilly") for cid in chunk_ids[:10]), (
        "sanity: a plain prefix at a real-world default limit never reaches tilly"
    )

    page = get_name("Charles Tilly", 4, vault_dir=vault_dir)

    assert [m.chunk_id for m in page.members] == [
        "bayat-1997_1_a_001",
        "malesevic-2004_1_a_001",
        "mann-2012_1_a_001",
        "tilly-1978_1_a_001",
    ]
    assert page.member_count == len(chunk_ids), "member_count stays the true, uncapped total"


def test_get_name_limit_covering_every_member_returns_chunk_id_order(tmp_path):
    """The spread is a truncation rule, not a re-sort (issue #562): a
    `limit` that already covers every member must see `chunk_id` order,
    byte-for-byte, whether `limit` equals `member_count` exactly or exceeds
    it (`axial.query.store.name_members` orders by `chunk_id`)."""
    vault_dir = tmp_path / "vault"
    chunk_ids = (
        ["bayat-1997_1_a_001"]
        + [f"malesevic-2004_1_a_{i:03d}" for i in range(1, 4)]
        + [f"mann-2012_1_a_{i:03d}" for i in range(1, 4)]
        + [f"tilly-1978_1_a_{i:03d}" for i in range(1, 3)]
    )
    _write_store(vault_dir, {"Charles Tilly": ("person", chunk_ids)})
    ordered = sorted(chunk_ids)

    exact = get_name("Charles Tilly", len(chunk_ids), vault_dir=vault_dir)
    assert [m.chunk_id for m in exact.members] == ordered

    over = get_name("Charles Tilly", len(chunk_ids) + 5, vault_dir=vault_dir)
    assert [m.chunk_id for m in over.members] == ordered


def test_get_name_truncated_window_is_deterministic_across_repeated_calls(tmp_path):
    vault_dir = tmp_path / "vault"
    chunk_ids = (
        [f"aaa-src_1_a_{i:03d}" for i in range(1, 6)]
        + [f"bbb-src_1_a_{i:03d}" for i in range(1, 6)]
        + [f"ccc-src_1_a_{i:03d}" for i in range(1, 6)]
    )
    _write_store(vault_dir, {"a concept": ("concept", chunk_ids)})

    first = [m.chunk_id for m in get_name("a concept", 5, vault_dir=vault_dir).members]
    second = [m.chunk_id for m in get_name("a concept", 5, vault_dir=vault_dir).members]

    assert first == second
    assert first == [
        "aaa-src_1_a_001",
        "bbb-src_1_a_001",
        "ccc-src_1_a_001",
        "aaa-src_1_a_002",
        "bbb-src_1_a_002",
    ]


def test_get_name_small_window_places_an_unparsed_member_first_and_does_not_crash(tmp_path):
    """A member whose `chunk_id` does not parse has `source_id=None`. It is
    grouped under the empty string, which sorts before any real `source_id`
    -- issue #517's own placement -- so it is reachable in a small window
    rather than dropped, and grouping it never raises.

    Three groups here (the unparsed one, `aaa-src`, `bbb-src`), so since
    issue #802 a `limit` of 2 returns one member from each rather than
    stopping after two: `bbb-src`'s SECOND note is what the window still
    excludes, which is a rotation doing its job rather than a book being
    dropped."""
    vault_dir = tmp_path / "vault"
    chunk_ids = ["not-a-real-chunk-id", "aaa-src_1_a_001", "bbb-src_1_a_001", "bbb-src_1_a_002"]
    _write_store(vault_dir, {"a concept": ("concept", chunk_ids)})

    page = get_name("a concept", 2, vault_dir=vault_dir)

    assert [m.chunk_id for m in page.members] == [
        "not-a-real-chunk-id",
        "aaa-src_1_a_001",
        "bbb-src_1_a_001",
    ]
    assert page.members[0].source_id is None


def test_get_name_resolves_an_alias_or_folded_argument_to_the_same_door(tmp_path):
    """`get_name`'s own `canonical` argument must be resolved through the
    alias map -- a caller passing an alias, or a case/whitespace variant
    that only folds to the canonical, must not raise `NameNotFoundError`
    just because it never equalled the raw canonical string exactly."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [{"canonical": "Infrastructural power", "kind": "concept", "aliases": ["infra power"]}],
    )
    _write_store(vault_dir, {"Infrastructural power": ("concept", ["src_1_a_001"])})

    by_canonical = get_name("Infrastructural power", vault_dir=vault_dir, names_dir=names_dir)
    by_alias = get_name("infra power", vault_dir=vault_dir, names_dir=names_dir)
    by_fold = get_name("infrastructural power", vault_dir=vault_dir, names_dir=names_dir)

    assert by_canonical.canonical == "Infrastructural power"
    assert by_alias.canonical == by_canonical.canonical
    assert by_alias.member_count == by_canonical.member_count == 1
    assert [m.chunk_id for m in by_alias.members] == [m.chunk_id for m in by_canonical.members]
    assert by_fold.canonical == by_canonical.canonical


def test_get_name_still_raises_for_a_name_the_alias_map_does_not_carry(tmp_path):
    """The widened resolution must not turn an honest miss into a wrong
    door: a query that resolves through none of the three exact tiers still
    raises `NameNotFoundError`, even with a populated layer that carries
    other names."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [{"canonical": "Infrastructural power", "kind": "concept", "aliases": ["infra power"]}],
    )
    _write_store(vault_dir, {"Infrastructural power": ("concept", ["src_1_a_001"])})

    with pytest.raises(NameNotFoundError) as exc_info:
        get_name("a wholly unrelated name", vault_dir=vault_dir, names_dir=names_dir)
    assert "a wholly unrelated name" in str(exc_info.value)


def test_get_name_disagreement_is_always_none(tmp_path):
    """Gather, the one writer of a name's disagreement section, is retired
    (DEC-75, issue #853): `get_name` never populates it any more."""
    vault_dir = tmp_path / "vault"
    _write_store(vault_dir, {"a concept": ("concept", ["src_1_a_001"])})

    assert get_name("a concept", vault_dir=vault_dir).disagreement is None


# -- the reader's own get_chunk (co-located, unaffected by DEC-75) ------------


def test_get_chunk_exposes_both_halves_of_the_mixed_frame_raw(tmp_path):
    """The note reader reports what the note carries and resolves nothing:
    `absent key` is information a single resolved field would destroy."""
    from axial.query import get_chunk

    vault_dir = tmp_path / "vault"
    _write_prose_note(
        vault_dir,
        "src_1_new_001",
        {"position_of": "the author", "position": "the new frame's answer"},
    )
    _write_prose_note(vault_dir, "src_1_old_001", {"position_of": "the old frame's answer"})

    new_frame = get_chunk("src_1_new_001", vault_dir=vault_dir)
    assert (new_frame.position_of, new_frame.position) == (
        "the author",
        "the new frame's answer",
    )

    old_frame = get_chunk("src_1_old_001", vault_dir=vault_dir)
    assert (old_frame.position_of, old_frame.position) == ("the old frame's answer", None)


# -- coverage_count (answered from the store, DEC-75) --------------------------


def test_coverage_count_over_a_vault_with_no_store_returns_empty(tmp_path):
    (tmp_path / "vault" / "prose").mkdir(parents=True)

    assert coverage_count(vault_dir=tmp_path / "vault") == {}


def test_coverage_count_reads_the_store_door_not_a_recount(tmp_path):
    """`coverage_count` reads `axial.query.store.all_doors`'s own GROUP BY
    over `note_names` -- the door's real member count, never independently
    stated and never recomputed a second way (D2)."""
    vault_dir = tmp_path / "vault"
    _write_store(vault_dir, {"a concept": ("concept", [f"src_{i}_a_001" for i in range(7)])})

    assert coverage_count(vault_dir=vault_dir) == {"a concept": 7}


def test_coverage_count_reports_every_name_the_store_carries(tmp_path):
    vault_dir = tmp_path / "vault"
    _write_store(
        vault_dir,
        {
            "good": ("concept", ["src_1_a_001", "src_2_a_001"]),
            "also good": ("concept", ["src_3_a_001"]),
        },
    )

    assert coverage_count(vault_dir=vault_dir) == {"good": 2, "also good": 1}


# -- small shared helpers -----------------------------------------------------


def test_as_string_list_normalizes_every_shape_a_free_text_answer_takes():
    assert as_string_list(["a", "b"]) == ["a", "b"]
    assert as_string_list("a") == ["a"]
    assert as_string_list("") == []
    assert as_string_list(None) == []
    assert as_string_list(["a", None, 3, "  "]) == ["a"]


# --- issue #802: the window never cuts the first rotation -------------------


def test_source_covering_limit_leaves_a_limit_that_already_covers_alone():
    from axial.query.names import source_covering_limit

    assert source_covering_limit(["a", "b", "c"], 10) == 10


def test_source_covering_limit_raises_a_limit_below_the_source_count():
    from axial.query.names import source_covering_limit

    assert source_covering_limit([f"s{index}" for index in range(12)], 10) == 12


def test_source_covering_limit_counts_distinct_sources_not_members():
    from axial.query.names import source_covering_limit

    assert source_covering_limit(["a", "a", "a", "b"], 1) == 2


def test_source_covering_limit_counts_a_missing_source_as_one():
    """A member whose `chunk_id` did not parse groups under `""` in the
    rotation, so it occupies a slot there and must be counted here."""
    from axial.query.names import source_covering_limit

    assert source_covering_limit(["a", None, None], 1) == 2
