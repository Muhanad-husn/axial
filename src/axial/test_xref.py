"""Inner unit tests for the axial xref module (issue #33 slice 01 --
cross-reference detection)."""

from __future__ import annotations

import json

import pytest

from axial.artifacts import ArtifactsError
from axial.chunk import ChunkError
from axial.llm import STUB_XREF_TARGET_ENV_VAR, XREF_PASS_NAME, StubLLMClient


# --- llm.py stub seam (mirroring test_llm.py's artifacts-pass coverage) -----


def test_stub_client_xref_response_defaults_to_no_references(monkeypatch):
    monkeypatch.delenv(STUB_XREF_TARGET_ENV_VAR, raising=False)
    client = StubLLMClient()

    raw = client.complete("prompt", pass_name=XREF_PASS_NAME)
    parsed = json.loads(raw)

    assert parsed["referenced_artifact_ids"] == []


def test_stub_client_honors_the_forced_xref_target_env_var(monkeypatch):
    monkeypatch.setenv(STUB_XREF_TARGET_ENV_VAR, "paper-abc123_art_1")
    client = StubLLMClient()

    raw = client.complete("prompt", pass_name=XREF_PASS_NAME)
    parsed = json.loads(raw)

    assert parsed["referenced_artifact_ids"] == ["paper-abc123_art_1"]


# --- prompt composition -----------------------------------------------------


def test_compose_xref_prompt_includes_chunk_text_and_known_artifact_ids():
    from axial.xref import compose_xref_prompt

    prompt = compose_xref_prompt("as Table 3 shows, state capacity varies.", ["paper_art_1"])

    assert "as Table 3 shows, state capacity varies." in prompt
    assert "paper_art_1" in prompt


def test_compose_xref_prompt_handles_no_known_artifacts():
    from axial.xref import compose_xref_prompt

    prompt = compose_xref_prompt("no tables mentioned here.", [])

    assert "no tables mentioned here." in prompt


# --- response parsing --------------------------------------------------------


def test_parse_referenced_artifact_ids_extracts_the_list():
    from axial.xref import parse_referenced_artifact_ids

    raw = json.dumps({"referenced_artifact_ids": ["paper_art_1"]})

    assert parse_referenced_artifact_ids(raw) == ["paper_art_1"]


def test_parse_referenced_artifact_ids_handles_empty_list():
    from axial.xref import parse_referenced_artifact_ids

    raw = json.dumps({"referenced_artifact_ids": []})

    assert parse_referenced_artifact_ids(raw) == []


def test_parse_referenced_artifact_ids_rejects_invalid_json():
    from axial.xref import XrefParseError, parse_referenced_artifact_ids

    with pytest.raises(XrefParseError):
        parse_referenced_artifact_ids("not json")


def test_parse_referenced_artifact_ids_rejects_missing_key():
    from axial.xref import XrefParseError, parse_referenced_artifact_ids

    with pytest.raises(XrefParseError):
        parse_referenced_artifact_ids(json.dumps({"unexpected": []}))


# --- membership filter / pair assembly --------------------------------------


def test_build_xref_pairs_keeps_only_known_artifact_ids():
    from axial.xref import build_xref_pairs

    pairs = build_xref_pairs(
        chunk_id="paper_1_intro_001",
        referenced_ids=["paper_art_1", "paper_art_999"],
        known_artifact_ids={"paper_art_1"},
    )

    assert pairs == [{"chunk_id": "paper_1_intro_001", "artifact_id": "paper_art_1"}]


def test_build_xref_pairs_produces_no_pair_for_a_dangling_reference():
    from axial.xref import build_xref_pairs

    pairs = build_xref_pairs(
        chunk_id="paper_1_intro_001",
        referenced_ids=["paper_art_999"],
        known_artifact_ids={"paper_art_1"},
    )

    assert pairs == []


def test_build_xref_pairs_returns_empty_for_no_references():
    from axial.xref import build_xref_pairs

    pairs = build_xref_pairs(
        chunk_id="paper_1_intro_001", referenced_ids=[], known_artifact_ids={"paper_art_1"}
    )

    assert pairs == []


# --- run_xref: end-to-end with monkeypatched run_chunk/run_artifacts -------


def _chunk_records():
    return [
        {"chunk_id": "paper_1_intro_001", "section": "Introduction", "text": "chunk one text"},
        {"chunk_id": "paper_2_discussion_001", "section": "Discussion", "text": "chunk two text"},
    ]


def _artifact_records():
    return [
        {"artifact_id": "paper_art_1", "artifact_role": "case-study", "section": "Introduction"}
    ]


class _TargetedClient:
    """Returns `target` as the sole referenced artifact id for every
    xref-pass call, mirroring the outer test's AXIAL_STUB_XREF_TARGET seam."""

    def __init__(self, target: str):
        self._target = target
        self.calls: list[str | None] = []

    def complete(self, prompt, pass_name=None):
        self.calls.append(pass_name)
        return json.dumps({"referenced_artifact_ids": [self._target]})


class _EmptyClient:
    def __init__(self):
        self.calls: list[str | None] = []

    def complete(self, prompt, pass_name=None):
        self.calls.append(pass_name)
        return json.dumps({"referenced_artifact_ids": []})


def test_run_xref_happy_path_pairs_every_chunk_with_the_real_artifact(monkeypatch, tmp_path):
    import axial.xref as xref_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(xref_mod, "run_chunk", lambda path, **kwargs: _chunk_records())
    monkeypatch.setattr(xref_mod, "run_artifacts", lambda path, **kwargs: _artifact_records())

    client = _TargetedClient("paper_art_1")
    pairs = xref_mod.run_xref(source, client=client)

    assert len(pairs) == 2
    assert {p["chunk_id"] for p in pairs} == {"paper_1_intro_001", "paper_2_discussion_001"}
    assert all(p["artifact_id"] == "paper_art_1" for p in pairs)
    assert client.calls == [XREF_PASS_NAME, XREF_PASS_NAME]


def test_run_xref_dangling_reference_yields_no_pairs(monkeypatch, tmp_path):
    import axial.xref as xref_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(xref_mod, "run_chunk", lambda path, **kwargs: _chunk_records())
    monkeypatch.setattr(xref_mod, "run_artifacts", lambda path, **kwargs: _artifact_records())

    client = _TargetedClient("paper_art_999")
    pairs = xref_mod.run_xref(source, client=client)

    assert pairs == []


def test_run_xref_empty_case_yields_no_pairs_without_error(monkeypatch, tmp_path):
    import axial.xref as xref_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(xref_mod, "run_chunk", lambda path, **kwargs: _chunk_records())
    monkeypatch.setattr(xref_mod, "run_artifacts", lambda path, **kwargs: _artifact_records())

    client = _EmptyClient()
    pairs = xref_mod.run_xref(source, client=client)

    assert pairs == []


def test_run_xref_zero_chunks_yields_zero_pairs_and_no_llm_call(monkeypatch, tmp_path):
    import axial.xref as xref_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(xref_mod, "run_chunk", lambda path, **kwargs: [])
    monkeypatch.setattr(xref_mod, "run_artifacts", lambda path, **kwargs: _artifact_records())

    stub_client = StubLLMClient()
    pairs = xref_mod.run_xref(source, client=stub_client)

    assert pairs == []
    assert stub_client.call_count == 0


def test_run_xref_missing_source_file_raises_missing_source_error(tmp_path):
    from axial.xref import MissingSourceError, run_xref

    missing = tmp_path / "does_not_exist.pdf"

    with pytest.raises(MissingSourceError):
        run_xref(missing, client=StubLLMClient())


def test_run_xref_wraps_chunk_errors(monkeypatch, tmp_path):
    import axial.xref as xref_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    def _raise_chunk_error(path, **kwargs):
        raise ChunkError("boom")

    monkeypatch.setattr(xref_mod, "run_chunk", _raise_chunk_error)

    with pytest.raises(xref_mod.ChunkingFailedError):
        xref_mod.run_xref(source, client=StubLLMClient())


def test_run_xref_wraps_artifacts_errors(monkeypatch, tmp_path):
    import axial.xref as xref_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(xref_mod, "run_chunk", lambda path, **kwargs: _chunk_records())

    def _raise_artifacts_error(path, **kwargs):
        raise ArtifactsError("boom")

    monkeypatch.setattr(xref_mod, "run_artifacts", _raise_artifacts_error)

    with pytest.raises(xref_mod.ArtifactsFailedError):
        xref_mod.run_xref(source, client=StubLLMClient())
