"""Inner unit tests for the name-layer query API (issue #487,
specs/PHASE-B.md §7.5): the properties underneath
tests/analysis/test_name_query.py's scenarios, each in isolation --
resolution-tier edges, the name-page body parse, the alias-fold matching the
two traversals share, and the lazy per-directory indexes.

Tier 4 needs a persisted lancedb table and is exercised in
tests/analysis/test_name_query_embedding_tier.py; nothing here loads an
encoder or a vector store.
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

    edges = who_cites("Charles Tilly", vault_dir=vault_dir, names_dir=names_dir)

    assert [(edge.cited, edge.stance) for edge in edges] == [("charles-tilly", "foil")]


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

    edges = who_cites("Tilly", vault_dir=vault_dir, names_dir=names_dir)
    assert [edge.cited for edge in edges] == ["C. Tilly", "Tilly"]
    assert who_cites("Tilly", vault_dir=vault_dir, names_dir=names_dir) == edges


def test_who_cites_ignores_a_malformed_citation_entry_rather_than_raising(tmp_path):
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_layer(names_dir, [{"canonical": "Tilly", "kind": "person", "aliases": []}])
    _write_prose_note(
        vault_dir, "src_1_a_001", {"citations": ["a bare string", {"stance": "support"}]}
    )

    assert who_cites("Tilly", vault_dir=vault_dir, names_dir=names_dir) == []


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

    edges = who_argues_against("Tilly", vault_dir=vault_dir, names_dir=names_dir)

    assert [(edge.arguing_against, edge.position_of, edge.claim) for edge in edges] == [
        ("Tilly", "the author", "A claim.")
    ]


def test_a_note_with_no_answers_block_at_all_is_read_as_naming_nothing(tmp_path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True)
    frontmatter = {"chunk_id": "src_1_a_001", "section": "A", "chunk_text": "T", "source_meta": {}}
    rendered = yaml.safe_dump(frontmatter, sort_keys=False)
    (prose_dir / "src_1_a_001.md").write_text(f"---\n{rendered}---\nBody.\n", encoding="utf-8")

    assert who_cites("Tilly", vault_dir=vault_dir, names_dir=tmp_path / "names") == []
    assert who_argues_against("Tilly", vault_dir=vault_dir, names_dir=tmp_path / "names") == []
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
