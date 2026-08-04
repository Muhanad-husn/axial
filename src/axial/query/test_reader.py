"""Inner unit tests for the vault note reader (issues #249/#251): the note
parser, `get_chunk`/`get_artifact` (including their budgeted-filename
resolution), the truncated-id repair lookups, `query_by_source` and
`get_envelope`.

The tag-query cases that used to live here went with `query_by_tag`,
`query_by_polity` and `follow_backlinks` (issue #487, D1/D5) -- the facets
they filtered are deleted, so there is nothing left for them to pin. The name
layer that replaces them is unit-tested in `test_names.py` beside it."""

from __future__ import annotations

import json

import pytest
import yaml

from axial.query import (
    ArtifactNotFoundError,
    ChunkNotFoundError,
    EnvelopeNotFoundError,
    MalformedChunkIdError,
    MalformedNoteError,
    MissingVaultDirError,
    get_artifact,
    get_chunk,
    get_envelope,
    query_by_source,
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
#
# These ids are deliberately SHORT: a real budgeted id runs to ~300 chars,
# but Linux (unlike Windows/NTFS) caps a single path COMPONENT at 255 bytes,
# so a filename that long fails outright on write/exists() on CI (Errno 36,
# ENAMETOOLONG) before the reader logic under test ever runs -- a test-
# portability defect, not a product one (`axial.query.test_reader` CI
# incident, 2026-07-25). Instead, `monkeypatch` lowers
# `axial.paths._WINDOWS_MAX_PATH` (a module-private test seam -- no new
# config key, env var, or CLI flag, and every production call site keeps its
# real 260-char default) far enough below these short ids' own length that
# the budgeting fallback is forced to trigger regardless of the OS or the
# tmp dir's own path length, while the resulting filenames stay well under
# 255 bytes on every OS.

_BUDGET_HASH12 = "0123456789ab"
_BUDGET_SOURCE_ID = f"{'A' * 20}-{_BUDGET_HASH12}"
# Low enough that `path_overage` is positive even for a zero-length
# directory and this module's short stem/slug (see the two tests below),
# so the shrink always fully empties them -- deterministic across OSes and
# tmp_path depths, never dependent on how long the test's own tmp dir is.
_TEST_MAX_PATH = 25

_BUDGET_RECORD_BASE = {
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
_BUDGET_ENVELOPE = {"thesis": "T", "scope": "S"}
_BUDGET_SOURCE_META = {
    "author": {"value": "A", "provenance": "p"},
    "title": {"value": "Ti", "provenance": "p"},
    "date": "unavailable",
}


def test_get_chunk_resolves_a_note_whose_filename_was_budgeted(tmp_path, monkeypatch):
    """The case that is broken today: a note written under a shortened
    on-disk filename must still resolve by its true, full `chunk_id`.

    Resolves via `_resolve_chunk_path` directly, not the full `get_chunk`
    (which also strictly parses the tag-pass axis block, `axial.vault.
    build_frontmatter` no longer writes -- issue #414, D4 -- and is
    query/reader.py's own read-side concern, out of this issue's scope,
    pending issue #411): the path-resolution/budgeting contract this test
    pins is independent of frontmatter shape."""
    import axial.paths
    from axial.query.reader import _resolve_chunk_path
    from axial.vault import write_chunk_note

    monkeypatch.setattr(axial.paths, "_WINDOWS_MAX_PATH", _TEST_MAX_PATH)

    slug = "b" * 20
    chunk_id = f"{_BUDGET_SOURCE_ID}_1_{slug}_001"
    record = {**_BUDGET_RECORD_BASE, "chunk_id": chunk_id}
    vault_dir = tmp_path / "vault"

    note_path = write_chunk_note(
        record, _BUDGET_ENVELOPE, _BUDGET_SOURCE_META, vault_dir, source_id=_BUDGET_SOURCE_ID
    )
    # Sanity: the writer really did shorten the filename (not just happened
    # to already fit) -- otherwise this test would not exercise the fallback.
    assert note_path.name != f"{chunk_id}.md"
    assert not (vault_dir / "prose" / f"{chunk_id}.md").exists()

    resolved_path = _resolve_chunk_path(chunk_id, vault_dir)

    assert resolved_path == note_path
    assert resolved_path.is_file()


def test_get_chunk_fast_path_resolves_directly_without_needing_chunk_id_grammar(tmp_path):
    """No regression on the direct `<chunk_id>.md` path (~97.8% of real
    notes): resolution must succeed even for an id that would raise
    `MalformedChunkIdError` if the fallback's `source_id_from_chunk_id`
    parse ran on it -- proving the fast, direct hit is tried FIRST and the
    fallback is never even consulted when it exists."""
    _write_chunk_note(tmp_path / "prose", "not-shaped-like-a-real-chunk-id")

    note = get_chunk("not-shaped-like-a-real-chunk-id", vault_dir=tmp_path)

    assert note.chunk_id == "not-shaped-like-a-real-chunk-id"


def test_get_artifact_resolves_a_note_whose_filename_was_budgeted(tmp_path, monkeypatch):
    """The `get_artifact` counterpart of the budgeted-chunk-note case."""
    import axial.paths
    from axial.vault import write_artifact_note

    monkeypatch.setattr(axial.paths, "_WINDOWS_MAX_PATH", _TEST_MAX_PATH)

    artifact_id = f"{_BUDGET_SOURCE_ID}_art_1.2"
    record = {
        "artifact_id": artifact_id,
        "source_id": _BUDGET_SOURCE_ID,
        "section": "Introduction",
        "caption": "A caption.",
    }
    vault_dir = tmp_path / "vault"

    note_path = write_artifact_note(record, vault_dir)
    assert note_path.name != f"{artifact_id}.md"
    assert not (vault_dir / "artifacts" / f"{artifact_id}.md").exists()

    note = get_artifact(artifact_id, vault_dir=vault_dir)

    assert note.artifact_id == artifact_id
    # `write_artifact_note` no longer emits `artifact_role` (issue #429);
    # this test's purpose is filename-budgeting, proven by `caption` (the
    # field the current write path actually carries) round-tripping intact.
    assert note.caption == "A caption."


def test_get_artifact_fast_path_resolves_directly_without_needing_artifact_id_grammar(tmp_path):
    """No regression on `get_artifact`'s direct path: an id that does not
    even carry the `_art_<order>` shape (so the fallback's source_id parse
    can never succeed on it) still resolves via the direct hit."""
    _write_artifact_note(tmp_path / "artifacts", "not-shaped-like-an-artifact-id")

    note = get_artifact("not-shaped-like-an-artifact-id", vault_dir=tmp_path)

    assert note.artifact_id == "not-shaped-like-an-artifact-id"


# -- find_chunk_ids_ending_with / find_artifact_ids_ending_with ---------------
# The `axial.analyze.synthesis` truncated-citation repair's lookup: a
# suffix scan over a frontmatter-built id index, used only when an exact
# match already failed. Candidate discovery is over TRUE ids, never
# filenames (fix/chunk-id-index-resolution) -- a P3-02 live brief died
# because a budgeted filename dropped the very tail the model cited (its
# stem was chopped mid-word), so a filename-keyed scan found zero
# candidates even though the true chunk_id ended with the cited suffix.


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


# -- find_chunk_ids_starting_with / find_artifact_ids_starting_with -----------
# The mirror image of the suffix lookups (issue #524): the model emitted the
# HEAD of a long id and dropped the slug and index. S-05 died on
# `caspersen-2012-fbc0efe4fffc_18`, whose real note is
# `caspersen-2012-fbc0efe4fffc_18_unrecognized-states-...-system_001`. Same
# index, same 0/1/2+ contract; the caller supplies the trailing `_` that makes
# the boundary a component separator.


def test_find_chunk_ids_starting_with_returns_the_sole_prefix_match(tmp_path):
    from axial.query.reader import find_chunk_ids_starting_with

    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "caspersen-2012-fbc0efe4fffc_18_unrecognized-states_001")
    _write_chunk_note(prose_dir, "caspersen-2012-fbc0efe4fffc_19_frozen-conflicts_001")

    assert find_chunk_ids_starting_with("caspersen-2012-fbc0efe4fffc_18_", vault_dir=tmp_path) == [
        "caspersen-2012-fbc0efe4fffc_18_unrecognized-states_001"
    ]


def test_find_chunk_ids_starting_with_does_not_match_a_longer_section_number(tmp_path):
    """The boundary case the trailing `_` exists for: section 18 and section
    180 share a numeric prefix, and only the separator keeps `_18` from
    reaching `_180`."""
    from axial.query.reader import find_chunk_ids_starting_with

    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "src-digest_18_a-section_001")
    _write_chunk_note(prose_dir, "src-digest_180_another-section_001")

    assert find_chunk_ids_starting_with("src-digest_18_", vault_dir=tmp_path) == [
        "src-digest_18_a-section_001"
    ]


def test_find_chunk_ids_starting_with_returns_every_match_when_ambiguous(tmp_path):
    """One section usually holds several chunks, so a head-truncated id is
    genuinely ambiguous more often than a tail-truncated one. The lookup
    reports both and lets the caller refuse."""
    from axial.query.reader import find_chunk_ids_starting_with

    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "src-digest_18_a-section_001")
    _write_chunk_note(prose_dir, "src-digest_18_a-section_002")

    assert find_chunk_ids_starting_with("src-digest_18_", vault_dir=tmp_path) == [
        "src-digest_18_a-section_001",
        "src-digest_18_a-section_002",
    ]


def test_find_chunk_ids_starting_with_returns_empty_when_no_match(tmp_path):
    from axial.query.reader import find_chunk_ids_starting_with

    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "src-digest_18_a-section_001")

    assert find_chunk_ids_starting_with("not-a-real-prefix_", vault_dir=tmp_path) == []


def test_find_chunk_ids_starting_with_returns_true_chunk_ids_not_filename_stems(tmp_path):
    """Same reason as the suffix lookup: a budgeted filename is a display
    artifact, so candidate discovery reads frontmatter ids."""
    from axial.query.reader import find_chunk_ids_starting_with

    prose_dir = tmp_path / "prose"
    true_id = "Some Long Human-Readable Title - digest123_26_a-section_012"
    _write_chunk_note(prose_dir, true_id, filename="Some Short-digest123_26.md")

    assert find_chunk_ids_starting_with(
        "Some Long Human-Readable Title - digest123_26_", vault_dir=tmp_path
    ) == [true_id]


def test_find_artifact_ids_starting_with_returns_the_sole_prefix_match(tmp_path):
    from axial.query.reader import find_artifact_ids_starting_with

    artifacts_dir = tmp_path / "artifacts"
    _write_artifact_note(artifacts_dir, "Long Human Title - digest123_art_3")
    _write_artifact_note(artifacts_dir, "Other Source - digest456_art_1")

    assert find_artifact_ids_starting_with("Long Human Title - digest123_", vault_dir=tmp_path) == [
        "Long Human Title - digest123_art_3"
    ]


def test_find_artifact_ids_ending_with_returns_the_sole_suffix_match(tmp_path):
    from axial.query.reader import find_artifact_ids_ending_with

    artifacts_dir = tmp_path / "artifacts"
    _write_artifact_note(artifacts_dir, "Long Human Title - digest123_artifact_003")

    assert find_artifact_ids_ending_with("digest123_artifact_003", vault_dir=tmp_path) == [
        "Long Human Title - digest123_artifact_003"
    ]


# -- P3-02: a budgeted filename can drop the very tail the model cited --------
#
# PR #394 fixed candidate discovery by resolving a filename-scan's candidates
# to their true ids, but the scan itself was still filename-keyed: a suffix
# that is a real chunk_id's tail but NOT also a tail of that note's
# (separately, and differently) shortened on-disk filename never surfaced as
# a candidate at all. `_shrink_pieces` (axial.paths) truncates the readable
# source stem from its END, so a stem ending in a distinctive marker (here,
# mirroring the real P3-02 failure, "libgen.li" immediately before the
# content-hash suffix) can be chopped mid-word, dropping that marker from
# the filename while the frontmatter chunk_id/artifact_id -- untouched by
# budgeting -- still carries it in full.

_P3_02_PREFIX = "Colin Turner (Editor) - Nationalism and the ("


def test_find_chunk_ids_ending_with_finds_a_suffix_the_budgeted_filename_dropped(tmp_path):
    """The P3-02 case: the cited suffix is a real tail of `chunk_id` but is
    NOT a tail of the note's shortened on-disk filename (the filename's
    truncated stem, "Edinb", lost "urgh University Press) - libgen.li" --
    including the "libgen.li-" the model's citation started with)."""
    from axial.query.reader import find_chunk_ids_ending_with

    true_id = (
        f"{_P3_02_PREFIX}Edinburgh University Press) - libgen.li-5f35a47d9657"
        "_28_a-religious-ordering-of-society-within-a-secular-nation-state-form_010"
    )
    cited_tail = (
        "libgen.li-5f35a47d9657"
        "_28_a-religious-ordering-of-society-within-a-secular-nation-state-form_010"
    )
    filename = (
        f"{_P3_02_PREFIX}Edinb-5f35a47d9657"
        "_28_a-religious-ordering-of-society-within-a-secular-nation-state-form_010.md"
    )
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, true_id, filename=filename)

    # Sanity: this really is the broken case -- the filename does NOT end
    # with the cited tail, only the true id does.
    assert not filename[: -len(".md")].endswith(cited_tail)
    assert true_id.endswith(cited_tail)

    assert find_chunk_ids_ending_with(cited_tail, vault_dir=tmp_path) == [true_id]


def test_find_artifact_ids_ending_with_finds_a_suffix_the_budgeted_filename_dropped(tmp_path):
    """The `find_artifact_ids_ending_with` counterpart of the P3-02 case."""
    from axial.query.reader import find_artifact_ids_ending_with

    true_id = f"{_P3_02_PREFIX}Edinburgh University Press) - libgen.li-5f35a47d9657_art_3"
    cited_tail = "libgen.li-5f35a47d9657_art_3"
    filename = f"{_P3_02_PREFIX}Edinb-5f35a47d9657_art_3.md"
    artifacts_dir = tmp_path / "artifacts"
    _write_artifact_note(artifacts_dir, true_id, filename=filename)

    assert not filename[: -len(".md")].endswith(cited_tail)
    assert true_id.endswith(cited_tail)

    assert find_artifact_ids_ending_with(cited_tail, vault_dir=tmp_path) == [true_id]


def test_find_chunk_ids_ending_with_still_raises_via_two_or_more_matches(tmp_path):
    """The existing exactly-one-else-ambiguous rule survives the switch to a
    frontmatter-built index: `find_chunk_ids_ending_with` itself just
    returns every match (its caller, `axial.analyze.synthesis`, is the one
    that raises `UnresolvableGroundError` on 2+ or 0 -- see
    test_synthesis.py's
    `test_a_ref_id_matching_two_or_more_real_ids_by_suffix_still_raises`)."""
    from axial.query.reader import find_chunk_ids_ending_with

    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "source-one_25_introduction_001")
    _write_chunk_note(prose_dir, "source-two_25_introduction_001")

    assert find_chunk_ids_ending_with("25_introduction_001", vault_dir=tmp_path) == [
        "source-one_25_introduction_001",
        "source-two_25_introduction_001",
    ]


def test_find_chunk_ids_ending_with_still_returns_empty_for_no_match(tmp_path):
    """The empty-match counterpart, same rationale as the test above (the
    caller's `UnresolvableGroundError` on zero matches is pinned in
    test_synthesis.py's
    `test_a_ref_id_matching_no_real_id_by_suffix_still_raises`)."""
    from axial.query.reader import find_chunk_ids_ending_with

    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "source-one_25_introduction_001")

    assert find_chunk_ids_ending_with("zzz_totally_invented_999", vault_dir=tmp_path) == []


def test_get_chunk_fast_path_does_not_build_the_suffix_index(tmp_path):
    """`get_chunk`'s direct-then-budgeted-name resolution must never build
    the (comparatively expensive, whole-corpus) suffix index -- observable
    here as the resolved vault_dir never gaining an entry in the module's
    process-lifetime index cache."""
    from axial.query import reader

    _write_chunk_note(tmp_path / "prose", "c1")
    resolved_vault_dir = tmp_path.resolve()
    assert resolved_vault_dir not in reader._CHUNK_ID_INDEX_CACHE

    note = get_chunk("c1", vault_dir=tmp_path)

    assert note.chunk_id == "c1"
    assert resolved_vault_dir not in reader._CHUNK_ID_INDEX_CACHE


def test_chunk_id_index_is_built_at_most_once_across_repeated_suffix_lookups(tmp_path, monkeypatch):
    """A rebuild-per-call would be pathological inside a retrieval loop over
    the real ~18k-note corpus: the index must be cached for the process
    lifetime and built at most once per vault_dir, observable here by
    counting `_read_id_only` calls (one per note on the first lookup, zero
    more on the second)."""
    from axial.query import reader

    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "source-one_25_introduction_001")
    _write_chunk_note(prose_dir, "source-two_25_introduction_002")

    calls = []
    original = reader._read_id_only

    def counting(path, id_field):
        calls.append(path)
        return original(path, id_field)

    monkeypatch.setattr(reader, "_read_id_only", counting)

    first = reader.find_chunk_ids_ending_with("introduction_001", vault_dir=tmp_path)
    calls_after_first = len(calls)
    second = reader.find_chunk_ids_ending_with("introduction_002", vault_dir=tmp_path)

    assert first == ["source-one_25_introduction_001"]
    assert second == ["source-two_25_introduction_002"]
    assert calls_after_first == 2  # one _read_id_only call per note, built once
    assert len(calls) == calls_after_first  # the second lookup did not rescan


# -- LLM-free by construction --------------------------------------------------


def test_module_imports_and_runs_with_no_llm_client_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "c1")

    # None of these should ever touch an LLM client; AXIAL_LLM_PROVIDER=explode
    # makes any hidden `.complete()` call crash loudly rather than pass silently.
    assert get_chunk("c1", vault_dir=tmp_path).chunk_id == "c1"


# =============================================================================
# query_by_source / get_envelope (issue #251)
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


def test_query_by_source_excludes_a_back_matter_note(tmp_path):
    """Issue #661: a live run reached an acknowledgments page through this
    exact tool -- `query_by_source` lists every chunk under a source
    straight off disk, unfiltered, which the store-backed tools never went
    through at all. A note whose own `section` is non-substantive
    front/back-matter (`axial.back_matter.is_evidence_back_matter`) must
    never come back as one of that source's citable chunks, while an
    ordinary body note from the same source still does."""
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "srcA_0_intro_001", section="Introduction")
    _write_chunk_note(prose_dir, "srcA_9_acknowledgments_001", section="Acknowledgments")

    result = query_by_source("srcA", vault_dir=tmp_path)

    assert result == ["srcA_0_intro_001"]


def test_query_by_source_raises_when_the_vault_dir_does_not_exist(tmp_path):
    """A missing or typo'd `vault_dir` is a caller bug, not an empty corpus
    (`_iter_chunk_frontmatter`'s own contract)."""
    with pytest.raises(MissingVaultDirError):
        query_by_source("srcA", vault_dir=tmp_path / "no-such-vault")


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


# -- LLM-free by construction (the whole surviving reader) -----------------------


def test_every_reader_tool_runs_with_no_llm_client_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "some-source_1_intro_001")
    _write_artifact_note(tmp_path / "artifacts", "a1", cited_by=["some-source_1_intro_001"])
    _write_envelope(tmp_path / "envelopes", "some-source")

    assert query_by_source("some-source", vault_dir=tmp_path) == ["some-source_1_intro_001"]
    assert get_chunk("some-source_1_intro_001", vault_dir=tmp_path).chunk_id == (
        "some-source_1_intro_001"
    )
    assert get_artifact("a1", vault_dir=tmp_path).artifact_id == "a1"
    assert get_envelope("some-source", envelopes_dir=tmp_path / "envelopes").source_id == (
        "some-source"
    )
