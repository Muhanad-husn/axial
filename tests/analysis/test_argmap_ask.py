"""Acceptance tests for issue #572, PR 3 of 4: the door and the landing
(`axial.argmap.ask`) -- turning a brief into the arguments it is about, and
landing those arguments on the position map PR 1 built.

This is a port of a scratchpad run already measured over the real corpus
(`stage3_brief_on_map.py`'s `DECOMPOSE_PROMPT` and its landing step); these
tests pin the behavioral contract the port must preserve, not a new design.
Fixtures and a fake client/encoder throughout -- no real model call, no
dependence on `data/` (a worktree has none).

Covered here:

  - the door prompt carries the brief's own case/request and the "name no
    authors and no books" rule verbatim, and never leaks `lens`;
  - a door response that isn't usable JSON, is shaped as something other
    than the expected object, or names no usable arguments all fail loudly
    (`DecomposeError`), never landing on an empty set silently;
  - the landing keeps the top 4 positions per argument, keeps a position
    reached by more than one argument once at its best score, and orders the
    result by that score, descending;
  - landing against a map recorded under a different encoder is refused
    (`EncoderMismatchError`), not silently computed;
  - a missing or empty map gives `MapNotBuiltError`, and the CLI wrapper
    turns any `AskError` into a clear stderr message and a non-zero exit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from axial.argmap import ask as ask_module
from axial.argmap.ask import (
    DECOMPOSE_PROMPT,
    DecomposeError,
    EncoderMismatchError,
    MapNotBuiltError,
    decompose_brief,
    land_arguments,
    render_decompose_prompt,
    run_map_ask,
)
from axial.brief.intake import Brief, load_brief

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _write_brief(tmp_path: Path, *, case: str, request: str) -> Path:
    path = tmp_path / "brief.yaml"
    path.write_text(f"case: {case!r}\nrequest: {request!r}\n", encoding="utf-8")
    return path


def _position(
    position_id: str,
    argument: str,
    *,
    size: int = 1,
    sources: list[str] | None = None,
    authors: list[str] | None = None,
    chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "position_id": position_id,
        "argument": argument,
        "size": size,
        "sources": sources or [f"{position_id}-book"],
        "authors": authors or [f"{position_id}-author"],
        "chunk_ids": chunk_ids or [f"{position_id}-c1"],
    }


def _write_map(
    tmp_path: Path, pin: str, positions: list[dict[str, Any]], *, encoder: str = "fake-encoder"
) -> Path:
    outdir = tmp_path / "map" / pin
    outdir.mkdir(parents=True)
    with (outdir / "positions.jsonl").open("w", encoding="utf-8") as handle:
        for position in positions:
            handle.write(json.dumps(position) + "\n")
    (outdir / "map.json").write_text(json.dumps({"encoder": encoder}), encoding="utf-8")
    return tmp_path / "map"


class _ScriptedClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.call_count = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        return self._response

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "scripted"

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return None


# ---------------------------------------------------------------------------
# render_decompose_prompt: carries the brief's own case/request, never lens,
# and keeps the "name no authors and no books" rule intact
# ---------------------------------------------------------------------------


def test_door_prompt_carries_case_and_request_names_no_author_no_book() -> None:
    brief = Brief(
        brief_id="deadbeef",
        case="Kalyvas's theory of selective violence vs. Elcheroth's account of identity mobilisation",
        request="Which account better explains paramilitary violence in the Syrian civil war?",
        lens="political-economy",
    )

    rendered = render_decompose_prompt(brief)

    assert "CASE: Kalyvas's theory of selective violence vs. Elcheroth's account" in rendered
    assert "QUESTION: Which account better explains paramilitary violence" in rendered
    assert "Name no authors and no books." in rendered
    assert "political-economy" not in rendered  # the door never sees the lens


# ---------------------------------------------------------------------------
# decompose_brief: an unusable door response fails loudly, never lands on
# nothing silently
# ---------------------------------------------------------------------------


def _brief(tmp_path: Path) -> Any:
    return load_brief(_write_brief(tmp_path, case="A case.", request="A question?"))


def test_decompose_raises_on_unparseable_json(tmp_path: Path) -> None:
    brief = _brief(tmp_path)
    client = _ScriptedClient("not json at all")

    with pytest.raises(DecomposeError):
        decompose_brief(brief, client)


def test_decompose_raises_when_response_is_not_the_expected_object(tmp_path: Path) -> None:
    brief = _brief(tmp_path)
    # Valid JSON, but shaped as a bare list -- `.get("arguments")` itself
    # fails, same fault class `extract_positions_for_slice` guards against.
    client = _ScriptedClient(json.dumps(["not", "an", "object"]))

    with pytest.raises(DecomposeError):
        decompose_brief(brief, client)


def test_decompose_raises_when_no_usable_arguments_are_named(tmp_path: Path) -> None:
    brief = _brief(tmp_path)
    # Valid JSON, valid shape, but nothing usable inside: an empty list, a
    # blank string, and a non-string entry all count as "nothing stated".
    client = _ScriptedClient(json.dumps({"arguments": ["", "   ", 42]}))

    with pytest.raises(DecomposeError):
        decompose_brief(brief, client)


def test_decompose_returns_the_stated_arguments_stripped(tmp_path: Path) -> None:
    brief = _brief(tmp_path)
    client = _ScriptedClient(
        json.dumps({"arguments": ["  States extract resources through coercion.  ", "Claim two."]})
    )

    asks = decompose_brief(brief, client)

    assert asks == ["States extract resources through coercion.", "Claim two."]


# ---------------------------------------------------------------------------
# land_arguments: top 4 per argument, dedup at best score, ordered by score
# ---------------------------------------------------------------------------

_N_POSITIONS = 8

# Each position's argument text is its own lookup key; each ask's text is
# also a lookup key. Encoding a text returns an 8-dim vector whose i-th
# component is that (ask, position) pair's intended dot-product score --
# real cosine similarity isn't needed here, only that `land_arguments` reads
# `argument_vectors @ ask_vector` and treats the result as a score, so this
# is the simplest vector construction that lets a test dictate exact,
# independently-chosen scores for every (ask, position) pair.
_POSITION_ARGS = [f"argument {i}" for i in range(_N_POSITIONS)]
_ASK_1 = "ask one"
_ASK_2 = "ask two"

# Position i's own vector is the i-th standard basis vector, so
# `_ASK_1_VECTOR @ position_vectors[i] == _ASK_1_VECTOR[i]`.
_ASK_1_SCORES = [0.9, 0.8, 0.7, 0.6, 0.5, 0.95, -1.0, -1.0]
_ASK_2_SCORES = [0.1, 0.2, 0.85, 0.3, 0.99, 0.4, -1.0, -1.0]

_VECTORS = {text: np.eye(_N_POSITIONS)[i] for i, text in enumerate(_POSITION_ARGS)}
_VECTORS[_ASK_1] = np.array(_ASK_1_SCORES)
_VECTORS[_ASK_2] = np.array(_ASK_2_SCORES)


def _fake_encode(texts: list[str]) -> np.ndarray:
    return np.array([_VECTORS[text] for text in texts])


def _positions_fixture() -> list[dict[str, Any]]:
    return [_position(f"pos-{i:04d}", _POSITION_ARGS[i], size=i + 1) for i in range(_N_POSITIONS)]


def test_landing_keeps_top_4_per_ask_dedups_at_best_score_and_orders_by_score() -> None:
    positions = _positions_fixture()

    landed = land_arguments([_ASK_1, _ASK_2], positions, _fake_encode, top_k=4)

    # ask 1's own top 4 (by score): pos-0005 (.95), pos-0000 (.9), pos-0001
    # (.8), pos-0002 (.7) -- pos-0003/0004/0006/0007 are its bottom four,
    # dropped by the top-4 cap.
    # ask 2's own top 4: pos-0004 (.99), pos-0002 (.85), pos-0005 (.4),
    # pos-0003 (.3).
    # pos-0002 is reached by both (.7 from ask 1, .85 from ask 2) and must
    # survive once, at .85 -- the higher of the two. pos-0005 is reached by
    # both the other way (.95 from ask 1, .4 from ask 2) and must survive at
    # .95 -- proving the max-keep works in both directions, not just
    # "whichever ask is seen last".
    ids = [p.position_id for p in landed]
    assert ids == [
        "pos-0004",  # .99
        "pos-0005",  # .95
        "pos-0000",  # .9
        "pos-0002",  # .85
        "pos-0001",  # .8
        "pos-0003",  # .3
    ]
    assert "pos-0006" not in ids and "pos-0007" not in ids  # never in anyone's top 4

    by_id = {p.position_id: p for p in landed}
    assert by_id["pos-0002"].score == pytest.approx(0.85)
    assert by_id["pos-0005"].score == pytest.approx(0.95)
    assert by_id["pos-0004"].argument == "argument 4"
    assert by_id["pos-0004"].size == 5
    assert by_id["pos-0004"].authors == ("pos-0004-author",)
    assert by_id["pos-0004"].chunk_ids == ("pos-0004-c1",)

    # strictly descending
    scores = [p.score for p in landed]
    assert scores == sorted(scores, reverse=True)


def test_landing_with_no_asks_or_no_positions_lands_on_nothing() -> None:
    assert land_arguments([], _positions_fixture(), _fake_encode) == []
    assert land_arguments([_ASK_1], [], _fake_encode) == []


# ---------------------------------------------------------------------------
# run_map_ask: encoder mismatch is refused, a missing/empty map is refused
# ---------------------------------------------------------------------------


def test_run_map_ask_refuses_a_map_built_by_a_different_encoder(tmp_path: Path) -> None:
    brief_path = _write_brief(tmp_path, case="A case.", request="A question?")
    map_dir = _write_map(
        tmp_path, "testpin", [_position("pos-0001", "Some argument.")], encoder="other-model"
    )
    client = _ScriptedClient(json.dumps({"arguments": ["should never be reached"]}))

    with pytest.raises(EncoderMismatchError):
        run_map_ask(
            brief_path,
            map_dir=map_dir,
            pin="testpin",
            client=client,
            encode=_fake_encode,
            encoder_model="the-real-encoder",
        )

    # The door call is paid; a refused encoder must short-circuit before it.
    assert client.call_count == 0


def test_run_map_ask_succeeds_when_the_encoder_matches(tmp_path: Path) -> None:
    brief_path = _write_brief(tmp_path, case="A case.", request="A question?")
    map_dir = _write_map(
        tmp_path,
        "testpin",
        [_position("pos-0001", _ASK_1)],
        encoder="the-real-encoder",
    )
    client = _ScriptedClient(json.dumps({"arguments": [_ASK_1]}))

    result = run_map_ask(
        brief_path,
        map_dir=map_dir,
        pin="testpin",
        client=client,
        encode=_fake_encode,
        encoder_model="the-real-encoder",
    )

    assert client.call_count == 1
    assert result.asks == (_ASK_1,)
    assert len(result.landed) == 1
    assert result.landed[0].position_id == "pos-0001"


# ---------------------------------------------------------------------------
# run_map_ask: the resolved pin is carried on the result (issue #583) --
# an analysis record built from it must be able to say which map answered
# the brief, whether the caller pinned the map explicitly or the corpus
# default was resolved for it.
# ---------------------------------------------------------------------------


def test_run_map_ask_carries_the_pin_it_was_given_explicitly(tmp_path: Path) -> None:
    brief_path = _write_brief(tmp_path, case="A case.", request="A question?")
    map_dir = _write_map(
        tmp_path,
        "testpin",
        [_position("pos-0001", _ASK_1)],
        encoder="the-real-encoder",
    )
    client = _ScriptedClient(json.dumps({"arguments": [_ASK_1]}))

    result = run_map_ask(
        brief_path,
        map_dir=map_dir,
        pin="testpin",
        client=client,
        encode=_fake_encode,
        encoder_model="the-real-encoder",
    )

    assert result.pin == "testpin"
    assert (map_dir / result.pin).is_dir()


def test_run_map_ask_carries_the_corpus_resolved_default_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    brief_path = _write_brief(tmp_path, case="A case.", request="A question?")
    map_dir = _write_map(
        tmp_path,
        "computed-pin-007",
        [_position("pos-0001", _ASK_1)],
        encoder="the-real-encoder",
    )
    monkeypatch.setattr(ask_module, "compute_corpus_pin", lambda *_a, **_k: "computed-pin-007")
    client = _ScriptedClient(json.dumps({"arguments": [_ASK_1]}))

    result = run_map_ask(
        brief_path,
        map_dir=map_dir,
        client=client,
        encode=_fake_encode,
        encoder_model="the-real-encoder",
    )

    assert result.pin == "computed-pin-007"
    assert (map_dir / result.pin).is_dir()


def test_run_map_ask_raises_on_a_missing_pin_directory(tmp_path: Path) -> None:
    brief_path = _write_brief(tmp_path, case="A case.", request="A question?")

    with pytest.raises(MapNotBuiltError):
        run_map_ask(
            brief_path,
            map_dir=tmp_path / "map",
            pin="never-built",
            client=_ScriptedClient("{}"),
            encode=_fake_encode,
        )


def test_run_map_ask_raises_on_an_empty_positions_file(tmp_path: Path) -> None:
    brief_path = _write_brief(tmp_path, case="A case.", request="A question?")
    outdir = tmp_path / "map" / "testpin"
    outdir.mkdir(parents=True)
    (outdir / "positions.jsonl").write_text("", encoding="utf-8")
    (outdir / "map.json").write_text(json.dumps({"encoder": "any"}), encoding="utf-8")

    with pytest.raises(MapNotBuiltError):
        run_map_ask(
            brief_path,
            map_dir=tmp_path / "map",
            pin="testpin",
            client=_ScriptedClient("{}"),
            encode=_fake_encode,
        )


# ---------------------------------------------------------------------------
# CLI wrapper: any AskError becomes a clear stderr message and exit 1
# ---------------------------------------------------------------------------


def test_cli_map_ask_reports_a_clear_error_and_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from axial import cli

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise MapNotBuiltError(tmp_path / "map" / "nope")

    monkeypatch.setattr(cli, "run_map_ask", _raise)

    exit_code = cli._map_ask(str(tmp_path / "brief.yaml"))

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "error" in captured.err.lower()
    assert "no argument map built" in captured.err


def test_cli_map_ask_prints_the_arguments_and_the_landed_positions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from axial import cli
    from axial.argmap.ask import AskResult, LandedPosition
    from axial.brief.intake import Brief

    fake_result = AskResult(
        brief=Brief(brief_id="abc123", case="A case.", request="A question?", lens=None),
        asks=("States extract resources through coercion.",),
        landed=(
            LandedPosition(
                position_id="pos-0001",
                score=0.87,
                argument="States extract resources through coercion.",
                size=12,
                sources=("alpha-2020-book",),
                authors=("alpha",),
                chunk_ids=("c1",),
            ),
        ),
    )
    monkeypatch.setattr(cli, "run_map_ask", lambda *_a, **_k: fake_result)

    exit_code = cli._map_ask("some-brief.yaml")

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "abc123" in out
    assert "States extract resources through coercion." in out
    assert "0.87" in out
    assert "alpha" in out
    assert "12" in out


# Sanity: DECOMPOSE_PROMPT itself must still contain the load-bearing rule
# text this port exists to preserve verbatim (issue #572 kickoff).
def test_decompose_prompt_constant_carries_the_load_bearing_rules() -> None:
    assert "Name no authors and no books." in DECOMPOSE_PROMPT
    assert "Six to ten arguments." in DECOMPOSE_PROMPT
    assert "{case}" in DECOMPOSE_PROMPT
    assert "{request}" in DECOMPOSE_PROMPT
