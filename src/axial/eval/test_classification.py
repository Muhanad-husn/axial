"""Inner unit tests for the §7.15 source-classification reader (issue #563)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.eval.classification import default_classification_path, load_classification

_PAYLOAD = {
    "version": 1,
    "corpus_pin": "sim-2026-07-30",
    "note_weighted_baseline": {
        "corpus_pin": "sim-2026-07-30",
        "commentary_note_count": 7812,
        "total_note_count": 141268,
        "share": 0.055299,
        "commentary_note_counts_by_source": {
            "hall-2006-449559bfe4dc": 4635,
            "malesevic-2007-323a2518e61b": 3177,
        },
    },
    "sources": {
        "hall-2006-449559bfe4dc": {"class": "commentary", "about": "Michael Mann"},
        "malesevic-2007-323a2518e61b": {"class": "commentary", "about": "Ernest Gellner"},
        "tilly-1978-f908c910464c": {"class": "primary", "about": None},
        "bayat-2017-ce6bb0643cfb": {"class": "primary", "about": None},
    },
}


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_classification_reads_classes_and_the_corpus_pin(tmp_path):
    path = _write(tmp_path / "classification.json", _PAYLOAD)
    classification = load_classification(path=path)
    assert classification is not None
    assert classification.corpus_pin == "sim-2026-07-30"
    assert classification.classes["hall-2006-449559bfe4dc"] == "commentary"
    assert classification.classes["tilly-1978-f908c910464c"] == "primary"


def test_commentary_source_ids_is_exactly_the_commentary_subset(tmp_path):
    path = _write(tmp_path / "classification.json", _PAYLOAD)
    classification = load_classification(path=path)
    assert classification.commentary_source_ids == frozenset(
        {"hall-2006-449559bfe4dc", "malesevic-2007-323a2518e61b"}
    )


def test_baseline_commentary_share_reads_the_committed_measured_share(tmp_path):
    """The baseline is read straight off `note_weighted_baseline.share` --
    never recomputed from source counts, which would silently be the wrong,
    unweighted quantity (issue #563 follow-up)."""
    path = _write(tmp_path / "classification.json", _PAYLOAD)
    classification = load_classification(path=path)
    assert classification.baseline_commentary_share == pytest.approx(0.055299)


def test_baseline_commentary_share_is_none_when_the_block_is_absent(tmp_path):
    """No `note_weighted_baseline` block -- `None`, never a source-count
    fallback: a wrong baseline silently substituted for a right one is worse
    than an absent one."""
    path = _write(tmp_path / "classification.json", {**_PAYLOAD, "note_weighted_baseline": None})
    classification = load_classification(path=path)
    assert classification.baseline_commentary_share is None


def test_baseline_commentary_share_is_none_when_share_is_not_a_number(tmp_path):
    payload = {
        **_PAYLOAD,
        "note_weighted_baseline": {**_PAYLOAD["note_weighted_baseline"], "share": "5.5%"},
    }
    path = _write(tmp_path / "classification.json", payload)
    classification = load_classification(path=path)
    assert classification.baseline_commentary_share is None


def test_baseline_commentary_share_does_not_recompute_from_source_counts(tmp_path):
    """Regression for the exact defect: 2 of 4 sources here are commentary
    (a 0.5 source-count share) but the authored `note_weighted_baseline`
    states a different, measured number -- the reader must return THAT
    number, not silently recompute 0.5 from `classes`."""
    path = _write(tmp_path / "classification.json", _PAYLOAD)
    classification = load_classification(path=path)
    assert classification.baseline_commentary_share != 0.5
    assert classification.baseline_commentary_share == pytest.approx(0.055299)


def test_a_missing_classification_file_is_none_not_an_error(tmp_path):
    """The classification ships after the fact (issue #563) -- an absent
    file must cost only the one figure that reads it, never a crash."""
    assert load_classification(path=tmp_path / "nope.json") is None


def test_a_malformed_classification_file_is_none_not_a_crash(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_classification(path=path) is None


def test_a_source_without_a_recognised_class_is_dropped(tmp_path):
    path = _write(
        tmp_path / "classification.json",
        {
            "sources": {
                "tilly-1978-f908c910464c": {"class": "primary"},
                "ghost-2000-000000000000": {"class": "secondary"},
                "no-class-2000-111111111111": {},
            }
        },
    )
    classification = load_classification(path=path)
    assert classification.classes == {"tilly-1978-f908c910464c": "primary"}


def test_default_classification_path_is_the_committed_evals_location():
    assert default_classification_path() == Path("evals/sources/classification.json")


# -- the committed file itself, in the spirit of
# axial.eval.test_cases.test_every_committed_sim_case_still_states_both_oracles --


def test_the_committed_classification_covers_every_pinned_source():
    """Every `source_id` in the committed `sim-2026-07-30` corpus pin
    (`evals/corpus_pin/sim-2026-07-30.json`) has a classification entry --
    the whole point of issue #563 is that the report can look every ground
    citation's source up without a gap."""
    pin_path = Path("evals/corpus_pin/sim-2026-07-30.json")
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    pinned_source_ids = {entry["source_id"] for entry in pin["sources"]}

    classification = load_classification()
    assert classification is not None
    assert pinned_source_ids <= set(classification.classes)


def test_the_committed_classification_names_exactly_the_two_known_commentary_sources():
    classification = load_classification()
    assert classification is not None
    assert classification.commentary_source_ids == frozenset(
        {"hall-2006-449559bfe4dc", "malesevic-2007-323a2518e61b"}
    )


def test_the_committed_classification_states_the_measured_note_weighted_baseline():
    """Measured against the live name index at pin `sim-2026-07-30`
    (2026-08-01): the two commentary volumes are 7,812 of 141,268 index
    notes, 5.53% -- a point off the 2/31 = 6.45% source-count share the
    reader used to derive, which is the exact defect this pins."""
    classification = load_classification()
    assert classification is not None
    assert classification.baseline_commentary_share == pytest.approx(7812 / 141268, abs=1e-6)
