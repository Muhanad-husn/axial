"""Inner unit tests for the vault reader and tag-query tool set (issue #249,
slice 01; plans/vault-query/01-vault-reader-and-tag-query.md's inner-loop
list). Slice 02 (issue #251,
plans/vault-query/02-facet-and-traversal-queries.md's inner-loop list) adds
unit tests for `query_by_polity`, `query_by_source`, `get_envelope`,
`follow_backlinks`, `coverage_count` further down this file."""

from __future__ import annotations

import json

import pytest
import yaml

from axial.query import (
    ArtifactNotFoundError,
    BacklinkTargetNotFoundError,
    ChunkNotFoundError,
    EnvelopeNotFoundError,
    MalformedChunkIdError,
    MalformedNoteError,
    MissingVaultDirError,
    UnknownFilterError,
    coverage_count,
    follow_backlinks,
    get_artifact,
    get_chunk,
    get_envelope,
    query_by_polity,
    query_by_source,
    query_by_tag,
)
from axial.query.reader import source_id_from_chunk_id

# -- fixture helpers ----------------------------------------------------------


def _write_chunk_note(prose_dir, chunk_id, *, filename=None, **overrides):
    """Write a prose note whose FRONTMATTER `chunk_id` is `chunk_id` and
    whose on-disk filename is `filename` (defaulting to `f"{chunk_id}.md"`,
    the ordinary unbudgeted case). A caller passing an explicit `filename`
    simulates a filename-budgeted note (PR #377) or a stale duplicate
    written under a different name for the same true chunk_id."""
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
    (prose_dir / (filename or f"{chunk_id}.md")).write_text(text, encoding="utf-8")


def _write_artifact_note(artifacts_dir, artifact_id, *, filename=None, **overrides):
    """The artifact-note counterpart of `_write_chunk_note` -- same
    filename-independent-of-id contract."""
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
    (artifacts_dir / (filename or f"{artifact_id}.md")).write_text(text, encoding="utf-8")


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


# -- get_chunk / get_artifact: filename-budgeted notes (PR #377) --------------
#
# `axial.vault._note_path`/`_artifact_note_path` shorten a note's ON-DISK
# FILENAME (never `chunk_id`/`artifact_id` itself) when the full id would
# push the path over Windows' 260-char MAX_PATH. Before this fix, `get_chunk`/
# `get_artifact` assumed filename == id and could never find such a note
# again by its real, correct id -- measured on the real corpus: 399 notes
# across the three longest source_ids (Benjamin Thomas White, Syrias
# Peasantry, Andreas Wimmer) were unreachable this way.

_LONG_HASH12 = "0123456789ab"
_LONG_SOURCE_ID = f"{'A' * 200}-{_LONG_HASH12}"

_LONG_RECORD_BASE = {
    "section": "Introduction",
    "chunk_text": "Some long-source prose.",
    "role_in_argument": "role:claim",
    "schema_version": "1.0.0",
    "empirical_scope": "scope:country-case",
    "polity": "Syria",
    "polities_touched": ["Syria"],
    "field": {"primary": "field:political-science", "secondary": []},
    "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
    "theory_school": {"primary": "school:realism", "secondary": None, "status": "candidate"},
}
_LONG_ENVELOPE = {"thesis": "T", "scope": "S"}
_LONG_SOURCE_META = {
    "author": {"value": "A", "provenance": "p"},
    "title": {"value": "Ti", "provenance": "p"},
    "date": "unavailable",
}


def test_get_chunk_resolves_a_note_whose_filename_was_budgeted(tmp_path):
    """The case that is broken today: a note written under a shortened
    on-disk filename must still resolve by its true, full `chunk_id`."""
    from axial.vault import write_chunk_note

    slug = "b" * 80
    chunk_id = f"{_LONG_SOURCE_ID}_1_{slug}_001"
    record = {**_LONG_RECORD_BASE, "chunk_id": chunk_id}
    vault_dir = tmp_path / "vault"

    note_path = write_chunk_note(
        record, _LONG_ENVELOPE, _LONG_SOURCE_META, vault_dir, source_id=_LONG_SOURCE_ID
    )
    # Sanity: the writer really did shorten the filename (not just happened
    # to already fit) -- otherwise this test would not exercise the fallback.
    assert note_path.name != f"{chunk_id}.md"
    assert not (vault_dir / "prose" / f"{chunk_id}.md").exists()

    note = get_chunk(chunk_id, vault_dir=vault_dir)

    assert note.chunk_id == chunk_id
    assert note.chunk_text == "Some long-source prose."


def test_get_chunk_fast_path_resolves_directly_without_needing_chunk_id_grammar(tmp_path):
    """No regression on the direct `<chunk_id>.md` path (~97.8% of real
    notes): resolution must succeed even for an id that would raise
    `MalformedChunkIdError` if the fallback's `source_id_from_chunk_id`
    parse ran on it -- proving the fast, direct hit is tried FIRST and the
    fallback is never even consulted when it exists."""
    _write_chunk_note(tmp_path / "prose", "not-shaped-like-a-real-chunk-id")

    note = get_chunk("not-shaped-like-a-real-chunk-id", vault_dir=tmp_path)

    assert note.chunk_id == "not-shaped-like-a-real-chunk-id"


def test_get_artifact_resolves_a_note_whose_filename_was_budgeted(tmp_path):
    """The `get_artifact` counterpart of the budgeted-chunk-note case."""
    from axial.vault import write_artifact_note

    artifact_id = f"{_LONG_SOURCE_ID}_art_1.2"
    record = {
        "artifact_id": artifact_id,
        "artifact_role": "case-study",
        "field": {"primary": "state", "secondary": []},
        "source_id": _LONG_SOURCE_ID,
        "section": "Introduction",
    }
    vault_dir = tmp_path / "vault"

    note_path = write_artifact_note(record, vault_dir)
    assert note_path.name != f"{artifact_id}.md"
    assert not (vault_dir / "artifacts" / f"{artifact_id}.md").exists()

    note = get_artifact(artifact_id, vault_dir=vault_dir)

    assert note.artifact_id == artifact_id
    assert note.artifact_role == "case-study"


def test_get_artifact_fast_path_resolves_directly_without_needing_artifact_id_grammar(tmp_path):
    """No regression on `get_artifact`'s direct path: an id that does not
    even carry the `_art_<order>` shape (so the fallback's source_id parse
    can never succeed on it) still resolves via the direct hit."""
    _write_artifact_note(tmp_path / "artifacts", "not-shaped-like-an-artifact-id")

    note = get_artifact("not-shaped-like-an-artifact-id", vault_dir=tmp_path)

    assert note.artifact_id == "not-shaped-like-an-artifact-id"


# -- find_chunk_ids_ending_with / find_artifact_ids_ending_with ---------------
# The `axial.analyze.synthesis` truncated-citation repair's lookup: a
# filename-only suffix scan, used only when an exact match already failed.


def test_find_chunk_ids_ending_with_returns_the_sole_suffix_match(tmp_path):
    from axial.query.reader import find_chunk_ids_ending_with

    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "Long Human Title - digest123_25_intro_001")
    _write_chunk_note(prose_dir, "Other Source - digest456_1_conclusion_002")

    assert find_chunk_ids_ending_with("digest123_25_intro_001", vault_dir=tmp_path) == [
        "Long Human Title - digest123_25_intro_001"
    ]


def test_find_chunk_ids_ending_with_returns_every_match_when_ambiguous(tmp_path):
    from axial.query.reader import find_chunk_ids_ending_with

    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "srcA-digest_25_intro_001")
    _write_chunk_note(prose_dir, "srcB-digest_25_intro_001")

    assert find_chunk_ids_ending_with("digest_25_intro_001", vault_dir=tmp_path) == [
        "srcA-digest_25_intro_001",
        "srcB-digest_25_intro_001",
    ]


def test_find_chunk_ids_ending_with_returns_true_chunk_ids_not_filename_stems_for_budgeted_notes(
    tmp_path,
):
    """A budgeted note's filename stem is NOT a real id -- the fallback must
    resolve each candidate to its true `chunk_id` from frontmatter, not
    hand back the shortened on-disk name."""
    from axial.query.reader import find_chunk_ids_ending_with

    prose_dir = tmp_path / "prose"
    true_id = "Some Long Human-Readable Title - digest123_26_a-section_012"
    _write_chunk_note(
        prose_dir,
        true_id,
        filename="Some Short-digest123_26_a-section_012.md",
    )

    assert find_chunk_ids_ending_with("digest123_26_a-section_012", vault_dir=tmp_path) == [true_id]


def test_find_chunk_ids_ending_with_dedupes_a_budgeted_note_and_a_stale_duplicate_to_one_true_id(
    tmp_path,
):
    """Precisely the second P1-04 failure: a stale full-length-named note
    and a budgeted-named note both carry the SAME true chunk_id in
    frontmatter (a post-#377 re-run wrote the budgeted name without
    removing the earlier full-length one). Two filenames match the cited
    suffix, but they must dedupe to ONE distinct true id, not be treated as
    an ambiguous match."""
    from axial.query.reader import find_chunk_ids_ending_with

    prose_dir = tmp_path / "prose"
    true_id = "Some Long Human-Readable Title - digest123_26_a-section_012"
    _write_chunk_note(prose_dir, true_id)  # stale, full-length filename
    _write_chunk_note(
        prose_dir,
        true_id,
        filename="Some Short-digest123_26_a-section_012.md",
    )  # budgeted filename, same true chunk_id

    assert find_chunk_ids_ending_with("digest123_26_a-section_012", vault_dir=tmp_path) == [true_id]


def test_find_chunk_ids_ending_with_returns_empty_when_no_match(tmp_path):
    from axial.query.reader import find_chunk_ids_ending_with

    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "srcA-digest_25_intro_001")

    assert find_chunk_ids_ending_with("not_a_real_suffix", vault_dir=tmp_path) == []


def test_find_artifact_ids_ending_with_returns_the_sole_suffix_match(tmp_path):
    from axial.query.reader import find_artifact_ids_ending_with

    artifacts_dir = tmp_path / "artifacts"
    _write_artifact_note(artifacts_dir, "Long Human Title - digest123_artifact_003")

    assert find_artifact_ids_ending_with("digest123_artifact_003", vault_dir=tmp_path) == [
        "Long Human Title - digest123_artifact_003"
    ]


# -- LLM-free by construction --------------------------------------------------


def test_module_imports_and_runs_with_no_llm_client_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "c1")

    # None of these should ever touch an LLM client; AXIAL_LLM_PROVIDER=explode
    # makes any hidden `.complete()` call crash loudly rather than pass silently.
    assert query_by_tag(role_in_argument="role:claim", vault_dir=tmp_path) == ["c1"]
    assert get_chunk("c1", vault_dir=tmp_path).chunk_id == "c1"


# =============================================================================
# Slice 02 (issue #251): query_by_polity, query_by_source / get_envelope,
# follow_backlinks, coverage_count
# =============================================================================


def _write_envelope(envelopes_dir, source_id, **overrides):
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    envelope = {
        "source_id": source_id,
        "thesis": "T",
        "toc": [{"title": "Introduction", "children": ["Background"]}],
        "scope": "S",
        "stated_argument": "A",
    }
    envelope.update(overrides)
    (envelopes_dir / f"{source_id}.json").write_text(
        json.dumps(envelope, indent=2), encoding="utf-8"
    )


# -- query_by_polity ----------------------------------------------------------


def test_query_by_polity_matches_any_entry_of_the_many_valued_list(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "two_polities", polities_touched=["Syria", "Iraq"])
    _write_chunk_note(prose_dir, "one_polity", polities_touched=["Iraq"])
    _write_chunk_note(prose_dir, "no_match", polities_touched=["Lebanon"])
    _write_chunk_note(prose_dir, "empty_list", polities_touched=[])

    result = query_by_polity("Iraq", vault_dir=tmp_path)

    assert result == ["one_polity", "two_polities"]


def test_query_by_polity_is_distinct_from_empirical_scope_polity(tmp_path):
    """A chunk scoped to one polity but touching another is returned for
    the touched polity, not the scoped one -- the cross-case behaviour the
    scope axis cannot serve (§7.5)."""
    prose_dir = tmp_path / "prose"
    _write_chunk_note(
        prose_dir,
        "c1",
        empirical_scope={"value": "scope:comparative", "polity": "Syria"},
        polities_touched=["Syria", "Iraq"],
    )

    assert query_by_polity("Iraq", vault_dir=tmp_path) == ["c1"]
    assert query_by_tag(polity="Iraq", vault_dir=tmp_path) == [], (
        "the empirical_scope.polity filter must NOT match on the many-valued polities_touched facet"
    )


def test_query_by_polity_is_exact_string_no_normalization(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "c1", polities_touched=["Iraq"])

    assert query_by_polity("iraq", vault_dir=tmp_path) == []
    assert query_by_polity("Iraq ", vault_dir=tmp_path) == []


def test_query_by_polity_results_sorted_despite_scrambled_write_order(tmp_path):
    prose_dir = tmp_path / "prose"
    for chunk_id in ["c3", "c1", "c4", "c2"]:
        _write_chunk_note(prose_dir, chunk_id, polities_touched=["Iraq"])

    assert query_by_polity("Iraq", vault_dir=tmp_path) == ["c1", "c2", "c3", "c4"]


# -- source_id parsing (query_by_source's seam) --------------------------------


def test_source_id_from_chunk_id_pins_the_parse_rule():
    """chunk_id shape: <source_id>_<section_order>_<section_slug>_<NNN>
    (axial.chunk.build_chunk_records). source_id itself may contain
    hyphens (axial's own source_id convention, `{stem}-{hash}`); the three
    trailing segments never do."""
    assert (
        source_id_from_chunk_id("some-source-abc123_1-2_intro-section_007") == "some-source-abc123"
    )
    assert source_id_from_chunk_id("src_0_section_001") == "src"


def test_source_id_from_chunk_id_raises_on_a_malformed_chunk_id():
    with pytest.raises(MalformedChunkIdError):
        source_id_from_chunk_id("not-enough-segments")


def test_query_by_source_returns_only_that_sources_chunks(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "srcA_1_intro_001")
    _write_chunk_note(prose_dir, "srcA_1_intro_002")
    _write_chunk_note(prose_dir, "srcB_1_intro_001")

    result = query_by_source("srcA", vault_dir=tmp_path)

    assert result == ["srcA_1_intro_001", "srcA_1_intro_002"]


# -- get_envelope ---------------------------------------------------------------


def test_get_envelope_exposes_thesis_toc_scope_stated_argument(tmp_path):
    envelopes_dir = tmp_path / "envelopes"
    _write_envelope(
        envelopes_dir,
        "src1",
        thesis="The thesis.",
        toc=[{"title": "Intro", "children": ["A", "B"]}, {"title": "Conclusion", "children": []}],
        scope="The scope.",
        stated_argument="The restated argument.",
    )

    result = get_envelope("src1", envelopes_dir=envelopes_dir)

    assert result.source_id == "src1"
    assert result.thesis == "The thesis."
    assert result.toc == [
        {"title": "Intro", "children": ["A", "B"]},
        {"title": "Conclusion", "children": []},
    ]
    assert result.scope == "The scope."
    assert result.stated_argument == "The restated argument."


def test_get_envelope_preserves_the_nested_toc_shape_without_flattening(tmp_path):
    envelopes_dir = tmp_path / "envelopes"
    nested_toc = [{"title": "Chapter One", "children": ["Section A", "Section B"]}]
    _write_envelope(envelopes_dir, "src1", toc=nested_toc)

    result = get_envelope("src1", envelopes_dir=envelopes_dir)

    assert result.toc == nested_toc
    assert all(isinstance(entry, dict) for entry in result.toc), (
        "a flat list of strings would mean the pre-#235 toc shape leaked "
        "through instead of the nested {title, children} shape"
    )


def test_get_envelope_on_an_unknown_source_id_raises_not_found(tmp_path):
    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir(parents=True)

    with pytest.raises(EnvelopeNotFoundError) as exc_info:
        get_envelope("does-not-exist", envelopes_dir=envelopes_dir)
    assert "does-not-exist" in str(exc_info.value)


# -- follow_backlinks -----------------------------------------------------------


def test_follow_backlinks_chunk_to_artifact_refs(tmp_path):
    _write_chunk_note(tmp_path / "prose", "c1", artifact_refs=["a1", "a2"])

    assert follow_backlinks("c1", vault_dir=tmp_path) == ["a1", "a2"]


def test_follow_backlinks_artifact_to_cited_by_sorted(tmp_path):
    _write_artifact_note(tmp_path / "artifacts", "a1", cited_by=["c3", "c1"])

    assert follow_backlinks("a1", vault_dir=tmp_path) == ["c1", "c3"]


def test_follow_backlinks_empty_link_list_returns_empty_not_an_error(tmp_path):
    _write_chunk_note(tmp_path / "prose", "c1", artifact_refs=[])
    _write_artifact_note(tmp_path / "artifacts", "a1", cited_by=[])

    assert follow_backlinks("c1", vault_dir=tmp_path) == []
    assert follow_backlinks("a1", vault_dir=tmp_path) == []


def test_follow_backlinks_raises_on_an_id_that_is_neither_chunk_nor_artifact(tmp_path):
    (tmp_path / "prose").mkdir(parents=True)
    (tmp_path / "artifacts").mkdir(parents=True)

    with pytest.raises(BacklinkTargetNotFoundError) as exc_info:
        follow_backlinks("does-not-exist", vault_dir=tmp_path)
    assert "does-not-exist" in str(exc_info.value)


# -- coverage_count ---------------------------------------------------------------


def test_coverage_count_counts_each_chunk_once_per_distinct_polity(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "c1", polities_touched=["Iraq", "Syria"])
    _write_chunk_note(prose_dir, "c2", polities_touched=["Iraq"])
    _write_chunk_note(prose_dir, "c3", polities_touched=["Lebanon"])
    # A chunk that lists the same polity twice must count once, not twice.
    _write_chunk_note(prose_dir, "c4", polities_touched=["Iraq", "Iraq"])

    result = coverage_count(vault_dir=tmp_path)

    assert result == {"Iraq": 3, "Syria": 1, "Lebanon": 1}


def test_coverage_count_over_a_vault_with_no_polities_touched_returns_empty(tmp_path):
    _write_chunk_note(tmp_path / "prose", "c1", polities_touched=[])

    assert coverage_count(vault_dir=tmp_path) == {}


def test_coverage_count_raises_when_vault_dir_is_missing(tmp_path):
    with pytest.raises(MissingVaultDirError):
        coverage_count(vault_dir=tmp_path / "no-such-vault")


# -- LLM-free by construction (slice 02 tools) -----------------------------------


def test_slice_02_tools_run_with_no_llm_client_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")
    prose_dir = tmp_path / "prose"
    _write_chunk_note(
        prose_dir,
        "some-source_1_intro_001",
        polities_touched=["Iraq"],
        artifact_refs=["a1"],
    )
    _write_artifact_note(tmp_path / "artifacts", "a1", cited_by=["some-source_1_intro_001"])
    _write_envelope(tmp_path / "envelopes", "some-source")

    assert query_by_polity("Iraq", vault_dir=tmp_path) == ["some-source_1_intro_001"]
    assert query_by_source("some-source", vault_dir=tmp_path) == ["some-source_1_intro_001"]
    assert follow_backlinks("some-source_1_intro_001", vault_dir=tmp_path) == ["a1"]
    assert coverage_count(vault_dir=tmp_path) == {"Iraq": 1}
    assert get_envelope("some-source", envelopes_dir=tmp_path / "envelopes").source_id == (
        "some-source"
    )
