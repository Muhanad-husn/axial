"""Inner unit tests for the axial artifacts module (issue #30 slice 01 --
artifact collection; issue #429 -- the LLM call and the `artifact_role`/
`field` axes are retired)."""

from __future__ import annotations

import json

import pytest


def _tree_with_one_artifact() -> dict:
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": [
                    {"type": "prose", "order": "1.1", "text": "Intro body sentence."},
                    {"type": "artifact", "order": "1.2", "label": "table"},
                ],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Discussion",
                "children": [
                    {"type": "prose", "order": "2.1", "text": "Discussion body sentence."},
                ],
            },
        ]
    }


def _tree_with_no_artifacts() -> dict:
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


# --- artifact-node collection + section provenance --------------------------


def test_artifact_nodes_with_section_pairs_each_artifact_with_its_enclosing_heading():
    from axial.artifacts import _artifact_nodes_with_section

    tree = _tree_with_one_artifact()

    pairs = _artifact_nodes_with_section(tree)

    assert len(pairs) == 1
    node, section = pairs[0]
    assert node["order"] == "1.2"
    assert section == "Introduction"


def test_artifact_nodes_with_section_finds_nested_artifacts_recursively():
    from axial.artifacts import _artifact_nodes_with_section

    tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": [
                    {
                        "type": "prose",
                        "order": "1.1",
                        "text": "wrapper",
                        "children": [{"type": "artifact", "order": "1.1.1", "label": "figure"}],
                    }
                ],
            }
        ]
    }

    pairs = _artifact_nodes_with_section(tree)

    assert len(pairs) == 1
    node, section = pairs[0]
    assert node["order"] == "1.1.1"
    assert section == "Introduction"


def test_artifact_nodes_with_section_returns_empty_for_no_artifacts():
    from axial.artifacts import _artifact_nodes_with_section

    tree = _tree_with_no_artifacts()

    assert _artifact_nodes_with_section(tree) == []


# --- artifact_id / record shape (issue #429: no role/field) -----------------


def test_build_artifact_record_keeps_dotted_order_verbatim():
    from axial.artifacts import build_artifact_record

    record = build_artifact_record(
        source_id="paper-abc123",
        node={"type": "artifact", "order": "1.2"},
        section="Introduction",
    )

    assert record["artifact_id"] == "paper-abc123_art_1.2"
    assert record["section"] == "Introduction"
    assert record["source_id"] == "paper-abc123"


def test_build_artifact_record_is_deterministic():
    from axial.artifacts import build_artifact_record

    node = {"type": "artifact", "order": "3"}
    first = build_artifact_record(source_id="paper-abc123", node=node, section="Introduction")
    second = build_artifact_record(source_id="paper-abc123", node=node, section="Introduction")

    assert first == second


def test_build_artifact_record_carries_no_role_or_field_keys():
    """issue #429: the artifacts pass makes no LLM call, so a record never
    carries `artifact_role` or `field` -- neither key exists at all, not
    even as `None`."""
    from axial.artifacts import build_artifact_record

    record = build_artifact_record(
        source_id="paper-abc123",
        node={"type": "artifact", "order": "1.2"},
        section="Introduction",
    )

    assert "artifact_role" not in record
    assert "field" not in record


def test_build_artifact_record_omits_caption_key_when_none_given():
    from axial.artifacts import build_artifact_record

    record = build_artifact_record(
        source_id="paper-abc123",
        node={"type": "artifact", "order": "1.2"},
        section="Introduction",
    )

    assert "caption" not in record


def test_build_artifact_record_carries_caption_when_given():
    from axial.artifacts import build_artifact_record

    record = build_artifact_record(
        source_id="paper-abc123",
        node={"type": "artifact", "order": "1.2"},
        section="Introduction",
        caption="A caption describing the figure.",
    )

    assert record["caption"] == "A caption describing the figure."


# --- issue #168: router-routed artifact collection + caption attachment -----


def _tree_with_caption_table_and_apparatus() -> dict:
    """One section with a table, a picture, an immediately-following caption,
    and a document_index (TOC) block; a second, back-matter-titled section
    with a footnote block. Mirrors tests/test_artifacts.py's own outer
    fixture (issue #168) at a smaller scale for inner-unit coverage."""
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Findings",
                "children": [
                    {"type": "artifact", "order": "1.1", "label": "table", "text": "Table body."},
                    {
                        "type": "artifact",
                        "order": "1.2",
                        "label": "picture",
                        "text": "Figure body.",
                    },
                    {
                        "type": "prose",
                        "order": "1.3",
                        "label": "caption",
                        "text": "Caption body.",
                    },
                    {
                        "type": "prose",
                        "order": "1.4",
                        "label": "document_index",
                        "text": "TOC body.",
                    },
                ],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Endnotes",
                "children": [
                    {
                        "type": "prose",
                        "order": "2.1",
                        "label": "footnote",
                        "text": "Footnote body.",
                    },
                ],
            },
        ]
    }


def test_routed_artifact_blocks_includes_caption_and_excludes_apparatus():
    from axial.artifacts import _routed_artifact_blocks

    tree = _tree_with_caption_table_and_apparatus()
    blocks = _routed_artifact_blocks(tree)

    orders = [node["order"] for node, _section in blocks]
    assert orders == ["1.1", "1.2", "1.3"]
    assert all(section == "Findings" for _node, section in blocks)


def test_routed_artifact_blocks_still_collects_type_artifact_regardless_of_label():
    """Back-compat carve-out (issue #168): a genuine `type == 'artifact'`
    node (extract.py's own docling TableItem/PictureItem classification) is
    always collected even when its `label` isn't one of the router's own
    artifact labels -- guards a real artifact from vanishing on an
    unrecognized-label edge case (see e.g.
    tests/test_tag_artifacts_input_guard.py's `label: 'figure'` fixture)."""
    from axial.artifacts import _routed_artifact_blocks

    tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Findings",
                "children": [
                    {
                        "type": "artifact",
                        "order": "1.1",
                        "label": "figure",
                        "text": "Odd-label artifact.",
                    },
                ],
            }
        ]
    }

    blocks = _routed_artifact_blocks(tree)

    assert [node["order"] for node, _section in blocks] == ["1.1"]


def test_attach_captions_moves_caption_text_onto_the_preceding_artifact():
    from axial.artifacts import _attach_captions, _routed_artifact_blocks

    tree = _tree_with_caption_table_and_apparatus()
    blocks = _routed_artifact_blocks(tree)

    entries = _attach_captions(blocks)

    assert [entry["node"]["order"] for entry in entries] == ["1.1", "1.2"]
    assert entries[0]["caption"] is None
    assert entries[1]["caption"] == "Caption body."


def test_attach_captions_orphan_caption_with_no_preceding_artifact_becomes_standalone():
    """Fallback (issue #168 plan): a caption with no resolvable prior
    artifact never crashes and is never silently dropped -- it becomes its
    own standalone entry."""
    from axial.artifacts import _attach_captions

    orphan_caption = {
        "type": "prose",
        "order": "1.1",
        "label": "caption",
        "text": "Orphan caption.",
    }

    entries = _attach_captions([(orphan_caption, "Findings")])

    assert len(entries) == 1
    assert entries[0]["node"] is orphan_caption
    assert entries[0]["caption"] is None


def test_attach_captions_a_third_caption_never_overwrites_an_already_attached_second():
    """Regression for a caption-overwrite data-loss bug: once an entry
    already carries one attached caption's text (here, the orphan-turned-
    standalone entry's FIRST attached caption, "Second caption."), a THIRD
    caption block attaching to that same entry must never silently
    overwrite it -- the slice's own "caption text is never lost" invariant.
    Both attached captions must survive, concatenated."""
    from axial.artifacts import _attach_captions

    orphan_caption = {
        "type": "prose",
        "order": "1.1",
        "label": "caption",
        "text": "Orphan caption.",
    }
    second_caption = {
        "type": "prose",
        "order": "1.2",
        "label": "caption",
        "text": "Second caption.",
    }
    third_caption = {
        "type": "prose",
        "order": "1.3",
        "label": "caption",
        "text": "Third caption.",
    }

    entries = _attach_captions(
        [(orphan_caption, "Findings"), (second_caption, "Findings"), (third_caption, "Findings")]
    )

    assert len(entries) == 1
    assert "Second caption." in entries[0]["caption"]
    assert "Third caption." in entries[0]["caption"]


def test_run_artifacts_attaches_caption_to_figure_and_excludes_apparatus(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(
        artifacts_mod, "extract", lambda path: _tree_with_caption_table_and_apparatus()
    )

    records = artifacts_mod.run_artifacts(source)

    assert len(records) == 2
    table_record = next(r for r in records if r["artifact_id"].endswith("_art_1.1"))
    figure_record = next(r for r in records if r["artifact_id"].endswith("_art_1.2"))

    assert "caption" not in table_record
    assert figure_record["caption"] == "Caption body."
    # No role/field on either record -- this pass makes no LLM call.
    assert "artifact_role" not in table_record
    assert "artifact_role" not in figure_record


# --- run_artifacts: no LLM call, deterministic record shape (issue #429) ----


def test_run_artifacts_zero_artifacts_yields_zero_records(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_no_artifacts())

    records = artifacts_mod.run_artifacts(source)

    assert records == []


def test_run_artifacts_produces_one_record_per_artifact_node_with_id_and_provenance(
    monkeypatch, tmp_path
):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())

    records = artifacts_mod.run_artifacts(source)

    assert len(records) == 1
    record = records[0]
    assert record["section"] == "Introduction"
    assert record["artifact_id"].endswith("_art_1.2")
    assert set(record) == {"artifact_id", "source_id", "section"}


def test_run_artifacts_missing_source_file_raises_missing_source_error(tmp_path):
    from axial.artifacts import MissingSourceError, run_artifacts

    missing = tmp_path / "does_not_exist.pdf"

    with pytest.raises(MissingSourceError):
        run_artifacts(missing)


def test_run_artifacts_extraction_failure_raises_extraction_failed_error(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod
    from axial.extract import ExtractError

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    def _boom(path):
        raise ExtractError("simulated extraction failure")

    monkeypatch.setattr(artifacts_mod, "extract", _boom)

    with pytest.raises(artifacts_mod.ExtractionFailedError):
        artifacts_mod.run_artifacts(source)


def test_run_artifacts_is_stable_across_repeat_runs(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())

    first = artifacts_mod.run_artifacts(source)
    second = artifacts_mod.run_artifacts(source)

    assert first == second


# --- issue #98: per-artifact checkpoint/resume -------------------------------


def _tree_with_two_artifacts() -> dict:
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Findings",
                "children": [
                    {"type": "prose", "order": "1.1", "text": "Findings body sentence."},
                    {"type": "artifact", "order": "1.2", "label": "table"},
                    {"type": "artifact", "order": "1.3", "label": "table"},
                ],
            }
        ]
    }


def test_artifacts_checkpoint_append_load_round_trips(tmp_path):
    from axial.artifacts import append_artifact_checkpoint, load_artifact_checkpoint

    path = tmp_path / "artifacts" / "src-abc.jsonl"
    record_one = {"artifact_id": "src-abc_art_1", "source_id": "src-abc", "section": "Intro"}
    record_two = {"artifact_id": "src-abc_art_2", "source_id": "src-abc", "section": "Intro"}

    append_artifact_checkpoint(path, record_one)
    append_artifact_checkpoint(path, record_two)

    loaded = load_artifact_checkpoint(path)
    assert loaded == [record_one, record_two]


def test_artifacts_checkpoint_path_is_keyed_by_source_id(tmp_path):
    from axial.artifacts import artifacts_checkpoint_path

    path = artifacts_checkpoint_path("src-abc123", tmp_path)
    assert path == tmp_path / "src-abc123.jsonl"


def test_load_artifact_checkpoint_missing_file_returns_empty_list(tmp_path):
    from axial.artifacts import load_artifact_checkpoint

    assert load_artifact_checkpoint(tmp_path / "nonexistent.jsonl") == []


def test_load_artifact_checkpoint_drops_torn_final_line(tmp_path):
    from axial.artifacts import append_artifact_checkpoint, load_artifact_checkpoint

    path = tmp_path / "artifacts" / "src-abc.jsonl"
    intact = {"artifact_id": "src-abc_art_1", "source_id": "src-abc", "section": "Intro"}
    append_artifact_checkpoint(path, intact)

    full_second = json.dumps({"artifact_id": "src-abc_art_2", "source_id": "src-abc"})
    torn_tail = full_second[:15]
    assert not torn_tail.endswith("}")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(torn_tail)  # no trailing newline: simulates a torn in-flight write

    loaded = load_artifact_checkpoint(path)
    assert loaded == [intact]


def test_load_artifact_checkpoint_raises_naming_path_and_line_for_a_non_final_torn_line(tmp_path):
    from axial.artifacts import ArtifactCheckpointCorruptError, load_artifact_checkpoint

    path = tmp_path / "artifacts" / "src.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    intact_first = json.dumps({"artifact_id": "a"})
    torn_middle = '{"artifact_id": "b", "broken'
    intact_last = json.dumps({"artifact_id": "c"})
    path.write_text(f"{intact_first}\n{torn_middle}\n{intact_last}\n", encoding="utf-8")

    with pytest.raises(ArtifactCheckpointCorruptError) as exc_info:
        load_artifact_checkpoint(path)

    message = str(exc_info.value)
    assert str(path) in message
    assert "2" in message  # 1-indexed line number of the torn (non-final) line


def test_append_artifact_checkpoint_heals_a_torn_tail_before_appending(tmp_path):
    from axial.artifacts import append_artifact_checkpoint, load_artifact_checkpoint

    path = tmp_path / "artifacts" / "src.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"artifact_id": "a"}\n{"artifact_id": "b", "brok', encoding="utf-8")

    append_artifact_checkpoint(path, {"artifact_id": "c"})

    loaded = load_artifact_checkpoint(path)
    assert loaded == [{"artifact_id": "a"}, {"artifact_id": "c"}]


def test_run_artifacts_writes_a_source_keyed_checkpoint_when_artifacts_dir_given(
    monkeypatch, tmp_path
):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    source_id = artifacts_mod.compute_source_id(source)
    artifacts_dir = tmp_path / "artifacts"

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_two_artifacts())

    records = artifacts_mod.run_artifacts(source, artifacts_dir=artifacts_dir)

    checkpoint = artifacts_dir / f"{source_id}.jsonl"
    assert checkpoint.is_file()
    persisted = artifacts_mod.load_artifact_checkpoint(checkpoint)
    assert [r["artifact_id"] for r in persisted] == [r["artifact_id"] for r in records]
    assert len(persisted) == 2


def test_run_artifacts_resume_reuses_already_checkpointed_artifacts(monkeypatch, tmp_path):
    """Skip-set arithmetic (issue #98): an artifact already present in the
    checkpoint is reused verbatim, never rebuilt."""
    import axial.artifacts as artifacts_mod
    from axial.artifacts import append_artifact_checkpoint, artifacts_checkpoint_path

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    source_id = artifacts_mod.compute_source_id(source)
    artifacts_dir = tmp_path / "artifacts"

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_two_artifacts())

    # Pre-seed the checkpoint with the first artifact only, carrying a
    # sentinel value ("stale-section") that would only survive if the
    # checkpointed record is reused verbatim rather than rebuilt from the
    # tree (which would instead produce "Findings").
    checkpoint = artifacts_checkpoint_path(source_id, artifacts_dir)
    seeded = {
        "artifact_id": f"{source_id}_art_1.2",
        "source_id": source_id,
        "section": "stale-section",
    }
    append_artifact_checkpoint(checkpoint, seeded)

    records = artifacts_mod.run_artifacts(source, artifacts_dir=artifacts_dir)

    assert [r["artifact_id"] for r in records] == [
        f"{source_id}_art_1.2",
        f"{source_id}_art_1.3",
    ]
    # The seeded record is reused verbatim (its stale section survives).
    assert records[0]["section"] == "stale-section"

    persisted = artifacts_mod.load_artifact_checkpoint(checkpoint)
    assert len(persisted) == 2  # no duplicate line for the already-checkpointed artifact


def test_run_artifacts_checkpoint_disabled_by_default(monkeypatch, tmp_path):
    """When `artifacts_dir` is omitted (today's `axial artifacts` behavior,
    unchanged), no checkpoint file is ever written."""
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    artifacts_dir = tmp_path / "artifacts"

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_two_artifacts())

    artifacts_mod.run_artifacts(source)

    assert not artifacts_dir.exists()
