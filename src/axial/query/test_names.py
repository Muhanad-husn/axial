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
        "the truncated prefix is the head of the page's own written order"
    )
    assert capped.member_count == 4, "member_count is the true total, never capped"

    uncapped = get_name("a concept", 10, vault_dir=vault_dir)
    assert [m.chunk_id for m in uncapped.members] == ["m1", "m2", "m3", "m4"]
    assert uncapped.member_count == 4

    default = get_name("a concept", vault_dir=vault_dir)
    assert [m.chunk_id for m in default.members] == ["m1", "m2", "m3", "m4"], (
        "DEFAULT_LIMIT (10) does not truncate a 4-member page"
    )


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
    pages; a regression to a per-call scan leaves every other test green."""
    from axial.query import names as names_module

    vault_dir = tmp_path / "vault"
    _write_name_page(vault_dir, "a", member_count=1)
    _write_name_page(vault_dir, "b", member_count=2)

    reads: list[Path] = []
    original = names_module._read_name_page_head

    def counting(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(names_module, "_read_name_page_head", counting)

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


def test_no_index_is_built_on_a_direct_page_hit(tmp_path, monkeypatch):
    """`get_name`'s and `find_names`' fast path is the writer's own naming
    function plus a frontmatter check -- index-free, like `get_chunk`'s. A
    `find_names` that built the whole-vault index to decorate at most `limit`
    hits with their `member_count` would pay a 62.8k-page scan per run."""
    from axial.query import names as names_module

    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "a concept", "kind": "concept", "aliases": []}])
    _write_name_page(vault_dir, "a concept", member_count=1)

    def _explode(_vault_dir):
        raise AssertionError("a direct page hit must not build the name index")

    monkeypatch.setattr(names_module, "_name_page_index", _explode)

    assert get_name("a concept", vault_dir=vault_dir).canonical == "a concept"
    hits = find_names("a concept", 10, names_dir=names_dir, vault_dir=vault_dir)
    assert [(hit.canonical, hit.member_count) for hit in hits] == [("a concept", 1)]


# -- small shared helpers -----------------------------------------------------


def test_as_string_list_normalizes_every_shape_a_free_text_answer_takes():
    assert as_string_list(["a", "b"]) == ["a", "b"]
    assert as_string_list("a") == ["a"]
    assert as_string_list("") == []
    assert as_string_list(None) == []
    assert as_string_list(["a", None, 3, "  "]) == ["a"]


def test_resolve_encoder_model_name_is_none_without_a_manifest(tmp_path):
    assert resolve_encoder_model_name(tmp_path / "absent") is None
