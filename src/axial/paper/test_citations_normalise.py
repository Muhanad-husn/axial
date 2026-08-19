"""Marker normalisation at the parse boundary (issue #797).

A drafter that writes `[pc010]` for `[pc-010]` has made a punctuation slip,
not named a different claim. Correcting it is a lookup against the claim ids
the record already carries -- never a choice between candidates, and never a
weakening of §7.5, which still refuses a marker that corrects to nothing.
"""

from __future__ import annotations

from axial.paper.citations import normalise_markers

KNOWN = {"pc-001", "pc-002", "pc-003"}


def test_prose_whose_markers_all_resolve_is_returned_unchanged():
    prose = "War made the state [pc-001]. Extraction followed [pc-002]."
    assert normalise_markers(prose, KNOWN) == prose


def test_a_dropped_hyphen_is_corrected():
    assert normalise_markers("Extraction followed [pc002].", KNOWN) == (
        "Extraction followed [pc-002]."
    )


def test_correction_ignores_case_and_separator():
    """`PC_002` and `Pc 002` are the same id under the key; nothing else is."""
    assert normalise_markers("[PC_002]", KNOWN) == "[pc-002]"
    assert normalise_markers("[Pc 002]", KNOWN) == "[pc-002]"


def test_a_marker_matching_no_known_id_is_left_for_the_index_to_refuse():
    """Left untouched rather than dropped: `build_citation_index` names the
    offending token, and a marker deleted here would vanish from the error."""
    assert normalise_markers("[pc-099]", KNOWN) == "[pc-099]"
    assert normalise_markers("[not-a-claim]", KNOWN) == "[not-a-claim]"


def test_an_ambiguous_key_never_corrects():
    """Two known ids collapsing to one key make the marker a choice, and a
    correction that chooses is a guess."""
    ambiguous = {"pc-002", "PC002"}
    assert normalise_markers("[pc 002]", ambiguous) == "[pc 002]"


def test_only_the_malformed_member_of_a_run_is_rewritten():
    assert normalise_markers("Both [pc002][pc-003].", KNOWN) == "Both [pc-002][pc-003]."


def test_a_local_id_the_drafter_left_behind_is_untouched():
    """`[n1]` keys to nothing in the claim set, so it stays as written and
    fails at the index exactly as it does today."""
    assert normalise_markers("And so [n1].", KNOWN) == "And so [n1]."


def test_a_padded_but_valid_marker_is_tightened():
    """`[ pc-002 ]` resolves at the index -- `markers_in` strips -- but
    `axial.paper.reader`'s run regex does not match a leading space, so
    left as written it reaches the reader as a raw bracket token with no
    error raised anywhere. Rewriting it is the same lookup, not a new
    behaviour: the stripped form is already a claim id the record carries."""
    assert normalise_markers("Extraction followed [ pc-002 ].", KNOWN) == (
        "Extraction followed [pc-002]."
    )
