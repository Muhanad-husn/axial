"""Inner unit tests for the axial envelope module (issue #16 slice 04 --
structural envelope)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.llm import ExplodingLLMClient, StubLLMClient


def _tree_with_sections(*, include_body=True) -> dict:
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": (
                    [
                        {
                            "type": "prose",
                            "order": "1.1",
                            "text": "This paper argues X.",
                        }
                    ]
                    if include_body
                    else []
                ),
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Comparative Cases",
                "children": [
                    {"type": "prose", "order": "2.1", "text": "Body material, not envelope input."}
                ],
            },
            {
                "type": "prose",
                "order": "3",
                "text": "Conclusion",
                "children": [{"type": "prose", "order": "3.1", "text": "In sum, X is true."}],
            },
        ]
    }


# --- source_id -------------------------------------------------------------


def test_compute_source_id_is_deterministic_for_the_same_content(tmp_path):
    from axial.envelope import compute_source_id

    path = tmp_path / "paper.pdf"
    path.write_bytes(b"same bytes")

    assert compute_source_id(path) == compute_source_id(path)


def test_compute_source_id_differs_for_different_content(tmp_path):
    from axial.envelope import compute_source_id

    path_a = tmp_path / "paper.pdf"
    path_a.write_bytes(b"content a")
    path_b = tmp_path / "paper.pdf"  # same name, different dir/content below

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    path_b = other_dir / "paper.pdf"
    path_b.write_bytes(b"content b")

    assert compute_source_id(path_a) != compute_source_id(path_b)


def test_compute_source_id_missing_file_raises_missing_source_error(tmp_path):
    from axial.envelope import MissingSourceError, compute_source_id

    missing = tmp_path / "does_not_exist.pdf"

    with pytest.raises(MissingSourceError) as exc_info:
        compute_source_id(missing)

    assert missing.name in str(exc_info.value)


# --- node selection / prompt composition ------------------------------------


def test_select_envelope_nodes_picks_only_intro_abstract_conclusion():
    from axial.envelope import select_envelope_nodes

    tree = _tree_with_sections()

    selected = select_envelope_nodes(tree)

    headings = [node["text"] for node in selected]
    assert headings == ["Introduction", "Conclusion"]
    assert "Comparative Cases" not in headings


def test_select_envelope_nodes_matches_case_insensitively():
    from axial.envelope import select_envelope_nodes

    tree = {
        "children": [
            {"type": "prose", "order": "1", "text": "INTRODUCTION", "children": []},
            {"type": "prose", "order": "2", "text": "abstract", "children": []},
        ]
    }

    selected = select_envelope_nodes(tree)

    assert len(selected) == 2


def test_compose_prompt_excludes_body_section_text():
    from axial.envelope import compose_prompt

    tree = _tree_with_sections()

    prompt = compose_prompt(tree)

    assert "This paper argues X." in prompt
    assert "In sum, X is true." in prompt
    assert "Body material, not envelope input." not in prompt


# --- response parsing / validation ------------------------------------------


def test_parse_response_rejects_invalid_json():
    from axial.envelope import EnvelopeParseError, parse_response

    with pytest.raises(EnvelopeParseError):
        parse_response("not json at all")


def test_parse_response_accepts_a_markdown_fenced_response():
    """issue #72: deepseek-v4-flash sometimes wraps its JSON answer in a
    markdown fence despite the prompt's "no fences" instruction."""
    from axial.envelope import parse_response

    raw = f"```json\n{json.dumps({'thesis': 'This paper argues X.'})}\n```"

    assert parse_response(raw) == {"thesis": "This paper argues X."}


def test_parse_response_rejects_prose_with_a_snippet_in_the_message():
    """issue #72: parse errors must quote the raw response so failures are
    diagnosable from worker logs."""
    from axial.envelope import EnvelopeParseError, parse_response

    raw = "I cannot summarize this paper."

    with pytest.raises(EnvelopeParseError) as exc_info:
        parse_response(raw)

    assert raw in str(exc_info.value)


def test_parse_response_rejects_a_non_object_json_value():
    from axial.envelope import EnvelopeParseError, parse_response

    with pytest.raises(EnvelopeParseError):
        parse_response("[1, 2, 3]")


def test_validate_envelope_fields_accepts_a_well_formed_response():
    from axial.envelope import validate_envelope_fields

    validate_envelope_fields(
        {
            "thesis": "X",
            "toc": ["Introduction", "Conclusion"],
            "scope": "Y",
            "stated_argument": "Z",
        }
    )  # must not raise


@pytest.mark.parametrize(
    "field,value",
    [
        ("thesis", ""),
        ("thesis", None),
        ("scope", ""),
        ("stated_argument", ""),
    ],
)
def test_validate_envelope_fields_rejects_empty_required_strings(field, value):
    from axial.envelope import EnvelopeValidationError, validate_envelope_fields

    data = {
        "thesis": "X",
        "toc": ["A"],
        "scope": "Y",
        "stated_argument": "Z",
    }
    data[field] = value

    with pytest.raises(EnvelopeValidationError):
        validate_envelope_fields(data)


def test_validate_envelope_fields_rejects_empty_toc():
    from axial.envelope import EnvelopeValidationError, validate_envelope_fields

    data = {"thesis": "X", "toc": [], "scope": "Y", "stated_argument": "Z"}

    with pytest.raises(EnvelopeValidationError):
        validate_envelope_fields(data)


def test_validate_envelope_fields_rejects_non_list_toc():
    from axial.envelope import EnvelopeValidationError, validate_envelope_fields

    data = {"thesis": "X", "toc": "not a list", "scope": "Y", "stated_argument": "Z"}

    with pytest.raises(EnvelopeValidationError):
        validate_envelope_fields(data)


# --- envelope assembly / write-once -----------------------------------------


def test_build_envelope_carries_the_locked_shape(tmp_path):
    from axial.envelope import build_envelope

    path = tmp_path / "my_paper.pdf"
    parsed = {
        "thesis": "X",
        "toc": ["Introduction"],
        "scope": "Y",
        "stated_argument": "Z",
    }

    envelope = build_envelope(path, "source-123", parsed)

    assert envelope["source_id"] == "source-123"
    assert envelope["thesis"] == "X"
    assert envelope["toc"] == ["Introduction"]
    assert envelope["scope"] == "Y"
    assert envelope["stated_argument"] == "Z"
    assert envelope["title"] == "My Paper"
    assert envelope["author"] is None
    assert envelope["date"] is None


def test_write_envelope_creates_parent_directories(tmp_path):
    from axial.envelope import write_envelope

    out_path = tmp_path / "nested" / "dir" / "source-123.json"

    write_envelope({"source_id": "source-123"}, out_path)

    assert out_path.exists()
    assert json.loads(out_path.read_text(encoding="utf-8")) == {"source_id": "source-123"}


# --- run_envelope: cache-first, no-recompute --------------------------------


def test_run_envelope_missing_file_raises_missing_source_error(tmp_path):
    from axial.envelope import MissingSourceError, run_envelope

    missing = tmp_path / "does_not_exist.pdf"

    with pytest.raises(MissingSourceError) as exc_info:
        run_envelope(missing, envelopes_dir=tmp_path / "envelopes")

    assert missing.name in str(exc_info.value)


def test_run_envelope_second_run_short_circuits_with_zero_client_calls(monkeypatch, tmp_path):
    """A cache hit must return the stored envelope without constructing or
    calling an LLM client at all (PRD §10, 'no recompute')."""
    import axial.envelope as envelope_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"

    fake_tree = _tree_with_sections()
    monkeypatch.setattr(envelope_mod, "extract", lambda path: fake_tree)

    stub_client = StubLLMClient()
    first = envelope_mod.run_envelope(source, client=stub_client, envelopes_dir=envelopes_dir)
    assert stub_client.call_count == 1
    assert first["thesis"]

    def _fail_if_constructed():
        raise AssertionError("get_client() must not be called on a cache hit")

    monkeypatch.setattr(envelope_mod, "get_client", _fail_if_constructed)

    poison_client = ExplodingLLMClient()
    second = envelope_mod.run_envelope(source, client=poison_client, envelopes_dir=envelopes_dir)

    assert second == first


def test_run_envelope_wraps_extraction_failures(monkeypatch, tmp_path):
    import axial.envelope as envelope_mod
    from axial.extract import ConversionError

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    def _boom(path):
        raise ConversionError(Path(path), "simulated failure")

    monkeypatch.setattr(envelope_mod, "extract", _boom)

    with pytest.raises(envelope_mod.ExtractionFailedError):
        envelope_mod.run_envelope(
            source, client=StubLLMClient(), envelopes_dir=tmp_path / "envelopes"
        )


def test_run_envelope_wraps_llm_client_selection_errors(monkeypatch, tmp_path):
    """A missing API key / unknown provider (`LLMConfigError`, raised by
    `get_client()`) must surface as a typed `EnvelopeError`, not a bare
    `ValueError`/traceback -- so the CLI's `except EnvelopeError` handler in
    `cli.py` renders a clean `error: ...` for a real-provider misconfiguration
    instead of crashing (see llm.py's LLMError hierarchy)."""
    import axial.envelope as envelope_mod
    from axial.llm import LLMConfigError

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(envelope_mod, "extract", lambda path: _tree_with_sections())

    def _boom(*args, **kwargs):
        raise LLMConfigError("unknown LLM provider: 'bogus'")

    monkeypatch.setattr(envelope_mod, "get_client", _boom)

    with pytest.raises(envelope_mod.LLMFailedError) as exc_info:
        envelope_mod.run_envelope(source, client=None, envelopes_dir=tmp_path / "envelopes")

    assert isinstance(exc_info.value, envelope_mod.EnvelopeError)


def test_run_envelope_honors_the_configured_envelopes_dir_when_not_passed_explicitly(
    monkeypatch, tmp_path
):
    """`paths.envelopes_dir` in `config/pipeline.yaml` must actually be read
    and honored as the default output directory when `run_envelope` is
    called without an explicit `envelopes_dir` -- the config key is not
    dead. Mirrors how `get_client()` reads a `config_path`-relative file."""
    import axial.envelope as envelope_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    configured_dir = tmp_path / "configured-envelopes"
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        f"paths:\n  envelopes_dir: {configured_dir.as_posix()}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(envelope_mod, "extract", lambda path: _tree_with_sections())

    envelope_mod.run_envelope(source, client=StubLLMClient(), config_path=config_path)

    written = list(configured_dir.glob("*.json"))
    assert len(written) == 1, (
        f"expected the envelope to be written under the configured "
        f"envelopes_dir {configured_dir}, found: {written}"
    )


def test_run_envelope_writes_a_file_that_round_trips_the_locked_fields(monkeypatch, tmp_path):
    import axial.envelope as envelope_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"

    monkeypatch.setattr(envelope_mod, "extract", lambda path: _tree_with_sections())

    envelope = envelope_mod.run_envelope(
        source, client=StubLLMClient(), envelopes_dir=envelopes_dir
    )

    written = list(envelopes_dir.glob("*.json"))
    assert len(written) == 1
    on_disk = json.loads(written[0].read_text(encoding="utf-8"))
    assert on_disk == envelope
    for field in (
        "source_id",
        "author",
        "title",
        "date",
        "thesis",
        "toc",
        "scope",
        "stated_argument",
    ):
        assert field in on_disk
