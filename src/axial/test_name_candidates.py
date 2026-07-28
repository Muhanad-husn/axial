"""Issue #446: the merge pass never sees a name and its variant because slice
04's clustering never puts them in one cluster. This module (`axial.
name_candidates`) is a second, deterministic, LLM-free candidate-generation
step that proposes the missing pairs as additional clusters for the SAME
merge call (`axial.merge_names`) to decide -- it never merges anything
itself.

Fixtures below are drawn directly from the issue's own worked examples, not
invented, so a passing suite here is evidence against the exact cases the
issue names.
"""

from __future__ import annotations

from axial.name_candidates import generate_candidate_clusters


def _entry(
    surface: str, kind: str | None = "person", count: int = 1
) -> tuple[str, str | None, int]:
    return (surface, kind, count)


def _has_pair(clusters: list[tuple[str, ...]], *members: str) -> bool:
    target = frozenset(members)
    return any(frozenset(cluster) == target for cluster in clusters)


def _appear_together(clusters: list[tuple[str, ...]], a: str, b: str) -> bool:
    return any(a in cluster and b in cluster for cluster in clusters)


# ---------------------------------------------------------------------------
# Family 1: initial vs full forename, same surname, same first letter
# ---------------------------------------------------------------------------


def test_initial_forename_pairs_with_its_one_full_form():
    entries = [_entry("C. Tilly"), _entry("Charles Tilly")]

    clusters = generate_candidate_clusters(entries)

    assert _has_pair(clusters, "C. Tilly", "Charles Tilly")


def test_initial_forename_examples_from_the_issue():
    entries = [
        _entry("A. Al-Azmeh"),
        _entry("Aziz al-Azmeh"),
        _entry("A. Abdel-Malek"),
        _entry("Anwar Abdel-Malek"),
        _entry("A. Buchanan"),
        _entry("Allen Buchanan"),
    ]

    clusters = generate_candidate_clusters(entries)

    assert _has_pair(clusters, "A. Al-Azmeh", "Aziz al-Azmeh")
    assert _has_pair(clusters, "A. Abdel-Malek", "Anwar Abdel-Malek")
    assert _has_pair(clusters, "A. Buchanan", "Allen Buchanan")


def test_ambiguous_initial_is_refused_r_cohen():
    """R. Cohen matches both Robin Cohen and Roger Cohen -- unresolvable from
    the strings, so neither pair is proposed (issue #446)."""
    entries = [_entry("R. Cohen"), _entry("Robin Cohen"), _entry("Roger Cohen")]

    clusters = generate_candidate_clusters(entries)

    assert not _appear_together(clusters, "R. Cohen", "Robin Cohen")
    assert not _appear_together(clusters, "R. Cohen", "Roger Cohen")


def test_double_initial_form_is_out_of_scope_a_d_smith():
    """`A. D. Smith` vs `Adam Smith` must stay apart -- `A. D. Smith` is not
    the two-token initial-form shape this family matches (issue #446, 'what
    must NOT be merged')."""
    entries = [_entry("A. D. Smith"), _entry("Adam Smith")]

    clusters = generate_candidate_clusters(entries)

    assert not _appear_together(clusters, "A. D. Smith", "Adam Smith")


def test_scan_typo_full_forenames_are_out_of_scope():
    """`Anthony D. Smith` vs `Antony D. Smith` is a scan typo the issue
    explicitly scopes OUT -- no fourth rule should catch it."""
    entries = [_entry("Anthony D. Smith"), _entry("Antony D. Smith")]

    clusters = generate_candidate_clusters(entries)

    assert not _appear_together(clusters, "Anthony D. Smith", "Antony D. Smith")


# ---------------------------------------------------------------------------
# Family 2: bare surname with exactly one full-name candidate, both `person`
# ---------------------------------------------------------------------------


def test_bare_surname_pairs_with_its_one_full_name_candidate():
    entries = [_entry("Abercrombie"), _entry("Nikolas Abercrombie")]

    clusters = generate_candidate_clusters(entries)

    assert _has_pair(clusters, "Abercrombie", "Nikolas Abercrombie")


def test_bare_surname_with_apostrophe_prefix():
    entries = [_entry("'Ammash"), _entry("Salih Mahdi 'Ammash")]

    clusters = generate_candidate_clusters(entries)

    assert _has_pair(clusters, "'Ammash", "Salih Mahdi 'Ammash")


def test_bare_surname_ambiguous_is_refused_bare_ali():
    """Bare `'Ali` matches seven distinct people and must be refused
    entirely (issue #446, #442's measured gate)."""
    full_names = [
        "Muhammad 'Ali",
        "Hussein ibn 'Ali",
        "Bin 'Ali",
        "Zayn al-'Abidin 'Ali",
        "Sharif 'Ali",
        "Ahmad 'Ali",
        "Karim 'Ali",
    ]
    entries = [_entry("'Ali"), *[_entry(name) for name in full_names]]

    clusters = generate_candidate_clusters(entries)

    for name in full_names:
        assert not _appear_together(clusters, "'Ali", name)


def test_bare_surname_gated_on_both_sides_being_person():
    """Both sides must be `kind == person` (issue #446); a bare surname
    tagged as a concept/place must not be paired even when a same-spelled
    full name exists."""
    entries = [_entry("Abercrombie", kind="concept"), _entry("Nikolas Abercrombie")]

    clusters = generate_candidate_clusters(entries)

    assert not _appear_together(clusters, "Abercrombie", "Nikolas Abercrombie")


# ---------------------------------------------------------------------------
# Family 3: case-only / whitespace-only pairs (the #441 residual)
# ---------------------------------------------------------------------------


def test_case_only_pair_is_proposed():
    entries = [
        _entry("Janjaweed", kind="movement/religion"),
        _entry("janjaweed", kind="movement/religion"),
    ]

    clusters = generate_candidate_clusters(entries)

    assert _has_pair(clusters, "Janjaweed", "janjaweed")


def test_whitespace_only_pair_is_proposed():
    entries = [_entry("Nation  State", kind="concept"), _entry("Nation State", kind="concept")]

    clusters = generate_candidate_clusters(entries)

    assert _has_pair(clusters, "Nation  State", "Nation State")


# ---------------------------------------------------------------------------
# No fuzzy matching, no invented pairs
# ---------------------------------------------------------------------------


def test_unrelated_surfaces_produce_no_candidate():
    entries = [_entry("Ernest Gellner"), _entry("Perry Anderson")]

    assert generate_candidate_clusters(entries) == []


def test_every_proposed_cluster_has_at_least_two_members():
    entries = [_entry("C. Tilly"), _entry("Charles Tilly"), _entry("Perry Anderson")]

    for cluster in generate_candidate_clusters(entries):
        assert len(cluster) >= 2


def test_output_is_deduplicated():
    """Overlapping evidence for the same pair (e.g. it separately satisfies
    two families) must not yield two identical clusters."""
    entries = [_entry("Tilly"), _entry("C. Tilly"), _entry("Charles Tilly")]

    clusters = generate_candidate_clusters(entries)

    assert len(clusters) == len({frozenset(c) for c in clusters})
