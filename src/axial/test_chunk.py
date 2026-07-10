"""Inner unit tests for the axial chunk module (issue #17 slice 05 --
argumentative chunking)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.llm import CHUNK_PASS_NAME, StubLLMClient


def _tree_with_sections(*, middle_body: bool = True) -> dict:
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": [{"type": "prose", "order": "1.1", "text": "Intro body sentence."}],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Comparative Cases",
                "children": (
                    [{"type": "prose", "order": "2.1", "text": "Middle body sentence."}]
                    if middle_body
                    else []
                ),
            },
            {
                "type": "prose",
                "order": "3",
                "text": "Conclusion",
                "children": [
                    {"type": "prose", "order": "3.1", "text": "Conclusion body sentence."}
                ],
            },
        ]
    }


_ENVELOPE = {
    "source_id": "paper-abc123",
    "thesis": "Envelope thesis text.",
    "scope": "Envelope scope text.",
    "stated_argument": "Envelope stated_argument text.",
}


# --- context assembly -------------------------------------------------------


def test_compose_chunk_prompt_contains_target_envelope_and_both_neighbours():
    from axial.chunk import compose_chunk_prompt

    tree = _tree_with_sections()
    intro, middle, conclusion = tree["children"]

    prompt = compose_chunk_prompt(middle, intro, conclusion, _ENVELOPE)

    assert "Middle body sentence." in prompt
    assert "Intro body sentence." in prompt
    assert "Conclusion body sentence." in prompt
    assert _ENVELOPE["stated_argument"] in prompt


def test_compose_chunk_prompt_never_leaks_the_internal_pass_dispatch_marker():
    """The chunk prompt is what a real model (OpenRouter) sees verbatim, so
    it must never carry an internal test-dispatch marker -- pass identity is
    threaded out-of-band via `pass_name` on `.complete()`, not embedded in
    prompt text."""
    from axial.chunk import compose_chunk_prompt

    tree = _tree_with_sections()
    intro, middle, conclusion = tree["children"]

    prompt = compose_chunk_prompt(middle, intro, conclusion, _ENVELOPE)

    assert "AXIAL_CHUNK_PASS_V1" not in prompt


def test_compose_chunk_prompt_with_no_neighbours_still_contains_target_and_envelope():
    from axial.chunk import compose_chunk_prompt

    tree = _tree_with_sections()
    intro = tree["children"][0]

    prompt = compose_chunk_prompt(intro, None, None, _ENVELOPE)

    assert "Intro body sentence." in prompt
    assert _ENVELOPE["stated_argument"] in prompt


def test_section_nodes_selects_only_top_level_headed_sections():
    from axial.chunk import _section_nodes

    tree = _tree_with_sections()

    sections = _section_nodes(tree)

    assert [s["text"] for s in sections] == ["Introduction", "Comparative Cases", "Conclusion"]


# --- response parsing --------------------------------------------------------


def test_parse_response_accepts_an_object_with_a_chunks_array():
    from axial.chunk import parse_response

    raw = json.dumps({"chunks": [{"text": "a"}, {"text": "b"}]})

    chunks = parse_response(raw)

    assert chunks == [{"text": "a"}, {"text": "b"}]


def test_parse_response_accepts_a_bare_array():
    from axial.chunk import parse_response

    raw = json.dumps([{"text": "a"}])

    chunks = parse_response(raw)

    assert chunks == [{"text": "a"}]


def test_parse_response_rejects_invalid_json():
    from axial.chunk import ChunkParseError, parse_response

    with pytest.raises(ChunkParseError):
        parse_response("not json at all")


def test_parse_response_accepts_a_markdown_fenced_response():
    """issue #72: deepseek-v4-flash sometimes wraps its JSON answer in a
    markdown fence despite the prompt's "no fences" instruction."""
    from axial.chunk import parse_response

    raw = f"```json\n{json.dumps({'chunks': [{'text': 'a'}]})}\n```"

    assert parse_response(raw) == [{"text": "a"}]


def test_parse_response_rejects_prose_with_a_snippet_in_the_message():
    """issue #72: parse errors must quote the raw response so failures are
    diagnosable from worker logs."""
    from axial.chunk import ChunkParseError, parse_response

    raw = "I cannot chunk this section."

    with pytest.raises(ChunkParseError) as exc_info:
        parse_response(raw)

    assert raw in str(exc_info.value)


def test_parse_response_rejects_missing_chunks_key():
    from axial.chunk import ChunkParseError, parse_response

    with pytest.raises(ChunkParseError):
        parse_response(json.dumps({"nope": []}))


def test_parse_response_rejects_a_chunk_without_text():
    from axial.chunk import ChunkParseError, parse_response

    with pytest.raises(ChunkParseError):
        parse_response(json.dumps({"chunks": [{"no_text": "a"}]}))


def test_parse_response_normalizes_bare_string_chunks_in_chunks_array():
    from axial.chunk import parse_response

    raw = json.dumps({"chunks": ["a", "b"]})

    chunks = parse_response(raw)

    assert chunks == [{"text": "a"}, {"text": "b"}]


def test_parse_response_normalizes_bare_string_chunks_in_bare_array():
    from axial.chunk import parse_response

    raw = json.dumps(["a", "b"])

    chunks = parse_response(raw)

    assert chunks == [{"text": "a"}, {"text": "b"}]


def test_parse_response_normalizes_mixed_string_and_object_chunks():
    from axial.chunk import parse_response

    raw = json.dumps({"chunks": [{"text": "a", "extra": "kept"}, "b"]})

    chunks = parse_response(raw)

    assert chunks == [{"text": "a", "extra": "kept"}, {"text": "b"}]


def test_parse_response_rejects_a_chunk_that_is_neither_string_nor_object():
    from axial.chunk import ChunkParseError, parse_response

    with pytest.raises(ChunkParseError):
        parse_response(json.dumps({"chunks": [42]}))


# --- chunk_id / section provenance -------------------------------------------


def test_build_chunk_records_have_stable_ids_and_section_provenance():
    from axial.chunk import build_chunk_records

    records = build_chunk_records(
        "paper-abc123", "2", "Comparative Cases", [{"text": "a"}, {"text": "b"}]
    )

    assert [r["chunk_id"] for r in records] == [
        "paper-abc123_2_comparative-cases_001",
        "paper-abc123_2_comparative-cases_002",
    ]
    assert all(r["section"] == "Comparative Cases" for r in records)


def test_build_chunk_records_is_deterministic_across_calls():
    from axial.chunk import build_chunk_records

    chunks = [{"text": "a"}, {"text": "b"}]
    first = build_chunk_records("paper-abc123", "3", "Conclusion", chunks)
    second = build_chunk_records("paper-abc123", "3", "Conclusion", chunks)

    assert [r["chunk_id"] for r in first] == [r["chunk_id"] for r in second]


def test_build_chunk_records_does_not_collide_across_sections_sharing_a_heading():
    """extract.py's tree-builder opens a fresh top-level section node per
    heading occurrence (unnested), so a real source can have two distinct
    sections both titled e.g. "Introduction" -- folding the section's own
    `order` into chunk_id must keep their chunk_ids from colliding even
    though the heading slug is identical (review finding: chunk_id
    collisions on duplicate section headings)."""
    from axial.chunk import build_chunk_records

    chunks = [{"text": "a"}]
    first_chapter = build_chunk_records("paper-abc123", "1", "Introduction", chunks)
    second_chapter = build_chunk_records("paper-abc123", "4", "Introduction", chunks)

    assert first_chapter[0]["chunk_id"] != second_chapter[0]["chunk_id"]
    assert first_chapter[0]["section"] == second_chapter[0]["section"] == "Introduction"


# --- run_chunk: envelope-required, no-recompute, neighbour context ----------


def test_run_chunk_missing_envelope_raises_clear_error(monkeypatch, tmp_path):
    import axial.chunk as chunk_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(chunk_mod, "extract", lambda path: _tree_with_sections())

    with pytest.raises(chunk_mod.MissingEnvelopeError) as exc_info:
        chunk_mod.run_chunk(source, client=StubLLMClient(), envelopes_dir=tmp_path / "envelopes")

    assert "envelope" in str(exc_info.value)


def test_run_chunk_missing_source_file_raises_missing_source_error(tmp_path):
    from axial.chunk import MissingSourceError, run_chunk

    missing = tmp_path / "does_not_exist.pdf"

    with pytest.raises(MissingSourceError):
        run_chunk(missing, client=StubLLMClient(), envelopes_dir=tmp_path / "envelopes")


def test_run_chunk_never_calls_llm_for_a_section_with_no_prose(monkeypatch, tmp_path):
    """A section with no chunkable prose yields zero chunks without error and
    without ever invoking the LLM client for that section."""
    import axial.chunk as chunk_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir()

    source_id = chunk_mod.compute_source_id(source)
    env_path = chunk_mod.envelope_path(source_id, envelopes_dir)
    env_path.write_text(json.dumps(_ENVELOPE), encoding="utf-8")

    empty_middle_tree = _tree_with_sections(middle_body=False)
    monkeypatch.setattr(chunk_mod, "extract", lambda path: empty_middle_tree)

    stub_client = StubLLMClient()
    records = chunk_mod.run_chunk(source, client=stub_client, envelopes_dir=envelopes_dir)

    sections_seen = {r["section"] for r in records}
    assert "Comparative Cases" not in sections_seen
    # Only Introduction and Conclusion have chunkable prose -> exactly 2 calls.
    assert stub_client.call_count == 2


def test_run_chunk_never_rewrites_the_stored_envelope(monkeypatch, tmp_path):
    import axial.chunk as chunk_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir()

    source_id = chunk_mod.compute_source_id(source)
    env_path = chunk_mod.envelope_path(source_id, envelopes_dir)
    env_path.write_text(json.dumps(_ENVELOPE), encoding="utf-8")
    before = env_path.read_bytes()

    monkeypatch.setattr(chunk_mod, "extract", lambda path: _tree_with_sections())

    chunk_mod.run_chunk(source, client=StubLLMClient(), envelopes_dir=envelopes_dir)

    assert env_path.read_bytes() == before


def test_run_chunk_produces_chunk_ids_stable_across_repeat_runs(monkeypatch, tmp_path):
    import axial.chunk as chunk_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir()

    source_id = chunk_mod.compute_source_id(source)
    env_path = chunk_mod.envelope_path(source_id, envelopes_dir)
    env_path.write_text(json.dumps(_ENVELOPE), encoding="utf-8")

    monkeypatch.setattr(chunk_mod, "extract", lambda path: _tree_with_sections())

    first = chunk_mod.run_chunk(source, client=StubLLMClient(), envelopes_dir=envelopes_dir)
    second = chunk_mod.run_chunk(source, client=StubLLMClient(), envelopes_dir=envelopes_dir)

    assert {r["chunk_id"] for r in first} == {r["chunk_id"] for r in second}


def test_run_chunk_calls_the_client_with_the_chunk_pass_name(monkeypatch, tmp_path):
    """The chunk pass must identify itself out-of-band via `pass_name`
    (never embedded in the prompt text) so stub/record dispatch correctly
    without leaking an internal marker into a real model's prompt."""
    import axial.chunk as chunk_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir()

    source_id = chunk_mod.compute_source_id(source)
    env_path = chunk_mod.envelope_path(source_id, envelopes_dir)
    env_path.write_text(json.dumps(_ENVELOPE), encoding="utf-8")

    monkeypatch.setattr(chunk_mod, "extract", lambda path: _tree_with_sections())

    calls = []

    class _CapturingClient:
        def complete(self, prompt, pass_name=None):
            calls.append(pass_name)
            return json.dumps({"chunks": [{"text": "a"}]})

    chunk_mod.run_chunk(source, client=_CapturingClient(), envelopes_dir=envelopes_dir)

    assert calls and all(name == CHUNK_PASS_NAME for name in calls)


def test_run_chunk_gives_distinct_chunk_ids_for_sections_sharing_a_heading(monkeypatch, tmp_path):
    import axial.chunk as chunk_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir()

    source_id = chunk_mod.compute_source_id(source)
    env_path = chunk_mod.envelope_path(source_id, envelopes_dir)
    env_path.write_text(json.dumps(_ENVELOPE), encoding="utf-8")

    duplicate_heading_tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": [{"type": "prose", "order": "1.1", "text": "Chapter one intro."}],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Introduction",
                "children": [{"type": "prose", "order": "2.1", "text": "Chapter two intro."}],
            },
        ]
    }
    monkeypatch.setattr(chunk_mod, "extract", lambda path: duplicate_heading_tree)

    records = chunk_mod.run_chunk(source, client=StubLLMClient(), envelopes_dir=envelopes_dir)

    chunk_ids = [r["chunk_id"] for r in records]
    assert len(chunk_ids) == len(set(chunk_ids)), (
        f"expected no chunk_id collisions across sections sharing a heading, got: {chunk_ids}"
    )
    assert all(r["section"] == "Introduction" for r in records)


def test_run_chunk_wraps_extraction_failures(monkeypatch, tmp_path):
    import axial.chunk as chunk_mod
    from axial.extract import ConversionError

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir()

    source_id = chunk_mod.compute_source_id(source)
    env_path = chunk_mod.envelope_path(source_id, envelopes_dir)
    env_path.write_text(json.dumps(_ENVELOPE), encoding="utf-8")

    def _boom(path):
        raise ConversionError(Path(path), "simulated failure")

    monkeypatch.setattr(chunk_mod, "extract", _boom)

    with pytest.raises(chunk_mod.ExtractionFailedError):
        chunk_mod.run_chunk(source, client=StubLLMClient(), envelopes_dir=envelopes_dir)


# --- run_chunk: bounded re-ask on complete-but-unparseable JSON (#76) ------


def _one_section_setup(tmp_path, chunk_mod):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir()

    source_id = chunk_mod.compute_source_id(source)
    env_path = chunk_mod.envelope_path(source_id, envelopes_dir)
    env_path.write_text(json.dumps(_ENVELOPE), encoding="utf-8")

    return source, envelopes_dir


def _single_section_tree() -> dict:
    """Exactly one prose section with chunkable body text, so a test can
    make deterministic assertions about the number of LLM calls (unlike
    `_tree_with_sections()`, which yields chunkable prose in all three
    sections by default)."""
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": [{"type": "prose", "order": "1.1", "text": "Intro body sentence."}],
            }
        ]
    }


def test_run_chunk_succeeds_when_first_completion_is_malformed_json(monkeypatch, tmp_path):
    import axial.chunk as chunk_mod

    source, envelopes_dir = _one_section_setup(tmp_path, chunk_mod)
    monkeypatch.setattr(chunk_mod, "extract", lambda path: _single_section_tree())

    valid = json.dumps({"chunks": [{"text": "a chunk"}]})

    class _ScriptedClient:
        def __init__(self):
            self._responses = ["{not json", valid]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    records = chunk_mod.run_chunk(source, client=client, envelopes_dir=envelopes_dir)

    assert records
    assert client.call_count == 2


def test_run_chunk_raises_chunk_parse_error_on_persistently_malformed_json(monkeypatch, tmp_path):
    import axial.chunk as chunk_mod

    source, envelopes_dir = _one_section_setup(tmp_path, chunk_mod)
    monkeypatch.setattr(chunk_mod, "extract", lambda path: _single_section_tree())

    class _AlwaysBrokenClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return "{not json"

    client = _AlwaysBrokenClient()

    with pytest.raises(chunk_mod.ChunkParseError):
        chunk_mod.run_chunk(source, client=client, envelopes_dir=envelopes_dir)

    assert client.call_count == 3
