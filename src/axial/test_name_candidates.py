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

from axial.name_candidates import (
    _extract_parenthesized_acronym,
    _family_parenthesized_acronym,
    fold_groups,
    generate_candidate_clusters,
)


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
# Family 3 (issue #498, D2): a parenthesized acronym against its own
# standalone inventory entry. The rule is a shape test, stated once: a
# parenthesized acronym is a run of two or more bare uppercase ASCII letters,
# alone in parentheses -- nothing else inside the parens, no fuzzy matching.
# This is a CANDIDATE, never a fold: the model's own evidence check (#449)
# decides each pair, exactly like family 1/2, because an acronym can resolve
# to more than one expansion depending on the corpus.
# ---------------------------------------------------------------------------

AANS = "AANS"
AANS_SURFACE = "Autonomous Administration of Northeast Syria (AANS)"


def test_extracts_a_bare_uppercase_acronym_in_parentheses():
    assert _extract_parenthesized_acronym(AANS_SURFACE) == "AANS"
    assert _extract_parenthesized_acronym("Kurdistan Workers' Party (PKK)") == "PKK"


def test_extraction_ignores_a_single_letter_in_parentheses():
    """A single letter is a list marker shape ('(a)', '(A)'), not an
    acronym -- the rule requires two or more letters."""
    assert _extract_parenthesized_acronym("Appendix A (A)") is None


def test_extraction_ignores_a_lowercase_word_in_parentheses():
    assert _extract_parenthesized_acronym("the report (ed.)") is None
    assert _extract_parenthesized_acronym("a translated work (trans.)") is None


def test_extraction_ignores_a_multi_word_parenthetical():
    """Two tokens inside the parentheses is a different shape -- a phrase,
    not a bare acronym -- even when both tokens are themselves all caps."""
    assert _extract_parenthesized_acronym("The report (UN Security)") is None


def test_extraction_ignores_a_year():
    assert _extract_parenthesized_acronym("The Second Coming (1920)") is None


def test_extraction_ignores_a_page_locator():
    assert _extract_parenthesized_acronym("Some claim (p. 12)") is None
    assert _extract_parenthesized_acronym("Some claim (see p.12)") is None


def test_acronym_pairs_with_its_own_standalone_entry():
    """The worked case (issue #498): a bare `AANS` node and the surface that
    carries `(AANS)` in parentheses become a candidate pair."""
    entries = [_entry(AANS, kind="institution"), _entry(AANS_SURFACE, kind="institution")]

    clusters = generate_candidate_clusters(entries)

    assert _has_pair(clusters, AANS, AANS_SURFACE)


def test_acronym_with_no_standalone_entry_produces_no_candidate():
    """`AANES` (out of scope, #498's own recorded smaller half): the corpus
    never writes it bare, so there is nothing for it to pair with -- silently
    skipped, never folded and never proposed."""
    surface = "Autonomous Administration of North and East Syria (AANES)"
    entries = [_entry(surface, kind="institution")]

    assert generate_candidate_clusters(entries) == []


def test_acronym_family_ignores_unrelated_surfaces_sharing_no_acronym():
    entries = [_entry("Ernest Gellner"), _entry("Perry Anderson (ANDR)")]

    assert generate_candidate_clusters(entries) == []


def test_acronym_with_more_than_one_expansion_is_refused_sdf():
    """Issue #498's own live-corpus measurement: `SDF` carries two distinct
    expansions -- `Marxist Social Democratic Federation` (a 19th-century
    British party) and `Syrian Democratic Forces` -- unrelated entities a
    century apart. Proposing one pair would make the acronym a HUB in the
    alias-map union and silently fuse them with no call ever asking whether
    they are the same. Refused entirely, exactly like family 1/2's own
    ambiguity gate: neither pair is proposed."""
    marxist = "Marxist Social Democratic Federation (SDF)"
    syrian = "Syrian Democratic Forces (SDF)"
    entries = [
        _entry("SDF", kind="institution"),
        _entry(marxist, kind="institution"),
        _entry(syrian, kind="institution"),
    ]

    clusters = generate_candidate_clusters(entries)

    assert not _appear_together(clusters, "SDF", marxist)
    assert not _appear_together(clusters, "SDF", syrian)


def test_acronym_with_exactly_one_expansion_is_still_proposed():
    """The SDF ambiguity gate above must not turn into a blanket refusal --
    an acronym carried by exactly one surface form is still proposed."""
    entries = [
        _entry("PKK", kind="institution"),
        _entry("Kurdistan Workers' Party (PKK)", kind="institution"),
    ]

    clusters = generate_candidate_clusters(entries)

    assert _has_pair(clusters, "PKK", "Kurdistan Workers' Party (PKK)")


def test_acronym_refusal_happens_at_proposal_never_a_decision():
    """The refusal lives in `_family_parenthesized_acronym` itself: the
    ambiguous pair never becomes a batch, let alone a merge call -- pinned
    directly on the candidate-generation function, not inferred through
    what a decision would have done with it."""
    entries = [
        _entry("SDF", kind="institution"),
        _entry("Marxist Social Democratic Federation (SDF)", kind="institution"),
        _entry("Syrian Democratic Forces (SDF)", kind="institution"),
    ]

    assert _family_parenthesized_acronym(entries) == []


def test_acronym_matches_through_the_upstream_fold_cia():
    """Issue #498's second live-corpus measurement: `fold_groups` runs
    upstream of every candidate family (issue #463) and had already unioned
    `CIA` with its dotted form `C.I.A.` before candidate generation ever ran
    -- only the fold's own representative (`C.I.A.` sorts before `CIA`)
    survived as an entry, so bare `CIA` was never in the inventory this
    function actually saw. The pair must still be found through the fold,
    using the surface form the run actually carries."""
    entries = [
        _entry("C.I.A.", kind="institution"),
        _entry("Central Intelligence Agency (CIA)", kind="institution"),
    ]

    clusters = generate_candidate_clusters(entries)

    assert _has_pair(clusters, "C.I.A.", "Central Intelligence Agency (CIA)")


def test_acronym_refusal_still_holds_when_standalone_form_is_folded():
    """The multi-expansion refusal must survive the fold too: even when the
    acronym's only surviving standalone entry is a dotted spelling
    (`S.D.F.`, not bare `SDF`), two distinct carrying expansions still
    refuse the pair entirely -- the fold must never reintroduce the SDF
    hub."""
    marxist = "Marxist Social Democratic Federation (SDF)"
    syrian = "Syrian Democratic Forces (SDF)"
    entries = [
        _entry("S.D.F.", kind="institution"),
        _entry(marxist, kind="institution"),
        _entry(syrian, kind="institution"),
    ]

    clusters = generate_candidate_clusters(entries)

    assert not _appear_together(clusters, "S.D.F.", marxist)
    assert not _appear_together(clusters, "S.D.F.", syrian)


def test_acronym_candidate_generation_is_deterministic():
    """Same inventory, same candidate pairs, in the same order across
    repeated calls (issue #498's own determinism requirement)."""
    entries = [
        _entry(AANS, kind="institution"),
        _entry(AANS_SURFACE, kind="institution"),
        _entry("Perry Anderson (ANDR)"),
        _entry("ANDR", kind="institution"),
    ]

    first = generate_candidate_clusters(entries)
    second = generate_candidate_clusters(entries)

    assert first == second


def test_acronym_pair_is_a_candidate_never_a_fold():
    """The acronym pair must reach `generate_candidate_clusters`, never
    `fold_groups` -- an acronym is not identical to its expansion under any
    case/whitespace/punctuation fold, so `fold_groups` must not touch it."""
    assert fold_groups([AANS, AANS_SURFACE]) == []


# ---------------------------------------------------------------------------
# The retired case-fold family (issue #463): a THIRD rule used to propose
# case-only and whitespace-only pairs as a candidate cluster, and the model
# refused 295 of ~305 of them on the real corpus. They are now folded
# upstream instead (`fold_groups`, below) and must never reach this
# function's output -- these two tests are edited, not deleted, to pin the
# opposite of what they used to assert.
# ---------------------------------------------------------------------------


def test_case_only_pairs_are_not_a_candidate_family():
    entries = [
        _entry("Janjaweed", kind="movement/religion"),
        _entry("janjaweed", kind="movement/religion"),
    ]

    clusters = generate_candidate_clusters(entries)

    assert not _appear_together(clusters, "Janjaweed", "janjaweed")


def test_whitespace_only_pairs_are_not_a_candidate_family():
    entries = [_entry("Nation  State", kind="concept"), _entry("Nation State", kind="concept")]

    clusters = generate_candidate_clusters(entries)

    assert not _appear_together(clusters, "Nation  State", "Nation State")


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


# ---------------------------------------------------------------------------
# Issue #463: the fold that replaces family 3 -- pinned directly on the
# issue's own worked examples. `fold_groups` is never a candidate cluster; it
# is unioned straight into the alias map (`axial.merge_names.
# build_alias_map_nodes`) and must never reach `generate_candidate_clusters`'
# output (covered above).
# ---------------------------------------------------------------------------


def test_fold_groups_case_only():
    groups = fold_groups(["Cold War", "Cold war", "cold war"])

    assert groups == [("Cold War", "Cold war", "cold war")]


def test_fold_groups_whitespace_only():
    groups = fold_groups(["Nation  State", "Nation State"])

    assert groups == [("Nation  State", "Nation State")]


def test_fold_groups_punctuation_apostrophe_and_quotes():
    groups = fold_groups(
        ["'Abbas", "Abbas", '"Protestant constitution"', "Protestant constitution"]
    )

    assert ("'Abbas", "Abbas") in groups
    assert ('"Protestant constitution"', "Protestant constitution") in groups


def test_fold_groups_hyphen_folds_to_a_space():
    """Decision (issue #463): a hyphen folds to a SPACE, not to nothing --
    this corpus's compound names and transliterations vary between
    hyphenated and spaced spellings of the same words."""
    groups = fold_groups(["Abd al-Rahman al-Kawakibi", "Abd al Rahman al Kawakibi"])

    assert groups == [("Abd al Rahman al Kawakibi", "Abd al-Rahman al-Kawakibi")]


def test_fold_groups_hashtag_folds_to_its_bare_word():
    """Decision (issue #463): the fold makes this automatic, not a special
    case -- a hashtag is a punctuation prefix, not a different name."""
    groups = fold_groups(["#MeToo", "MeToo"])

    assert groups == [("#MeToo", "MeToo")]


def test_fold_groups_leaves_diacritics_alone():
    """Diacritics are out of scope (issue #463, measured): folding them
    would collide the genuinely distinct `Galilee` / `Galilée`."""
    assert fold_groups(["Galilee", "Galilée"]) == []


def test_fold_groups_ignores_unrelated_surfaces():
    assert fold_groups(["Ernest Gellner", "Perry Anderson"]) == []


def test_fold_groups_never_appear_in_generate_candidate_clusters():
    """The fold is for candidate generation only in the sense of feeding the
    upstream union, never in the sense of being asked about -- a fold-only
    pair must never come back out of `generate_candidate_clusters`."""
    entries = [_entry("Cold War", kind="concept"), _entry("cold war", kind="concept")]

    assert generate_candidate_clusters(entries) == []
