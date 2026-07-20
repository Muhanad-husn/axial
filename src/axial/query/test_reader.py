"""Inner unit tests for the vault reader and tag-query tool set (issue #249,
slice 01; plans/vault-query/01-vault-reader-and-tag-query.md's inner-loop
list)."""

from __future__ import annotations

import pytest
import yaml

from axial.query import (
    ArtifactNotFoundError,
    ChunkNotFoundError,
    MalformedNoteError,
    MissingVaultDirError,
    UnknownFilterError,
    get_artifact,
    get_chunk,
    query_by_tag,
)

# -- fixture helpers ----------------------------------------------------------


def _write_chunk_note(prose_dir, chunk_id, **overrides):
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "A Section",
        "chunk_text": f"{chunk_id} text.",
        "source_meta": {"author": "A", "title": "T", "date": 2020, "thesis": "X", "scope": "Y"},
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": "Freedonia"},
        "polities_touched": ["Freedonia"],
        "artifact_refs": [],
    }
    frontmatter.update(overrides)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


def _write_artifact_note(artifacts_dir, artifact_id, **overrides):
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "artifact_id": artifact_id,
        "artifact_role": "case-study",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "source_id": "some-source",
        "section": "A Section",
        "retrievable": True,
        "cited_by": [],
    }
    frontmatter.update(overrides)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (artifacts_dir / f"{artifact_id}.md").write_text(text, encoding="utf-8")


# -- note parser: malformed frontmatter --------------------------------------


def test_get_chunk_raises_on_missing_frontmatter_delimiter(tmp_path):
    prose_dir = tmp_path / "prose"
    prose_dir.mkdir()
    (prose_dir / "bad.md").write_text("no frontmatter here at all\n", encoding="utf-8")

    with pytest.raises(MalformedNoteError) as exc_info:
        get_chunk("bad", vault_dir=tmp_path)
    assert "bad.md" in str(exc_info.value)


def test_get_chunk_raises_on_unterminated_frontmatter(tmp_path):
    prose_dir = tmp_path / "prose"
    prose_dir.mkdir()
    (prose_dir / "bad.md").write_text(
        "---\nchunk_id: bad\nno closing delimiter\n", encoding="utf-8"
    )

    with pytest.raises(MalformedNoteError) as exc_info:
        get_chunk("bad", vault_dir=tmp_path)
    assert "bad.md" in str(exc_info.value)


def test_get_chunk_raises_on_invalid_yaml(tmp_path):
    prose_dir = tmp_path / "prose"
    prose_dir.mkdir()
    (prose_dir / "bad.md").write_text("---\n[unterminated: [flow\n---\nBody.\n", encoding="utf-8")

    with pytest.raises(MalformedNoteError) as exc_info:
        get_chunk("bad", vault_dir=tmp_path)
    assert "bad.md" in str(exc_info.value)


def test_get_chunk_raises_on_missing_required_field(tmp_path):
    prose_dir = tmp_path / "prose"
    prose_dir.mkdir()
    (prose_dir / "bad.md").write_text("---\nchunk_id: bad\n---\nBody.\n", encoding="utf-8")

    with pytest.raises(MalformedNoteError) as exc_info:
        get_chunk("bad", vault_dir=tmp_path)
    assert "bad.md" in str(exc_info.value)


# -- note parser: real nested shapes ------------------------------------------


def test_get_chunk_exposes_the_full_nested_field_surface(tmp_path):
    _write_chunk_note(
        tmp_path / "prose",
        "c1",
        claim_type={
            "primary": "claim:causal",
            "secondary": "claim:comparative",
            "subtags": ["claim:causal:mechanism"],
        },
    )

    result = get_chunk("c1", vault_dir=tmp_path)

    assert result.chunk_id == "c1"
    assert result.section == "A Section"
    assert result.chunk_text == "c1 text."
    assert result.source_meta == {
        "author": "A",
        "title": "T",
        "date": 2020,
        "thesis": "X",
        "scope": "Y",
    }
    assert result.schema_version == "0.1"
    assert result.role_in_argument == "role:claim"
    assert result.field == {"primary": "field:political-sociology", "secondary": []}
    assert result.claim_type == {
        "primary": "claim:causal",
        "secondary": "claim:comparative",
        "subtags": ["claim:causal:mechanism"],
    }
    assert result.theory_school == {
        "primary": "school:synthetic-institutionalist",
        "secondary": None,
        "status": "candidate",
    }
    assert result.empirical_scope == {"value": "scope:country-case", "polity": "Freedonia"}
    assert result.polities_touched == ["Freedonia"]
    assert result.artifact_refs == []


def test_get_artifact_exposes_its_field_surface(tmp_path):
    _write_artifact_note(tmp_path / "artifacts", "a1", cited_by=["c1"])

    result = get_artifact("a1", vault_dir=tmp_path)

    assert result.artifact_id == "a1"
    assert result.artifact_role == "case-study"
    assert result.field == {"primary": "field:political-sociology", "secondary": []}
    assert result.source_id == "some-source"
    assert result.section == "A Section"
    assert result.retrievable is True
    assert result.cited_by == ["c1"]


def test_get_artifact_absent_caption_reads_as_none(tmp_path):
    _write_artifact_note(tmp_path / "artifacts", "a1")

    result = get_artifact("a1", vault_dir=tmp_path)

    assert result.caption is None


def test_get_artifact_present_caption_reads_through(tmp_path):
    _write_artifact_note(tmp_path / "artifacts", "a1", caption="A caption.")

    result = get_artifact("a1", vault_dir=tmp_path)

    assert result.caption == "A caption."


# -- query_by_tag: per-axis filtering -----------------------------------------


def test_field_filter_matches_primary_and_secondary(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "primary_match", field={"primary": "field:x", "secondary": []})
    _write_chunk_note(
        prose_dir, "secondary_match", field={"primary": "field:y", "secondary": ["field:x"]}
    )
    _write_chunk_note(prose_dir, "no_match", field={"primary": "field:z", "secondary": []})

    result = query_by_tag(field="field:x", vault_dir=tmp_path)

    assert result == ["primary_match", "secondary_match"]


def test_claim_type_filter_matches_primary_secondary_and_subtags(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(
        prose_dir, "by_primary", claim_type={"primary": "claim:x", "secondary": None, "subtags": []}
    )
    _write_chunk_note(
        prose_dir,
        "by_secondary",
        claim_type={"primary": "claim:y", "secondary": "claim:x", "subtags": []},
    )
    _write_chunk_note(
        prose_dir,
        "by_subtag",
        claim_type={"primary": "claim:y", "secondary": None, "subtags": ["claim:x"]},
    )
    _write_chunk_note(
        prose_dir, "no_match", claim_type={"primary": "claim:z", "secondary": None, "subtags": []}
    )

    result = query_by_tag(claim_type="claim:x", vault_dir=tmp_path)

    assert result == ["by_primary", "by_secondary", "by_subtag"]


def test_theory_school_filter_matches_primary_and_secondary_status_not_a_filter_key(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(
        prose_dir,
        "by_primary",
        theory_school={"primary": "school:x", "secondary": None, "status": "candidate"},
    )
    _write_chunk_note(
        prose_dir,
        "by_secondary",
        theory_school={"primary": "school:y", "secondary": "school:x", "status": "confirmed"},
    )

    result = query_by_tag(theory_school="school:x", vault_dir=tmp_path)

    assert result == ["by_primary", "by_secondary"]
    # `status` is carried on the parsed result but is never itself a filter
    # key -- querying by it must raise, not silently match.
    with pytest.raises(UnknownFilterError):
        query_by_tag(status="candidate", vault_dir=tmp_path)


def test_empirical_scope_filter_matches_value_polity_filter_matches_polity_separately(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(
        prose_dir, "value_a", empirical_scope={"value": "scope:country-case", "polity": "Freedonia"}
    )
    _write_chunk_note(
        prose_dir, "value_b", empirical_scope={"value": "scope:comparative", "polity": None}
    )

    assert query_by_tag(empirical_scope="scope:country-case", vault_dir=tmp_path) == ["value_a"]
    assert query_by_tag(polity="Freedonia", vault_dir=tmp_path) == ["value_a"]
    # A null polity never matches a polity filter, whatever the filter value.
    assert query_by_tag(polity="None", vault_dir=tmp_path) == []


def test_role_in_argument_filter_matches_exact_string(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "claim", role_in_argument="role:claim")
    _write_chunk_note(prose_dir, "evidence", role_in_argument="role:evidence")

    assert query_by_tag(role_in_argument="role:claim", vault_dir=tmp_path) == ["claim"]


# -- query_by_tag: conjunction, unknown keys, determinism ---------------------


def test_multiple_filters_compose_as_a_conjunction(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(
        prose_dir,
        "both",
        field={"primary": "field:x", "secondary": []},
        role_in_argument="role:claim",
    )
    _write_chunk_note(
        prose_dir,
        "field_only",
        field={"primary": "field:x", "secondary": []},
        role_in_argument="role:evidence",
    )
    _write_chunk_note(
        prose_dir,
        "role_only",
        field={"primary": "field:z", "secondary": []},
        role_in_argument="role:claim",
    )

    result = query_by_tag(field="field:x", role_in_argument="role:claim", vault_dir=tmp_path)

    assert result == ["both"]


def test_a_filter_set_no_note_satisfies_returns_an_empty_list(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "c1", role_in_argument="role:evidence")

    result = query_by_tag(role_in_argument="role:does-not-exist", vault_dir=tmp_path)

    assert result == []


def test_unknown_filter_key_raises(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "c1")

    with pytest.raises(UnknownFilterError) as exc_info:
        query_by_tag(not_a_real_axis="whatever", vault_dir=tmp_path)
    assert "not_a_real_axis" in str(exc_info.value)


def test_results_are_sorted_by_chunk_id_despite_scrambled_write_order(tmp_path):
    prose_dir = tmp_path / "prose"
    # Written deliberately out of lexical order.
    for chunk_id in ["c3", "c1", "c4", "c2"]:
        _write_chunk_note(prose_dir, chunk_id)

    result = query_by_tag(role_in_argument="role:claim", vault_dir=tmp_path)

    assert result == ["c1", "c2", "c3", "c4"]


def test_query_by_tag_vault_dir_is_keyword_only():
    """A filter value passed positionally must never be mistaken for
    vault_dir (issue #249 F4): query_by_tag takes no positional parameters
    at all, so a positional call raises TypeError immediately instead of
    silently resolving `vault_dir` to a filter string and returning `[]`."""
    with pytest.raises(TypeError):
        query_by_tag("field:political-sociology")


def test_query_by_tag_raises_when_the_vault_dir_does_not_exist(tmp_path):
    """A missing or typo'd `vault_dir` is a caller bug, not an empty corpus
    (issue #249 F3) -- every other bad input in this module raises, and a
    silently empty result here would hide that mistake as "no matches"."""
    missing_vault_dir = tmp_path / "no-such-vault"

    with pytest.raises(MissingVaultDirError) as exc_info:
        query_by_tag(role_in_argument="role:claim", vault_dir=missing_vault_dir)
    assert str(missing_vault_dir / "prose") in str(exc_info.value)


def test_query_by_tag_raises_on_a_note_missing_chunk_id(tmp_path):
    """`query_by_tag` must never hand back a filename-derived id for a note
    `get_chunk` would itself refuse (issue #249 F2) -- a note with no
    `chunk_id` key at all aborts the scan with the same `MalformedNoteError`
    `get_chunk` would raise, naming the offending file, rather than being
    silently included (or excluded) under a guessed id."""
    prose_dir = tmp_path / "prose"
    prose_dir.mkdir(parents=True)
    frontmatter = {"section": "A Section", "chunk_text": "text.", "role_in_argument": "role:claim"}
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / "no_id.md").write_text(text, encoding="utf-8")

    with pytest.raises(MalformedNoteError) as exc_info:
        query_by_tag(role_in_argument="role:claim", vault_dir=tmp_path)
    assert "no_id.md" in str(exc_info.value)


def test_query_by_tag_excludes_a_note_missing_the_filtered_axis_rather_than_raising(tmp_path):
    """Stated decision (issue #249 F5): a note missing the specific axis a
    filter targets is excluded from the match set, not an error -- so one
    thin note does not abort an otherwise-good full-vault scan. This is
    distinct from a missing `chunk_id` (F2 above), which always raises:
    `chunk_id` is the note's identity, not a filterable tag axis.
    `get_chunk` on that same note still raises, since it promises the
    note's full field surface (§7.5)."""
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "has_field", field={"primary": "field:x", "secondary": []})

    frontmatter = {
        "chunk_id": "missing_field",
        "section": "A Section",
        "chunk_text": "missing_field text.",
        "source_meta": {"author": "A", "title": "T", "date": 2020, "thesis": "X", "scope": "Y"},
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        # No `field` key at all.
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": "Freedonia"},
        "polities_touched": ["Freedonia"],
        "artifact_refs": [],
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / "missing_field.md").write_text(text, encoding="utf-8")

    result = query_by_tag(field="field:x", vault_dir=tmp_path)

    assert result == ["has_field"]
    with pytest.raises(MalformedNoteError):
        get_chunk("missing_field", vault_dir=tmp_path)


# -- get_chunk / get_artifact: not-found --------------------------------------


def test_get_chunk_raises_not_found_naming_the_id(tmp_path):
    (tmp_path / "prose").mkdir()

    with pytest.raises(ChunkNotFoundError) as exc_info:
        get_chunk("does-not-exist", vault_dir=tmp_path)
    assert "does-not-exist" in str(exc_info.value)


def test_get_artifact_raises_not_found_naming_the_id(tmp_path):
    (tmp_path / "artifacts").mkdir()

    with pytest.raises(ArtifactNotFoundError) as exc_info:
        get_artifact("does-not-exist", vault_dir=tmp_path)
    assert "does-not-exist" in str(exc_info.value)


# -- LLM-free by construction --------------------------------------------------


def test_module_imports_and_runs_with_no_llm_client_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "c1")

    # None of these should ever touch an LLM client; AXIAL_LLM_PROVIDER=explode
    # makes any hidden `.complete()` call crash loudly rather than pass silently.
    assert query_by_tag(role_in_argument="role:claim", vault_dir=tmp_path) == ["c1"]
    assert get_chunk("c1", vault_dir=tmp_path).chunk_id == "c1"
