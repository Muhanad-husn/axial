"""Regression test for a gap in the counter-position grounds id repair
(`axial.analyze.synthesis._resolve_counter_position_ground`): a real paid
eval run died at its final step, losing a finished synthesis, because the
model cited a grounds id keeping its head AND its trailing per-chunk index
but eliding the SLUG between them --
`malesevic-2007-323a2518e61b_59_002`, whose real note is
`malesevic-2007-323a2518e61b_59_the-expansion-and-externalisation-of-
violence_002`. Neither existing repair catches this shape: the suffix
repair's tail anchor (`..._59_002`) matches no real id, because the slug
always sits between the order key and the index; the prefix repair's head
anchor (`..._59_002_`) matches no real id either, because `002` is never a
component of a real id's head. The two anchors the model DID keep -- the
head and the index -- together identify the chunk uniquely, which is what
the third repair, `_resolve_head_and_index`, now uses.

Given a fixture vault whose real chunk ids share one source's head prefix
      and, across two different documents, a repeated trailing index, with
      only the slug differing between sibling ids
  And a cited grounds ref_id of the head-plus-index shape, eliding the slug
When  `_resolve_counter_position_ground` resolves that ref_id
Then  it returns the one real chunk id both anchors uniquely identify

Given a cited ref_id whose head+index anchors match TWO real ids at once
      (the same head, the same trailing index, different slugs)
When  it is resolved
Then  `UnresolvableCounterPositionGroundError` is still raised -- ambiguity
      is a hard error, never guessed at, exactly as firm as before this
      repair existed

Given a wholly fabricated ref_id matching no real id under any of the three
      repairs
When  it is resolved
Then  `UnresolvableCounterPositionGroundError` is still raised

See `_resolve_head_and_index`'s own docstring (src/axial/analyze/
synthesis.py) for the anti-confabulation argument this repair extends, and
specs/PHASE-B.md's truncated-citation-repair paragraph (§7.4) for the two
repairs it sits alongside.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from axial.analyze.synthesis import (
    UnresolvableCounterPositionGroundError,
    _resolve_counter_position_ground,
)

HEAD = "malesevic-2007-323a2518e61b"


def _write_chunk(prose_dir: Path, chunk_id: str) -> None:
    text = (
        "---\n"
        f"chunk_id: {chunk_id}\n"
        "section: Synthetic Section\n"
        f"chunk_text: 'SENTINEL_{chunk_id}: synthetic prose.'\n"
        "---\n"
        "Body.\n"
    )
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    prose_dir = tmp_path / "prose"
    prose_dir.mkdir(parents=True)
    # Document 59's four real chunks -- the exact shape the live failure's
    # own head+index matched down to one of. A cited "_59_002" must find
    # only the second.
    for slug, index in [
        ("the-expansion-and-externalisation-of-violence", "001"),
        ("the-expansion-and-externalisation-of-violence", "002"),
        ("conclusion", "003"),
        ("conclusion", "004"),
    ]:
        _write_chunk(prose_dir, f"{HEAD}_59_{slug}_{index}")
    # Document 60's two chunks share BOTH a head and a trailing index, so a
    # head+index citation of them is genuinely ambiguous.
    for slug in ("alpha-slug", "beta-slug"):
        _write_chunk(prose_dir, f"{HEAD}_60_{slug}_003")
    return tmp_path


def test_head_plus_index_citation_resolves_to_the_one_real_chunk(vault_dir: Path):
    resolved = _resolve_counter_position_ground(f"{HEAD}_59_002", vault_dir=vault_dir)
    assert resolved == f"{HEAD}_59_the-expansion-and-externalisation-of-violence_002"


def test_ambiguous_head_plus_index_still_raises(vault_dir: Path):
    with pytest.raises(UnresolvableCounterPositionGroundError):
        _resolve_counter_position_ground(f"{HEAD}_60_003", vault_dir=vault_dir)


def test_fabricated_id_still_raises(vault_dir: Path):
    with pytest.raises(UnresolvableCounterPositionGroundError):
        _resolve_counter_position_ground(
            "totally-fabricated-2099-deadbeef0000_1_999", vault_dir=vault_dir
        )
