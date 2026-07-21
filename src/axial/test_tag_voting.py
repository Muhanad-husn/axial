"""Inner unit tests for best-of-N majority voting on the blind tag axes
(issue #294, DEC-31): the voting function itself, the abstention marker's
shape, and `run_tag`'s draw loop -- spoiled ballots, the `unlisted`
soft-land as a legal ballot, and the preserved P0-6 hard error when every
draw is invalid.

Mirrors `src/axial/test_tag_theory_school_unlisted.py`'s in-process
`run_tag` style (a small synthetic domain under `tmp_path`, `read_chunks`
stubbed to a fixed chunk list, a scripted client returning one response per
call) -- the CLI-subprocess acceptance contract lives in
tests/ingestion/test_tag_best_of_n.py.
"""

from __future__ import annotations

import json

import pytest

from axial.llm import TAG_PASS_NAME
from axial.schema import load_schema
from axial.tag import ABSTAINED_KEY, TagNotInSchemaError, vote_blind_axes

IN_VOCAB_SCHOOL = "bellicist"
OTHER_SCHOOL = "marxist-political-economy"
OUT_OF_VOCAB_SCHOOL = "pluralist"
UNLISTED_SENTINEL = "unlisted"

IN_VOCAB_CLAIM = "state-formation"
OTHER_CLAIM = "state-capacity"
OUT_OF_VOCAB_CLAIM = "not-a-real-claim-type"


def _write_domain(tmp_path):
    """A minimal schema.yaml + codebook.yaml covering role_in_argument
    (single), field (primary_plus_secondary), claim_type
    (primary_plus_optional_secondary, closed and FATAL on a miss), and
    theory_school (primary_plus_optional_secondary, with the real domain's
    `none`/`open` sentinel groups)."""
    domain_dir = tmp_path / "domain"
    domain_dir.mkdir()
    (domain_dir / "schema.yaml").write_text(
        "version: 0.1\n"
        "axes:\n"
        "  role_in_argument:\n"
        "    applies_to: [prose]\n"
        "    cardinality: single\n"
        "    values: [role:claim, role:evidence]\n"
        "  field:\n"
        "    applies_to: [prose]\n"
        "    cardinality: primary_plus_secondary\n"
        "    values: [state, violence]\n"
        "  claim_type:\n"
        "    applies_to: [prose]\n"
        "    cardinality: primary_plus_optional_secondary\n"
        "    values:\n"
        "      - id: state-formation\n"
        "        status: firm\n"
        "        subtags: [formation:bellicist]\n"
        "      - id: state-capacity\n"
        "        status: firm\n"
        "        subtags: [capacity:infrastructural]\n"
        "  theory_school:\n"
        "    applies_to: [prose]\n"
        "    cardinality: primary_plus_optional_secondary\n"
        "    status: candidate\n"
        "    groups:\n"
        "      state:\n"
        "        - bellicist\n"
        "        - marxist-political-economy\n"
        "      none:\n"
        "        - not-applicable\n"
        "      open:\n"
        "        - unlisted\n",
        encoding="utf-8",
    )
    entry = "{definition: d, positive_example: p, negative_example: n}"
    (domain_dir / "codebook.yaml").write_text(
        "axes:\n"
        "  role_in_argument:\n"
        f"    role:claim: {entry}\n"
        f"    role:evidence: {entry}\n"
        "  field:\n"
        f"    state: {entry}\n"
        f"    violence: {entry}\n"
        "  claim_type:\n"
        f"    state-formation: {entry}\n"
        f"    state-capacity: {entry}\n"
        "  theory_school:\n"
        f"    bellicist: {entry}\n"
        f"    marxist-political-economy: {entry}\n"
        f"    not-applicable: {entry}\n"
        f"    unlisted: {entry}\n",
        encoding="utf-8",
    )
    return domain_dir


_CHUNK = {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}


def _one_chunk_read_chunks(monkeypatch, tag_mod):
    monkeypatch.setattr(tag_mod, "read_chunks", lambda *args, **kwargs: [dict(_CHUNK)])


def _payload(*, theory_school=IN_VOCAB_SCHOOL, claim_type=IN_VOCAB_CLAIM, role="role:claim"):
    return json.dumps(
        {
            "role_in_argument": role,
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": claim_type, "secondary": None, "subtags": []},
            "theory_school": {"primary": theory_school},
        }
    )


class _ScriptedClient:
    """Returns one scripted raw response per call, in order (mirrors
    `test_tag.py`'s own `_ScriptedClient`)."""

    def __init__(self, responses: list[str]):
        self._responses = responses
        self.call_count = 0

    def complete(self, prompt, pass_name=None):
        assert pass_name == TAG_PASS_NAME
        response = self._responses[self.call_count]
        self.call_count += 1
        return response


def _run(tmp_path, monkeypatch, responses, *, votes):
    import axial.tag as tag_mod

    domain_dir = _write_domain(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)
    client = _ScriptedClient(responses)
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf",
        client=client,
        domain_dir=domain_dir,
        tags_dir=tmp_path / "tags",
        votes=votes,
    )
    return records, client


# --- the voting function itself -------------------------------------------


def _axis(primary, **extra):
    return {"primary": primary, "secondary": None, **extra}


def test_strict_plurality_decides_a_blind_axis():
    """`{A, A, B}` decides A -- and the winning axis object is the one the
    winning draw actually produced, so `secondary`/`subtags` stay coherent
    with the primary they were drawn alongside."""
    schema = load_schema("config/domains/syria")
    draws = [
        {"theory_school": _axis("bellicist")},
        {"theory_school": _axis("marxist-political-economy", secondary="bellicist")},
        {"theory_school": _axis("marxist-political-economy", secondary="bellicist")},
    ]

    voted = vote_blind_axes(draws, schema)

    assert voted["theory_school"]["primary"] == "marxist-political-economy"
    assert voted["theory_school"]["secondary"] == "bellicist"
    assert ABSTAINED_KEY not in voted["theory_school"]


def test_three_distinct_draws_abstain_instead_of_coin_flipping():
    """`{A, B, C}` has no strict plurality: the axis records the abstention
    marker -- a null primary, the distinct draws in draw order, and the
    schema's own axis `status` -- never a fabricated tag."""
    schema = load_schema("config/domains/syria")
    draws = [
        {"theory_school": _axis("bellicist")},
        {"theory_school": _axis("marxist-political-economy")},
        {"theory_school": _axis("not-applicable")},
    ]

    voted = vote_blind_axes(draws, schema)["theory_school"]

    assert voted[ABSTAINED_KEY] is True
    assert voted["primary"] is None
    assert voted["draws"] == ["bellicist", "marxist-political-economy", "not-applicable"]
    assert voted["status"] == "candidate"


def test_abstention_is_never_a_vocabulary_value():
    """The abstention marker is a FLAG, never one of the axis's closed
    values: `not-applicable` (the passage advances no position) and
    `unlisted` (a real school this vocabulary misses) both stay available
    and distinct -- conflating them with "the draws disagree" is the exact
    error Appendix E's absence marker exists to prevent."""
    schema = load_schema("config/domains/syria")
    draws = [
        {"theory_school": _axis("bellicist")},
        {"theory_school": _axis("marxist-political-economy")},
        {"theory_school": _axis("constructivist")},
    ]

    voted = vote_blind_axes(draws, schema)["theory_school"]

    assert voted["primary"] not in schema.axes["theory_school"].tag_ids
    assert voted["primary"] is None


def test_unlisted_casts_a_legal_ballot_and_can_win_the_vote():
    """A draw soft-landed to `unlisted` votes like any other value: two of
    them out-vote a single real school."""
    schema = load_schema("config/domains/syria")
    draws = [
        {"theory_school": _axis(UNLISTED_SENTINEL)},
        {"theory_school": _axis(UNLISTED_SENTINEL)},
        {"theory_school": _axis("bellicist")},
    ]

    assert vote_blind_axes(draws, schema)["theory_school"]["primary"] == UNLISTED_SENTINEL


def test_head_axes_take_the_first_draw_and_never_gain_an_abstained_key():
    """`field` is a head axis: it keeps its FIRST draw's value even when the
    draws disagree, and never gains an `abstained` key (voting the
    pre-labeled axes is deliberately out of this slice)."""
    schema = load_schema("config/domains/syria")
    draws = [
        {"field": _axis("state"), "theory_school": _axis("bellicist")},
        {"field": _axis("violence"), "theory_school": _axis("bellicist")},
        {"field": _axis("ideology"), "theory_school": _axis("bellicist")},
    ]

    voted = vote_blind_axes(draws, schema)

    assert voted["field"]["primary"] == "state"
    assert ABSTAINED_KEY not in voted["field"]


def test_a_single_ballot_decides_without_abstaining():
    """One surviving draw is a strict plurality of one -- the axis decides
    among the VALID ballots, never abstaining merely because the others were
    spoiled."""
    schema = load_schema("config/domains/syria")

    voted = vote_blind_axes([{"theory_school": _axis("bellicist")}], schema)

    assert voted["theory_school"]["primary"] == "bellicist"
    assert ABSTAINED_KEY not in voted["theory_school"]


# --- run_tag's draw loop ---------------------------------------------------


def test_run_tag_votes_three_draws_and_records_the_modal_blind_values(tmp_path, monkeypatch):
    """`run_tag` draws `votes` times and records the modal blind values --
    here the ones the first draw did NOT choose, so the record can only have
    come from counting ballots."""
    responses = [
        _payload(theory_school=OTHER_SCHOOL, claim_type=OTHER_CLAIM),
        _payload(theory_school=IN_VOCAB_SCHOOL, claim_type=IN_VOCAB_CLAIM),
        _payload(theory_school=IN_VOCAB_SCHOOL, claim_type=IN_VOCAB_CLAIM),
    ]

    records, client = _run(tmp_path, monkeypatch, responses, votes=3)

    assert client.call_count == 3
    assert records[0]["theory_school"]["primary"] == IN_VOCAB_SCHOOL
    assert records[0]["claim_type"]["primary"] == IN_VOCAB_CLAIM


def test_run_tag_spoiled_claim_type_ballot_is_excluded_from_the_vote(tmp_path, monkeypatch):
    """A draw whose `claim_type` is still out of vocabulary after its OWN
    #102 re-ask casts no ballot (issue #294): the axis decides among the
    valid draws instead of aborting the source."""
    responses = [
        # Draw 1: out-of-vocab claim_type, and its bounded re-ask fails too
        # -- a spoiled ballot (2 calls).
        _payload(claim_type=OUT_OF_VOCAB_CLAIM),
        _payload(claim_type=OUT_OF_VOCAB_CLAIM),
        # Draws 2 and 3: valid (1 call each).
        _payload(claim_type=IN_VOCAB_CLAIM, theory_school=IN_VOCAB_SCHOOL),
        _payload(claim_type=IN_VOCAB_CLAIM, theory_school=IN_VOCAB_SCHOOL),
    ]

    records, client = _run(tmp_path, monkeypatch, responses, votes=3)

    assert client.call_count == 4
    assert len(records) == 1
    assert records[0]["claim_type"]["primary"] == IN_VOCAB_CLAIM
    assert ABSTAINED_KEY not in records[0]["claim_type"]


def test_run_tag_all_draws_invalid_still_raises_the_p0_6_hard_error(tmp_path, monkeypatch):
    """When EVERY draw is spoiled, the existing `TagNotInSchemaError` hard
    error stands -- the schema-gap guarantee survives best-of-N."""
    responses = [_payload(claim_type=OUT_OF_VOCAB_CLAIM)] * 6

    with pytest.raises(TagNotInSchemaError) as excinfo:
        _run(tmp_path, monkeypatch, responses, votes=3)

    assert excinfo.value.axis_name == "claim_type"
    assert excinfo.value.tag == OUT_OF_VOCAB_CLAIM


def test_run_tag_unlisted_softland_casts_a_ballot_and_can_lose(tmp_path, monkeypatch):
    """An out-of-vocab `theory_school` draw soft-lands to `unlisted` (a
    LEGAL ballot, unlike a spoiled claim_type draw) and then loses the vote
    to two draws that named a real school -- the vote self-repairing an
    invalid draw (DEC-31: out-of-vocab rate 0.0056 -> 0.0000)."""
    responses = [
        # Draw 1: out-of-vocab school, still out-of-vocab on its re-ask ->
        # soft-lands to `unlisted` (2 calls).
        _payload(theory_school=OUT_OF_VOCAB_SCHOOL),
        _payload(theory_school=OUT_OF_VOCAB_SCHOOL),
        # Draws 2 and 3: a real school (1 call each).
        _payload(theory_school=IN_VOCAB_SCHOOL),
        _payload(theory_school=IN_VOCAB_SCHOOL),
    ]

    records, client = _run(tmp_path, monkeypatch, responses, votes=3)

    assert client.call_count == 4
    assert records[0]["theory_school"]["primary"] == IN_VOCAB_SCHOOL


def test_run_tag_at_one_vote_is_an_exact_no_op(tmp_path, monkeypatch):
    """`votes=1` draws once and skips the voting layer entirely: today's
    record shape, with no `abstained` key anywhere."""
    records, client = _run(tmp_path, monkeypatch, [_payload()], votes=1)

    assert client.call_count == 1
    assert records[0]["theory_school"] == {
        "primary": IN_VOCAB_SCHOOL,
        "secondary": None,
        "status": "candidate",
    }
    assert ABSTAINED_KEY not in json.dumps(records)
