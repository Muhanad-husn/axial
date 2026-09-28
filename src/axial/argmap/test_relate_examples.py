"""Issue #855: the map build's relate prompt offers the committed relation
kinds as EXAMPLES, never as a menu (DEC-47's D8 rule), and is unchanged when
there is nothing to offer."""

from __future__ import annotations

import json

from axial.argmap.build import RELATE_PROMPT, Neighbourhood, relate_neighbourhood, render_relate_prompt
from axial.llm import StubLLMClient
from axial.vocabulary import SchemeCategory


def _kind(name: str, gloss: str) -> SchemeCategory:
    return SchemeCategory(id=name.replace(" ", "-"), name=name, gloss=gloss, parent_id="conflict", level=2)


def test_with_no_kinds_the_prompt_is_the_prompt_it_always_was():
    assert render_relate_prompt("[a1] x\n[a2] y") == RELATE_PROMPT.format(positions="[a1] x\n[a2] y")


def test_committed_kinds_are_offered_as_examples_and_the_menu_rule_stays():
    prompt = render_relate_prompt(
        "[a1] x\n[a2] y",
        examples=[_kind("redirects explanation", "moves the cause somewhere else")],
    )

    assert "redirects explanation" in prompt
    assert "moves the cause somewhere else" in prompt
    assert "There is no list of allowed relations." in prompt
    assert "not a menu" in prompt


class _RecordingClient(StubLLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.prompts.append(prompt)
        return json.dumps({"relations": []})


def test_relate_neighbourhood_sends_the_examples():
    client = _RecordingClient()
    by_id = {"p1": {"argument": "x"}, "p2": {"argument": "y"}}
    relate_neighbourhood(
        Neighbourhood(key="k", position_ids=("p1", "p2")),
        by_id,
        client,
        examples=[_kind("qualifies scope", "narrows where the other holds")],
    )
    assert "qualifies scope" in client.prompts[0]
