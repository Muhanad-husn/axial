"""The worst-case clusters PR #441 and its working notes name by hand.

These are the traps that killed `reasoning: false` -- the setting that was 5x
faster and over-merged 55 clusters against 7. A mechanical resolver is not
interesting because it scores well on `Faber & Faber` / `Faber and Faber`; it
is interesting only if it refuses these. They are scored as their own table,
separately from the corpus-wide run, because a corpus average hides them.

Each entry names the cluster by a substring that identifies its members in the
decision log, so the gold partition is read from the live pass rather than
asserted here.
"""

from __future__ import annotations

# (label, [surface forms that must appear in the cluster], what it tests)
HARD_CASES: list[tuple[str, list[str], str]] = [
    (
        "orourke-years",
        ["O'Rourke & Williamson"],
        "same authors, different works -- the year is the whole distinction",
    ),
    (
        "mendick-byline",
        ["Robert Mendick"],
        "author against a co-authored byline; one string contains the other",
    ),
    (
        "dignitas",
        ["dignitas"],
        "a word against a Latin phrase beginning with it",
    ),
    (
        "huxley",
        ["Aldous Huxley", "Thomas Huxley"],
        "two people sharing an ambiguous surname",
    ),
    (
        "upper-volta",
        ["Upper Volta"],
        "pure surface similarity that must be refused",
    ),
    (
        "khalife",
        ["Khalife"],
        "different people, one shared surname, diacritics in play",
    ),
    (
        "phelps-brown",
        ["Phelps-Brown"],
        "citation-variant orthography that SHOULD fold",
    ),
]


def select(clusters, case_forms: list[str]):
    """Every recorded cluster containing all of `case_forms` as substrings of
    some member."""
    found = []
    for cluster in clusters:
        joined = "\n".join(cluster.members)
        if all(form in joined for form in case_forms):
            found.append(cluster)
    return found
