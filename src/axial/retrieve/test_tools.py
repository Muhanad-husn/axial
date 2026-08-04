"""Inner unit tests for issue #493's own seam: `_shared_note_count_
distribution`, `name_neighbors`' new `detail` (specs/PHASE-B.md §7.5/§7.6).

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
    # `envelopes_dir`/`names_dir` on every adapter, for `positions_on`.
    ids, count, total, detail = spec.call({"canonical": "Anchor"}, vault_dir, None, None, None)

    assert count == 2
    assert set(ids) == {"Common", "Rare"}
    assert total is None, "name_neighbors carries no pre-cap total, unchanged by this fix"
    assert detail == (
        "2 neighbors, shared_note_count min=1 median=1.5 max=2 (1 of 2 at the floor of 1)"
    )
