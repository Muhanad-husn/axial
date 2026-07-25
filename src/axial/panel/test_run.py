"""Inner unit tests for the composed panel run (issue #385, §9.4): the
control runs first, and its verdict is what `trusted` means."""

from __future__ import annotations

import json

import pytest

import axial.panel.packet as packet_mod
from axial.llm import SYNTHESIZE_PASS_NAME
from axial.panel.control import PlantNotApplicableError
from axial.panel.review import reviewer_pass_name
from axial.panel.run import format_panel_run, run_panel


class _StubChunk:
    def __init__(self, text: str):
        self.chunk_text = text


class FakeClient:
    """Answers every reviewer call from `verdict_for(prompt)`, so a test can
    make the panel catch or miss planted defects by inspecting the packet."""

    def __init__(self, verdict_for):
        self._verdict_for = verdict_for
        self.calls = 0

    def model_for_pass(self, pass_name):
        models = {
            SYNTHESIZE_PASS_NAME: "deepseek/deepseek-v4-pro",
            reviewer_pass_name(1): "anthropic/claude-opus-4",
            reviewer_pass_name(2): "openai/gpt-5",
            reviewer_pass_name(3): "google/gemini-3-pro",
        }
        return models.get(pass_name, "deepseek/deepseek-v4-pro")

    def complete(self, prompt, pass_name=None):
        self.calls += 1
        return self._verdict_for(prompt)


def _bands(band="strong"):
    return {
        "factual_correctness": band,
        "citation_grounding": band,
        "completeness": band,
    }


def _record():
    return {
        "brief_id": "b-001",
        "claims": [
            {
                "claim_id": "c-1",
                "kind": "a",
                "text": "Bureaucratic capacity fell.",
                "polity": "syria",
                "confidence": "medium",
                "grounds": [{"ref_type": "chunk", "ref_id": "chunk_a"}],
            },
            {
                "claim_id": "c-2",
                "kind": "a",
                "text": "Militia payrolls grew.",
                "polity": "lebanon",
                "confidence": "high",
                "grounds": [{"ref_type": "chunk", "ref_id": "chunk_b"}],
            },
        ],
        "counter_position": {
            "present": True,
            "stance": "War strengthened the state.",
            "grounds": [{"ref_type": "chunk", "ref_id": "chunk_c"}],
        },
        "coverage_map": {
            "syria": {"coverage_band": "thin"},
            "lebanon": {"coverage_band": "rich"},
        },
    }


@pytest.fixture(autouse=True)
def stub_vault(monkeypatch):
    texts = {
        "chunk_a": "Tax receipts fell sharply.",
        "chunk_b": "Militia payrolls expanded.",
        "chunk_c": "Wartime ministries consolidated.",
    }
    monkeypatch.setattr(
        packet_mod, "get_chunk", lambda ref_id, vault_dir=None: _StubChunk(texts[ref_id])
    )


def _perfect_reviewer(prompt: str) -> str:
    """Catches every plant: each mutated packet is recognisable from the
    evidence it now carries, which is exactly what a real reviewer reads."""
    defects = []
    # mis_grounded: claim c-1 now cites c-2's evidence.
    if "Bureaucratic capacity fell." in prompt and "Tax receipts fell sharply." not in prompt:
        defects.append({"claim_id": "c-1", "kind": "mis_grounded", "note": ""})
    # strawman: the counter-position now rests on the claim's own grounds.
    if "Wartime ministries consolidated." not in prompt:
        defects.append(
            {"claim_id": "<counter_position>", "kind": "strawman_counter_position", "note": ""}
        )
    # overconfident: c-1 raised to high over a thin polity.
    if "[confidence: high]" in prompt.split("Militia payrolls grew.")[0]:
        defects.append({"claim_id": "c-1", "kind": "overconfident", "note": ""})
    return json.dumps({**_bands("weak"), "defects": defects})


def _generous_reviewer(_prompt: str) -> str:
    """Waves everything through -- the failure mode the control exists to
    detect."""
    return json.dumps({**_bands("strong"), "defects": []})


def test_a_generous_panel_fails_the_control_and_reports_untrusted():
    client = FakeClient(_generous_reviewer)
    run = run_panel([_record()], _record(), client=client, corpus_pin="pin-1")

    assert run.control.passed is False
    assert run.trusted is False
    assert all(report.trusted is False for report in run.reports)


def test_the_sample_is_still_reviewed_on_a_failed_control():
    """Suppressing the numbers would hide which packets a broken referee
    mis-scored; they are reported, marked untrusted."""
    client = FakeClient(_generous_reviewer)
    run = run_panel([_record()], _record(), client=client, corpus_pin="pin-1")
    assert len(run.reports) == 1


def test_a_catching_panel_passes_the_control_and_lifts_trusted():
    client = FakeClient(_perfect_reviewer)
    run = run_panel([_record()], _record(), client=client, corpus_pin="pin-1")

    assert run.control.passed is True, [o.to_json() for o in run.control.outcomes]
    assert run.trusted is True
    assert all(report.trusted is True for report in run.reports)


def test_the_control_runs_before_the_sample():
    seen: list[str] = []

    def recording(prompt: str) -> str:
        seen.append("control" if "Tax receipts fell sharply." not in prompt else "sample")
        return _generous_reviewer(prompt)

    run_panel([_record()], _record(), client=FakeClient(recording), corpus_pin="pin-1")
    assert seen.index("sample") > 0, "every control call must precede the first sample call"


def test_a_control_record_that_cannot_carry_a_plant_raises():
    thin = _record()
    thin["counter_position"] = {"present": False}
    with pytest.raises(PlantNotApplicableError):
        run_panel([_record()], thin, client=FakeClient(_generous_reviewer), corpus_pin="pin-1")


def test_every_report_states_its_frame():
    client = FakeClient(_generous_reviewer)
    run = run_panel(
        [_record()],
        _record(),
        client=client,
        corpus_pin="pin-1",
        frame={"tier": "medium", "model_combination": "baseline"},
    )
    frame = run.reports[0].frame
    assert frame["tier"] == "medium"
    assert frame["corpus_pin"] == "pin-1"
    assert frame["n_reviewers"] == 3


def test_rendered_run_leads_with_the_control():
    client = FakeClient(_generous_reviewer)
    rendered = format_panel_run(run_panel([_record()], _record(), client=client, corpus_pin=None))
    assert rendered.startswith("positive control:")
    assert "NOT human expert judgement" in rendered
