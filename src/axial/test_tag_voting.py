"""Inner unit tests for best-of-N majority voting on the blind tag axes
(issue #294, DEC-31): the voting function itself, the abstention marker's
shape, and `run_tag`'s draw loop -- spoiled ballots, the `unlisted`
soft-land as a legal ballot, and (issue #329, reversing the #120-era P0-6
ruling) the chunk quarantining -- rather than aborting the source -- when
every draw is invalid.

Mirrors `src/axial/test_tag_theory_school_unlisted.py`'s in-process
`run_tag` style (a small synthetic domain under `tmp_path`, `read_chunks`
stubbed to a fixed chunk list, a scripted client returning one response per
call) -- the CLI-subprocess acceptance contract lives in
tests/ingestion/test_tag_best_of_n.py.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from axial.llm import TAG_PASS_NAME
from axial.schema import load_schema
from axial.tag import ABSTAINED_KEY, AllChunksQuarantinedError, vote_blind_axes

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


# A correction re-ask's prompt is `compose_correction_prompt`'s
# `base_prompt + notice` (`tag.py`), and every primary draw shares the
# exact same `base_prompt` -- so this marker (the notice's own opening
# line) reliably tells a correction-reask call apart from a primary one,
# by content, regardless of call order.
_CORRECTION_REASK_MARKER = "CORRECTION REQUIRED"


class _ScriptedClient:
    """Returns one scripted raw response per call (mirrors `test_tag.py`'s
    own `_ScriptedClient`), from one of two independently-indexed pools:
    `primary_responses` for an ordinary draw call, `correction_responses`
    for a #102 correction re-ask (issue #325 follow-up).

    `run_tag`'s votes loop now fires its `votes` PRIMARY completions
    concurrently, so which physical draw-slot a given primary response
    lands in is no longer well-defined by call order alone (unlike before
    best-of-N went concurrent) -- but every draw's OWN correction re-ask (if
    any) still runs sequentially, afterward, in the post-processing loop.
    A single flat, call-count-indexed response list can no longer represent
    both a scenario's primary draws AND a triggered correction in one
    sequence: the concurrent primaries would race to consume the
    correction's own list slot before the correction call is ever made.
    Splitting the two pools by CONTENT (is this a correction re-ask?) rather
    than by ordinal position keeps every fixture correct regardless of
    which primary slot a given draw's own call lands in. Every access is
    locked (issue #325 follow-up): a shared instance is now called from
    multiple threads at once, and an unlocked read-then-increment is not
    atomic -- observed in practice to both corrupt `call_count` and raise a
    spurious `IndexError`."""

    def __init__(self, primary_responses: list[str], correction_responses: list[str] = ()):
        self._primary_responses = primary_responses
        self._correction_responses = list(correction_responses)
        self._primary_index = 0
        self._correction_index = 0
        self.call_count = 0
        self._lock = threading.Lock()

    def complete(self, prompt, pass_name=None):
        assert pass_name == TAG_PASS_NAME
        with self._lock:
            self.call_count += 1
            if _CORRECTION_REASK_MARKER in prompt:
                response = self._correction_responses[self._correction_index]
                self._correction_index += 1
            else:
                response = self._primary_responses[self._primary_index]
                self._primary_index += 1
        return response


def _run(tmp_path, monkeypatch, responses, *, votes, correction_responses=()):
    import axial.tag as tag_mod

    domain_dir = _write_domain(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)
    client = _ScriptedClient(responses, correction_responses)
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
    valid draws instead of aborting the source.

    Primary and correction responses are scripted as two SEPARATE pools
    (issue #325 follow-up): the 3 primary draws now fire concurrently, so
    which of the 3 physical slots gets the out-of-vocab primary is not
    well-defined by list position alone -- only that exactly one of the 3
    primaries is out-of-vocab, its own correction re-ask (a separate,
    content-identified call) still fails, and the other two are valid."""
    primary_responses = [
        # One out-of-vocab claim_type draw (its own #102 re-ask below fails
        # too -- a spoiled ballot) and two valid draws -- concurrent, so
        # order here is not the physical call order, only the multiset.
        _payload(claim_type=OUT_OF_VOCAB_CLAIM),
        _payload(claim_type=IN_VOCAB_CLAIM, theory_school=IN_VOCAB_SCHOOL),
        _payload(claim_type=IN_VOCAB_CLAIM, theory_school=IN_VOCAB_SCHOOL),
    ]
    correction_responses = [_payload(claim_type=OUT_OF_VOCAB_CLAIM)]

    records, client = _run(
        tmp_path,
        monkeypatch,
        primary_responses,
        votes=3,
        correction_responses=correction_responses,
    )

    assert client.call_count == 4
    assert len(records) == 1
    assert records[0]["claim_type"]["primary"] == IN_VOCAB_CLAIM
    assert ABSTAINED_KEY not in records[0]["claim_type"]


def test_run_tag_all_draws_invalid_quarantines_the_chunk(tmp_path, monkeypatch):
    """When EVERY draw is spoiled, issue #329 (reversing the #120-era P0-6
    ruling that this used to raise `TagNotInSchemaError` and abort the
    source) means the chunk quarantines instead -- `_run`'s fixture supplies
    exactly one chunk, so with it quarantined and zero tagged records,
    `run_tag` raises `AllChunksQuarantinedError` (#327), naming the
    offending value/axis in its own message (each quarantine's `detail` is
    `str()` of the original `TagNotInSchemaError`). The schema-gap guarantee
    still holds at the chunk level -- best-of-N only self-repairs when at
    least one draw is valid.

    Every primary AND every correction re-ask returns the identical
    out-of-vocab payload (issue #325 follow-up: both pools need their own
    entries now that they're dispatched separately -- see `_ScriptedClient`)
    -- up to 3 of each, one pair per draw, all spoiled."""
    responses = [_payload(claim_type=OUT_OF_VOCAB_CLAIM)] * 3
    correction_responses = [_payload(claim_type=OUT_OF_VOCAB_CLAIM)] * 3

    with pytest.raises(AllChunksQuarantinedError) as excinfo:
        _run(tmp_path, monkeypatch, responses, votes=3, correction_responses=correction_responses)

    assert excinfo.value.quarantine_count == 1
    assert "claim_type" in str(excinfo.value)
    assert OUT_OF_VOCAB_CLAIM in str(excinfo.value)


def test_run_tag_unlisted_softland_casts_a_ballot_and_can_lose(tmp_path, monkeypatch):
    """An out-of-vocab `theory_school` draw soft-lands to `unlisted` (a
    LEGAL ballot, unlike a spoiled claim_type draw) and then loses the vote
    to two draws that named a real school -- the vote self-repairing an
    invalid draw (DEC-31: out-of-vocab rate 0.0056 -> 0.0000).

    Primary/correction responses are two separate pools (issue #325
    follow-up), exactly mirroring the spoiled-ballot test above: the 3
    primary draws fire concurrently, so only the MULTISET (one out-of-vocab,
    two real schools) is scripted, not a physical call order."""
    primary_responses = [
        _payload(theory_school=OUT_OF_VOCAB_SCHOOL),
        _payload(theory_school=IN_VOCAB_SCHOOL),
        _payload(theory_school=IN_VOCAB_SCHOOL),
    ]
    correction_responses = [_payload(theory_school=OUT_OF_VOCAB_SCHOOL)]

    records, client = _run(
        tmp_path,
        monkeypatch,
        primary_responses,
        votes=3,
        correction_responses=correction_responses,
    )

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


# --- concurrency (issue #325 follow-up): votes fire concurrently, but the
# outcome must stay identical to the sequential algorithm given the same N
# raw responses, and the whole point is that it must be FASTER -----------


def test_run_tag_concurrent_votes_are_deterministic_across_repeated_runs(tmp_path, monkeypatch):
    """The same fixed set of 3 raw responses, run through `run_tag` many
    times, must produce the EXACT same majority-voted record every time --
    concurrency changes wall-clock, never the outcome. The modal values are
    deliberately NOT the first draw's (mirrors
    `test_run_tag_votes_three_draws_and_records_the_modal_blind_values`), so
    a stable, correct result can only come from a genuine, repeatable vote.

    Domain/chunk setup runs once (`_run` itself re-`mkdir`s a fresh domain
    dir per call, so a bare loop over `_run` cannot reuse one `tmp_path`)."""
    import axial.tag as tag_mod

    domain_dir = _write_domain(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)
    responses = [
        _payload(theory_school=OTHER_SCHOOL, claim_type=OTHER_CLAIM),
        _payload(theory_school=IN_VOCAB_SCHOOL, claim_type=IN_VOCAB_CLAIM),
        _payload(theory_school=IN_VOCAB_SCHOOL, claim_type=IN_VOCAB_CLAIM),
    ]
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")

    for _ in range(10):
        client = _ScriptedClient(responses)
        records = tag_mod.run_tag(
            tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=3
        )
        assert client.call_count == 3
        assert records[0]["theory_school"]["primary"] == IN_VOCAB_SCHOOL
        assert records[0]["claim_type"]["primary"] == IN_VOCAB_CLAIM
        assert ABSTAINED_KEY not in records[0]["theory_school"]
        assert ABSTAINED_KEY not in records[0]["claim_type"]


class _ContentDelayedClient:
    """Wraps `_ScriptedClient`, sleeping `slow_delay` seconds ONLY for the
    calls whose response equals `slow_response`, after that response has
    already been decided (issue #325 follow-up).

    Lets a test make a SPECIFIC draw's own network call the slowest of the
    concurrent votes -- proving `run_tag`'s outcome is decided by which
    response each draw's own `Future` resolves to, gathered in submission
    order (`completion_futures` list order), never by which draw happens to
    finish first."""

    def __init__(self, primary_responses, correction_responses=(), *, slow_response, slow_delay):
        self._inner = _ScriptedClient(primary_responses, correction_responses)
        self._slow_response = slow_response
        self._slow_delay = slow_delay

    def complete(self, prompt, pass_name=None):
        response = self._inner.complete(prompt, pass_name=pass_name)
        if response == self._slow_response:
            time.sleep(self._slow_delay)
        return response

    @property
    def call_count(self):
        return self._inner.call_count


def test_run_tag_spoiled_ballot_excluded_even_when_its_own_call_finishes_last(
    tmp_path, monkeypatch
):
    """The spoiled draw's own primary call is deliberately the SLOWEST of
    the 3 concurrent votes (it finishes last) -- the vote still excludes it
    and decides on the 2 valid draws, exactly as
    `test_run_tag_spoiled_claim_type_ballot_is_excluded_from_the_vote` does
    with no artificial delay at all. Proves out-of-order completion cannot
    flip which draw casts a ballot."""
    import axial.tag as tag_mod

    domain_dir = _write_domain(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    bad_primary = _payload(claim_type=OUT_OF_VOCAB_CLAIM)
    good = _payload(claim_type=IN_VOCAB_CLAIM, theory_school=IN_VOCAB_SCHOOL)
    client = _ContentDelayedClient(
        [bad_primary, good, good],
        correction_responses=[_payload(claim_type=OUT_OF_VOCAB_CLAIM)],
        slow_response=bad_primary,
        slow_delay=0.3,
    )
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")

    records = tag_mod.run_tag(
        tmp_path / "paper.pdf",
        client=client,
        domain_dir=domain_dir,
        tags_dir=tmp_path / "tags",
        votes=3,
    )

    assert len(records) == 1
    assert records[0]["claim_type"]["primary"] == IN_VOCAB_CLAIM
    assert ABSTAINED_KEY not in records[0]["claim_type"]


def test_run_tag_votes_run_concurrently_not_sequentially(tmp_path, monkeypatch):
    """The actual concurrency proof -- deterministic, no wall-clock
    threshold to tune: every one of the 3 votes' `complete()` calls must
    reach a shared `threading.Barrier(votes)` before ANY of them is allowed
    to return. That is only satisfiable if all 3 are genuinely in flight at
    the same time. A sequential votes loop (one call fully returning before
    the next begins) can never satisfy it -- the first call would sit alone
    at the barrier, since the second and third are never concurrently in
    flight to arrive with it, and the barrier's own bounded timeout turns
    that into a clean, deterministic `BrokenBarrierError` failure rather
    than a hang. This is the whole point of the change: it fails under the
    old sequential votes loop and passes under the concurrent one, with no
    reruns needed to trust either outcome."""
    import axial.tag as tag_mod

    domain_dir = _write_domain(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    votes = 3
    barrier = threading.Barrier(votes, timeout=5.0)

    class _BarrierClient:
        def complete(self, prompt, pass_name=None):
            barrier.wait()
            return _payload()

    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")

    records = tag_mod.run_tag(
        tmp_path / "paper.pdf",
        client=_BarrierClient(),
        domain_dir=domain_dir,
        tags_dir=tmp_path / "tags",
        votes=votes,
    )

    assert len(records) == 1
