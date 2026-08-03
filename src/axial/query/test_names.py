"""Inner unit tests for the name-layer query API (issue #487,
specs/PHASE-B.md §7.5): the properties underneath
tests/analysis/test_name_query.py's scenarios, each in isolation --
resolution-tier edges, the name-page body parse, the alias-fold matching the
two traversals share, and the lazy per-directory indexes.

Tier 4 needs a persisted lancedb table and is exercised in
tests/analysis/test_name_query_embedding_tier.py; nothing here loads an
encoder or a vector store.

Issue #505: `who_cites`/`who_argues_against` now return `(edges, total)`
instead of a bare list, and `get_name` takes a `limit`. Every existing call
site below is updated to unpack the new return shape -- a one-line
justification for editing a locked contract, per the founder-approved #505
decision moving these three tools' signatures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.paths import name_page_filename
from axial.query.names import (
    DISAGREEMENT_HEADING,
    NameNeighbor,
    NameNotFoundError,
    _name_page_index,
    _parse_name_page_body,
    _split_member_line,
    as_string_list,
    canonical_for_surface,
    coverage_count,
    find_names,
    get_name,
    name_neighbors,
    resolve_encoder_model_name,
    who_argues_against,
    who_cites,
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


def _write_name_page(
    vault_dir: Path,
    canonical: str,
    *,
    kind: str | None = "concept",
    aliases: list[str] | None = None,
    member_count: int | None = None,
    body: str = "",
    used: set[str] | None = None,
) -> Path:
    names_dir = vault_dir / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "name": canonical,
        "kind": kind,
        "aliases": aliases or [],
        "member_count": member_count if member_count is not None else 0,
    }
    path = names_dir / name_page_filename(names_dir, canonical, used)
    rendered = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{rendered}---\n{body}", encoding="utf-8")
    return path


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


def _exploding_encoder(_texts):
    raise AssertionError("no encoder may be loaded on tiers 1-3")


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
        "diacritics are out of scope for the fold -- that is what tier 4 is for"
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


def test_member_count_is_none_when_this_vault_holds_no_page_for_the_name(tmp_path):
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
#
# `_page_body`, defined later in this module (near `where_names_meet`'s own
# tests), is reused here rather than re-derived -- these tests just run
# after it exists at import time, same as every other forward reference in
# this file.


def test_find_names_exact_hit_does_not_suppress_a_bigger_same_family_page(tmp_path):
    """Issue #632's own motivating case: `Mandate` used to return only
    itself because an exact hit stopped every other tier. The new
    `contains` route now also surfaces `French Mandate`, a bigger
    same-family page, and ranks it AHEAD of the exact hit by its own
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
    _write_name_page(
        vault_dir,
        "Mandate",
        member_count=3,
        body=_page_body(["srcA_000_intro_001", "srcA_000_intro_002", "srcB_000_intro_001"]),
    )
    _write_name_page(
        vault_dir,
        "French Mandate",
        member_count=5,
        body=_page_body(
            [
                "srcD_000_intro_001",
                "srcE_000_intro_001",
                "srcF_000_intro_001",
                "srcD_000_intro_002",
                "srcE_000_intro_002",
            ]
        ),
    )

    hits = find_names("Mandate", 10, names_dir=names_dir, vault_dir=vault_dir)

    assert [(hit.canonical, hit.tier, hit.member_count, hit.source_count) for hit in hits] == [
        ("French Mandate", "contains", 5, 3),
        ("Mandate", "exact", 3, 2),
    ]


def test_find_names_ranks_a_work_kind_page_last_regardless_of_size(tmp_path):
    """Issue #632: 8,583 of the real vault's pages are book/article titles;
    a concept query's `contains` scan turns up work-titled pages sharing
    its words, and those must rank LAST even when they are the bigger page
    -- a work is a citation target (`who_cites` already serves it), not an
    argument page."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {"canonical": "Culture of Sectarianism", "kind": "work", "aliases": []},
            {"canonical": "sectarianism", "kind": "concept", "aliases": []},
        ],
    )
    _write_name_page(
        vault_dir,
        "Culture of Sectarianism",
        kind="work",
        member_count=20,
        body=_page_body([f"srcBig{i}_000_intro_001" for i in range(5)]),
    )
    _write_name_page(
        vault_dir,
        "sectarianism",
        kind="concept",
        member_count=5,
        body=_page_body(["srcSmall_000_intro_001"]),
    )

    hits = find_names("sectarianism", 10, names_dir=names_dir, vault_dir=vault_dir)

    assert [hit.canonical for hit in hits] == ["sectarianism", "Culture of Sectarianism"], (
        "the work-kind page ranks last even though it spans five sources against one"
    )


def test_embedding_group_keeps_similarity_order_never_reranked_by_size(tmp_path, monkeypatch):
    """Issue #632: ranking an embedding hit by size drifts to hubs (measured
    in the issue's own prototype: `United States` outranks the real match
    for the query `Syria`). Group 2 keeps `_embedding_tier`'s own
    similarity order even when a later hit's page is far bigger than an
    earlier one's -- `_embedding_tier` itself is stubbed here so this test
    pins `find_names`'s OWN assembly, not the ranked tier's math (which
    `tests/analysis/test_name_query_embedding_tier.py` already covers)."""
    from axial.query import names as names_module

    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {"canonical": "Small Match", "kind": "concept", "aliases": []},
            {"canonical": "Big Hub", "kind": "concept", "aliases": []},
        ],
    )
    _write_name_page(vault_dir, "Small Match", member_count=2)
    _write_name_page(vault_dir, "Big Hub", member_count=900)

    def fake_embedding_tier(_query, _layer, _names_dir, _encoder):
        # The real nearest-neighbour order: the small page is the closer
        # match, the hub a distant second -- the shape a size re-rank flips.
        return [("Small Match", "Small Match"), ("Big Hub", "Big Hub")]

    monkeypatch.setattr(names_module, "_embedding_tier", fake_embedding_tier)

    # A query no literal route matches at all, so the slate is pure group 2.
    hits = find_names("an unmatched query phrase", 10, names_dir=names_dir, vault_dir=vault_dir)

    assert [hit.canonical for hit in hits] == ["Small Match", "Big Hub"], (
        "group 2 must keep the embedding tier's own similarity order, never "
        "re-rank by member_count/source_count"
    )


def test_group_two_only_tops_up_when_group_one_is_short(tmp_path, monkeypatch):
    """Issue #632: the embedding group is appended only while the literal
    group (or its compound-query stand-in) has not already filled `limit`
    -- and is never even COMPUTED once it has, so a call the literal group
    alone answers pays no vector-store read and builds no encoder."""
    from axial.query import names as names_module

    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "One Door", "kind": "concept", "aliases": []}])
    _write_name_page(vault_dir, "One Door", member_count=1)

    calls: list[str] = []

    def fake_embedding_tier(query, _layer, _names_dir, _encoder):
        calls.append(query)
        return [("Embedded Door", "Embedded Door")]

    monkeypatch.setattr(names_module, "_embedding_tier", fake_embedding_tier)

    filled = find_names("One Door", 1, names_dir=names_dir, vault_dir=vault_dir)
    assert [hit.canonical for hit in filled] == ["One Door"]
    assert calls == [], "the embedding group must not even be computed once group 1 fills limit"

    topped_up = find_names("One Door", 2, names_dir=names_dir, vault_dir=vault_dir)
    assert [hit.canonical for hit in topped_up] == ["One Door", "Embedded Door"]
    assert calls == ["One Door"], "group 2 tops up exactly once group 1 falls short of limit"


def test_compound_query_fallback_offers_the_best_door_per_content_word(tmp_path):
    """Issue #632's own motivating compound case: no page's name literally
    carries "mandate-era institutions Syria" as a phrase, so each content
    word is resolved separately and the best door per word stands in for
    group 1, marked `tier="word"` so a caller can tell "your phrase matched
    no page; this word did" from a real phrase resolution -- and
    `matched_on` names the query WORD, not the page, for the same reason."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {"canonical": "French Mandate", "kind": "concept", "aliases": []},
            {"canonical": "Syria", "kind": "country/state/place", "aliases": []},
        ],
    )
    _write_name_page(
        vault_dir,
        "French Mandate",
        member_count=5,
        body=_page_body(["srcD_000_intro_001", "srcE_000_intro_001", "srcF_000_intro_001"]),
    )
    _write_name_page(
        vault_dir,
        "Syria",
        member_count=20,
        body=_page_body([f"src{i}_000_intro_001" for i in range(4)]),
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
    of this fixture's page names, `rare` in one, and `rare` leads even
    though it comes SECOND in the query text."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    canonicals = ["Rare Concept", "Common Era", "Common Ground", "Common Law", "Common Sense"]
    _write_layer(
        names_dir, [{"canonical": c, "kind": "concept", "aliases": []} for c in canonicals]
    )
    for c in canonicals:
        _write_name_page(vault_dir, c, member_count=1)

    # Neither word, nor the two-word phrase, is any page's own name, so
    # this exercises the fallback rather than group 1's literal routes.
    hits = find_names("common rare", 10, names_dir=names_dir, vault_dir=vault_dir)

    word_hits = [hit for hit in hits if hit.tier == "word"]
    assert [hit.matched_on for hit in word_hits] == ["rare", "common"], (
        "the rarer word's door leads even though 'common' comes first in the query text"
    )
    assert word_hits[0].canonical == "Rare Concept"
    assert word_hits[1].canonical == "Common Era", (
        "among the four 'common' pages the usual group-1 ranking still decides which one wins"
    )


def test_find_names_ordering_is_deterministic_including_group_one_ties(tmp_path):
    """Issue #632: two pages tied on kind/source_count/member_count break by
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
    _write_name_page(
        vault_dir, "Zeta Mandate", member_count=1, body=_page_body(["srcX_000_intro_001"])
    )
    _write_name_page(
        vault_dir, "Alpha Mandate", member_count=1, body=_page_body(["srcY_000_intro_001"])
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


# -- the name-page body parse -------------------------------------------------


def test_split_member_line_reads_the_writers_own_two_author_renderings():
    """The real corpus renders authors both ways; both split the same."""
    assert _split_member_line("Michael Mann (2013): A claim.") == (
        "Michael Mann",
        "2013",
        "A claim.",
    )
    assert _split_member_line("Ayubi, Nazih N.; (1995): A claim.") == (
        "Ayubi, Nazih N.;",
        "1995",
        "A claim.",
    )


def test_split_member_line_is_honest_when_it_cannot_split_author_and_year():
    author, year, claim = _split_member_line("no author-year shape here")
    assert (author, year) == (None, None)
    assert claim == "no author-year shape here", "the claim is what the page says, not a guess"


def test_split_member_line_splits_at_the_first_seam_so_a_claim_may_contain_one():
    author, year, claim = _split_member_line("M. Mann (2013): he argues (contra Tilly): the state.")
    assert (author, year) == ("M. Mann", "2013")
    assert claim == "he argues (contra Tilly): the state."


def test_the_artifacts_section_is_not_parsed_as_a_member_note():
    """253 real name pages carry an `**Artifacts:**` block of bare
    `- [[id]]` links above the member list."""
    body = (
        "# a figure\n\n"
        "**Artifacts:**\n- [[src_art_1]]\n- [[src_art_2]]\n\n"
        "**Member notes:**\n- [[src_1_a_001]] — A (2020): A claim.\n"
    )
    members, disagreement = _parse_name_page_body(body)

    assert [member.chunk_id for member in members] == ["src_1_a_001"]
    assert disagreement is None


def test_a_page_with_no_members_parses_as_no_members():
    members, _ = _parse_name_page_body("# a name\n\n**Member notes:**\n(none)\n")
    assert members == []


def test_a_disagreement_with_no_runs_between_line_still_parses(tmp_path):
    body = f"**Member notes:**\n(none)\n\n{DISAGREEMENT_HEADING}\n\nThey disagree.\n"
    _members, disagreement = _parse_name_page_body(body)

    assert disagreement is not None
    assert disagreement.text == "They disagree."
    assert disagreement.names == []


def test_a_multi_paragraph_disagreement_keeps_its_whole_text():
    body = (
        f"**Member notes:**\n(none)\n\n{DISAGREEMENT_HEADING}\n\n"
        "First paragraph.\n\nSecond paragraph.\n\n**Runs between:** [[A]], [[B]]\n"
    )
    _members, disagreement = _parse_name_page_body(body)

    assert disagreement.text == "First paragraph.\n\nSecond paragraph."
    assert disagreement.names == ["A", "B"]


def test_get_name_on_a_member_whose_chunk_id_does_not_parse_reports_no_source_id(tmp_path):
    vault_dir = tmp_path / "vault"
    _write_name_page(
        vault_dir,
        "a concept",
        member_count=1,
        body="**Member notes:**\n- [[not-a-real-chunk-id]] — A (2020): A claim.\n",
    )

    page = get_name("a concept", vault_dir=vault_dir)

    assert page.members[0].source_id is None
    assert page.members[0].chunk_id == "not-a-real-chunk-id"


def test_get_name_raises_naming_the_canonical_when_no_page_exists(tmp_path):
    (tmp_path / "vault" / "names").mkdir(parents=True)

    with pytest.raises(NameNotFoundError) as exc_info:
        get_name("absent name", vault_dir=tmp_path / "vault")
    assert "absent name" in str(exc_info.value)


def test_get_name_truncates_members_at_limit_but_not_member_count(tmp_path):
    """issue #505: `Syria` returns 962 members with no `limit` at all, and
    re-sending that list on every later turn flooded a real retrieval-loop
    prompt to ~72,000 characters. `members` is capped; `member_count` is the
    page's own frontmatter total and must stay the true count regardless, so
    a caller can see both the window and the whole it is a window onto."""
    vault_dir = tmp_path / "vault"
    body = "**Member notes:**\n" + "\n".join(
        f"- [[m{i}]] — A ({2000 + i}): claim {i}." for i in range(1, 5)
    )
    _write_name_page(vault_dir, "a concept", member_count=4, body=body + "\n")

    capped = get_name("a concept", 2, vault_dir=vault_dir)
    assert [m.chunk_id for m in capped.members] == ["m1", "m2"], (
        "these chunk_ids carry no parseable source_id (issue #562's round-robin "
        "groups every one of them under the same empty-string bucket), so the "
        "spread degenerates to the page's own written order here -- see the "
        "round-robin-specific tests below for a fixture with real source spread"
    )
    assert capped.member_count == 4, "member_count is the true total, never capped"

    uncapped = get_name("a concept", 10, vault_dir=vault_dir)
    assert [m.chunk_id for m in uncapped.members] == ["m1", "m2", "m3", "m4"]
    assert uncapped.member_count == 4

    default = get_name("a concept", vault_dir=vault_dir)
    assert [m.chunk_id for m in default.members] == ["m1", "m2", "m3", "m4"], (
        "DEFAULT_LIMIT (10) does not truncate a 4-member page"
    )


def test_get_name_truncated_window_reaches_a_primary_source_deep_in_page_order(tmp_path):
    """issue #562: `Charles Tilly`'s own page groups members by `source_id`
    alphabetically, and two secondary sources (`malesevic-2004`,
    `mann-2012`) hold far more members between them than the primary source
    (`tilly-1978`) -- the exact hub shape measured on the real vault, where
    Tilly's own book sat at member 108 of 154. A plain prefix truncation at
    any limit under 74 never reaches it; the round-robin spread reaches it
    as soon as every distinct source has contributed once, which for a
    4-source page is limit=4."""
    vault_dir = tmp_path / "vault"
    chunk_ids = (
        ["bayat-1997_1_a_001"]
        + [f"malesevic-2004_1_a_{i:03d}" for i in range(1, 31)]
        + [f"mann-2012_1_a_{i:03d}" for i in range(1, 41)]
        + [f"tilly-1978_1_a_{i:03d}" for i in range(1, 4)]
    )
    _write_name_page(
        vault_dir, "Charles Tilly", member_count=len(chunk_ids), body=_page_body(chunk_ids)
    )
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


def test_get_name_limit_covering_every_member_returns_page_order_unchanged(tmp_path):
    """The spread is a truncation rule, not a re-sort (issue #562): a `limit`
    that already covers every member must see the page's own written order,
    byte-for-byte, whether `limit` equals `member_count` exactly or exceeds
    it."""
    vault_dir = tmp_path / "vault"
    chunk_ids = (
        ["bayat-1997_1_a_001"]
        + [f"malesevic-2004_1_a_{i:03d}" for i in range(1, 4)]
        + [f"mann-2012_1_a_{i:03d}" for i in range(1, 4)]
        + [f"tilly-1978_1_a_{i:03d}" for i in range(1, 3)]
    )
    _write_name_page(
        vault_dir, "Charles Tilly", member_count=len(chunk_ids), body=_page_body(chunk_ids)
    )

    exact = get_name("Charles Tilly", len(chunk_ids), vault_dir=vault_dir)
    assert [m.chunk_id for m in exact.members] == chunk_ids

    over = get_name("Charles Tilly", len(chunk_ids) + 5, vault_dir=vault_dir)
    assert [m.chunk_id for m in over.members] == chunk_ids


def test_get_name_truncated_window_is_deterministic_across_repeated_calls(tmp_path):
    vault_dir = tmp_path / "vault"
    chunk_ids = (
        [f"aaa-src_1_a_{i:03d}" for i in range(1, 6)]
        + [f"bbb-src_1_a_{i:03d}" for i in range(1, 6)]
        + [f"ccc-src_1_a_{i:03d}" for i in range(1, 6)]
    )
    _write_name_page(
        vault_dir, "a concept", member_count=len(chunk_ids), body=_page_body(chunk_ids)
    )

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


def test_get_name_truncated_window_places_an_unparsed_member_first_and_does_not_crash(tmp_path):
    """A member whose `chunk_id` does not parse (`_parse_name_page_body`)
    has `source_id=None`. It is grouped under the empty string, which sorts
    before any real `source_id` -- the same placement `where_names_meet`'s
    own round-robin already gives an unparsed member (issue #517) -- so it
    is reachable in a small window rather than dropped, and grouping it
    never raises."""
    vault_dir = tmp_path / "vault"
    chunk_ids = ["not-a-real-chunk-id", "aaa-src_1_a_001", "bbb-src_1_a_001", "bbb-src_1_a_002"]
    _write_name_page(
        vault_dir, "a concept", member_count=len(chunk_ids), body=_page_body(chunk_ids)
    )

    page = get_name("a concept", 2, vault_dir=vault_dir)

    assert [m.chunk_id for m in page.members] == ["not-a-real-chunk-id", "aaa-src_1_a_001"]
    assert page.members[0].source_id is None


def test_get_name_never_returns_a_different_pages_content_on_a_filename_collision(tmp_path):
    """Two canonicals sanitizing to one filename: the second is
    hash-suffixed by the writer, and resolving by filename alone would hand
    back the first page's content under the second name."""
    vault_dir = tmp_path / "vault"
    used: set[str] = set()
    _write_name_page(vault_dir, "A-B", member_count=1, used=used)
    _write_name_page(vault_dir, "A/B", member_count=2, used=used)

    assert get_name("A-B", vault_dir=vault_dir).member_count == 1
    assert get_name("A/B", vault_dir=vault_dir).member_count == 2


def test_get_name_resolves_an_alias_or_folded_argument_to_the_same_page(tmp_path):
    """`get_name`'s own `canonical` argument must be resolved through the
    alias map, same as `name_neighbors` already does on its argument and
    `who_cites`/`who_argues_against` already do via `_surface_matches_
    canonical` -- a caller passing an alias, or a case/whitespace variant
    that only folds to the canonical, must not raise `NameNotFoundError`
    just because it never equalled the raw canonical string exactly. Mirrors
    PR #516's `name_neighbors` fix, the last of the four siblings to do
    this."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [{"canonical": "Infrastructural power", "kind": "concept", "aliases": ["infra power"]}],
    )
    _write_name_page(
        vault_dir,
        "Infrastructural power",
        member_count=1,
        body="**Member notes:**\n- [[src_1_a_001]] — A (2020): A claim.\n",
    )

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
    page: a query that resolves through none of the three exact tiers still
    raises `NameNotFoundError`, even with a populated layer that carries
    other names and even though tier 4 (embedding) is never reached here."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [{"canonical": "Infrastructural power", "kind": "concept", "aliases": ["infra power"]}],
    )
    _write_name_page(vault_dir, "Infrastructural power", member_count=1)

    with pytest.raises(NameNotFoundError) as exc_info:
        get_name("a wholly unrelated name", vault_dir=vault_dir, names_dir=names_dir)
    assert "a wholly unrelated name" in str(exc_info.value)


# -- where_names_meet (issue #517) --------------------------------------------


def _member_line(
    chunk_id: str, *, author: str = "Author", year: int = 2020, claim: str = "A claim."
) -> str:
    return f"- [[{chunk_id}]] — {author} ({year}): {claim}"


def _page_body(chunk_ids: list[str]) -> str:
    return "**Member notes:**\n" + "\n".join(_member_line(cid) for cid in chunk_ids) + "\n"


def test_where_names_meet_returns_the_shared_members_and_the_true_total(tmp_path):
    from axial.query.names import where_names_meet

    vault_dir = tmp_path / "vault"
    _write_name_page(
        vault_dir,
        "Syria",
        member_count=3,
        body=_page_body(["src1_1_a_001", "src2_1_a_001", "src3_1_a_001"]),
    )
    _write_name_page(
        vault_dir,
        "Ottoman Empire",
        member_count=3,
        body=_page_body(["src2_1_a_001", "src3_1_a_001", "src4_1_a_001"]),
    )

    members, total = where_names_meet("Syria", "Ottoman Empire", 10, vault_dir=vault_dir)

    assert {m.chunk_id for m in members} == {"src2_1_a_001", "src3_1_a_001"}
    assert total == 2
    assert all(m.author == "Author" and m.year == "2020" for m in members), (
        "the shared member's own rendering (author/year/claim) travels with it"
    )


def test_where_names_meet_orders_round_robin_by_source_not_alphabetically(tmp_path):
    """Three notes from one source and one from a lexically LATER source all
    intersect. A `chunk_id`-ascending prefix at limit=2 would return two
    notes from the ONE source; round-robin-by-source surfaces both."""
    from axial.query.names import where_names_meet

    vault_dir = tmp_path / "vault"
    shared = ["aaa_1_a_001", "aaa_1_a_002", "aaa_1_a_003", "zzz_1_a_001"]
    assert sorted(shared)[:2] == ["aaa_1_a_001", "aaa_1_a_002"], (
        "sanity: plain chunk_id-ascending order is one source at limit=2"
    )
    body = _page_body(shared)
    _write_name_page(vault_dir, "A", member_count=4, body=body)
    _write_name_page(vault_dir, "B", member_count=4, body=body)

    members, total = where_names_meet("A", "B", 2, vault_dir=vault_dir)

    assert [m.chunk_id for m in members] == ["aaa_1_a_001", "zzz_1_a_001"], (
        "round-robin surfaces both sources at limit=2, distinguishably from the alphabetical prefix"
    )
    assert total == 4


def test_where_names_meet_total_is_uncapped_by_limit(tmp_path):
    from axial.query.names import where_names_meet

    vault_dir = tmp_path / "vault"
    shared = [f"src{i}_1_a_001" for i in range(1, 5)]
    body = _page_body(shared)
    _write_name_page(vault_dir, "A", member_count=4, body=body)
    _write_name_page(vault_dir, "B", member_count=4, body=body)

    members, total = where_names_meet("A", "B", 2, vault_dir=vault_dir)

    assert len(members) == 2
    assert total == 4


def test_where_names_meet_empty_intersection_is_not_an_error(tmp_path):
    from axial.query.names import where_names_meet

    vault_dir = tmp_path / "vault"
    _write_name_page(vault_dir, "A", member_count=1, body=_page_body(["src1_1_a_001"]))
    _write_name_page(vault_dir, "B", member_count=1, body=_page_body(["src2_1_a_001"]))

    assert where_names_meet("A", "B", vault_dir=vault_dir) == ([], 0)


def test_where_names_meet_raises_name_not_found_naming_whichever_side_fails(tmp_path):
    from axial.query.names import NameNotFoundError, where_names_meet

    vault_dir = tmp_path / "vault"
    _write_name_page(vault_dir, "A", member_count=0, body="**Member notes:**\n(none)\n")

    with pytest.raises(NameNotFoundError) as exc_info:
        where_names_meet("A", "absent name", vault_dir=vault_dir)
    assert "absent name" in str(exc_info.value)

    with pytest.raises(NameNotFoundError) as exc_info:
        where_names_meet("absent name", "A", vault_dir=vault_dir)
    assert "absent name" in str(exc_info.value)


def test_where_names_meet_resolves_an_alias_argument_on_either_side(tmp_path):
    from axial.query.names import where_names_meet

    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {
                "canonical": "Syria",
                "kind": "country/state/place",
                "aliases": ["Syrian Arab Republic"],
            },
            {"canonical": "Ottoman Empire", "kind": "country/state/place", "aliases": ["Ottomans"]},
        ],
    )
    shared_body = _page_body(["src1_1_a_001"])
    _write_name_page(vault_dir, "Syria", member_count=1, body=shared_body)
    _write_name_page(vault_dir, "Ottoman Empire", member_count=1, body=shared_body)

    by_canonical, canonical_total = where_names_meet(
        "Syria", "Ottoman Empire", vault_dir=vault_dir, names_dir=names_dir
    )
    by_alias, alias_total = where_names_meet(
        "Syrian Arab Republic", "Ottomans", vault_dir=vault_dir, names_dir=names_dir
    )

    assert [m.chunk_id for m in by_alias] == [m.chunk_id for m in by_canonical] == ["src1_1_a_001"]
    assert alias_total == canonical_total == 1


def test_where_names_meet_never_reaches_the_whole_corpus_answers_index(tmp_path, monkeypatch):
    """Reading two name pages is O(pages); the whole-corpus answers scan
    `name_neighbors`/`who_cites`/`who_argues_against` pay for (measured
    139.7s cold, issue #520) must never be touched here."""
    from axial.query import names as names_module

    def _explode(_vault_dir):
        raise AssertionError("where_names_meet must never build the answers index")

    monkeypatch.setattr(names_module, "_answers_index", _explode)

    vault_dir = tmp_path / "vault"
    body = _page_body(["src1_1_a_001"])
    _write_name_page(vault_dir, "A", member_count=1, body=body)
    _write_name_page(vault_dir, "B", member_count=1, body=body)

    members, total = names_module.where_names_meet("A", "B", vault_dir=vault_dir)
    assert total == 1
    assert [m.chunk_id for m in members] == ["src1_1_a_001"]


# -- the traversals -----------------------------------------------------------


def test_who_cites_matches_a_folded_variant_of_the_canonical(tmp_path):
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "Charles Tilly", "kind": "person", "aliases": []}])
    _write_prose_note(
        vault_dir,
        "src_1_a_001",
        {"citations": [{"cited": "charles-tilly", "stance": "foil", "about": "war"}]},
    )

    edges, total = who_cites("Charles Tilly", vault_dir=vault_dir, names_dir=names_dir)

    assert [(edge.cited, edge.stance) for edge in edges] == [("charles-tilly", "foil")]
    assert total == 1


def test_who_cites_orders_two_citations_from_one_note_totally(tmp_path):
    """`chunk_id` alone is not a total order: one note can cite the same name
    twice, under two surfaces."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "Tilly", "kind": "person", "aliases": ["C. Tilly"]}])
    _write_prose_note(
        vault_dir,
        "src_1_a_001",
        {
            "citations": [
                {"cited": "C. Tilly", "stance": "support", "about": "z"},
                {"cited": "Tilly", "stance": "authority", "about": "a"},
            ]
        },
    )

    edges, total = who_cites("Tilly", vault_dir=vault_dir, names_dir=names_dir)
    assert [edge.cited for edge in edges] == ["C. Tilly", "Tilly"]
    assert total == 2
    assert who_cites("Tilly", vault_dir=vault_dir, names_dir=names_dir) == (edges, total)


def test_who_cites_truncates_at_limit_and_reports_the_true_total(tmp_path):
    """issue #505: `who_cites` had no `limit` at all and returned every
    matching row -- `Max Weber` reaches 165 on the real vault. The truncated
    prefix is the head of the same `chunk_id`-ascending order an uncapped
    call returns, and `total` is the honest pre-cap count."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "Tilly", "kind": "person", "aliases": []}])
    for i in range(1, 5):
        _write_prose_note(
            vault_dir,
            f"src_{i}_a_001",
            {"citations": [{"cited": "Tilly", "stance": "support", "about": f"point {i}"}]},
        )

    uncapped, uncapped_total = who_cites("Tilly", 10, vault_dir=vault_dir, names_dir=names_dir)
    assert len(uncapped) == 4
    assert uncapped_total == 4

    capped, capped_total = who_cites("Tilly", 2, vault_dir=vault_dir, names_dir=names_dir)
    assert [edge.chunk_id for edge in capped] == [edge.chunk_id for edge in uncapped[:2]], (
        "the capped prefix is the head of the uncapped order, deterministically"
    )
    assert capped_total == 4, "the true pre-cap total, not the returned count"

    default, default_total = who_cites("Tilly", vault_dir=vault_dir, names_dir=names_dir)
    assert len(default) == 4, "DEFAULT_LIMIT (10) does not truncate 4 edges"
    assert default_total == 4


def test_who_cites_ignores_a_malformed_citation_entry_rather_than_raising(tmp_path):
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "Tilly", "kind": "person", "aliases": []}])
    _write_prose_note(
        vault_dir, "src_1_a_001", {"citations": ["a bare string", {"stance": "support"}]}
    )

    assert who_cites("Tilly", vault_dir=vault_dir, names_dir=names_dir) == ([], 0)


def test_who_argues_against_accepts_a_bare_string_answer(tmp_path):
    """`arguing_against` is a list on the real corpus, but nothing enforces
    that on a free-text answer."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "Tilly", "kind": "person", "aliases": []}])
    _write_prose_note(
        vault_dir,
        "src_1_a_001",
        {"arguing_against": "Tilly", "position_of": "the author", "claim": "A claim."},
    )

    edges, total = who_argues_against("Tilly", vault_dir=vault_dir, names_dir=names_dir)

    assert [(edge.arguing_against, edge.position, edge.claim) for edge in edges] == [
        ("Tilly", "the author", "A claim.")
    ]
    assert total == 1


def test_who_argues_against_truncates_at_limit_and_reports_the_true_total(tmp_path):
    """Same shape as `who_cites` (issue #505): `who_argues_against` had no
    `limit` at all before this and returned every matching row."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "Tilly", "kind": "person", "aliases": []}])
    for i in range(1, 5):
        _write_prose_note(
            vault_dir,
            f"src_{i}_a_001",
            {"arguing_against": ["Tilly"], "position_of": "the author", "claim": f"claim {i}."},
        )

    uncapped, uncapped_total = who_argues_against(
        "Tilly", 10, vault_dir=vault_dir, names_dir=names_dir
    )
    assert len(uncapped) == 4
    assert uncapped_total == 4

    capped, capped_total = who_argues_against("Tilly", 2, vault_dir=vault_dir, names_dir=names_dir)
    assert [edge.chunk_id for edge in capped] == [edge.chunk_id for edge in uncapped[:2]], (
        "the capped prefix is the head of the uncapped order, deterministically"
    )
    assert capped_total == 4


# -- issue #496's mixed frame: `position` when the key is there, else
#    `position_of` -----------------------------------------------------------


def test_who_argues_against_prefers_the_frame_02_position_answer(tmp_path):
    """A note interrogated under frame 0.2 carries both keys, and `position`
    ("what is the position?") is the one a reader wants -- `position_of`
    ("whose position is this?") answers a different question."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "Tilly", "kind": "person", "aliases": []}])
    _write_prose_note(
        vault_dir,
        "src_1_a_001",
        {
            "arguing_against": ["Tilly"],
            "position_of": "the author",
            "position": "durable rule was built by a party, not an army",
            "claim": "A claim.",
        },
    )

    edges, _total = who_argues_against("Tilly", vault_dir=vault_dir, names_dir=names_dir)

    assert [edge.position for edge in edges] == ["durable rule was built by a party, not an army"]


def test_who_argues_against_falls_back_to_position_of_when_the_key_is_absent(tmp_path):
    """Every note in the live corpus is this case: no `position` key at all,
    and no re-run is planned."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "Tilly", "kind": "person", "aliases": []}])
    _write_prose_note(
        vault_dir,
        "src_1_a_001",
        {"arguing_against": ["Tilly"], "position_of": "bellicist", "claim": "A claim."},
    )

    edges, _total = who_argues_against("Tilly", vault_dir=vault_dir, names_dir=names_dir)
    assert [edge.position for edge in edges] == ["bellicist"]


def test_who_argues_against_reads_a_present_position_key_even_when_it_is_null(tmp_path):
    """Key presence, not truthiness: a note that WAS asked the frame-0.2
    question and answered nothing must not silently report the older
    question's answer instead."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "Tilly", "kind": "person", "aliases": []}])
    _write_prose_note(
        vault_dir,
        "src_1_a_001",
        {
            "arguing_against": ["Tilly"],
            "position_of": "the author",
            "position": None,
            "claim": "A claim.",
        },
    )

    edges, _total = who_argues_against("Tilly", vault_dir=vault_dir, names_dir=names_dir)
    assert [edge.position for edge in edges] == [None]


def test_who_argues_against_carries_both_frames_in_one_result_set(tmp_path):
    """The corpus is genuinely mixed, and one name's members can span both
    frames -- so one call's results carry a frame-0.2 `position` and a
    pre-0.2 `position_of` side by side, with nothing marking which is which."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "Tilly", "kind": "person", "aliases": []}])
    _write_prose_note(
        vault_dir,
        "src_1_new_001",
        {
            "arguing_against": ["Tilly"],
            "position_of": "the author",
            "position": "the new frame's answer",
            "claim": "A claim.",
        },
    )
    _write_prose_note(
        vault_dir,
        "src_1_old_001",
        {"arguing_against": ["Tilly"], "position_of": "the old frame's answer", "claim": "B."},
    )

    edges, total = who_argues_against("Tilly", vault_dir=vault_dir, names_dir=names_dir)

    assert [(edge.chunk_id, edge.position) for edge in edges] == [
        ("src_1_new_001", "the new frame's answer"),
        ("src_1_old_001", "the old frame's answer"),
    ]
    assert total == 2


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


def test_a_note_with_no_answers_block_at_all_is_read_as_naming_nothing(tmp_path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True)
    frontmatter = {"chunk_id": "src_1_a_001", "section": "A", "chunk_text": "T", "source_meta": {}}
    rendered = yaml.safe_dump(frontmatter, sort_keys=False)
    (prose_dir / "src_1_a_001.md").write_text(f"---\n{rendered}---\nBody.\n", encoding="utf-8")

    assert who_cites("Tilly", vault_dir=vault_dir, names_dir=tmp_path / "names") == ([], 0)
    assert who_argues_against("Tilly", vault_dir=vault_dir, names_dir=tmp_path / "names") == (
        [],
        0,
    )
    assert name_neighbors("Tilly", 10, vault_dir=vault_dir, names_dir=tmp_path / "names") == []


def test_name_neighbors_counts_a_note_once_however_many_times_it_names_a_neighbour(tmp_path):
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {"canonical": "A", "kind": "person", "aliases": []},
            {"canonical": "B", "kind": "concept", "aliases": ["B prime"]},
        ],
    )
    _write_prose_note(
        vault_dir,
        "src_1_a_001",
        {
            "names": [
                {"name": "A", "kind": "person"},
                {"name": "B", "kind": "concept"},
                {"name": "B prime", "kind": "concept"},
            ]
        },
    )

    neighbors = name_neighbors("A", 10, vault_dir=vault_dir, names_dir=names_dir)

    assert [(n.canonical, n.shared_note_count) for n in neighbors] == [("B", 1)], (
        "two spellings of one name on one note are one shared note, not two"
    )


def test_name_neighbors_of_a_name_no_note_names_is_empty(tmp_path):
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "A", "kind": "person", "aliases": []}])
    _write_prose_note(vault_dir, "src_1_a_001", {"names": [{"name": "Z", "kind": "person"}]})

    assert name_neighbors("A", 10, vault_dir=vault_dir, names_dir=names_dir) == []


def test_name_neighbors_resolves_an_alias_or_folded_argument_to_the_same_result(tmp_path):
    """The `canonical` argument itself must be resolved through the alias map,
    same as the note side already is -- a caller passing an alias, or a
    case/whitespace variant that only folds to the canonical, must not reach
    zero neighbours just because it never equalled the raw canonical string."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(
        names_dir,
        [
            {"canonical": "Infrastructural power", "kind": "concept", "aliases": ["infra power"]},
            {"canonical": "Nationalism", "kind": "concept", "aliases": []},
        ],
    )
    _write_prose_note(
        vault_dir,
        "src_1_a_001",
        {
            "names": [
                {"name": "Infrastructural power", "kind": "concept"},
                {"name": "Nationalism", "kind": "concept"},
            ]
        },
    )

    by_canonical = name_neighbors(
        "Infrastructural power", 10, vault_dir=vault_dir, names_dir=names_dir
    )
    by_alias = name_neighbors("infra power", 10, vault_dir=vault_dir, names_dir=names_dir)
    by_fold = name_neighbors("infrastructural power", 10, vault_dir=vault_dir, names_dir=names_dir)

    assert by_canonical == [
        NameNeighbor(canonical="Nationalism", kind="concept", shared_note_count=1)
    ]
    assert by_alias == by_canonical
    assert by_fold == by_canonical


# -- coverage_count -----------------------------------------------------------


def test_coverage_count_over_a_vault_with_no_name_pages_returns_empty(tmp_path):
    (tmp_path / "vault" / "prose").mkdir(parents=True)

    assert coverage_count(vault_dir=tmp_path / "vault") == {}


def test_coverage_count_reads_the_pages_own_member_count_not_a_recount(tmp_path):
    """A page whose frontmatter `member_count` disagrees with its rendered
    member list reports the frontmatter value -- Materialize wrote it, and
    nothing here recomputes a denominator (D2)."""
    vault_dir = tmp_path / "vault"
    _write_name_page(
        vault_dir,
        "a concept",
        member_count=7,
        body="**Member notes:**\n- [[src_1_a_001]] — A (2020): A claim.\n",
    )

    assert coverage_count(vault_dir=vault_dir) == {"a concept": 7}


def test_coverage_count_skips_a_malformed_page_rather_than_aborting_the_scan(tmp_path):
    vault_dir = tmp_path / "vault"
    _write_name_page(vault_dir, "good", member_count=2)
    (vault_dir / "names" / "broken.md").write_text("not a note at all\n", encoding="utf-8")

    assert coverage_count(vault_dir=vault_dir) == {"good": 2}


# -- the lazy indexes ---------------------------------------------------------


def test_the_name_page_index_is_built_at_most_once_per_vault(tmp_path, monkeypatch):
    """Repeated calls inside one retrieval loop must not re-scan ~62.8k
    pages; a regression to a per-call scan leaves every other test green.

    Patches `_read_name_page_full`, not `_read_name_page_head` (issue #634):
    the fallback scan now reads each page's body too, since `source_count`
    is not in the frontmatter -- a one-line justification for editing this
    existing unit, the mechanism the index is built from actually moved."""
    from axial.query import names as names_module

    vault_dir = tmp_path / "vault"
    _write_name_page(vault_dir, "a", member_count=1)
    _write_name_page(vault_dir, "b", member_count=2)

    reads: list[Path] = []
    original = names_module._read_name_page_full

    def counting(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(names_module, "_read_name_page_full", counting)

    coverage_count(vault_dir=vault_dir)
    after_first = len(reads)
    coverage_count(vault_dir=vault_dir)

    assert after_first == 2
    assert len(reads) == after_first, "the second call read nothing off disk"


def test_the_name_page_index_is_keyed_per_vault_not_shared(tmp_path):
    vault_a = tmp_path / "a"
    vault_b = tmp_path / "b"
    _write_name_page(vault_a, "only in a", member_count=1)
    _write_name_page(vault_b, "only in b", member_count=2)

    assert set(_name_page_index(vault_a)) == {"only in a"}
    assert set(_name_page_index(vault_b)) == {"only in b"}


def test_get_name_avoids_the_index_on_a_direct_page_hit(tmp_path, monkeypatch):
    """`get_name`'s fast path is the writer's own naming function plus a
    frontmatter check -- index-free, like `get_chunk`'s. Issue #632 leaves
    this alone on purpose: `get_name` resolves its own argument through
    `canonical_for_surface` (never the door index), so an alias or folded
    variant still lands the same page as its canonical without a slate."""
    from axial.query import names as names_module

    vault_dir = tmp_path / "vault"
    _write_name_page(vault_dir, "a concept", member_count=1)

    def _explode(_vault_dir):
        raise AssertionError("a direct page hit must not build the name index")

    monkeypatch.setattr(names_module, "_name_page_index", _explode)

    assert get_name("a concept", vault_dir=vault_dir).canonical == "a concept"


def test_find_names_scans_the_vault_at_most_once_per_call(tmp_path, monkeypatch):
    """Issue #632: `find_names`'s new `contains` route needs the whole door
    index up front to scan every page name, so the old "index-free direct
    hit" claim this test descends from (`test_no_index_is_built_on_a_direct_
    page_hit`, now `test_get_name_avoids_the_index_on_a_direct_page_hit`
    above) no longer holds for `find_names` -- a locked-contract edit this
    change deliberately makes, one line of justification: the slate cannot
    be assembled without seeing every page's name. What survives, and is
    the actual cost claim (the issue's own "one file read, no page opens"):
    the underlying page scan still runs at most ONCE per vault per process
    (`_name_page_index`'s own cache), never once per hit, even though this
    module's own helpers (the `contains` route, the door decoration) each
    ask for the index."""
    from axial.query import names as names_module

    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "a concept", "kind": "concept", "aliases": []}])
    _write_name_page(vault_dir, "a concept", member_count=1)

    reads: list[Path] = []
    original = names_module._read_name_page_full

    def counting(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(names_module, "_read_name_page_full", counting)

    hits = find_names("a concept", 10, names_dir=names_dir, vault_dir=vault_dir)

    assert [(hit.canonical, hit.member_count, hit.source_count) for hit in hits] == [
        ("a concept", 1, 0)
    ]
    assert len(reads) == 1, "the whole-vault scan runs once, cached, not once per hit"


# -- the door index (issue #634) ----------------------------------------------


def test_name_page_index_reads_the_persisted_file_and_never_scans_when_present(
    tmp_path, monkeypatch
):
    """When Materialize already wrote `<vault_dir>/names.jsonl`, the reader
    builds its in-memory index from that one file and never opens a page."""
    from axial.query import names as names_module

    vault_dir = tmp_path / "vault"
    page_path = _write_name_page(vault_dir, "a concept", kind="concept", member_count=3)
    (vault_dir / "names.jsonl").write_text(
        json.dumps(
            {
                "name": "a concept",
                "filename": page_path.name,
                "kind": "concept",
                "member_count": 3,
                "source_count": 2,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def _explode(_path):
        raise AssertionError("the persisted index file was present; no page scan may run")

    monkeypatch.setattr(names_module, "_read_name_page_full", _explode)

    index = _name_page_index(vault_dir)

    assert index["a concept"].path == page_path
    assert index["a concept"].kind == "concept"
    assert index["a concept"].member_count == 3
    assert index["a concept"].source_count == 2


def test_absent_index_file_falls_back_to_a_scan_and_writes_one(tmp_path):
    """An already-materialized vault with no `names.jsonl` yet (issue #634)
    still resolves, by scanning `names/` itself, and self-heals by writing
    the index it just built -- so the next call reads the file instead."""
    vault_dir = tmp_path / "vault"
    _write_name_page(
        vault_dir,
        "cross-book concept",
        kind="concept",
        member_count=2,
        body=(
            "**Member notes:**\n"
            "- [[srcA_000_intro_001]] — A (2020): claim a.\n"
            "- [[srcB_000_intro_001]] — B (2021): claim b.\n"
        ),
    )
    _write_name_page(
        vault_dir,
        "one-book concept",
        kind="concept",
        member_count=1,
        body="**Member notes:**\n- [[srcA_001_intro_002]] — A (2020): claim.\n",
    )
    assert not (vault_dir / "names.jsonl").is_file()

    index = _name_page_index(vault_dir)

    assert index["cross-book concept"].source_count == 2
    assert index["one-book concept"].source_count == 1

    index_path = vault_dir / "names.jsonl"
    assert index_path.is_file(), "a missing index self-heals by writing one"
    rows = {
        row["name"]: row
        for row in (
            json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()
        )
    }
    assert rows["cross-book concept"]["source_count"] == 2
    assert rows["one-book concept"]["source_count"] == 1


def test_write_name_page_index_file_degrades_silently_when_not_writable(tmp_path):
    """A vault directory the process cannot write to must not turn a
    successful in-memory build into a raised error (issue #634)."""
    from axial.query.names import _NamePageEntry, _write_name_page_index_file

    unwritable_vault_dir = tmp_path / "does-not-exist" / "nested"
    entry = _NamePageEntry(
        path=unwritable_vault_dir / "names" / "a.md", kind="concept", member_count=1, source_count=1
    )

    _write_name_page_index_file(unwritable_vault_dir, {"a": entry})  # must not raise


def test_write_name_page_index_file_is_atomic_never_exposes_a_partial_write(tmp_path, monkeypatch):
    """Issue #637: a concurrent reader of `names.jsonl` must never observe a
    truncated or partial file, only the complete prior content or the
    complete new content.

    `Path.write_text`'s "w" mode truncates the file the instant it opens,
    before a single byte of the new content is written, so a writer that
    calls `path.write_text(...)` directly exposes an empty file for that
    whole window. Demonstrated by spying on every direct `open()` of the
    real index path in write mode: this test fails for the right reason
    against the pre-fix code (which opens `path` itself for writing) and
    passes once the write goes through a temp-file-plus-`os.replace` swap,
    which never opens the real path for writing at all."""
    from axial.query.names import (
        NAME_PAGE_INDEX_FILENAME,
        _NamePageEntry,
        _write_name_page_index_file,
    )

    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    index_path = vault_dir / NAME_PAGE_INDEX_FILENAME

    old_entry = _NamePageEntry(
        path=vault_dir / "names" / "Old Name.md", kind="person", member_count=1, source_count=1
    )
    _write_name_page_index_file(vault_dir, {"Old Name": old_entry})
    old_bytes = index_path.read_bytes()
    assert old_bytes, "fixture setup: the first write must actually land"

    new_entry = _NamePageEntry(
        path=vault_dir / "names" / "New Name.md", kind="concept", member_count=5, source_count=3
    )

    observed_mid_write: list[bytes] = []
    real_open = Path.open

    def spying_open(self, mode="r", *args, **kwargs):
        handle = real_open(self, mode, *args, **kwargs)
        if self == index_path and "w" in mode:
            # `real_open` above already ran -- if this is a direct write
            # open of the real path, it has already truncated it.
            observed_mid_write.append(index_path.read_bytes())
        return handle

    monkeypatch.setattr(Path, "open", spying_open)

    _write_name_page_index_file(vault_dir, {"New Name": new_entry})

    assert observed_mid_write == [], (
        "the real index path was opened directly for writing -- a concurrent "
        f"reader would have observed a truncated file: {observed_mid_write!r}"
    )
    new_bytes = index_path.read_bytes()
    assert b"New Name" in new_bytes
    assert b"Old Name" not in new_bytes


# -- small shared helpers -----------------------------------------------------


def test_as_string_list_normalizes_every_shape_a_free_text_answer_takes():
    assert as_string_list(["a", "b"]) == ["a", "b"]
    assert as_string_list("a") == ["a"]
    assert as_string_list("") == []
    assert as_string_list(None) == []
    assert as_string_list(["a", None, 3, "  "]) == ["a"]


def test_resolve_encoder_model_name_is_none_without_a_manifest(tmp_path):
    assert resolve_encoder_model_name(tmp_path / "absent") is None


def test_the_default_encoder_is_built_once_per_model_and_never_reaches_the_hub(monkeypatch):
    """Issue #524: a fresh `SentenceTransformer` per semantic `find_names`
    carried a live, unauthenticated round-trip to huggingface.co on a
    retrieval code path (2.9s online against 0.28s offline, for weights
    already on disk). One construction per model name, local files only."""
    import sys
    import types

    from axial.query import names as names_module

    constructions: list[tuple[str, dict[str, Any]]] = []

    class _FakeTransformer:
        def __init__(self, model_name: str, **kwargs: Any):
            constructions.append((model_name, kwargs))

        def encode(self, texts, convert_to_numpy=True):
            import numpy

            return numpy.zeros((len(texts), 3), dtype=numpy.float32)

    stub = types.ModuleType("sentence_transformers")
    stub.SentenceTransformer = _FakeTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", stub)
    monkeypatch.setattr(names_module, "_ENCODER_CACHE", {})

    first = names_module._default_encoder("fake-model")
    second = names_module._default_encoder("fake-model")
    other = names_module._default_encoder("another-fake-model")

    assert first is second, "a second call must reuse the cached encoder, not rebuild one"
    assert first is not other, "the cache is per model_name: the store names which one to use"
    assert [model for model, _kwargs in constructions] == ["fake-model", "another-fake-model"]
    assert all(kwargs.get("local_files_only") is True for _model, kwargs in constructions)
    assert first(["a query"]) == [[0.0, 0.0, 0.0]]
