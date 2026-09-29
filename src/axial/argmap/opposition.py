"""Issue #860: opposition-seeded bags for `axial map build --grouping
opposition`. A passage's keys are what its author said they argue against:
each resolved `arguing_against` target (`arg:<canonical>`) and each work cited
with stance `foil` (`foil:<normalised citation>`), read from `notes.db`."""

from __future__ import annotations

import collections
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Sequence

from axial.query import store as note_store

if TYPE_CHECKING:
    from axial.argmap.build import Passage


def _normalise(cited: str) -> str:
    return " ".join(cited.casefold().split())


def load_opposition_keys(vault_dir: Path) -> dict[str, list[str]]:
    """`chunk_id -> keys`, sorted, from the vault's `notes.db`. `FileNotFoundError`
    when the vault has no store: without it there is nothing to group by."""
    connection = note_store.connect(vault_dir)
    if connection is None:
        raise FileNotFoundError(f"no {note_store.STORE_FILENAME} under {vault_dir}")
    keys: dict[str, set[str]] = collections.defaultdict(set)
    with connection:
        for chunk_id, canonical in connection.execute(
            "SELECT chunk_id, resolved_canonical FROM note_arguing_against "
            "WHERE resolved_canonical IS NOT NULL"
        ):
            keys[chunk_id].add(f"arg:{canonical}")
        for chunk_id, cited in connection.execute(
            "SELECT chunk_id, cited FROM note_citations WHERE lower(stance) = 'foil'"
        ):
            if _normalise(cited):
                keys[chunk_id].add(f"foil:{_normalise(cited)}")
    connection.close()
    return {chunk_id: sorted(found) for chunk_id, found in keys.items()}


def opposition_bags(
    passages: Sequence[Passage], keys: Mapping[str, Sequence[str]]
) -> tuple[dict[str, list[Passage]], list[Passage]]:
    """`(bags, rest)`: one bag per key, and the passages that fall back to
    wording bags.

    A key held by fewer than two passages forms no bag. A passage with several
    keys joins the ONE key held across the most distinct books, then by most
    passages, then lexically: the widest opposition is the one that puts
    different books in a room together, and the ordering is total, so a rebuild
    reproduces it. A bag the passages then leave under two members dissolves
    into `rest`."""
    held: dict[str, list[Passage]] = collections.defaultdict(list)
    for passage in passages:
        for key in keys.get(passage.chunk_id, ()):
            held[key].append(passage)
    usable = {key: members for key, members in held.items() if len(members) >= 2}
    rank = {
        key: (-len({m.source_id for m in members}), -len(members), key)
        for key, members in usable.items()
    }
    bags: dict[str, list[Passage]] = collections.defaultdict(list)
    rest: list[Passage] = []
    for passage in passages:
        candidates = [key for key in keys.get(passage.chunk_id, ()) if key in usable]
        if candidates:
            bags[min(candidates, key=rank.__getitem__)].append(passage)
        else:
            rest.append(passage)
    kept = {}
    for key, members in bags.items():
        if len(members) >= 2:
            kept[key] = members
        else:
            rest.extend(members)
    return kept, sorted(rest, key=lambda passage: passage.chunk_id)
