"""Outer acceptance test for issue #489 (Phase B v1 slice 04): evidence
assembly and the synthesis prompt rebuilt on the interrogation's answers.

Given a fixture vault whose prose notes carry the interrogation `answers`
      block (`specs/PRODUCT.md` §7.15) instead of the retired tag axes
When  the stage-4 synthesis pass runs over an assembled evidence set
Then  the prompt lists each note's own answers -- claim, move, whose position,
      what that position is, who it argues against, who it cites and with what
      stance -- alongside the real prose
  And a field the passage abstained on appears NOWHERE in the prompt, in any of
      §7.15's three abstention forms
  And `[]` on a multi-valued field is rendered as the answer it is
  And no real `chunk_id` appears anywhere in the prompt (the #410 property,
      re-asserted under the rewritten prompt)
  And the prompt forbids citing a Gather-pass disagreement finding (D4)

Given a scripted response whose claim cites `ref_type: "finding"`
When  the synthesis pass parses it
Then  it fails loudly: the grounds vocabulary is `chunk` or `artifact` and
      gains no third value, so no claim in a produced record can cite a
      Gather finding

Given a persisted record carrying a (b) claim whose text reads as a single
      source's assertion, and the attribution validator's bounded (b)-seam
      check scripted to flag it
When  the attribution validator runs
Then  the claim is reported with reason `b_seam_voiced_as_source` (P0-4), under
      a pass_name distinct from the synthesis pass

Two of the issue's observables are asserted in the files that already own
them, rather than duplicated here: `axial brief examine` making zero synthesis
calls and reporting the new evidence shape is
tests/analysis/test_brief_examine.py, and `names_touched` as the alias-map
union over the grounds notes' own `names` answers is
tests/analysis/test_synthesis_claim_graph.py (which controls the name layer
the resolution reads).

See specs/PHASE-B.md §7.4 (the claim contract, opaque handles, `names_touched`),
§7.5 D4 (a finding is a hint, never a citation), §7.9 (the validators), and
`specs/PRODUCT.md` §7.15 (the answer record and the three-state abstention
rule).

Seam decisions
--------------
Library-level, in-process (mirroring test_synthesis_claim_graph.py's own seam):
`RecordLLMClient` logs the composed prompt to disk so the prompt-content
properties are asserted against what was really sent, not against a string
this test rebuilt. The (b)-seam scenario calls `validate_attribution` directly
with a `StubLLMClient` and `AXIAL_STUB_MODEL_BY_PASS`, which is what keeps the
check's own same-model guard from (correctly) refusing to run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.analyze.assembly import assemble_evidence
from axial.analyze.synthesis import (
    InvalidGroundRefTypeError,
    compose_prompt,
    parse_synthesis_response,
    synthesize,
)
from axial.brief.intake import Brief
from axial.llm import (
    ATTRIBUTION_PASS_NAME,
    STUB_ATTRIBUTION_RESPONSE_ENV_VAR,
    STUB_MODEL_BY_PASS_ENV_VAR,
    STUB_SYNTHESIZE_RESPONSE_ENV_VAR,
    SYNTHESIZE_PASS_NAME,
    RecordLLMClient,
    StubLLMClient,
)
from axial.validators.attribution import REASON_B_SEAM_VOICED_AS_SOURCE, validate_attribution

# Two long, similar ids -- the real #410 failure shape (ayubi-1995 /
# batatu-1999), so "no real chunk_id in the prompt" is asserted over ids a
# model would actually blend.
TILLY_NOTE = "tilly-1978-f908c910464c_105_organized-challengers_002"
BAYAT_NOTE = "bayat-2017-ce6bb0643cfb_105_organized-challengers_002"


def _note(*, chunk_id: str, answers: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        # Deliberately does NOT embed the note's own id: a real chunk's prose
        # never contains it, which is what makes the "the id is nowhere in the
        # prompt" assertion meaningful.
        "chunk_text": "Generic prose about organized challengers and mobilization.",
        "source_meta": {
            "author": "A. Synthetic Author",
            "title": "A Synthetic Fixture Source",
            "date": 1978,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "frame_version": "0.1",
        "answers": answers,
    }


def _write_vault(root: Path, notes: list[dict[str, Any]]) -> Path:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for frontmatter in notes:
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")
    return root / "data" / "vault"


ANSWERED = {
    "claim": "Organized challengers convert a revolutionary situation into an outcome.",
    "move": "narrowing an earlier claim to cases with prior organization",
    "position_of": "the author",
    "position": "mobilization without organization does not convert",
    "arguing_against": ["the spontaneous-uprising account"],
    "names": [
        {"name": "Charles Tilly", "kind": "person"},
        {"name": "Syria", "kind": "country/state/place"},
    ],
    "citations": [{"cited": "Asef Bayat", "stance": "foil", "about": "revolutionary situations"}],
    "mechanism": "accumulated resources let a challenger hold territory long enough to bargain",
}

# §7.15's three abstention forms, plus each of the two legal one-element list
# wrappings. Every one of them is an abstention, not an answer.
ABSTENTION_FORMS = {
    "bare-string": "not-in-passage",
    "object-with-reason": {"not-in-passage": "the passage does not settle whose position this is"},
    "one-element-list": ["not-in-passage"],
    "one-element-object-list": [{"not-in-passage": "the passage does not say"}],
}


@pytest.fixture
def brief() -> Brief:
    return Brief(
        brief_id="p3-01",
        case="Syria, 2011-2024",
        request="Does organization convert a revolutionary situation into an outcome?",
        lens="political-economy",
    )


def test_prompt_lists_each_notes_own_answers_beside_its_prose(tmp_path: Path, brief: Brief):
    """The evidence block is the interrogation's answers now, not five deleted
    tag axes: every one of them rendered empty against the v1 vault."""
    vault_dir = _write_vault(tmp_path, [_note(chunk_id=TILLY_NOTE, answers=ANSWERED)])
    evidence = assemble_evidence([TILLY_NOTE], vault_dir=vault_dir)

    composed = compose_prompt(brief, "political-economy", evidence, vault_dir=vault_dir)

    assert "claim: Organized challengers convert" in composed.text
    assert "move in the argument: narrowing an earlier claim" in composed.text
    assert "whose position: the author" in composed.text
    assert "the position: mobilization without organization does not convert" in composed.text
    assert "arguing against: the spontaneous-uprising account" in composed.text
    assert "mechanism: accumulated resources" in composed.text
    # A name carries its kind, and a citation carries the author's own stance.
    assert "names: Charles Tilly (person); Syria (country/state/place)" in composed.text
    assert "cites: Asef Bayat [foil] -- revolutionary situations" in composed.text
    # The prose itself is still there -- answers are a second reading of the
    # passage, never a replacement for it.
    assert "Generic prose about organized challengers" in composed.text
    # And none of the retired axes, which carry nothing on any v1 note.
    for retired in ("role_in_argument", "theory_school", "claim_type", "empirical_scope"):
        assert retired not in composed.text


@pytest.mark.parametrize("form", sorted(ABSTENTION_FORMS), ids=sorted(ABSTENTION_FORMS))
def test_an_abstained_position_never_reaches_the_prompt_as_an_answer(
    tmp_path: Path, brief: Brief, form: str
):
    """23% of the live corpus abstains on `position_of` and 24% on
    `arguing_against`. An abstention rendered as an answer is indistinguishable
    downstream from a read one, which is exactly what D7 exists to prevent."""
    abstained = ABSTENTION_FORMS[form]
    answers = dict(ANSWERED, position_of=abstained, position=abstained, arguing_against=abstained)
    vault_dir = _write_vault(tmp_path, [_note(chunk_id=TILLY_NOTE, answers=answers)])
    evidence = assemble_evidence([TILLY_NOTE], vault_dir=vault_dir)

    composed = compose_prompt(brief, "political-economy", evidence, vault_dir=vault_dir)

    assert "not-in-passage" not in composed.text
    assert "whose position:" not in composed.text
    assert "the position:" not in composed.text
    assert "arguing against:" not in composed.text
    # The passage's real answers are unaffected -- an abstention on one field
    # is not a reason to drop the note or its other answers.
    assert "claim: Organized challengers convert" in composed.text
    assert "Generic prose about organized challengers" in composed.text


def test_an_empty_multi_valued_answer_is_rendered_as_the_answer_it_is(tmp_path: Path, brief: Brief):
    """`[]` says the passage names none of that kind of thing -- a read, not a
    refusal (§7.15). It is never normalised onto an abstention, and it is said
    in words rather than as an empty bracket pair a model would read as a
    missing field."""
    answers = dict(ANSWERED, arguing_against=[])
    vault_dir = _write_vault(tmp_path, [_note(chunk_id=TILLY_NOTE, answers=answers)])
    evidence = assemble_evidence([TILLY_NOTE], vault_dir=vault_dir)

    composed = compose_prompt(brief, "political-economy", evidence, vault_dir=vault_dir)

    assert "arguing against: (the passage names none)" in composed.text
    assert "not-in-passage" not in composed.text


def test_the_prompt_contains_no_real_chunk_id_under_the_new_evidence_block(
    tmp_path: Path, brief: Brief
):
    """The #410 property, re-asserted under the rewritten prompt: the model is
    offered a short per-call handle and never a real id, so there is nothing
    long to transcribe, truncate, or blend across two similar sources. A
    blended id is not a handle at all, so it cannot resolve onto either
    scholar's note."""
    vault_dir = _write_vault(
        tmp_path,
        [
            _note(chunk_id=TILLY_NOTE, answers=ANSWERED),
            _note(chunk_id=BAYAT_NOTE, answers=ANSWERED),
        ],
    )
    evidence = assemble_evidence([TILLY_NOTE, BAYAT_NOTE], vault_dir=vault_dir)

    composed = compose_prompt(brief, "political-economy", evidence, vault_dir=vault_dir)

    assert TILLY_NOTE not in composed.text
    assert BAYAT_NOTE not in composed.text
    assert composed.handle_map == {"[c1]": TILLY_NOTE, "[c2]": BAYAT_NOTE}

    blended = "tilly-1978-ce6bb0643cfb_105_organized-challengers_002"
    raw = json.dumps(
        {
            "claims": [
                {
                    "text": "A claim citing a blended cross-source id.",
                    "kind": "a",
                    "grounds": [{"ref_type": "chunk", "ref_id": blended}],
                    "confidence": "medium",
                }
            ]
        }
    )
    with pytest.raises(Exception) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir, handle_map=composed.handle_map)
    assert blended in str(exc_info.value)


def test_the_prompt_forbids_citing_a_gather_finding(tmp_path: Path, brief: Brief):
    """D4: a finding is a retrieval hint and another pass's reading of the
    corpus, never a source. The 575 findings have never been scored (DEC-55),
    so a claim resting on one would launder unscored prose into an attributed
    answer."""
    vault_dir = _write_vault(tmp_path, [_note(chunk_id=TILLY_NOTE, answers=ANSWERED)])
    evidence = assemble_evidence([TILLY_NOTE], vault_dir=vault_dir)

    composed = compose_prompt(brief, "political-economy", evidence, vault_dir=vault_dir)

    lowered = composed.text.lower()
    assert "disagreement" in lowered
    assert "not quotable, not citable" in lowered
    assert "chunk handles and artifact_ids listed above, and nothing else" in lowered


def test_a_claim_citing_a_finding_is_rejected_the_vocabulary_has_two_values(
    tmp_path: Path, brief: Brief
):
    """`ref_type` is `chunk` or `artifact` and gains no third value (D4), so
    no claim in a produced record can cite a Gather finding, however the model
    words it."""
    vault_dir = _write_vault(tmp_path, [_note(chunk_id=TILLY_NOTE, answers=ANSWERED)])
    raw = json.dumps(
        {
            "claims": [
                {
                    "text": "A claim grounded in what another pass concluded.",
                    "kind": "b",
                    "grounds": [{"ref_type": "finding", "ref_id": "Charles Tilly"}],
                    "confidence": "medium",
                }
            ]
        }
    )

    with pytest.raises(InvalidGroundRefTypeError) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir, handle_map={"[c1]": TILLY_NOTE})

    assert "finding" in str(exc_info.value)


def test_every_ground_in_a_produced_claim_graph_is_a_chunk_or_an_artifact(
    tmp_path: Path, brief: Brief, monkeypatch: pytest.MonkeyPatch
):
    vault_dir = _write_vault(
        tmp_path,
        [
            _note(chunk_id=TILLY_NOTE, answers=ANSWERED),
            _note(chunk_id=BAYAT_NOTE, answers=ANSWERED),
        ],
    )
    monkeypatch.setenv(
        STUB_SYNTHESIZE_RESPONSE_ENV_VAR,
        json.dumps(
            {
                "claims": [
                    {
                        "text": "The tool infers, across Tilly and Bayat, that organization "
                        "and mobilization come apart.",
                        "kind": "b",
                        "grounds": [
                            {"ref_type": "chunk", "ref_id": "[c1]"},
                            {"ref_type": "chunk", "ref_id": "[c2]"},
                        ],
                        "confidence": "medium",
                    }
                ]
            }
        ),
    )
    evidence = assemble_evidence([TILLY_NOTE, BAYAT_NOTE], vault_dir=vault_dir)
    client = RecordLLMClient(tmp_path / "record.jsonl")

    graph = synthesize(evidence, brief, client=client, vault_dir=vault_dir)

    assert graph.claims
    for claim in graph.claims:
        for ground in claim.grounds:
            assert ground.ref_type in {"chunk", "artifact"}
            assert ground.ref_id in {TILLY_NOTE, BAYAT_NOTE}


def test_the_attribution_validator_still_catches_a_b_claim_voiced_as_a_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """P0-4 survives the prompt rewrite on both sides: the prompt states the
    rule, and the bounded (b)-seam check still catches a claim that breaks it
    -- under its own pass_name, never the generating model's."""
    vault_dir = _write_vault(tmp_path, [_note(chunk_id=TILLY_NOTE, answers=ANSWERED)])
    monkeypatch.setenv(
        STUB_MODEL_BY_PASS_ENV_VAR,
        json.dumps({SYNTHESIZE_PASS_NAME: "stub-generator", ATTRIBUTION_PASS_NAME: "stub-checker"}),
    )
    monkeypatch.setenv(
        STUB_ATTRIBUTION_RESPONSE_ENV_VAR, json.dumps({"flagged_claim_ids": ["c-002"]})
    )
    record = {
        "claims": [
            {
                "claim_id": "c-002",
                "kind": "b",
                # Voiced as though one source said it -- the P0-4 violation.
                "text": "Tilly shows that organization is what converts a situation.",
                "grounds": [{"ref_type": "chunk", "ref_id": TILLY_NOTE}],
                "confidence": "medium",
                "names_touched": [],
            }
        ]
    }

    report = validate_attribution(record, client=StubLLMClient(), vault_dir=vault_dir)

    assert not report.passed
    assert [(f.claim_id, f.reason) for f in report.failures] == [
        ("c-002", REASON_B_SEAM_VOICED_AS_SOURCE)
    ]


def test_the_prompt_still_marks_a_cross_source_inference_as_the_tools_own(
    tmp_path: Path, brief: Brief
):
    vault_dir = _write_vault(tmp_path, [_note(chunk_id=TILLY_NOTE, answers=ANSWERED)])
    evidence = assemble_evidence([TILLY_NOTE], vault_dir=vault_dir)

    composed = compose_prompt(brief, "political-economy", evidence, vault_dir=vault_dir)

    assert "must NEVER be voiced as though a single source asserted it" in composed.text
    assert "parametric memory" in composed.text.lower()
    assert "open web" in composed.text.lower()
