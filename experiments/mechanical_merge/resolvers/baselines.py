"""The two floors every candidate resolver has to beat.

Neither reads a single character of a surface form. They exist because
"partition agreement" is only meaningful against them: half of the live pass's
clusters were left entirely unmerged, so a resolver scoring 50% may be doing
nothing at all.
"""

from __future__ import annotations

from experiments.mechanical_merge.harness import Partition


def split_all(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Never merge. Zero over-merges by construction -- the safest possible
    resolver, and the honest zero point for pair recall."""
    return frozenset(frozenset({member}) for member in members)


def merge_all(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Trust the clusterer completely: every member of a cluster is the same
    thing. The other floor -- perfect recall, and the over-merge disaster the
    whole pass exists to prevent."""
    return frozenset({frozenset(members)})
