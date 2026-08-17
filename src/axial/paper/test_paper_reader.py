"""The reader-facing paper render (`axial.paper.reader`, issue #783).

The bar is what does NOT reach the page: no chunk id, no coverage table, no
shape band, no provenance tag, and no `[pc-001]` claim id left standing in
the prose. And one thing that must: an unresolved reference stays visible.
"""

from __future__ import annotations

from typing import Any

from axial.paper.reader import render_reader_paper
from axial.paper.render import render_paper

_CITATION = {
    "source_id": "vignal-2021",
    "author": "Leila Vignal ;",
    "title": "War-Torn",
    "date": "2021",
    "chapter": "ANATOMY OF A CONFLICT",
    "section": "Fragmenting space",
}
_OTHER_CITATION = {
    "source_id": "bayat-2017",
    "author": "Asef Bayat",
    "title": "Revolution Without Revolutionaries",
    "date": "2017",
    "chapter": None,
    "section": "Neoliberal Effect",
}


def _record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "paper_brief_id": "p1",
        "paper_brief": {"thesis": "Did war make the state?", "title": None},
        "plan": {
            "thesis_statement": "War made the state.",
            "sections": [
                {"section_id": "s1", "heading": "The argument", "role": "body"},
            ],
        },
        "drafts": [
            {
                "section_id": "s1",
                "prose": "War made the state [pc-001][pc-002]. It also unmade it [pc-003].",
            }
        ],
        "claims": [
            {
                "paper_claim_id": "pc-001",
                "kind": "a",
                "confidence": "high",
                "source_ids": ["vignal-2021"],
                "grounds": [
                    {"ref_type": "chunk", "ref_id": "vignal-2021_30_x_002", "citation": _CITATION},
                    {
                        "ref_type": "chunk",
                        "ref_id": "vignal-2021_48_y_001",
                        "citation": dict(_CITATION, section="Conclusion"),
                    },
                ],
            },
            {
                "paper_claim_id": "pc-002",
                "kind": "b",
                "confidence": "low",
                "source_ids": ["bayat-2017"],
                "grounds": [
                    {
                        "ref_type": "chunk",
                        "ref_id": "bayat-2017_19_z_005",
                        "citation": _OTHER_CITATION,
                    }
                ],
            },
        ],
        "counter_position": {"present": True, "failed": False},
        "coverage_map": {"Syria": {"corpus_note_count": 9, "cited_claim_count": 1,
                                   "coverage_band": "thin"}},
        "confidence": {"overall_band": "medium", "rationale": "because"},
        "shape": {"band": "strong", "defects": [], "title": None},
        "bibliography": [
            {
                "source_id": "vignal-2021",
                "author": {"value": "Leila Vignal ;", "provenance": "embedded metadata"},
                "title": {"value": "War-Torn", "provenance": "embedded metadata"},
                "date": {"value": "2021", "provenance": "title page"},
                "publisher": {"value": "C. Hurst", "provenance": "open_library"},
            }
        ],
    }
    record.update(overrides)
    return record


def test_the_reader_paper_carries_no_operator_telemetry():
    markdown = render_reader_paper(_record())

    assert "chunk" not in markdown
    assert "vignal-2021_30_x_002" not in markdown
    assert "## Citations" not in markdown
    assert "## Confidence and coverage" not in markdown
    assert "## Shape check" not in markdown
    assert "corpus notes" not in markdown
    assert "from embedded metadata" not in markdown


def test_the_audit_paper_still_carries_all_of_it():
    """The split moves the apparatus; it does not delete it. The sealed
    peer-review packet and the instant-dismissal judge read this render."""
    markdown = render_paper(_record())

    assert "vignal-2021_30_x_002" in markdown
    assert "## Citations" in markdown
    assert "## Shape check" in markdown
    assert "from embedded metadata" in markdown


def test_a_marker_run_becomes_one_parenthetical_naming_the_books():
    markdown = render_reader_paper(_record())

    assert "War made the state (Vignal 2021; Bayat 2017)." in markdown
    assert "[pc-001]" not in markdown
    assert "[pc-002]" not in markdown


def test_a_marker_with_no_claim_in_the_record_stays_visible():
    """`pc-003` is cited by the prose but carries no claim -- an unresolved
    reference a reader can see beats one silently deleted."""
    markdown = render_reader_paper(_record())

    assert "It also unmade it [pc-003]." in markdown


def test_the_bibliography_reads_like_a_bibliography():
    markdown = render_reader_paper(_record())

    assert "- Leila Vignal. War-Torn. C. Hurst, 2021." in markdown


def test_a_record_with_no_citations_resolved_still_renders():
    """Purity's other half: the render never reads a vault itself, so a
    record nobody resolved renders with its markers intact rather than
    raising."""
    record = _record()
    for claim in record["claims"]:
        for ground in claim["grounds"]:
            ground.pop("citation")

    markdown = render_reader_paper(record)

    assert "War made the state [pc-001][pc-002]." in markdown


def test_rendering_is_deterministic():
    assert render_reader_paper(_record()) == render_reader_paper(_record())


def test_an_ungrounded_c_claim_cites_the_fact_that_it_runs_past_the_books():
    """A (c) claim has no grounds by definition (§7.4). Left as a raw
    `[pc-003]` marker it would read as a broken reference; the raw marker is
    reserved for a claim id the record does not carry at all. Measured on
    `data/papers/273aea05df54e2df.json`, which carries three of them."""
    record = _record()
    record["claims"].append(
        {"paper_claim_id": "pc-003", "kind": "c", "confidence": "low", "grounds": []}
    )

    markdown = render_reader_paper(record)

    assert "It also unmade it (runs past the books)." in markdown


def test_a_paper_with_no_title_does_not_say_its_thesis_twice():
    """Issue #784. `paper_title` falls back to the plan's own
    `thesis_statement` when the brief names no title (§7.1), and a paper
    drafted from an ask never names one -- so the H1 and the first body line
    were the identical sentence on every answer an analyst reads."""
    rendered = render_reader_paper(_record())

    lines = [line for line in rendered.splitlines() if line.strip()]
    assert lines[0] == "# War made the state."
    assert lines[1] != "War made the state."


def test_a_titled_paper_still_states_its_thesis_under_the_title():
    """The de-duplication is about a title that IS the thesis, not about
    dropping the thesis. A paper whose brief names its own title still opens
    with the title, then states the thesis."""
    record = _record(paper_brief={"thesis": "Did war make the state?", "title": "War and the State"})
    rendered = render_reader_paper(record)

    lines = [line for line in rendered.splitlines() if line.strip()]
    assert lines[0] == "# War and the State"
    assert lines[1] == "War made the state."
