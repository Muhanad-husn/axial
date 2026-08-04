"""Inner unit tests for two `detail` seams: issue #493's `_shared_note_count_
distribution` on `name_neighbors`, and issue #650's follow-up
`_resolution_detail` on the store-backed tools (specs/PHASE-B.md §7.5/§7.6).

Before this, `name_neighbors` always left `ToolResult.detail` `None` -- a
returned neighbour list carried a canonical string per hit and nothing about
its own `shared_note_count`, so a caller reading the persisted §7.6 record
could not tell a real ranking gradient (a handful of high counts, a long
tail) from a ranked list whose ranking carries no signal past the first tie
(a hub anchor whose neighbours mostly sit at the floor). The compact
min/median/max/floor-count summary this module adds is the fix, and these
tests pin its arithmetic directly, plus the wrapper wiring it through
`_name_neighbors` (`axial.retrieve.tools`) to a real `axial.query.names`
call -- the outer, whole-loop persistence path (that the loop then writes
this same string onto the trajectory entry) is covered by
`axial.retrieve.test_loop`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from axial.query import store as note_store
from axial.query.names import NameNeighbor
from axial.retrieve.tools import TOOL_REGISTRY, _shared_note_count_distribution


def test_empty_neighbor_list_has_no_distribution_to_describe():
    assert _shared_note_count_distribution([]) is None


def test_a_single_neighbor_is_its_own_min_median_and_max():
    neighbors = [NameNeighbor(canonical="A", kind=None, shared_note_count=4)]
    assert _shared_note_count_distribution(neighbors) == (
        "1 neighbors, shared_note_count min=4 median=4 max=4 (1 of 1 at the floor of 4)"
    )


def test_distribution_matches_the_neighbours_it_was_given_measured_shape():
    """Mirrors the measured real-index shape this fix was written from
    (`name_neighbors('state formation')`: 30 neighbours, 26 of them tied at
    `shared_note_count` 1) -- a ranked list whose ranking carries no signal
    past the head, now checkable from the summary alone rather than by
    counting a 30-line breakdown."""
    neighbors = [
        NameNeighbor(canonical=f"tied-{i}", kind=None, shared_note_count=1) for i in range(26)
    ] + [
        NameNeighbor(canonical="mid-a", kind=None, shared_note_count=2),
        NameNeighbor(canonical="mid-b", kind=None, shared_note_count=2),
        NameNeighbor(canonical="mid-c", kind=None, shared_note_count=3),
        NameNeighbor(canonical="top", kind=None, shared_note_count=5),
    ]
    assert len(neighbors) == 30

    result = _shared_note_count_distribution(neighbors)

    assert result == (
        "30 neighbors, shared_note_count min=1 median=1 max=5 (26 of 30 at the floor of 1)"
    )


def test_an_even_count_of_neighbours_averages_the_two_middle_values():
    neighbors = [
        NameNeighbor(canonical="a", kind=None, shared_note_count=1),
        NameNeighbor(canonical="b", kind=None, shared_note_count=2),
    ]
    assert _shared_note_count_distribution(neighbors) == (
        "2 neighbors, shared_note_count min=1 median=1.5 max=2 (1 of 2 at the floor of 1)"
    )


def test_the_distribution_is_order_independent_of_the_neighbours_list():
    """The summary describes the VALUES, never the order `name_neighbors`
    (ranked by count times idf, specs/PHASE-B.md §7.5) returned them in."""
    ascending = [
        NameNeighbor(canonical="a", kind=None, shared_note_count=1),
        NameNeighbor(canonical="b", kind=None, shared_note_count=3),
        NameNeighbor(canonical="c", kind=None, shared_note_count=1),
    ]
    descending = list(reversed(ascending))
    assert _shared_note_count_distribution(ascending) == _shared_note_count_distribution(descending)


# ---------------------------------------------------------------------------
# The wrapper wiring (`_name_neighbors` in `axial.retrieve.tools`, dispatched
# through `TOOL_REGISTRY`): a real `axial.query.names.name_neighbors` call's
# own neighbours end up summarized in `ToolResult`-shaped output, not just
# the pure function in isolation above.
# ---------------------------------------------------------------------------


def _write_note(prose_dir: Path, chunk_id: str, names: list[str]) -> None:
    frontmatter: dict[str, Any] = {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {"author": "Someone", "title": "T", "date": 2000},
        "answers": {
            "claim": "A claim.",
            "position_of": "the author",
            "names": [{"name": name} for name in names],
        },
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


def test_name_neighbors_tool_call_carries_the_distribution_of_the_neighbours_dispatched(
    tmp_path: Path,
):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)

    # Two notes name ("Anchor", "Common") -- Common's shared_note_count is 2.
    # One note names ("Anchor", "Rare") -- Rare's shared_note_count is 1.
    _write_note(prose_dir, "src-1_1_a_001", ["Anchor", "Common"])
    _write_note(prose_dir, "src-1_2_a_001", ["Anchor", "Common"])
    _write_note(prose_dir, "src-2_1_a_001", ["Anchor", "Rare"])

    spec = TOOL_REGISTRY["name_neighbors"]
    # Five positional slots since issue #650: `map_dir` joined `vault_dir`/
    # `envelopes_dir`/`names_dir` on every adapter, for `positions_on`; and
    # five RETURNED slots since its second follow-up, `resolved_name` last.
    ids, count, total, detail, resolved = spec.call(
        {"canonical": "Anchor"}, vault_dir, None, None, None
    )

    assert count == 2
    assert set(ids) == {"Common", "Rare"}
    assert total is None, "name_neighbors carries no pre-cap total, unchanged by this fix"
    assert resolved is None, "a name-layer tool takes a canonical; it resolves no phrase"
    assert detail == (
        "2 neighbors, shared_note_count min=1 median=1.5 max=2 (1 of 2 at the floor of 1)"
    )


# ---------------------------------------------------------------------------
# `_resolution_detail` (issue #650's follow-up): a zero result says what it
# looked for. Measured on the live paired run -- 25 of 42 steps returned a
# bare `0/0` because a descriptive phrase never became a name, and one phrase
# was re-asked six times in a row against that silence.
# ---------------------------------------------------------------------------

STATE_A = "mann-2012-aaaaaaaaaaaa_000_intro_001"
FORMATION_A = "mann-2012-aaaaaaaaaaaa_001_intro_002"
STATE_B = "hall-2006-bbbbbbbbbbbb_000_intro_001"


def _store_vault(tmp_path: Path) -> tuple[Path, Path]:
    """`(vault_dir, names_dir)` -- a store whose `names` table carries two
    doors sharing a word (`the state`, 2 notes across 2 sources; `state
    formation`, 1 note in 1 source), and an empty name layer, so every
    resolution here goes through the routes beyond the exact tiers."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    note_store.write_store(
        note_store.store_path(vault_dir),
        sources=[
            ("mann-2012-aaaaaaaaaaaa", "Mann", "Sources", "2012", 2012),
            ("hall-2006-bbbbbbbbbbbb", "Hall", "Anatomy", "2006", 2006),
        ],
        notes=[
            (STATE_A, "mann-2012-aaaaaaaaaaaa", "One", None, "A cage.", "Mann's own"),
            (FORMATION_A, "mann-2012-aaaaaaaaaaaa", "Two", None, "War made states.", None),
            (STATE_B, "hall-2006-bbbbbbbbbbbb", "One", None, "A bargain.", None),
        ],
        names=[
            ("the state", "concept", "the state"),
            ("state formation", "concept", "state formation"),
        ],
        note_names=[
            (STATE_A, "mann-2012-aaaaaaaaaaaa", "the state", "concept"),
            (FORMATION_A, "mann-2012-aaaaaaaaaaaa", "state formation", "concept"),
            (STATE_B, "hall-2006-bbbbbbbbbbbb", "the state", "concept"),
        ],
        note_arguing_against=[],
        note_citations=[],
    )
    return vault_dir, names_dir


def test_find_notes_answers_a_descriptive_phrase_and_says_what_it_resolved_to(tmp_path: Path):
    """The defect: `about` used to resolve through the exact tiers alone and
    then fall back to the raw surface, which matches no `note_names` row --
    every phrase a model actually writes returned `0/0`."""
    vault_dir, names_dir = _store_vault(tmp_path)
    spec = TOOL_REGISTRY["find_notes"]

    ids, count, total, detail, resolved = spec.call(
        {"about": "the modern state and war"}, vault_dir, None, names_dir, None
    )

    assert count == 2 and total == 2
    assert set(ids) == {STATE_A, STATE_B}
    assert "'the modern state and war' resolved to 'the state'" in detail
    # And as DATA, for the record: what the run leaned on, not the phrase.
    assert resolved == "the state"
    assert "tier=word, member_count=2, source_count=2" in detail
    # What came back is still described beside what was looked for.
    assert "2 notes across 2 sources" in detail


def test_the_other_doors_a_phrase_reaches_are_named_answer_or_not(tmp_path: Path):
    """Both shapes, and the non-empty one is the case that needs it most:
    re-measured live, `violence against civilians Syria` resolves to
    `Filipino civilians` -- ONE note -- while `Syria` sits further down the
    same slate, because a compound query's words are ordered rarest-first
    (#632). A thin answer to the wrong door does not look like a failure, so
    the alternatives ride on every non-exact resolution, not just a zero."""
    vault_dir, names_dir = _store_vault(tmp_path)
    spec = TOOL_REGISTRY["find_notes"]
    others = "other names this phrase reaches: state formation (member_count=1, source_count=1)"

    answered = spec.call({"about": "state"}, vault_dir, None, names_dir, None)
    emptied = spec.call(
        {"about": "state", "published_after": 2020}, vault_dir, None, names_dir, None
    )

    assert answered[1] == 2 and "'state' resolved to 'the state'" in answered[3]
    # A filter narrows which notes come back, never which name was queried.
    assert answered[4] == emptied[4] == "the state"
    assert others in answered[3]
    assert emptied[:2] == ([], 0)
    assert others in emptied[3]


def test_a_phrase_that_resolves_to_nothing_says_so_instead_of_a_bare_zero(tmp_path: Path):
    """The other zero: nothing matched, and the detail says the phrase and
    its words were both tried, so the model can tell "this corpus has
    nothing on it" from "your words never became a name"."""
    vault_dir, names_dir = _store_vault(tmp_path)
    spec = TOOL_REGISTRY["find_notes"]

    ids, count, _total, detail, resolved = spec.call(
        {"about": "zzqqx quorf"}, vault_dir, None, names_dir, None
    )

    assert (ids, count) == ([], 0)
    assert detail == (
        "'zzqqx quorf' matched no name this corpus carries -- "
        "the phrase itself and each of its words were tried"
    )
    # A call that resolved nothing records nothing: an unresolved phrase is
    # not a queried name and must not enter §7.7's map or §7.13's denominator.
    assert resolved is None


def test_a_tool_with_no_substrate_claims_no_resolution_it_never_attempted(tmp_path: Path):
    """`detail` must not say "matched no name" when nothing was looked up at
    all: a vault with no store, and a corpus with no argument map, are both
    honest silences rather than a resolution failure they never reached."""
    bare = tmp_path / "bare-vault"
    bare.mkdir()
    vault_dir, names_dir = _store_vault(tmp_path)

    *_, no_store, no_store_name = TOOL_REGISTRY["find_notes"].call(
        {"about": "the state"}, bare, None, names_dir, None
    )
    *_, no_map, no_map_name = TOOL_REGISTRY["positions_on"].call(
        {"name": "the state"}, vault_dir, None, names_dir, None
    )

    assert no_store is None and no_map is None
    assert no_store_name is None and no_map_name is None
