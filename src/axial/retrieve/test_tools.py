"""Inner unit tests for issue #650's `_resolution_detail` on the store-backed
tools (specs/PHASE-B.md §7.5/§7.6). `name_neighbors` and its own
`_shared_note_count_distribution` `detail` seam (issue #493) were retired
along with the name-layer tools (DEC-75, issue #853): there is no page-
walking tool left to carry that summary.
"""

from __future__ import annotations

from pathlib import Path

from axial.query import store as note_store
from axial.retrieve.tools import TOOL_REGISTRY

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
