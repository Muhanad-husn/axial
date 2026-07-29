"""Outer acceptance test for issue #487, Phase B v1 slice 02: the name query
API -- `find_names`, `get_name`, `name_neighbors`, `who_cites`,
`who_argues_against`, per-name `coverage_count`.

Locked behavioral contract -- do not edit once committed green without a
one-line justification in the PR body.

Given a fixture name layer whose index holds "Charles Tilly",
      "Giorgio Agamben", "Uğur Ümit Üngör", "SDF", "Rojava" and "PYD"
  And a fixture vault of name pages and prose notes carrying the
      interrogation's own answer block
  And no LLM client configured or constructible in the test process
When  find_names("Charles Tilly") / find_names("Tilly") /
      find_names("charles  tilly") are called
Then  each reaches the canonical "Charles Tilly", reporting which tier and
      which surface form matched -- exact, alias, folded
  And no encoder is loaded for any of them

Given the same fixture
When  find_names(<a query the corpus does not hold>) is called
Then  [] is returned -- a real answer, distinguishable from an error
  And find_names("SDF") is not empty

Given the same fixture
When  get_name("Charles Tilly") is called
Then  its kind, aliases, member_count and member notes come back in the
      page's own written order, each member carrying its chunk_id,
      source_id, author, year and one-sentence claim
  And every returned chunk_id resolves through get_chunk
  And `disagreement` is {text, names} on a page Gather wrote a section for
      and None on a page it did not -- the two are distinguishable

Given the same fixture
When  name_neighbors / who_cites / who_argues_against are called for
      "Charles Tilly"
Then  the co-occurring names come back ranked by shared note count,
      the citation edges come back with the author's own stance, and the
      opposition edges come back with the note's stated `position` and its
      `claim` -- each matched through every surface form the alias map folds
      into the canonical, never string equality on the canonical alone
  And `position` is read from a note's `position` answer where that key is
      present and from its `position_of` answer otherwise, so one result set
      carries both of issue #496's frames

Given a name page whose on-disk filename was budgeted down to a name that
      another page already claimed
When  get_name is called with its real name
Then  that page is still returned -- the `name` frontmatter is the sole
      authoritative id, never the filename

Given the same fixture
When  coverage_count() is called
Then  it returns {canonical: member_count} for every name page, ascending

See specs/PHASE-B.md §7.5 (the name layer tools, [FIRM]), §7.7 (the per-name
coverage map) and §8 P0-2 (the observables) for the source of truth, and
plans/phase-b-v1/README.md D1/D2/D5/D10.

Seam decisions
--------------
Library calls, not a CLI subprocess: this slice's boundary is the plain
`axial.query` entry points (there is no `axial query` subcommand), the same
seam tests/analysis/test_vault_query.py already established for the reader.

The whole fixture -- name layer, name pages, prose notes -- is built fresh
under `tmp_path` per test and passed in through explicit `names_dir` /
`vault_dir` arguments. Nothing here reads `data/`, which does not exist in a
worktree; every name, source and claim is synthetic (DEC-23: no book text in
the repo), and the scholars named are real people used only as name strings,
exactly as the issue's own resolution cases require.

`AXIAL_LLM_PROVIDER=explode` proves "no LLM client configured or
constructible" the same way every other poison-provider test in this
codebase does. Tiers 1-3 additionally get an exploding encoder: passing it
in proves no encoder is loaded at all on those paths, which is P0-2's own
observable for the D10 relaxation. Tier 4 is exercised in
test_name_query_embedding_tier.py, which needs the `distill` group's
lancedb to persist a real vector table.

Fixture files are written in a deliberately adversarial order (reverse
alphabetical, so filesystem enumeration order is neither the answer nor
alphabetical) so an implementation that leaks `Path.iterdir()` order cannot
pass by luck.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from axial.paths import name_page_filename

# --- the resolution cases the issue names, measured against the live index --

TILLY = "Charles Tilly"
AGAMBEN = "Giorgio Agamben"
UNGOR = "Uğur Ümit Üngör"
BELLICIST = "bellicist state formation"

SDF = "SDF"
ROJAVA = "Rojava"
PYD = "PYD"

# A query the corpus genuinely does not hold, and the one the live-vault run
# measured (2026-07-30): it is cut at cosine 0.4518 and returns `[]`. NOT
# "AANES" -- that entity IS in the index under its full name
# ("Autonomous Administration of North and East Syria", 2 members), and the
# acronym failing to reach it is a name-layer gap filed against Phase A, not
# an honest answer about the corpus (specs/PHASE-B.md §7.5).
UNHELD_QUERY = "zzqqx nonexistent scholar"

# Three canonicals that exercise the two distinct collisions the name layer
# really has. `FOLD_SPACED` and `FOLD_HYPHENATED` are identical under Phase
# A's own surface fold (hyphen to a space), so one folded query reaches both.
# `BUDGETED_NAME` sanitizes to the SAME FILENAME as `FOLD_HYPHENATED` ('/' is
# illegal in a Windows filename and becomes '-'), so whichever of the two is
# written second gets a hash-suffixed filename no reader can reproduce
# (`axial.paths.name_page_filename`'s `used` set is a write-order fact).
FOLD_SPACED = "Israel Palestine"
FOLD_HYPHENATED = "Israel-Palestine"
BUDGETED_NAME = "Israel/Palestine"

TILLY_NOTE = "tillyfix-1975-aaaaaaaaaaaa_1_war-making_001"
AGAMBEN_NOTE = "agambenfix-2005-bbbbbbbbbbbb_1_the-camp_001"
PYD_NOTE = "pydfix-2019-cccccccccccc_1_self-administration_001"
ARTIFACT_ID = "tillyfix-1975-aaaaaaaaaaaa_art_1"

TILLY_SOURCE_ID = "tillyfix-1975-aaaaaaaaaaaa"
AGAMBEN_SOURCE_ID = "agambenfix-2005-bbbbbbbbbbbb"
PYD_SOURCE_ID = "pydfix-2019-cccccccccccc"

TILLY_CLAIM = "Synthetic claim: coercive extraction built the fixture state."
AGAMBEN_CLAIM = "Synthetic claim: the fixture camp is the nomos of the fixture polity."
PYD_CLAIM = "Synthetic claim: the fixture administration governs without a fixture state."

# Issue #496's frame-0.2 `position` answer ("what is the position?"), carried
# by exactly one of the three fixture notes. The other two carry only
# `position_of` ("whose position is this?"), which is what every note in the
# live corpus carries -- so one `who_argues_against` call spans both frames.
AGAMBEN_POSITION = "sovereignty is exercised through the exception, not through war"

TILLY_DISAGREEMENT = (
    "Synthetic finding: the authors gathered here disagree about whether war "
    "making explains fixture state capacity at all."
)


@pytest.fixture(autouse=True)
def _no_real_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Poison any LLM construction/call for every test in this module via the
    project's established `AXIAL_LLM_PROVIDER=explode` idiom -- proving §7.5's
    "zero LLM calls" clause and giving a hidden `.complete()` nothing to pass
    silently through."""
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")


def _exploding_encoder(_texts: list[str]) -> list[list[float]]:
    """P0-2's own observable for D10: tiers 1-3 are exercised with no encoder
    loaded at all. Passing this in means a tier-1/2/3 resolution that reaches
    the embedding tier crashes loudly instead of passing quietly."""
    raise AssertionError("tiers 1-3 must resolve without ever loading an encoder")


# ---------------------------------------------------------------------------
# The fixture: a name layer, name pages, prose notes
# ---------------------------------------------------------------------------

NODES: list[dict[str, Any]] = [
    {"canonical": TILLY, "kind": "person", "aliases": ["Tilly", "C. Tilly 1975"]},
    {"canonical": AGAMBEN, "kind": "person", "aliases": ["Agamben"]},
    {"canonical": UNGOR, "kind": "person", "aliases": []},
    {"canonical": BELLICIST, "kind": "concept", "aliases": ["bellicist state-formation"]},
    {"canonical": SDF, "kind": "institution/group", "aliases": []},
    {"canonical": ROJAVA, "kind": "country/state/place", "aliases": []},
    {"canonical": PYD, "kind": "institution/group", "aliases": []},
    {"canonical": FOLD_SPACED, "kind": "country/state/place", "aliases": []},
    {"canonical": FOLD_HYPHENATED, "kind": "country/state/place", "aliases": []},
    {"canonical": BUDGETED_NAME, "kind": "country/state/place", "aliases": []},
]


def _write_name_layer(names_dir: Path) -> None:
    """`index.json` + `alias_map.json` in Reconcile's own persisted shapes
    (`axial.merge_names.write_index` / `write_alias_map`)."""
    names_dir.mkdir(parents=True, exist_ok=True)
    (names_dir / "index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generated_at": "2026-07-29T00:00:00Z",
                "names": [node["canonical"] for node in NODES],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (names_dir / "alias_map.json").write_text(
        json.dumps(
            {"version": 1, "generated_at": "2026-07-29T00:00:00Z", "nodes": NODES},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _render_note(frontmatter: dict[str, Any], body: str) -> str:
    import yaml

    return (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True, default_style='"')
        + "---\n"
        + body
    )


def _prose_note(
    *,
    chunk_id: str,
    author: str,
    year: int,
    claim: str,
    move: str,
    position_of: str,
    arguing_against: list[str],
    names: list[dict[str, str]],
    citations: list[dict[str, str]],
    position: str | None = None,
) -> dict[str, Any]:
    """One prose note's frontmatter in Materialize's own written shape
    (`axial.vault.build_frontmatter`): the answer block nested under
    `answers`, plain strings, never wikilinks.

    `position` given adds issue #496's frame-0.2 key alongside `position_of`;
    omitted leaves the pre-0.2 shape, which is what every note in the live
    corpus carries. The fixture holds both, since the corpus is a mixed frame
    and stays one."""
    answers: dict[str, Any] = {
        "claim": claim,
        "move": move,
        "position_of": position_of,
        "arguing_against": arguing_against,
        "names": names,
        "citations": citations,
        "about": ["fixture"],
    }
    if position is not None:
        answers["position"] = position
    return {
        "chunk_id": chunk_id,
        "source": f"{author} — A Synthetic Fixture Source",
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": author,
            "title": "A Synthetic Fixture Source",
            "date": year,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "chapter": "Synthetic Chapter",
        "frame_version": "1",
        "interrogated": {"pass": "interrogate", "model": "fixture", "at": "2026-07-29T00:00:00Z"},
        "answers": answers,
    }


PROSE_NOTES = [
    _prose_note(
        chunk_id=TILLY_NOTE,
        author="Charles Tilly",
        year=1975,
        claim=TILLY_CLAIM,
        move="argues",
        position_of="bellicist state formation",
        arguing_against=["Agamben"],
        names=[
            {"name": TILLY, "kind": "person"},
            {"name": BELLICIST, "kind": "concept"},
            {"name": ROJAVA, "kind": "country/state/place"},
        ],
        citations=[
            {"cited": AGAMBEN, "stance": "foil", "about": "the state of exception"},
            {"cited": "unmapped fixture author", "stance": "support", "about": "a side point"},
        ],
    ),
    _prose_note(
        chunk_id=AGAMBEN_NOTE,
        author="Giorgio Agamben",
        year=2005,
        claim=AGAMBEN_CLAIM,
        move="reframes",
        # Frame 0.2 (issue #496): this one note carries BOTH keys, and the
        # other two carry only `position_of`, so the fixture is the mixed
        # frame the corpus is.
        position_of="the author",
        position=AGAMBEN_POSITION,
        arguing_against=["C. Tilly 1975"],
        names=[
            {"name": AGAMBEN, "kind": "person"},
            {"name": BELLICIST, "kind": "concept"},
            {"name": TILLY, "kind": "person"},
        ],
        citations=[{"cited": "Tilly", "stance": "authority", "about": "war making"}],
    ),
    _prose_note(
        chunk_id=PYD_NOTE,
        author="A. Synthetic Author",
        year=2019,
        claim=PYD_CLAIM,
        move="describes",
        position_of="stateless self-administration",
        arguing_against=["charles  tilly"],
        names=[
            {"name": PYD, "kind": "institution/group"},
            {"name": ROJAVA, "kind": "country/state/place"},
            {"name": SDF, "kind": "institution/group"},
        ],
        citations=[{"cited": "C. Tilly 1975", "stance": "support", "about": "coercion"}],
    ),
]


def _write_prose_notes(vault_dir: Path) -> None:
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    # Reverse-alphabetical write order: enumeration order is neither the
    # answer nor alphabetical.
    for frontmatter in sorted(PROSE_NOTES, key=lambda note: note["chunk_id"], reverse=True):
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(
            _render_note(frontmatter, "Body.\n"), encoding="utf-8"
        )


def _write_artifact_note(vault_dir: Path) -> None:
    artifacts_dir = vault_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / f"{ARTIFACT_ID}.md").write_text(
        _render_note(
            {
                "artifact_id": ARTIFACT_ID,
                "source_id": TILLY_SOURCE_ID,
                "section": "Synthetic Section",
                "retrievable": True,
                "caption": "Table 1: synthetic fixture extraction rates",
                "cited_by": [],
            },
            "Body.\n",
        ),
        encoding="utf-8",
    )


def _name_page_body(
    canonical: str,
    aliases: list[str],
    members: list[tuple[str, str, int, str]],
    artifact_ids: list[str] = (),
    disagreement: tuple[str, list[str]] | None = None,
) -> str:
    """A name page body in Materialize's own render
    (`axial.materialize.render_name_page_body`), plus Gather's own section
    (`axial.gather.render_disagreement_section`) when there is one."""
    lines = [f"# {canonical}", ""]
    if aliases:
        lines += ["**Aliases:** " + ", ".join(aliases), ""]
    if artifact_ids:
        lines.append("**Artifacts:**")
        lines += [f"- [[{artifact_id}]]" for artifact_id in artifact_ids]
        lines.append("")
    lines.append("**Member notes:**")
    if not members:
        lines.append("(none)")
    for chunk_id, author, year, claim in members:
        lines.append(f"- [[{chunk_id}]] — {author} ({year}): {claim}")
    body = "\n".join(lines) + "\n"
    if disagreement is not None:
        text, runs_between = disagreement
        section = ["## What the authors here disagree about", "", text]
        if runs_between:
            section += ["", "**Runs between:** " + ", ".join(f"[[{n}]]" for n in runs_between)]
        body = body.rstrip("\n") + "\n\n" + "\n".join(section) + "\n"
    return body


# `canonical -> (aliases, members, artifact_ids, disagreement)`. Member order
# is the page's own written order, which is Materialize's (ascending
# chunk_id) -- `get_name` must preserve it verbatim, not re-sort.
NAME_PAGES: dict[str, tuple[list[str], list[tuple[str, str, int, str]], list[str], Any]] = {
    TILLY: (
        ["Tilly", "C. Tilly 1975"],
        [
            (AGAMBEN_NOTE, "Giorgio Agamben", 2005, AGAMBEN_CLAIM),
            (TILLY_NOTE, "Charles Tilly", 1975, TILLY_CLAIM),
        ],
        [ARTIFACT_ID],
        (TILLY_DISAGREEMENT, [AGAMBEN, BELLICIST]),
    ),
    AGAMBEN: (["Agamben"], [(AGAMBEN_NOTE, "Giorgio Agamben", 2005, AGAMBEN_CLAIM)], [], None),
    UNGOR: ([], [], [], None),
    BELLICIST: (
        ["bellicist state-formation"],
        [
            (AGAMBEN_NOTE, "Giorgio Agamben", 2005, AGAMBEN_CLAIM),
            (TILLY_NOTE, "Charles Tilly", 1975, TILLY_CLAIM),
        ],
        [],
        None,
    ),
    SDF: ([], [(PYD_NOTE, "A. Synthetic Author", 2019, PYD_CLAIM)], [], None),
    ROJAVA: (
        [],
        [
            (PYD_NOTE, "A. Synthetic Author", 2019, PYD_CLAIM),
            (TILLY_NOTE, "Charles Tilly", 1975, TILLY_CLAIM),
        ],
        [],
        None,
    ),
    PYD: ([], [(PYD_NOTE, "A. Synthetic Author", 2019, PYD_CLAIM)], [], None),
    FOLD_SPACED: ([], [], [], None),
    FOLD_HYPHENATED: ([], [], [], None),
    BUDGETED_NAME: ([], [(PYD_NOTE, "A. Synthetic Author", 2019, PYD_CLAIM)], [], None),
}


def _write_name_pages(vault_dir: Path) -> None:
    """Write every name page through the writer's OWN filename assignment
    (`axial.paths.name_page_filename` with one shared `used` set, in
    ascending-canonical order -- `axial.materialize.name_page_paths`), so the
    two colliding canonicals land on the same budgeted-down filenames the
    real writer would give them."""
    names_dir = vault_dir / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    paths = {
        canonical: names_dir / name_page_filename(names_dir, canonical, used)
        for canonical in sorted(NAME_PAGES)
    }
    for canonical in sorted(NAME_PAGES, reverse=True):  # adversarial write order
        aliases, members, artifact_ids, disagreement = NAME_PAGES[canonical]
        frontmatter = {
            "name": canonical,
            "kind": next(node["kind"] for node in NODES if node["canonical"] == canonical),
            "aliases": aliases,
            "member_count": len(members),
        }
        paths[canonical].write_text(
            _render_note(
                frontmatter,
                _name_page_body(canonical, aliases, members, artifact_ids, disagreement),
            ),
            encoding="utf-8",
        )


@pytest.fixture
def fixture_layer(tmp_path: Path) -> tuple[Path, Path]:
    """`(vault_dir, names_dir)` -- the whole fixture built before any tool is
    called, since every index in the query layer is built once per process
    per directory and does not re-scan a vault that changed underneath it."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_name_layer(names_dir)
    _write_name_pages(vault_dir)
    _write_prose_notes(vault_dir)
    _write_artifact_note(vault_dir)
    return vault_dir, names_dir


# ---------------------------------------------------------------------------
# find_names -- tiers 1-3, with no encoder loaded at all
# ---------------------------------------------------------------------------


def test_find_names_exact_canonical_is_tier_one(fixture_layer: tuple[Path, Path]):
    from axial.query import find_names

    vault_dir, names_dir = fixture_layer
    hits = find_names(
        TILLY, 10, names_dir=names_dir, vault_dir=vault_dir, encoder=_exploding_encoder
    )

    assert [hit.canonical for hit in hits] == [TILLY]
    hit = hits[0]
    assert hit.tier == "exact"
    assert hit.matched_on == TILLY
    assert hit.kind == "person"
    assert hit.aliases == ["Tilly", "C. Tilly 1975"]
    assert hit.member_count == 2, (
        "member_count is the name page's own frontmatter value, not a recount"
    )


def test_find_names_reaches_the_canonical_through_an_alias(fixture_layer: tuple[Path, Path]):
    """The measured failure exact match alone produces: the index holds
    "Charles Tilly" and briefs say Tilly."""
    from axial.query import find_names

    vault_dir, names_dir = fixture_layer
    hits = find_names(
        "Tilly", 10, names_dir=names_dir, vault_dir=vault_dir, encoder=_exploding_encoder
    )

    assert [hit.canonical for hit in hits] == [TILLY]
    assert hits[0].tier == "alias"
    assert hits[0].matched_on == "Tilly"


def test_find_names_reaches_the_canonical_through_phase_as_own_fold(
    fixture_layer: tuple[Path, Path],
):
    """Tier 3 is the fold Phase A already applies to surface forms (case,
    whitespace, punctuation, hyphen to a space -- `specs/PRODUCT.md` §7.16,
    issue #463), reused rather than re-derived here."""
    from axial.query import find_names

    vault_dir, names_dir = fixture_layer
    for query in ("charles  tilly", "CHARLES TILLY", "Charles-Tilly"):
        hits = find_names(
            query, 10, names_dir=names_dir, vault_dir=vault_dir, encoder=_exploding_encoder
        )
        assert [hit.canonical for hit in hits] == [TILLY], f"{query!r} should fold onto {TILLY!r}"
        assert hits[0].tier == "folded"
        assert hits[0].matched_on == TILLY

    # The fold reaches an ALIAS too, not only a canonical.
    hits = find_names(
        "bellicist  state  formation",
        10,
        names_dir=names_dir,
        vault_dir=vault_dir,
        encoder=_exploding_encoder,
    )
    assert [hit.canonical for hit in hits] == [BELLICIST]
    assert hits[0].tier == "folded"


def test_find_names_tiers_are_exhausted_in_order_not_unioned(fixture_layer: tuple[Path, Path]):
    """An exact canonical hit is not diluted with the fold's own wider set:
    "SDF" is a canonical, so tier 1 answers and tiers 2-4 never run."""
    from axial.query import find_names

    vault_dir, names_dir = fixture_layer
    hits = find_names(SDF, 10, names_dir=names_dir, vault_dir=vault_dir, encoder=_exploding_encoder)

    assert [(hit.canonical, hit.tier) for hit in hits] == [(SDF, "exact")]


def test_find_names_on_a_name_the_corpus_does_not_hold_returns_empty_not_an_error(
    fixture_layer: tuple[Path, Path],
):
    """P0-2's own observable: a query the corpus does not hold returns `[]`
    against the pinned vault while `find_names("SDF")` does not. An empty
    result is a real answer the caller can report as an honest resolution
    failure -- never an exception, never a nearest-neighbour substitution that
    hands the agent the wrong scholar."""
    from axial.query import find_names

    vault_dir, names_dir = fixture_layer
    absent = find_names(
        UNHELD_QUERY, 10, names_dir=names_dir, vault_dir=vault_dir, encoder=_exploding_encoder
    )
    present = find_names(
        SDF, 10, names_dir=names_dir, vault_dir=vault_dir, encoder=_exploding_encoder
    )

    assert absent == [], f"expected an empty list for {UNHELD_QUERY!r}, got {absent!r}"
    assert present != []
    assert isinstance(absent, list), "the empty answer is a list, not None and not an exception"


def test_find_names_is_deterministic_and_respects_its_limit(fixture_layer: tuple[Path, Path]):
    from axial.query import find_names

    vault_dir, names_dir = fixture_layer
    first = find_names(
        "israel palestine",
        10,
        names_dir=names_dir,
        vault_dir=vault_dir,
        encoder=_exploding_encoder,
    )
    second = find_names(
        "israel palestine",
        10,
        names_dir=names_dir,
        vault_dir=vault_dir,
        encoder=_exploding_encoder,
    )

    assert [hit.canonical for hit in first] == [FOLD_SPACED, FOLD_HYPHENATED], (
        "two canonicals folding onto the same key come back in ascending "
        f"canonical order, got {[hit.canonical for hit in first]!r}"
    )
    assert first == second, "§7.5's determinism contract: same query, same fixture, same order"

    truncated = find_names(
        "israel palestine", 1, names_dir=names_dir, vault_dir=vault_dir, encoder=_exploding_encoder
    )
    assert [hit.canonical for hit in truncated] == [FOLD_SPACED]


# ---------------------------------------------------------------------------
# get_name
# ---------------------------------------------------------------------------


def test_get_name_returns_the_pages_own_members_in_the_pages_own_order(
    fixture_layer: tuple[Path, Path],
):
    from axial.query import get_chunk, get_name

    vault_dir, _names_dir = fixture_layer
    page = get_name(TILLY, vault_dir=vault_dir)

    assert page.canonical == TILLY
    assert page.kind == "person"
    assert page.aliases == ["Tilly", "C. Tilly 1975"]
    assert page.member_count == 2

    assert [member.chunk_id for member in page.members] == [AGAMBEN_NOTE, TILLY_NOTE], (
        "members come back in the page's own written order (Materialize's), "
        "and the Artifacts section is not mistaken for a member line"
    )
    first, second = page.members
    assert first.source_id == AGAMBEN_SOURCE_ID
    assert first.author == "Giorgio Agamben"
    assert first.year == "2005"
    assert first.claim == AGAMBEN_CLAIM
    assert second.claim == TILLY_CLAIM

    for member in page.members:
        assert get_chunk(member.chunk_id, vault_dir=vault_dir).chunk_id == member.chunk_id, (
            "every id a tool returns resolves back through get_chunk"
        )


def test_get_name_disagreement_present_is_distinguishable_from_absent(
    fixture_layer: tuple[Path, Path],
):
    from axial.query import get_name

    vault_dir, _names_dir = fixture_layer

    with_finding = get_name(TILLY, vault_dir=vault_dir)
    assert with_finding.disagreement is not None
    assert with_finding.disagreement.text == TILLY_DISAGREEMENT
    assert with_finding.disagreement.names == [AGAMBEN, BELLICIST], (
        "the `Runs between:` wikilinks are the disagreement's own names[]"
    )

    without_finding = get_name(AGAMBEN, vault_dir=vault_dir)
    assert without_finding.disagreement is None, (
        "a null finding writes no section at all, and `None` is how that is "
        "reported -- never an empty-string text that reads like a finding"
    )


def test_get_name_finds_a_page_whose_filename_was_budgeted_down(
    fixture_layer: tuple[Path, Path],
):
    """§7.5's filenames-are-display-artifacts rule, for name pages: two
    canonicals sanitize to one filename, so the second gets a hash suffix
    the reader cannot reproduce (the writer's `used` set is a write-order
    fact). The `name` frontmatter is the sole authoritative id."""
    from axial.query import get_name

    vault_dir, _names_dir = fixture_layer

    assert get_name(FOLD_HYPHENATED, vault_dir=vault_dir).canonical == FOLD_HYPHENATED
    page = get_name(BUDGETED_NAME, vault_dir=vault_dir)
    assert page.canonical == BUDGETED_NAME, (
        "resolving by the un-suffixed filename would return the OTHER page, "
        "whose `name` frontmatter says a different canonical"
    )
    assert [member.chunk_id for member in page.members] == [PYD_NOTE]


def test_get_name_on_an_unknown_canonical_raises_naming_it(fixture_layer: tuple[Path, Path]):
    from axial.query import get_name

    vault_dir, _names_dir = fixture_layer
    with pytest.raises(Exception) as exc_info:
        get_name(UNHELD_QUERY, vault_dir=vault_dir)

    assert UNHELD_QUERY in str(exc_info.value)


# ---------------------------------------------------------------------------
# name_neighbors / who_cites / who_argues_against
# ---------------------------------------------------------------------------


def test_name_neighbors_ranks_co_occurring_names_by_shared_note_count(
    fixture_layer: tuple[Path, Path],
):
    """The cheapest real edge the interrogation produced: two names on one
    note are two things one author discussed together. `bellicist state
    formation` shares two notes with Tilly; Agamben and Rojava share one
    each and tie-break on canonical ascending."""
    from axial.query import name_neighbors

    vault_dir, names_dir = fixture_layer
    neighbors = name_neighbors(TILLY, 10, vault_dir=vault_dir, names_dir=names_dir)

    assert [(n.canonical, n.shared_note_count) for n in neighbors] == [
        (BELLICIST, 2),
        (AGAMBEN, 1),
        (ROJAVA, 1),
    ]
    assert neighbors[0].kind == "concept"
    assert TILLY not in [n.canonical for n in neighbors], "a name is never its own neighbour"

    assert name_neighbors(TILLY, 1, vault_dir=vault_dir, names_dir=names_dir) == neighbors[:1]


def test_who_cites_matches_every_surface_the_alias_map_folds_in(
    fixture_layer: tuple[Path, Path],
):
    """Two notes cite Tilly, one by the alias "Tilly" and one by the alias
    "C. Tilly 1975" -- neither is string-equal to the canonical, and both
    must be found, each carrying the author's own stance and `about`."""
    from axial.query import get_chunk, who_cites

    vault_dir, names_dir = fixture_layer
    edges = who_cites(TILLY, vault_dir=vault_dir, names_dir=names_dir)

    assert [(e.chunk_id, e.cited, e.stance) for e in edges] == [
        (AGAMBEN_NOTE, "Tilly", "authority"),
        (PYD_NOTE, "C. Tilly 1975", "support"),
    ], f"expected both alias-cited edges sorted by chunk_id, got {edges!r}"
    assert edges[0].source_id == AGAMBEN_SOURCE_ID
    assert edges[0].about == "war making"
    for edge in edges:
        assert get_chunk(edge.chunk_id, vault_dir=vault_dir).chunk_id == edge.chunk_id

    assert who_cites(AGAMBEN, vault_dir=vault_dir, names_dir=names_dir)[0].stance == "foil", (
        "the author's own stance vocabulary (support/foil/authority) survives"
    )
    assert who_cites(UNGOR, vault_dir=vault_dir, names_dir=names_dir) == []


def test_who_argues_against_carries_the_stated_position_and_claim(
    fixture_layer: tuple[Path, Path],
):
    """Same alias matching, plus each note's own stated `position` and
    one-sentence `claim`, so the opposition is legible without a second
    fetch. One note names the alias "C. Tilly 1975", the other only a folded
    variant of the canonical.

    The two edges also span issue #496's mixed frame in one result set: the
    Agamben note carries a frame-0.2 `position` key and is read from it, the
    PYD note carries only `position_of` and falls back to it, and nothing in
    the result marks which is which -- key presence decides, never
    `frame_version`."""
    from axial.query import who_argues_against

    vault_dir, names_dir = fixture_layer
    edges = who_argues_against(TILLY, vault_dir=vault_dir, names_dir=names_dir)

    assert [(e.chunk_id, e.arguing_against) for e in edges] == [
        (AGAMBEN_NOTE, "C. Tilly 1975"),
        (PYD_NOTE, "charles  tilly"),
    ]
    assert [e.position for e in edges] == [
        AGAMBEN_POSITION,  # frame 0.2: the `position` key is present
        "stateless self-administration",  # pre-0.2: `position_of` is the fallback
    ]
    assert edges[0].claim == AGAMBEN_CLAIM
    assert edges[0].source_id == AGAMBEN_SOURCE_ID

    assert [
        e.chunk_id for e in who_argues_against(AGAMBEN, vault_dir=vault_dir, names_dir=names_dir)
    ] == [TILLY_NOTE]


# ---------------------------------------------------------------------------
# coverage_count
# ---------------------------------------------------------------------------


def test_coverage_count_is_per_name_and_ascending(fixture_layer: tuple[Path, Path]):
    """§7.7's denominator: `{canonical: member_count}` read off the name
    pages' own `member_count`, for every name page in the vault, built in
    ascending-canonical order. A polity is a name whose `kind` is
    `country/state/place`; nothing special-cases it."""
    from axial.query import coverage_count

    vault_dir, _names_dir = fixture_layer
    counts = coverage_count(vault_dir=vault_dir)

    assert counts == {
        AGAMBEN: 1,
        TILLY: 2,
        FOLD_SPACED: 0,
        FOLD_HYPHENATED: 0,
        BUDGETED_NAME: 1,
        PYD: 1,
        ROJAVA: 2,
        SDF: 1,
        UNGOR: 0,
        BELLICIST: 2,
    }
    assert list(counts) == sorted(counts), "built in ascending-canonical order"
    assert counts[ROJAVA] == 2, (
        "a country/state/place name gets a coverage number like any other name"
    )


# ---------------------------------------------------------------------------
# The whole tool set, with no LLM client and no encoder
# ---------------------------------------------------------------------------


def test_the_full_name_tool_set_runs_with_no_llm_client_and_no_encoder(
    fixture_layer: tuple[Path, Path],
):
    """P0-2's headline observable: the full tool set is exercised with no LLM
    client present. `AXIAL_LLM_PROVIDER=explode` (autouse above) makes any
    hidden model call crash; `_exploding_encoder` makes any hidden encoder
    load crash."""
    from axial.query import (
        coverage_count,
        find_names,
        get_name,
        name_neighbors,
        who_argues_against,
        who_cites,
    )

    vault_dir, names_dir = fixture_layer

    assert find_names(
        "Agamben", 10, names_dir=names_dir, vault_dir=vault_dir, encoder=_exploding_encoder
    )
    assert get_name(AGAMBEN, vault_dir=vault_dir).canonical == AGAMBEN
    assert name_neighbors(AGAMBEN, 10, vault_dir=vault_dir, names_dir=names_dir)
    assert who_cites(AGAMBEN, vault_dir=vault_dir, names_dir=names_dir)
    assert who_argues_against(AGAMBEN, vault_dir=vault_dir, names_dir=names_dir)
    assert coverage_count(vault_dir=vault_dir)
