"""The originating analysis record is visible on every claim line, and a
single-record (b) proposal is retried rather than fatal (specs/PHASE-C.md
§7.4, issue #616).

`_NEW_CLAIM_B` holds the drafter to a rule stated over `origin.brief_id`, but
the rendered claim lines never showed it -- the drafter was asked to obey a
rule over a field it could not see. Two of #605's D1 multi-record dev briefs
failed on exactly this shape: a proposed (b) claim whose `derived_from`
resolved to one distinct source record, discovered only AFTER
`draft_section` had already returned, which discarded every section drafted
so far (`data/logs/2026-08-02-phase-c-dev-briefs/console.log`).
"""

from __future__ import annotations

import json

from axial.paper.draft import Section as DraftSection, draft_section
from axial.paper.lens import resolve_lens

LENS = resolve_lens("political-economy")


class _QueueClient:
    """Returns one queued response per call, in order, and records every
    prompt sent -- same shape as `tests/paper/test_paper_retry.py`."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, prompt, pass_name=None, **_):
        self.prompts.append((pass_name, prompt))
        return self._responses.pop(0)

    def model_for_pass(self, pass_name=None):
        return f"stub/{pass_name}"

    def usage_for_pass(self, pass_name=None):
        return None


SECTION = DraftSection(
    section_id="s1",
    heading="The claim",
    role="claim",
    assigned_claims=(("brief-a", "key-1"), ("brief-a", "key-2")),
)
CLAIM_IDS = {("brief-a", "key-1"): "pc-001", ("brief-a", "key-2"): "pc-002"}
CLAIMS_BY_ID = {
    "pc-001": {
        "kind": "a",
        "confidence": "high",
        "text": "War made the state.",
        "origin": {"brief_id": "tilly-1978", "claim_id": "a1"},
        "derived_from": [],
    },
    "pc-002": {
        "kind": "a",
        "confidence": "high",
        "text": "Extraction follows coercion.",
        "origin": {"brief_id": "tilly-1978", "claim_id": "a2"},
        "derived_from": [],
    },
}


def _valid_draft_json() -> str:
    return json.dumps({"prose": "War made the state [pc-001].", "new_claims": []})


def test_a_carried_claims_line_names_its_originating_record():
    client = _QueueClient([_valid_draft_json()])
    draft_section(client, "Thesis.", LENS, SECTION, CLAIM_IDS, CLAIMS_BY_ID, [])

    prompt = client.prompts[0][1]
    assert "record tilly-1978" in prompt


def test_a_new_claim_cited_earlier_names_the_records_it_derives_from():
    """A carried claim's origin is direct; a new (b)/(c) claim's is not -- it
    resolves through `derived_from`, which can itself name another new claim
    (issue #616)."""
    claims_by_id = dict(CLAIMS_BY_ID)
    claims_by_id["pc-003"] = {
        "kind": "a",
        "confidence": "high",
        "text": "Mobilization mattered too.",
        "origin": {"brief_id": "mccarthy-1977", "claim_id": "b1"},
        "derived_from": [],
    }
    already_cited = [
        {
            "paper_claim_id": "pc-010",
            "kind": "b",
            "confidence": "low",
            "text": "The two accounts diverge on organization.",
            "origin": None,
            "derived_from": ["pc-001", "pc-003"],
        }
    ]

    client = _QueueClient([_valid_draft_json()])
    draft_section(client, "Thesis.", LENS, SECTION, CLAIM_IDS, claims_by_id, already_cited)

    prompt = client.prompts[0][1]
    assert "record mccarthy-1977, tilly-1978" in prompt


def test_a_single_record_b_proposal_is_retried_not_fatal_shaped_like_the_real_failure():
    """Reproduces the real production shape from
    `data/logs/2026-08-02-phase-c-dev-briefs/console.log`: a (b) claim whose
    `derived_from` resolves to exactly one distinct source record
    (`tilly-1978`, both `pc-001` and `pc-002` here). Before this fix that
    raised `SingleRecordInferenceError` out of
    `axial.paper.claims.new_b_claim`, called only after `draft_section`
    returned -- fatal on the first occurrence, discarding every section
    already drafted."""
    single_record_proposal = json.dumps(
        {
            "prose": "War made the state [pc-001]. And extraction follows [n1].",
            "new_claims": [
                {
                    "local_id": "n1",
                    "kind": "b",
                    "text": "A restatement, not a synthesis.",
                    "derived_from": ["pc-001", "pc-002"],
                }
            ],
        }
    )
    corrected = json.dumps({"prose": "War made the state [pc-001].", "new_claims": []})
    client = _QueueClient([single_record_proposal, corrected])

    draft = draft_section(client, "Thesis.", LENS, SECTION, CLAIM_IDS, CLAIMS_BY_ID, [])

    assert draft.retries == 1
    assert draft.new_claims == ()

    retry_prompt = client.prompts[1][1]
    assert "distinct source record" in retry_prompt
    assert "tilly-1978" in retry_prompt
