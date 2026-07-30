"""Inner unit tests for Phase A v1 slice 04 (issue #415: the name inventory
and similarity view, spec §7.16).

`lancedb`/`hdbscan`/`scikit-learn` are optional `distill`-group dependencies
(`uv sync --group distill`) -- `importorskip` here means this whole module
skips cleanly (not errors) on an environment that never synced the group,
mirroring `axial.distill.embed`'s own inner unit tests (`src/axial/distill/
test_embed_unit.py`).

Most tests here use an injected fake `encoder`/`cluster_fn` (plain
callables, mirroring `axial.distill.embed`'s `encoder` seam and
`axial.distill.readiness`'s `cluster_fn` seam) so the collect/persist/report
path runs fast and network-free, independent of the real model or the real
PCA+HDBSCAN pipeline's own behaviour on any given input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lancedb = pytest.importorskip("lancedb")

from axial.names import (  # noqa: E402
    NameOccurrence,
    NoAnswersToEmbedError,
    NoNamesToClusterError,
    TABLE_NAME,
    _borderline_pairs,
    _nearest_neighbour_pairs,
    _relabel_from_tree,
    build_inventory,
    carries_author_year_citation,
    collect_occurrences,
    examine_names,
    format_names_report,
    is_apparatus_pointer_shaped,
    is_cut_from_name_space,
    is_date_shaped,
    is_locator_shaped,
    is_numeral_only_surface,
    is_reference_pointer_shaped,
    is_source_pointer_shaped,
    iter_name_occurrences,
    load_answer_records,
    parse_scoped_source,
    run_names,
    scoped_surface_form,
    unscope_surface_form,
    write_inventory,
)


def _fake_encoder(surface_forms: list[str]) -> list[list[float]]:
    """A deterministic stand-in for the real sentence-transformer: maps each
    distinct surface form to a 2D vector by its position in a fixed
    alphabet, so near-identical strings land near each other and unrelated
    ones land far apart -- exactly the property the real encoder is trusted
    to have, without downloading it."""
    return [[float(len(form)), float(sum(ord(ch) for ch in form) % 97)] for form in surface_forms]


def _fake_cluster_fn(vectors: list[list[float]]) -> list[int]:
    """Groups vectors by exact value into small integer labels, deterministic
    and independent of HDBSCAN's own real clustering decisions."""
    labels: dict[tuple[float, ...], int] = {}
    result = []
    for vector in vectors:
        key = tuple(vector)
        if key not in labels:
            labels[key] = len(labels)
        result.append(labels[key])
    return result


def _write_answers(answers_dir: Path, source_id: str, records: list[dict]) -> Path:
    answers_dir.mkdir(parents=True, exist_ok=True)
    path = answers_dir / f"{source_id}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


def _answer_record(chunk_id: str, source_id: str, answers: dict, section: str = "") -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "section": section,
        "pass": "note_interrogate",
        "answers": answers,
    }


def _base_answers(**overrides) -> dict:
    base = {
        "about": ["x"],
        "claim": "x",
        "move": "x",
        "ranges_over": "not-in-passage",
        "stops_holding": "not-in-passage",
        "position_of": "not-in-passage",
        "arguing_against": [],
        "names": [],
        "citations": [],
        "mechanism": "not-in-passage",
        "evidence": "not-in-passage",
        "comparison": "not-in-passage",
        "defines": [],
        "uses": [],
        "concedes": "not-in-passage",
        "assumes": "not-in-passage",
    }
    base.update(overrides)
    return base


# --- iter_name_occurrences ---------------------------------------------------


def test_iter_name_occurrences_collects_names_only():
    """Issue #508 class A: `citations[].cited` no longer seeds the name
    space. The field keeps being recorded on the answer record; nothing
    reads it into an inventory surface any more."""
    record = _answer_record(
        "c1",
        "s1",
        _base_answers(
            names=[{"name": "Kevin Attell", "kind": "person"}],
            citations=[{"cited": "Gellner 1992", "stance": "authority", "about": "x"}],
            uses=["SENTINEL_never_collected"],
            defines=["SENTINEL_never_collected"],
            arguing_against=["SENTINEL_never_collected"],
            position_of="SENTINEL_never_collected",
        ),
    )

    occurrences = list(iter_name_occurrences(record))
    surface_forms = {occ.surface_form for occ in occurrences}

    assert surface_forms == {"Kevin Attell"}
    assert not any("SENTINEL" in form for form in surface_forms)
    by_form = {occ.surface_form: occ for occ in occurrences}
    assert by_form["Kevin Attell"].kind == "person"
    assert all(occ.chunk_id == "c1" for occ in occurrences)


def test_iter_name_occurrences_skips_abstentions_and_blank_records():
    record = _answer_record(
        "c1", "s1", _base_answers(names=["not-in-passage"], citations=["not-in-passage"])
    )
    failure_record = {"chunk_id": "c2", "source_id": "s1", "failure_reason": "boom"}

    assert list(iter_name_occurrences(record)) == []
    assert list(iter_name_occurrences(failure_record)) == []


def test_iter_name_occurrences_skips_malformed_entries_without_crashing():
    record = _answer_record(
        "c1",
        "s1",
        _base_answers(
            names=[{"name": "Real Name", "kind": "person"}, {"kind": "person"}, "not-a-dict"],
        ),
    )

    occurrences = list(iter_name_occurrences(record))
    surface_forms = {occ.surface_form for occ in occurrences}

    assert surface_forms == {"Real Name"}


# --- issue #508: the cut set, enforced at inventory time ---------------------
#
# One test per row of the issue's own table, each naming a real surface the
# rule removes and a real surface it must not.


def _names_record(*surfaces: str, section: str = "") -> dict:
    return _answer_record(
        "c1",
        "s1",
        _base_answers(names=[{"name": surface, "kind": "person"} for surface in surfaces]),
        section=section,
    )


def _collected(*surfaces: str, section: str = "") -> set[str]:
    record = _names_record(*surfaces, section=section)
    return {occ.surface_form for occ in iter_name_occurrences(record)}


def test_cut_a_citation_channel_leaves_the_name_space():
    """Class A, 13,661 surfaces: an author-plus-title citation string is not
    a name page. `Charles Tilly`, named in the same note's `names[]`, is."""
    record = _answer_record(
        "c1",
        "s1",
        _base_answers(
            names=[{"name": "Charles Tilly", "kind": "person"}],
            citations=[
                {"cited": "Philip S. Khoury, Syria and the French Mandate", "stance": "support"},
                {"cited": "Marx and Engels", "stance": "authority"},
            ],
        ),
    )

    assert {occ.surface_form for occ in iter_name_occurrences(record)} == {"Charles Tilly"}


def test_row_b_is_not_applied_and_a_back_matter_name_survives():
    """Row B -- cutting a surface seen only in a bibliography, index, front
    matter or appendix -- is re-scoped out of this change and has its own
    issue. Nothing here reads a section, so a bibliography name keeps its
    page, and this pass makes no model call."""
    assert _collected("Hanna Batatu", section="Bibliography") == {"Hanna Batatu"}
    assert _collected("Hanna Batatu", section="N O T E S") == {"Hanna Batatu"}


def test_cut_c_bare_numeral_leaves_the_name_space():
    """Class C, 623 surfaces: `13` (18 member notes across 12 books) goes;
    `10 Downing Street` stays."""
    assert _collected("13", "10 Downing Street") == {"10 Downing Street"}


def test_cut_d_apparatus_pointer_leaves_the_name_space():
    """Class D, 746 surfaces: `Chapter 5` (52 member notes) goes;
    `Chapter VII of the UN Charter` stays."""
    assert _collected("Chapter 5", "Chapter VII of the UN Charter") == {
        "Chapter VII of the UN Charter"
    }


def test_cut_e_locator_leaves_the_name_space():
    """Class E, 441 surfaces: `Table 4.1` goes; `Bramall table 2.2` stays."""
    assert _collected("Table 4.1", "Bramall table 2.2") == {"Bramall table 2.2"}


def test_cut_f_dates_leave_the_name_space():
    """Class F, 1,012 surfaces: `1917-1918`, `6 June 1975` and `March 1963`
    go; `10th of Ramadan` and `1948 War` stay."""
    assert _collected("1917-1918", "6 June 1975", "March 1963", "10th of Ramadan", "1948 War") == {
        "10th of Ramadan",
        "1948 War",
    }


def test_cut_g_reference_pointer_leaves_the_name_space():
    """Class G, 140 surfaces: `p. 34`, `vol. 2`, `ibid.` and `op. cit.` go;
    `Volume One` and the surname `Page` stay."""
    assert _collected("p. 34", "vol. 2", "ibid.", "op. cit.", "Volume One", "Page") == {
        "Volume One",
        "Page",
    }


def test_cut_h_author_year_citation_leaves_the_name_space():
    """Class H, 5,995 surfaces: a name carrying its own citation year or
    `et al` goes; the bare person and a parenthesized acronym stay."""
    assert _collected(
        "Gellner (1983)",
        "Tilly, 1990",
        "Bourdieu et al",
        "Ernest Gellner",
        "Autonomous Administration of Northeast Syria (AANS)",
    ) == {"Ernest Gellner", "Autonomous Administration of Northeast Syria (AANS)"}


def test_cut_p_source_pointer_leaves_the_name_space():
    """Class P, 661 surfaces: `source 26`, `reference 12` and a bare
    bracketed `[34]` go; `Sources of Social Power` stays."""
    assert _collected("source 26", "reference 12", "[34]", "Sources of Social Power") == {
        "Sources of Social Power"
    }


def test_cut_s_the_abstention_sentinel_leaves_the_name_space():
    """Class S, 1 surface with 24 member notes: the interrogation's own
    `not-in-passage` sentinel, minted as a name when a model wrote it inside
    a list rather than as the list. `Not in Passage Press` is not it."""
    assert _collected("not-in-passage", "Not in Passage Press") == {"Not in Passage Press"}


def test_legitimate_names_survive_the_whole_cut_set():
    """The acceptance's own survivor list: a `work` title, a lowercase
    concept, and an endnote-only name."""
    record = _answer_record(
        "c1",
        "s1",
        _base_answers(
            names=[
                {"name": "The Great Transformation", "kind": "work"},
                {"name": "negative sovereignty", "kind": "concept"},
                {"name": "Hanna Batatu", "kind": "person"},
            ]
        ),
        section="N O T E S",
    )

    assert {occ.surface_form for occ in iter_name_occurrences(record)} == {
        "The Great Transformation",
        "negative sovereignty",
        "Hanna Batatu",
    }


def test_a_name_survives_when_only_its_citation_shaped_alias_is_cut():
    """The page stays; only the alias that carried a year leaves it."""
    assert _collected("Ernest Gellner", "Gellner (1983)") == {"Ernest Gellner"}


# --- load_answer_records / collect_occurrences -------------------------------


def test_load_answer_records_reads_every_source_sorted(tmp_path: Path):
    answers_dir = tmp_path / "answers"
    _write_answers(answers_dir, "src2", [_answer_record("c1", "src2", _base_answers())])
    _write_answers(answers_dir, "src1", [_answer_record("c1", "src1", _base_answers())])

    records = load_answer_records(answers_dir)

    assert [record["source_id"] for record in records] == ["src1", "src2"]


def test_load_answer_records_missing_dir_returns_empty(tmp_path: Path):
    assert load_answer_records(tmp_path / "nope") == []


def test_collect_occurrences_flat_maps_over_records():
    records = [
        _answer_record("c1", "s1", _base_answers(names=[{"name": "a", "kind": "concept"}])),
        _answer_record("c2", "s1", _base_answers(names=[{"name": "b", "kind": "concept"}])),
    ]

    forms = sorted(occ.surface_form for occ in collect_occurrences(records))

    assert forms == ["a", "b"]


# --- build_inventory (§7.16's exact shape) -----------------------------------


def test_build_inventory_groups_exact_surface_form_across_notes():
    occurrences = [
        NameOccurrence("Kevin Attell", "c1", "person"),
        NameOccurrence("Kevin Attell", "c1", "person"),
        NameOccurrence("Kevin Attell", "c2", "person"),
    ]

    entries = build_inventory(occurrences)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.surface_form == "Kevin Attell"
    assert entry.count == 3
    assert entry.kind == "person"
    assert entry.chunk_ids == ("c1", "c2")


def test_build_inventory_resolves_kind_by_frequency_then_first_occurrence():
    # "state" tagged concept twice, person once -- concept wins on frequency.
    occurrences = [
        NameOccurrence("state", "c1", "concept"),
        NameOccurrence("state", "c2", "person"),
        NameOccurrence("state", "c3", "concept"),
    ]

    entries = build_inventory(occurrences)

    assert entries[0].kind == "concept"


def test_build_inventory_kind_tie_broken_by_first_occurrence():
    occurrences = [
        NameOccurrence("state", "c1", "concept"),
        NameOccurrence("state", "c2", "person"),
    ]

    entries = build_inventory(occurrences)

    assert entries[0].kind == "concept"  # first-seen kind wins a 1-1 tie


def test_build_inventory_surface_the_corpus_gave_no_kind_keeps_none():
    entries = build_inventory([NameOccurrence("Gellner", "c1", None)])

    assert entries[0].kind is None


def test_build_inventory_keeps_distinct_case_as_distinct_entries():
    occurrences = [
        NameOccurrence("gellner", "c1"),
        NameOccurrence("Gellner", "c2"),
    ]

    entries = build_inventory(occurrences)

    assert sorted(entry.surface_form for entry in entries) == ["Gellner", "gellner"]


def test_build_inventory_sorted_by_surface_form():
    occurrences = [NameOccurrence("Zeta", "c1"), NameOccurrence("Alpha", "c2")]

    entries = build_inventory(occurrences)

    assert [entry.surface_form for entry in entries] == ["Alpha", "Zeta"]


# --- build_inventory: locator scoping (issue #445) ---------------------------


def test_build_inventory_scopes_a_locator_surface_spanning_multiple_sources():
    """The actual bug: "Table 4.1" named in two different books must not
    collapse into one node -- it becomes two, each carrying only its own
    book's chunk_ids/count."""
    occurrences = [
        NameOccurrence("Table 4.1", "src1_000_intro_001", "table", "src1"),
        NameOccurrence("Table 4.1", "src2_000_intro_001", "table", "src2"),
    ]

    entries = build_inventory(occurrences)

    surface_forms = {entry.surface_form for entry in entries}
    assert surface_forms == {"Table 4.1 (src1)", "Table 4.1 (src2)"}
    by_form = {entry.surface_form: entry for entry in entries}
    assert by_form["Table 4.1 (src1)"].chunk_ids == ("src1_000_intro_001",)
    assert by_form["Table 4.1 (src2)"].chunk_ids == ("src2_000_intro_001",)
    assert by_form["Table 4.1 (src1)"].count == 1
    assert by_form["Table 4.1 (src1)"].kind == "table"


def test_build_inventory_leaves_a_single_source_locator_bare():
    """306 of 358 real locator surfaces are already single-source and must
    keep working exactly as before -- no rename, no page churn."""
    occurrences = [
        NameOccurrence("Figure 2.1", "src1_000_intro_001", "figure", "src1"),
        NameOccurrence("Figure 2.1", "src1_001_body_002", "figure", "src1"),
    ]

    entries = build_inventory(occurrences)

    assert len(entries) == 1
    assert entries[0].surface_form == "Figure 2.1"
    assert entries[0].count == 2
    assert entries[0].chunk_ids == ("src1_000_intro_001", "src1_001_body_002")


def test_build_inventory_never_scopes_a_non_locator_surface_across_sources():
    """A person/place/concept surface (`United States`, `Kevin Attell`)
    genuinely is one thing across books -- locator scoping must not touch
    it, however many sources it spans."""
    occurrences = [
        NameOccurrence("Kevin Attell", "src1_000_intro_001", "person", "src1"),
        NameOccurrence("Kevin Attell", "src2_000_intro_001", "person", "src2"),
    ]

    entries = build_inventory(occurrences)

    assert len(entries) == 1
    assert entries[0].surface_form == "Kevin Attell"
    assert entries[0].chunk_ids == ("src1_000_intro_001", "src2_000_intro_001")


def test_build_inventory_scopes_a_locator_mentioned_only_as_a_citation():
    """The shape test gates on surface text, not `kind` -- a citation mention
    of a locator (no `kind` at all) is exactly as book-relative."""
    occurrences = [
        NameOccurrence("Table 4.1", "src1_000_intro_001", None, "src1"),
        NameOccurrence("Table 4.1", "src2_000_intro_001", None, "src2"),
    ]

    entries = build_inventory(occurrences)

    assert {entry.surface_form for entry in entries} == {
        "Table 4.1 (src1)",
        "Table 4.1 (src2)",
    }


# --- the locator-scoping helpers themselves ----------------------------------


@pytest.mark.parametrize(
    "surface",
    [
        "Table 4.1",
        "table 4.1",
        "Fig. 2",
        "Figure 2",
        "fig 9",
        "Map 1",
        "Chart 3",
        "Graph 1",
        "Plate IV",
        "Box 2",
        "Diagram 1",
        "Appendix A",
    ],
)
def test_is_locator_shaped_matches_every_named_prefix(surface):
    assert is_locator_shaped(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "6.1. Aseel's displacement trajectory",
        "Bramall table 2.2",
        "Kevin Attell",
        "Figuratively speaking",
    ],
)
def test_is_locator_shaped_rejects_names_the_prefix_does_not_match(surface):
    assert not is_locator_shaped(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "13",
        "100",
        "1",
        "135",
        "10th century",
        "11th century",
        "1st",
        "22nd",
        "3rd",
        "20TH CENTURY",
    ],
)
def test_is_numeral_only_surface_matches_bare_numbers_and_centuries(surface):
    assert is_numeral_only_surface(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "10 Downing Street",
        "10th of Ramadan",
        "11 September 2001",
        "101 Facts & Figures on the Syrian Refugee Crisis",
        "1 John 5.19",
        "10th Congress of the Russian Communist Party",
        "117. Jager-Division",
        "1050-1250",
        "1060s",
        "1100-1750",
        "1. Event Section",
        "United States",
    ],
)
def test_is_numeral_only_surface_rejects_real_digit_initial_names(surface):
    assert not is_numeral_only_surface(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "Chapter 4",
        "Chapter 21",
        "chapter 2",
        "Ch. 4",
        "Chap. 3",
        "Footnote 36",
        "Footnote 1",
        "Endnote 12",
        "Appendix 2",
        "APPENDIX 4",
        "Table 4",
        "Figure 2",
        "Fig. 9",
        "Map 3",
        "Chapter 11 bibliography",
        "Chapter 3 (footnote 8)",
        "Chapter 5 (of Volume I)",
        "Chapter 13 The Post-1970 Ba'ath",
        "Chapter Eight: Transnational Syria",
        "Chapter Five",
        "Chapter One",
    ],
)
def test_is_apparatus_pointer_shaped_matches_chapter_and_apparatus_pointers(surface):
    assert is_apparatus_pointer_shaped(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "Note on the State",
        "Chapter of Sainte-Chapelle",
        "Chapter: A New History",
        "Chapter VII of the UN Charter",
        "Chapter I",
        "Table of Ranks",
        "Table Ronde",
        "Appendix A",
        "Table B.1",
        "Charles Tilly",
        "China",
    ],
)
def test_is_apparatus_pointer_shaped_rejects_real_names_and_lettered_apparatus(surface):
    assert not is_apparatus_pointer_shaped(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "1917-1918",
        "1917–1918",
        "1990/91",
        "1050-1250",
        "1060s",
        "1950s-1960s",
        "6 June 1975",
        "June 6, 1975",
        "March 1963",
        "MARCH 1963",
    ],
)
def test_is_date_shaped_matches_dates_and_date_ranges(surface):
    assert is_date_shaped(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "1948 War",
        "June 1967 War",
        "March on Washington",
        "March",
        "10th of Ramadan",
        "Six-Day War",
        "1917 Balfour Declaration",
        "Charles Tilly",
    ],
)
def test_is_date_shaped_rejects_names_that_merely_carry_a_date(surface):
    assert not is_date_shaped(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "p. 34",
        "pp. 34-56",
        "page 12",
        "pages 12-14",
        "vol. 2",
        "Volume 3",
        "no. 3",
        "nos. 1-2",
        "ibid",
        "ibid.",
        "Ibid.",
        "op. cit.",
        "loc. cit.",
        "passim",
    ],
)
def test_is_reference_pointer_shaped_matches_page_volume_and_ibid(surface):
    assert is_reference_pointer_shaped(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "Page",
        "Volume One",
        "P. Anderson",
        "Ibn Khaldun",
        "Nos Ancetres les Gaulois",
        "Pages from a Syrian Notebook",
        "Number Nine",
    ],
)
def test_is_reference_pointer_shaped_rejects_real_names(surface):
    assert not is_reference_pointer_shaped(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "Gellner (1983)",
        "Anderson (1983a)",
        "Tilly, 1990",
        "Khoury, 1987, p. 12",
        "Bourdieu et al",
        "Bourdieu et al.",
        "Wallerstein (2004)",
    ],
)
def test_carries_author_year_citation_matches_citation_shaped_names(surface):
    assert carries_author_year_citation(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "Charles Tilly",
        "Autonomous Administration of Northeast Syria (AANS)",
        "The 1948 War",
        "Israel/Palestine",
        "Etat, pouvoir et societe",
        "negative sovereignty",
    ],
)
def test_carries_author_year_citation_rejects_ordinary_names(surface):
    assert not carries_author_year_citation(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "source 26",
        "Source 3",
        "sources 4",
        "reference 12",
        "References 7",
        "[34]",
        "[ 23 ]",
    ],
)
def test_is_source_pointer_shaped_matches_pointers(surface):
    assert is_source_pointer_shaped(surface)


@pytest.mark.parametrize(
    "surface",
    [
        "Sources of Social Power",
        "Reference Group Theory",
        "[Damascus]",
        "Source",
        "source of legitimacy",
    ],
)
def test_is_source_pointer_shaped_rejects_real_names(surface):
    assert not is_source_pointer_shaped(surface)


def test_is_cut_from_name_space_unions_every_shape_rule():
    """The one predicate `iter_name_occurrences` calls: rows C, D, E, F, G,
    H, P and S of the cut set, and nothing else."""
    cut = [
        "13",  # C
        "Chapter 5",  # D
        "Table 4.1",  # E
        "1917-1918",  # F
        "ibid.",  # G
        "Gellner (1983)",  # H
        "[34]",  # P
        "not-in-passage",  # S
    ]
    kept = [
        "Charles Tilly",
        "negative sovereignty",
        "The Great Transformation",
        "Autonomous Administration of Northeast Syria (AANS)",
        "10 Downing Street",
    ]

    assert [surface for surface in cut if not is_cut_from_name_space(surface)] == []
    assert [surface for surface in kept if is_cut_from_name_space(surface)] == []


def test_scoped_and_unscope_surface_form_round_trip():
    scoped = scoped_surface_form("Table 4.1", "huneidi-2024")

    assert scoped == "Table 4.1 (huneidi-2024)"
    assert unscope_surface_form(scoped, "huneidi-2024") == "Table 4.1"
    # A source_id that is not actually this surface's own suffix changes
    # nothing -- never strips a mismatched or absent suffix.
    assert unscope_surface_form(scoped, "someone-else-2020") == scoped
    assert unscope_surface_form("Table 4.1", "huneidi-2024") == "Table 4.1"


def test_parse_scoped_source_reads_back_the_embedded_source():
    assert parse_scoped_source("Table 4.1 (huneidi-2024)") == "huneidi-2024"
    assert parse_scoped_source("Table 4.1") is None  # bare, single-source
    assert parse_scoped_source("Kevin Attell") is None  # not locator-shaped
    # A real surface form that happens to end in parentheses but is not
    # locator-shaped must never be misread as source-scoped.
    assert parse_scoped_source("Phelps-Brown and Hopkins (1956)") is None


def test_write_inventory_matches_spec_shape(tmp_path: Path):
    entries = build_inventory(
        [
            NameOccurrence("Kevin Attell", "c1", "person"),
            NameOccurrence("Kevin Attell", "c2", "person"),
        ]
    )
    path = tmp_path / "inventory.jsonl"

    write_inventory(entries, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record == {
        "surface": "Kevin Attell",
        "kind": "person",
        "count": 2,
        "chunk_ids": ["c1", "c2"],
    }


# --- run_names: loud failures ------------------------------------------------


def test_run_names_missing_answers_dir_raises(tmp_path: Path):
    with pytest.raises(NoAnswersToEmbedError):
        run_names(
            answers_dir=tmp_path / "answers",
            inventory_path=tmp_path / "inventory.jsonl",
            embeddings_dir=tmp_path / "embeddings.lance",
            manifest_path=tmp_path / "manifest.json",
            encoder=_fake_encoder,
            cluster_fn=_fake_cluster_fn,
        )


def test_run_names_no_names_in_any_note_raises(tmp_path: Path):
    answers_dir = tmp_path / "answers"
    _write_answers(answers_dir, "s1", [_answer_record("c1", "s1", _base_answers())])

    with pytest.raises(NoAnswersToEmbedError):
        run_names(
            answers_dir=answers_dir,
            inventory_path=tmp_path / "inventory.jsonl",
            embeddings_dir=tmp_path / "embeddings.lance",
            manifest_path=tmp_path / "manifest.json",
            encoder=_fake_encoder,
            cluster_fn=_fake_cluster_fn,
        )


# --- run_names: the persisted artifacts --------------------------------------


def test_run_names_persists_inventory_vectors_and_cluster_labels(tmp_path: Path):
    answers_dir = tmp_path / "answers"
    _write_answers(
        answers_dir,
        "s1",
        [
            _answer_record(
                "c1", "s1", _base_answers(names=[{"name": "Kevin Attell", "kind": "person"}])
            ),
            _answer_record(
                "c2",
                "s1",
                _base_answers(names=[{"name": "Gellner"}]),
            ),
        ],
    )
    inventory_path = tmp_path / "inventory.jsonl"
    embeddings_dir = tmp_path / "embeddings.lance"
    manifest_path = tmp_path / "manifest.json"

    result = run_names(
        answers_dir=answers_dir,
        inventory_path=inventory_path,
        embeddings_dir=embeddings_dir,
        manifest_path=manifest_path,
        encoder=_fake_encoder,
        cluster_fn=_fake_cluster_fn,
    )

    assert result.entry_count == 2
    assert result.occurrence_count == 2

    inventory_lines = inventory_path.read_text(encoding="utf-8").splitlines()
    inventory = {json.loads(line)["surface"]: json.loads(line) for line in inventory_lines}
    assert inventory["Kevin Attell"] == {
        "surface": "Kevin Attell",
        "kind": "person",
        "count": 1,
        "chunk_ids": ["c1"],
    }
    assert inventory["Gellner"]["kind"] is None

    db = lancedb.connect(embeddings_dir)
    rows = db.open_table("names").to_arrow().to_pylist()
    by_form = {row["surface_form"]: row for row in rows}
    assert by_form["Kevin Attell"]["kind"] == "person"
    assert by_form["Gellner"]["kind"] == ""
    assert json.loads(by_form["Kevin Attell"]["chunk_ids_json"]) == ["c1"]
    for row in rows:
        assert isinstance(row["vector"], list) and row["vector"]
        assert "cluster_label" in row

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["entry_count"] == 2
    assert manifest["occurrence_count"] == 2
    assert manifest["model_name"]
    assert manifest["config"]["min_cluster_size"] == 2
    assert manifest["config"]["min_samples"] == 1
    assert manifest["inventory_path"] == str(inventory_path)


def test_run_names_makes_no_model_call(tmp_path: Path):
    """The inventory pass is LLM-free, as it was before issue #508: every
    surviving cut-set row is a shape test, and row B -- the one that needed
    a judgment about a section heading -- is re-scoped to its own issue. A
    poisoned client here would never be reached, so the assertion is on the
    real seam: `run_names` takes no client at all."""
    import inspect

    assert "client" not in inspect.signature(run_names).parameters

    answers_dir = tmp_path / "answers"
    _write_answers(
        answers_dir,
        "s1",
        [
            _answer_record(
                "c1",
                "s1",
                _base_answers(names=[{"name": "Hanna Batatu", "kind": "person"}]),
                section="B I B L I O G R A P H Y",
            ),
            _answer_record(
                "c2",
                "s1",
                _base_answers(names=[{"name": "Charles Tilly", "kind": "person"}]),
                section="N O T E S",
            ),
        ],
    )
    inventory_path = tmp_path / "inventory.jsonl"

    result = run_names(
        answers_dir=answers_dir,
        inventory_path=inventory_path,
        embeddings_dir=tmp_path / "embeddings.lance",
        manifest_path=tmp_path / "manifest.json",
        encoder=_fake_encoder,
        cluster_fn=_fake_cluster_fn,
    )

    # Both survive: no section is read, so a bibliography name keeps its page.
    assert result.entry_count == 2
    surfaces = {
        json.loads(line)["surface"]
        for line in inventory_path.read_text(encoding="utf-8").splitlines()
    }
    assert surfaces == {"Charles Tilly", "Hanna Batatu"}


def test_run_names_is_deterministic_across_reruns(tmp_path: Path):
    answers_dir = tmp_path / "answers"
    _write_answers(
        answers_dir,
        "s1",
        [
            _answer_record(
                "c1",
                "s1",
                _base_answers(
                    names=[
                        {"name": "Alpha", "kind": "concept"},
                        {"name": "Beta", "kind": "concept"},
                    ]
                ),
            )
        ],
    )
    kwargs = dict(
        answers_dir=answers_dir,
        inventory_path=tmp_path / "inventory.jsonl",
        embeddings_dir=tmp_path / "embeddings.lance",
        manifest_path=tmp_path / "manifest.json",
        encoder=_fake_encoder,
        cluster_fn=_fake_cluster_fn,
    )

    first = run_names(**kwargs)
    second = run_names(**kwargs)

    assert first.entry_count == second.entry_count == 2
    assert first.cluster_count == second.cluster_count
    assert first.noise_count == second.noise_count


# --- examine_names / format_names_report -------------------------------------


def _write_names_table(embeddings_dir: Path, entries: list[tuple[str, list[float], int]]) -> None:
    """Write a `names` LanceDB table directly, with CONTROLLED vectors --
    `examine_names` always re-clusters with the real PCA+HDBSCAN pipeline
    (no `cluster_fn` injection seam; that IS the behaviour under test), so
    its tests need vectors whose real geometry is known, not `_fake_encoder`'s
    arbitrary string-derived ones."""
    rows = [
        {
            "surface_form": surface_form,
            "kind": "",
            "count": count,
            "chunk_ids_json": "[]",
            "cluster_label": -1,  # unused by examine_names; it re-clusters
            "vector": vector,
        }
        for surface_form, vector, count in entries
    ]
    db = lancedb.connect(embeddings_dir)
    db.create_table(TABLE_NAME, data=rows, mode="overwrite")


def test_examine_names_missing_table_raises(tmp_path: Path):
    with pytest.raises(NoNamesToClusterError):
        examine_names(embeddings_dir=tmp_path / "nope.lance")


def _tightness_fixture_vectors() -> list[tuple[str, list[float], int]]:
    """Two dense, well-separated (antipodal-direction) groups -- mirrors
    `axial.distill.readiness`'s own real-pipeline unit-test fixture shape
    (`test_default_cluster_fn_separates_two_dense_regions...`), which is
    proven stable through this exact normalise/standardise/PCA pipeline at
    small N, unlike a hand-picked "obviously distinct" fixture (verified
    directly: a magnitude-only or too-small fixture collapses unpredictably
    once StandardScaler sees near-zero per-feature variance -- small-N
    synthetic data does not behave like the real, thousands-of-points
    corpus this pipeline is tuned for). `min_cluster_size=2` vs `5` is an
    empirically found (not guessed) real transition on this exact fixture:
    both dense groups survive at 2, and BOTH collapse to noise at 5 (`leaf`
    selection requires every surviving leaf to meet the size, so the
    smaller 3-member group failing drags the whole tree's leaf selection
    down) -- exactly the real, if blunt, "where this setting decides
    something" case a founder would see in the real report."""
    group_a = [(f"Alpha{i}", [5.0 + i * 0.01, 5.0, 5.0], 1) for i in range(6)]
    group_b = [(f"Beta{i}", [-5.0 + i * 0.01, -5.0, -5.0], 1) for i in range(3)]
    noise = [("Gamma", [5.0, -5.0, 5.0], 1), ("Delta", [-5.0, 5.0, -5.0], 1)]
    return group_a + group_b + noise


def test_examine_names_sweeps_tightness_from_one_fit(tmp_path: Path):
    embeddings_dir = tmp_path / "embeddings.lance"
    entries = _tightness_fixture_vectors()
    _write_names_table(embeddings_dir, entries)

    stats = examine_names(embeddings_dir=embeddings_dir, min_cluster_sizes=[2, 5], min_samples=1)

    assert stats.entry_count == len(entries)
    assert stats.occurrence_count == len(entries)
    assert stats.similarity_min is not None
    assert [t.min_cluster_size for t in stats.tightness] == [2, 5]

    loose, tight = stats.tightness
    assert loose.min_samples == tight.min_samples == 1
    # mcs=2: both dense groups form their own real cluster.
    assert loose.cluster_count == 2
    assert loose.noise_count == 0
    # mcs=5: the 3-member group can no longer meet the threshold, and
    # `leaf` selection carries that down to noise for everyone.
    assert tight.cluster_count == 0
    assert tight.noise_count == len(entries)
    assert tight.noise_fraction == 1.0
    # noise never DEcreases as min_cluster_size tightens -- a structural
    # HDBSCAN invariant (a stricter threshold only ever demotes points to
    # noise, never promotes noise back into a cluster).
    assert tight.noise_count >= loose.noise_count

    # At mcs=5 every entry is noise, so the highest-similarity sampled pair
    # (within either original dense group) is a real borderline pair: a
    # near-identical pair this tightness declined to cluster at all.
    assert tight.borderline_pairs
    assert tight.borderline_pairs == sorted(
        tight.borderline_pairs, key=lambda item: item[2], reverse=True
    )

    report = format_names_report(stats)
    assert f"{len(entries)} distinct surface form(s)" in report
    assert f"{len(entries)} total occurrence(s)" in report
    assert "tightness sweep (2 candidate(s))" in report
    assert "min_cluster_size=2 min_samples=1" in report
    assert "min_cluster_size=5 min_samples=1" in report
    assert "nearest-neighbour cosine similarity spread" in report
    assert "borderline pairs" in report


def test_examine_names_default_sweep_uses_module_defaults(tmp_path: Path):
    embeddings_dir = tmp_path / "embeddings.lance"
    _write_names_table(
        embeddings_dir,
        [("Alpha", [0.0, 0.0], 1), ("Alpha2", [0.01, 0.01], 1), ("Zeta", [50.0, 50.0], 1)],
    )

    from axial.names import DEFAULT_TIGHTNESS_MIN_CLUSTER_SIZES

    stats = examine_names(embeddings_dir=embeddings_dir)

    assert [t.min_cluster_size for t in stats.tightness] == sorted(
        DEFAULT_TIGHTNESS_MIN_CLUSTER_SIZES
    )


def test_format_names_report_handles_no_tightness_candidates():
    class _Stats:
        entry_count = 0
        occurrence_count = 0
        similarity_min = None
        similarity_max = None
        similarity_mean = None
        similarity_median = None
        tightness: list = []

    report = format_names_report(_Stats())

    assert "tightness sweep (0 candidate(s))" in report
    assert "(fewer than 2 entries)" in report


# --- _relabel_from_tree: cheap relabel matches a fresh fit -------------------


def test_relabel_from_tree_matches_a_fresh_fit_at_the_same_settings():
    import hdbscan
    import numpy as np

    rng = np.random.default_rng(0)
    reduced = np.vstack(
        [
            rng.normal(loc=[0, 0], scale=0.05, size=(6, 2)),
            rng.normal(loc=[5, 5], scale=0.05, size=(4, 2)),
            rng.uniform(-10, 15, size=(10, 2)),
        ]
    )

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=2,
        min_samples=1,
        cluster_selection_method="leaf",
        allow_single_cluster=True,
    )
    clusterer.fit(reduced)
    slt = clusterer.single_linkage_tree_.to_numpy()

    cheap_labels = _relabel_from_tree(reduced, slt, min_cluster_size=4)

    fresh = hdbscan.HDBSCAN(
        min_cluster_size=4,
        min_samples=1,
        cluster_selection_method="leaf",
        allow_single_cluster=True,
    )
    fresh_labels = fresh.fit_predict(reduced)

    def partition(labels):
        groups: dict[int, set[int]] = {}
        for index, label in enumerate(labels):
            if label == -1:
                continue
            groups.setdefault(label, set()).add(index)
        return sorted(frozenset(group) for group in groups.values())

    assert partition(cheap_labels) == partition(list(fresh_labels))
    assert {i for i, label in enumerate(cheap_labels) if label == -1} == {
        i for i, label in enumerate(fresh_labels) if label == -1
    }


# --- _nearest_neighbour_pairs / _borderline_pairs ----------------------------


def test_nearest_neighbour_pairs_finds_the_closest_other_row():
    rows = [
        {"surface_form": "a", "vector": [1.0, 0.0]},
        {"surface_form": "b", "vector": [0.99, 0.01]},  # nearly identical to "a"
        {"surface_form": "c", "vector": [-1.0, 0.0]},  # opposite direction
    ]

    pairs = _nearest_neighbour_pairs(rows, sample_size=3)

    by_index = {i: (j, sim) for i, j, sim in pairs}
    assert by_index[0][0] == 1  # "a"'s nearest is "b"
    assert by_index[0][1] > 0.9
    assert by_index[2][1] < 0  # "c" is anti-correlated with everything else


def test_nearest_neighbour_pairs_empty_for_fewer_than_two_rows():
    assert _nearest_neighbour_pairs([{"surface_form": "a", "vector": [1.0]}], sample_size=5) == []
    assert _nearest_neighbour_pairs([], sample_size=5) == []


def test_borderline_pairs_excludes_same_cluster_dedupes_and_sorts():
    rows = [
        {"surface_form": "a"},
        {"surface_form": "b"},
        {"surface_form": "c"},
        {"surface_form": "d"},
    ]
    # (i, j, similarity): a-b same cluster (excluded); a-c and b-d cross
    # clusters at different similarities; c-d both noise.
    pairs = [(0, 1, 0.99), (0, 2, 0.5), (1, 3, 0.8), (2, 3, 0.6)]
    labels = [0, 0, 1, -1]  # a,b in cluster 0; c in cluster 1; d is noise

    result = _borderline_pairs(rows, pairs, labels, top_n=5)

    assert ("b", "d", 0.8) in result
    assert ("c", "d", 0.6) in result
    assert not any({a, b} == {"a", "b"} for a, b, _sim in result)  # same-cluster excluded
    assert result == sorted(result, key=lambda item: item[2], reverse=True)


def test_borderline_pairs_respects_top_n():
    rows = [{"surface_form": str(i)} for i in range(5)]
    pairs = [(0, 1, 0.9), (1, 2, 0.8), (2, 3, 0.7), (3, 4, 0.6)]
    labels = [-1, -1, -1, -1, -1]  # everything noise -> every pair qualifies

    result = _borderline_pairs(rows, pairs, labels, top_n=2)

    assert len(result) == 2
    assert result[0][2] == 0.9 and result[1][2] == 0.8
