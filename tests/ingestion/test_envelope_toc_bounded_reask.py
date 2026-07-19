"""Outer acceptance test for issue #241 (envelope `toc` reconstruction is
high-variance on large contributed volumes -- Direction 1: one bounded toc
re-ask on an invalid/degenerate shape, before falling back to the
deterministic raw `_toc_from_tree` dump).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given the structural-envelope pass's single model call returns a valid
      thesis/scope/stated_argument but an invalid/degenerate `toc` shape
      (fails `is_valid_toc`)
When  `run_envelope` resolves the final `toc`
Then  it issues exactly ONE additional model call (the toc re-ask) before
      ever falling back to `_fallback_toc`'s deterministic raw-heading dump,
      and if that second call's `toc` validates, the WRITTEN envelope's
      `toc` is the second call's `toc` -- not the raw dump

Given TWO consecutive invalid/degenerate `toc` answers (the original call
      and the one bounded re-ask)
Then  a THIRD model call must never happen -- the re-ask is bounded to
      exactly one -- and the written envelope's `toc` falls back to
      `_fallback_toc`'s deterministic result, which is non-empty and passes
      `validate_envelope_fields`, so the non-empty guarantee (PRD §7.3)
      still holds

Given a first model call whose `toc` already validates
Then  `run_envelope` issues NO second call -- the re-ask must never add
      cost to a source that was already stable (the 29/30 sources DEC-28
      names as clean today)

Given `complete_json`'s own bounded re-ask budget (`reject_degenerate_
      thesis_fields`, issue #80) is entirely consumed bringing
      thesis/scope/stated_argument from degenerate to valid, and the
      response that finally satisfies that budget carries an invalid `toc`
Then  the toc re-ask still fires as one call BEYOND that already-exhausted
      budget -- proving the two re-ask mechanisms are on separate,
      non-interacting budgets, and thesis-field degeneracy handling (#80)
      is otherwise unchanged

See issue #241 (this repo's GitHub issue tracker) and DEC-28 (docs/
DECISIONS.md): "the model choice is deferred behind the model-independent
robustness fix #241 (a bounded toc re-ask on an invalid shape before the
raw-dump fallback)." The founder's scoping comment on #241 ratifies
"Direction 1 -- one bounded toc re-ask on invalid/degenerate shape, before
falling back to the raw `_toc_from_tree` dump" and explicitly rejects
Direction 2 (best-of-N) and Direction 3 (curating Signal B). The founder's
spec-adjudication comment on #241 rules this is implementation, not spec
drift: PRD §7.3's "one API call per source" describes the happy path (the
pass already issues extra calls on the thesis-degeneracy failure branch,
`reject_degenerate_thesis_fields`/#80); this issue's own re-ask is a second,
SEPARATE-budget failure-branch retry of the same established shape, gated
only on `toc`, that "always falls through to `_fallback_toc`" (never
hard-fails the whole pass) -- so `specs/PRODUCT.md` needs no edit and this
test asserts no PRD section number.

Why this test does NOT attempt to lock re-ask PROMPT wording or content
-----------------------------------------------------------------------
Issue #241's own root-cause section is explicit that the failure mode is a
single-shot model roll, not a prompt-wording defect (`chouliaraki`/`zaum`/
etc. roll differently across identical calls under either model, DEC-28's
own decisive `zaum` datapoint). This test locks the MECHANICAL contract:
call counts, which raw content wins, and the deterministic fallback still
holding -- exactly the same species of contract
`test_envelope_toc_two_signal_reconstruction.py`'s own module docstring
argues for, and for the same reason (asserting prompt-shape identity would
be tautological against a stub/fake client that never reasons about
content; real-model re-ask quality is validated separately, against the
concrete sources #241's own comment thread names, as a post-merge
regenerate-only step, not part of this TDD).

Seam decision -- direct `run_envelope(client=...)` injection, no CLI/
subprocess, no new stub-provider seam
-----------------------------------------------------------------------
Issue #241's own "Note for the implementing session" names this exact seam:
"A fake `LLMClient` returning an invalid-shape toc then a valid one proves
the re-ask deterministically -- same seam
`test_envelope_deterministic_nested_fallback_on_reconstruction_failure`
already uses (`run_envelope(client=...)`)." Every fake client below
implements the single-method `complete(self, prompt, pass_name=None) -> str`
protocol every stub/record/real client in `src/axial/llm.py` shares
(`axial.llm.LLMClient`), and hard-fails loudly (`AssertionError`, raised
from inside `complete()` itself, never swallowed by any bounded-retry loop
downstream) the moment it is called more times than the scenario's own
contract permits -- so an unbounded re-ask fails this test with a clear,
attributable message rather than a silent extra call.

Fixture reuse: `tests/fixtures/envelope/llm_toc_selection_paper.pdf` +
`llm_toc_selection_tree.json` (issue #231's own fixture, already reused by
`test_envelope_toc_two_signal_reconstruction.py`). Its tree carries eleven
flattened `section_header` headings and matches none of intro/abstract/
conclusion (confirmed by that file's own fixture-sanity check), so
`_toc_from_tree(tree)` is reliably non-empty -- exactly what the
deterministic-fallback scenario below needs -- and `compose_thesis_evidence`
reliably clears the evidence floor via the head-of-tree widen, so every
scenario's thesis/scope/stated_argument text is free-form rather than
needing to match any particular section.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import axial.envelope as envelope_module
from axial.envelope import compute_source_id, run_envelope

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
TREES_DIR = REPO_ROOT / "data" / "trees"

LLM_TOC_PDF = FIXTURES_DIR / "llm_toc_selection_paper.pdf"
LLM_TOC_TREE_FIXTURE = FIXTURES_DIR / "llm_toc_selection_tree.json"


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path) -> Path:
    """Pre-place a hand-authored tree fixture at data/trees/<source_id>.json
    (mirrors every other envelope acceptance test's helper of the same
    name, e.g. test_envelope_toc_two_signal_reconstruction.py)."""
    source_id = compute_source_id(source_pdf)
    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _assert_valid_nested_toc(toc: Any) -> None:
    """PRD §7.3's locked shape: `toc` is a non-empty list of
    `{title, children[]}` objects, each `title` a non-empty string and each
    `children` a (possibly empty) list of strings."""
    assert isinstance(toc, list) and len(toc) > 0, (
        f"expected `toc` to be a non-empty list (PRD §7.3), got {toc!r}"
    )
    for entry in toc:
        assert isinstance(entry, dict), (
            f"expected every `toc` entry to be a {{title, children[]}} "
            f"object, got a {type(entry).__name__}: {entry!r}\nFull toc: {toc!r}"
        )
        title = entry.get("title")
        assert isinstance(title, str) and title.strip(), (
            f"expected every `toc` entry's `title` to be a non-empty "
            f"string, got {title!r} in entry {entry!r}\nFull toc: {toc!r}"
        )
        children = entry.get("children")
        assert isinstance(children, list) and all(isinstance(c, str) for c in children), (
            f"expected every `toc` entry's `children` to be a list of "
            f"strings, got {children!r} in entry {entry!r}\nFull toc: {toc!r}"
        )


def _envelope_response(
    *,
    thesis: str = "Contentious episodes escalate through a predictable sequence.",
    scope: str = "A comparative survey of contentious episodes and their aftermaths.",
    stated_argument: str = "Escalation and settlement follow a recurring sequence.",
    toc: Any,
) -> str:
    """A raw JSON envelope-pass response with the given field values --
    every fake client below builds its canned responses from this, so each
    scenario's ONLY varying axis is exactly what it needs to prove (a valid
    vs. invalid `toc`, or a valid vs. degenerate thesis/scope/
    stated_argument), never an accidental difference."""
    return json.dumps(
        {
            "thesis": thesis,
            "scope": scope,
            "stated_argument": stated_argument,
            "toc": toc,
        }
    )


class _BoundedSequenceLLMClient:
    """A fake `LLMClient` that answers each successive call with the next
    raw response from a fixed list, and raises `AssertionError` from inside
    `complete()` itself -- never swallowed by `complete_json`'s own
    bounded-retry loop, since that loop only catches exceptions raised by
    `parse_model_json`/`validate`, not by `client.complete()` -- the moment
    it is asked for one more call than the scenario configured. This is what
    makes an unbounded/extra re-ask fail this test loudly and specifically,
    rather than silently returning a stale repeated answer."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        if self.call_count > len(self._responses):
            raise AssertionError(
                f"unexpected call #{self.call_count} to the fake LLM client "
                f"-- only {len(self._responses)} canned response(s) were "
                f"configured for this scenario, so this call means the toc "
                f"re-ask fired more times than the bounded 'at most one "
                f"re-ask' contract (issue #241, Direction 1) allows"
            )
        return self._responses[self.call_count - 1]


def _tree() -> dict:
    return json.loads(LLM_TOC_TREE_FIXTURE.read_text(encoding="utf-8"))


def _run(client: _BoundedSequenceLLMClient, tmp_path: Path) -> dict:
    """Invoke `run_envelope` with the fake client injected and a private
    `tmp_path` envelopes dir (mirrors `test_envelope_deterministic_nested_
    fallback_on_reconstruction_failure`'s own in-process seam), after
    pre-placing the shared tree fixture."""
    _place_tree_fixture(LLM_TOC_PDF, LLM_TOC_TREE_FIXTURE)
    envelopes_dir = tmp_path / "envelopes"
    return run_envelope(LLM_TOC_PDF, client=client, envelopes_dir=envelopes_dir)


# --- Scenario 1: the re-ask fires once and its valid answer wins ------------


def test_toc_reask_fires_once_and_second_response_wins(tmp_path):
    """First call: valid thesis/scope/stated_argument, INVALID toc (`[]`).
    Second call (the bounded re-ask): valid thesis/scope/stated_argument,
    VALID toc carrying a marker no fallback-derived toc could ever produce
    (the fallback's titles are drawn only from this tree's own detected
    headings, `_toc_from_tree`). Exactly two calls; the written envelope's
    `toc` must be the second call's answer, not the deterministic dump."""
    reask_toc = [
        {
            "title": "REASK-WON: The Onset of Contention",
            "children": ["a child no _toc_from_tree heading could ever produce"],
        }
    ]
    client = _BoundedSequenceLLMClient(
        [
            _envelope_response(toc=[]),
            _envelope_response(toc=reask_toc),
        ]
    )

    envelope = _run(client, tmp_path)

    assert client.call_count == 2, (
        f"expected exactly TWO model calls -- the original call (invalid "
        f"toc) plus one bounded re-ask (issue #241, Direction 1) -- got "
        f"{client.call_count}"
    )
    assert "toc" in envelope, (
        f"expected the written envelope to carry a `toc` field, got keys: {sorted(envelope.keys())}"
    )
    _assert_valid_nested_toc(envelope["toc"])
    assert envelope["toc"] == reask_toc, (
        f"expected the written envelope's `toc` to be exactly the bounded "
        f"re-ask's own valid answer (issue #241: the re-ask, when it "
        f"succeeds, wins over the deterministic raw-heading dump), got "
        f"{envelope['toc']!r} instead of {reask_toc!r}"
    )

    tree = _tree()
    deterministic_fallback = envelope_module._fallback_toc(
        tree, LLM_TOC_PDF, json.loads(_envelope_response(toc=[]))
    )
    assert envelope["toc"] != deterministic_fallback, (
        f"expected the written envelope's `toc` to differ from "
        f"`_fallback_toc`'s deterministic raw-heading dump "
        f"({deterministic_fallback!r}) -- if they match, the re-ask's own "
        f"valid answer was silently discarded in favor of the fallback, "
        f"even though a valid re-ask response was available"
    )


# --- Scenario 2: the re-ask is bounded to exactly one, and the fallback is
# still guaranteed when both calls stay invalid ------------------------------


def test_toc_reask_bounded_and_fallback_guaranteed_when_both_invalid(tmp_path):
    """Both the original call and the one bounded re-ask return an INVALID
    toc (`[]`). A third model call must never happen (the fake client raises
    if asked for one). The written envelope's `toc` must equal
    `_fallback_toc`'s deterministic result, be non-empty, and pass
    `validate_envelope_fields` -- the non-empty guarantee (PRD §7.3) must
    survive introducing the re-ask."""
    client = _BoundedSequenceLLMClient(
        [
            _envelope_response(toc=[]),
            _envelope_response(toc=[]),
        ]
    )

    envelope = _run(client, tmp_path)

    assert client.call_count == 2, (
        f"expected exactly TWO model calls total when both the original "
        f"call and the one bounded re-ask return an invalid toc -- a third "
        f"call would mean the re-ask is not bounded to 'at most one' (issue "
        f"#241, Direction 1), got {client.call_count}"
    )

    assert "toc" in envelope, (
        f"expected the written envelope to carry a `toc` field, got keys: {sorted(envelope.keys())}"
    )
    _assert_valid_nested_toc(envelope["toc"])

    tree = _tree()
    parsed = json.loads(_envelope_response(toc=[]))
    expected_fallback = envelope_module._fallback_toc(tree, LLM_TOC_PDF, parsed)
    assert envelope["toc"] == expected_fallback, (
        f"expected the written envelope's `toc` to equal `_fallback_toc`'s "
        f"own deterministic result (PRD §7.3: 'falls back deterministically "
        f"to the tree's own detected heading list ..., preserving the "
        f"non-empty guarantee') when both the original call and the bounded "
        f"re-ask fail validation, got {envelope['toc']!r} instead of "
        f"{expected_fallback!r}"
    )

    envelope_module.validate_envelope_fields(envelope)


# --- Scenario 3: the happy path pays no re-ask cost --------------------------


def test_toc_reask_never_fires_when_first_response_already_valid(tmp_path):
    """A first call whose toc already validates must never trigger a second
    call -- the re-ask must not add cost to the 29/30 sources DEC-28 names
    as already stable."""
    happy_toc = [{"title": "Introduction", "children": []}]
    client = _BoundedSequenceLLMClient([_envelope_response(toc=happy_toc)])

    envelope = _run(client, tmp_path)

    assert client.call_count == 1, (
        f"expected exactly ONE model call when the first response's toc "
        f"already validates -- a second call here would mean the re-ask "
        f"fires even on the happy path, adding cost to every stable source "
        f"(issue #241), got {client.call_count}"
    )
    assert envelope["toc"] == happy_toc, (
        f"expected the written envelope's `toc` to be exactly the first "
        f"(and only) call's own valid answer, got {envelope['toc']!r}"
    )


# --- Scenario 4: the toc re-ask sits on a budget separate from
# `complete_json`'s own thesis-degeneracy re-ask (#80) ------------------------


def test_toc_reask_budget_is_separate_from_thesis_degeneracy_budget(tmp_path):
    """`complete_json`'s own bounded re-ask (default `attempts=3`,
    `reject_degenerate_thesis_fields`, #80) is entirely consumed bringing
    thesis/scope/stated_argument from degenerate to valid: calls 1 and 2
    both answer with a degenerate (empty-string) `stated_argument`, and only
    call 3 -- the LAST of that budget's three attempts -- finally answers
    with valid thesis/scope/stated_argument. That same call 3 carries an
    INVALID toc. If the toc re-ask shared `complete_json`'s budget, there
    would be no attempts left for it; instead, a 4th call must still fire as
    the toc re-ask, entirely BEYOND that already-exhausted budget -- proving
    the two mechanisms are separate and non-interacting. Call 4 answers with
    a valid toc, so it wins; the final envelope's thesis/scope/
    stated_argument must still come from call 3 (the response that actually
    satisfied #80's own degeneracy check), not silently be swapped out by
    whatever call 4 (a response never routed through
    `reject_degenerate_thesis_fields` at all) happens to carry -- pinning
    that thesis-field degeneracy handling (#80) is otherwise unchanged."""
    call_3_thesis = "Escalation is driven by shifting elite alignments."
    call_4_thesis = "A DIFFERENT thesis the toc re-ask response must NOT win with."

    client = _BoundedSequenceLLMClient(
        [
            _envelope_response(stated_argument="", toc=[]),  # 1: degenerate thesis field
            _envelope_response(stated_argument="", toc=[]),  # 2: degenerate thesis field
            _envelope_response(thesis=call_3_thesis, toc=[]),  # 3: valid thesis, invalid toc
            _envelope_response(
                thesis=call_4_thesis,
                toc=[{"title": "REASK Chapter", "children": []}],
            ),  # 4: the separate toc re-ask
        ]
    )

    envelope = _run(client, tmp_path)

    assert client.call_count == 4, (
        f"expected exactly FOUR model calls: complete_json's own bounded "
        f"re-ask budget (#80) fully consumed by two degenerate-thesis "
        f"responses plus the third, finally-valid one, THEN one more, "
        f"separate toc re-ask beyond that exhausted budget -- got "
        f"{client.call_count}. A count of 3 would mean the toc re-ask never "
        f"fired at all once #80's own budget was spent; a count over 4 "
        f"would mean the toc re-ask itself is unbounded."
    )

    assert envelope["thesis"] == call_3_thesis, (
        f"expected the written envelope's `thesis` to come from call 3 -- "
        f"the response that actually satisfied `reject_degenerate_thesis_"
        f"fields`'s own degeneracy check (#80) -- not from call 4 (the "
        f"separate toc re-ask, whose own thesis/scope/stated_argument were "
        f"never validated by #80's mechanism at all), got "
        f"{envelope['thesis']!r}"
    )
    assert envelope["thesis"] != call_4_thesis, (
        "expected the toc re-ask's own thesis answer to NOT silently "
        "override the already-validated thesis from call 3 -- the toc "
        "re-ask's budget/effect must stay confined to `toc` alone (issue "
        "#241's 'separate budget' contract)"
    )

    assert envelope["toc"] == [{"title": "REASK Chapter", "children": []}], (
        f"expected the written envelope's `toc` to be call 4's own valid "
        f"answer, got {envelope['toc']!r}"
    )
