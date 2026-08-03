"""Outer acceptance test for issue #411 (Phase A v1 slice 06 -- Materialize:
the vault writer, spec §7.17, P0-8).

Locked behavioural contract, read off `specs/PRODUCT.md` §7.17/§7.2/Appendix H
and D11 (`docs/DECISIONS.md`, `plans/phase-a-v1/README.md`):

Given slice 02's per-note interrogation answers on disk
      (`data/answers/<source_id>.jsonl`) and slice 05's reversible alias map
      (`data/names/alias_map.json`, `axial.merge_names`)
When  the operator runs `axial names materialize`
Then  every chunk that has an interrogation answer record gets a prose note
      carrying that answer record as frontmatter -- in place of the retired
      tag/xref axis block -- with NO outbound links anywhere in the note
      (D11: link direction is name-page -> note only)
And   one name page exists per surviving canonical name, at the expected
      path, carrying `name`/`kind`/`aliases`/`member_count` in frontmatter
      and every member note as an `[[chunk_id]]` link in the body, with
      author, year and one-sentence claim
And   a name whose members span two different sources still gets ONE page
      whose member links cover both books (the whole point of the graph)
And   a name whose `kind` is `figure`/`table` additionally links to the
      artifact note its surface names, resolved from the artifacts pass's
      own persisted captions (`data/artifacts/<source_id>.jsonl`) -- the
      honest replacement for the deleted table-reference hunt (D5), and the
      join this spec leaves as an Open Question for this slice to confirm
And   every persisted artifacts-pass record gets an artifact note under
      `data/vault/artifacts/`, via the existing, untouched
      `axial.vault.write_artifact_note` (issue #429's shape)
And   re-running against an unchanged alias map reproduces byte-identical
      output and rewrites nothing; a changed alias map rewrites only the
      name pages a merge decision actually touched, never a prose note
And   zero LLM (text-generation) calls happen anywhere in this pass --
      Materialize is LLM-free by construction (D11)

Seam decision
-----------------------------------------------------------------------
Fixture files are written directly in slice 02/04/05's own documented
on-disk shapes (`axial.interrogate.build_answer_record`,
`axial.names.write_inventory`, `axial.merge_names.write_alias_map`), not
produced by running those passes for real -- each already has its own
acceptance test; this one's subject is what Materialize does with them.
One CLI-level smoke test at the bottom exercises the real `axial names
materialize` subprocess end to end, poisoned against any LLM call, to prove
the subcommand itself is wired -- everything else calls `run_materialize`
directly, which is faster and the same code path the CLI invokes.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from axial.materialize import (
    MissingAliasMapError,
    find_artifact_links,
    load_alias_map,
    load_inventory,
    member_chunk_ids_for_node,
    run_materialize,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _answer_record(chunk_id: str, source_id: str, section: str, **overrides) -> dict:
    answers = {
        "about": ["x"],
        "claim": "x",
        "move": "x",
        "ranges_over": "not-in-passage",
        "stops_holding": "not-in-passage",
        "position_of": "not-in-passage",
        "arguing_against": [],
        "names": [],
        "citations": [],
        "mechanism": "not-in-passage",
        "evidence": "not-in-passage",
        "comparison": "not-in-passage",
        "defines": [],
        "uses": [],
        "concedes": "not-in-passage",
        "assumes": "not-in-passage",
    }
    answers.update(overrides)
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "section": section,
        "pass": "note_interrogate",
        "model": "stub",
        "frame_version": "0.1",
        "answered_at": "2026-01-01T00:00:00Z",
        "answers": answers,
    }


def _build_fixture(root: Path) -> None:
    """Two sources: `src1` (two notes, one naming a person and a table) and
    `src2` (one note naming the same person) -- so "Kevin Attell" is a
    cross-book name and "Table 3.1" is a figure/table name resolvable to
    `src1`'s own artifact record."""
    # -- src1 --
    _write_jsonl(
        root / "data" / "chunks" / "src1.jsonl",
        [
            {
                "chunk_id": "src1_000_intro_001",
                "section": "Introduction",
                "section_order": "0",
                "text": "Kevin Attell discusses Table 3.1 in this passage.",
            },
            {
                "chunk_id": "src1_001_body_002",
                "section": "Introduction",
                "section_order": "1",
                "text": "A second, unrelated passage with no names.",
            },
        ],
    )
    _write_json(
        root / "data" / "envelopes" / "src1.json",
        {
            "source_id": "src1",
            "thesis": "Thesis one.",
            "toc": [{"title": "Chapter 1", "children": ["Introduction"]}],
            "scope": "Scope one.",
            "stated_argument": "Argument one.",
        },
    )
    _write_json(
        root / "data" / "source_meta" / "src1.json",
        {
            "author": {"value": "Author One", "provenance": "title page"},
            "title": {"value": "Book One", "provenance": "embedded metadata"},
            "date": {"value": 2001, "provenance": "embedded metadata"},
        },
    )
    _write_jsonl(
        root / "data" / "answers" / "src1.jsonl",
        [
            _answer_record(
                "src1_000_intro_001",
                "src1",
                "Introduction",
                claim="State formation through war.",
                names=[
                    {"name": "Kevin Attell", "kind": "person"},
                    {"name": "Table 3.1", "kind": "table"},
                ],
            ),
            _answer_record("src1_001_body_002", "src1", "Introduction", claim="Unrelated claim."),
        ],
    )
    _write_jsonl(
        root / "data" / "artifacts" / "src1.jsonl",
        [
            {
                "artifact_id": "src1_art_3.1",
                "source_id": "src1",
                "section": "Chapter 1",
                "caption": "Table 3.1: Employment rates by sector",
            }
        ],
    )

    # -- src2 --
    _write_jsonl(
        root / "data" / "chunks" / "src2.jsonl",
        [
            {
                "chunk_id": "src2_000_intro_001",
                "section": "Introduction",
                "section_order": "0",
                "text": "Kevin Attell is cited here too.",
            }
        ],
    )
    _write_json(
        root / "data" / "envelopes" / "src2.json",
        {
            "source_id": "src2",
            "thesis": "Thesis two.",
            "toc": [{"title": "Chapter 1", "children": ["Introduction"]}],
            "scope": "Scope two.",
            "stated_argument": "Argument two.",
        },
    )
    _write_json(
        root / "data" / "source_meta" / "src2.json",
        {
            "author": {"value": "Author Two", "provenance": "title page"},
            "title": {"value": "Book Two", "provenance": "embedded metadata"},
            "date": {"value": 2002, "provenance": "embedded metadata"},
        },
    )
    _write_jsonl(
        root / "data" / "answers" / "src2.jsonl",
        [
            _answer_record(
                "src2_000_intro_001",
                "src2",
                "Introduction",
                claim="Bellicist state building.",
                names=[{"name": "Kevin Attell", "kind": "person"}],
            )
        ],
    )

    # -- slice 04's inventory + slice 05's alias map --
    _write_jsonl(
        root / "data" / "names" / "inventory.jsonl",
        [
            {
                "surface": "Kevin Attell",
                "kind": "person",
                "count": 2,
                "chunk_ids": ["src1_000_intro_001", "src2_000_intro_001"],
            },
            {
                "surface": "Table 3.1",
                "kind": "table",
                "count": 1,
                "chunk_ids": ["src1_000_intro_001"],
            },
        ],
    )
    _write_json(
        root / "data" / "names" / "alias_map.json",
        {
            "version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "nodes": [
                {"canonical": "Kevin Attell", "kind": "person", "aliases": []},
                {"canonical": "Table 3.1", "kind": "table", "aliases": []},
            ],
        },
    )


def _dirs(root: Path) -> dict:
    return {
        "alias_map_path": root / "data" / "names" / "alias_map.json",
        "inventory_path": root / "data" / "names" / "inventory.jsonl",
        "answers_dir": root / "data" / "answers",
        "chunks_dir": root / "data" / "chunks",
        "envelopes_dir": root / "data" / "envelopes",
        "source_meta_dir": root / "data" / "source_meta",
        "artifacts_dir": root / "data" / "artifacts",
        "vault_dir": root / "data" / "vault",
    }


def _read_note(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    end = lines.index("---", 1)
    frontmatter = yaml.safe_load("\n".join(lines[1:end]))
    body = "\n".join(lines[end + 1 :])
    return frontmatter, body


# -- inner unit tests: the small, pure joins ----------------------------------


def test_member_chunk_ids_for_node_unions_canonical_and_alias_chunk_ids():
    inventory = {
        "A": {"kind": "person", "count": 1, "chunk_ids": ["c1", "c2"]},
        "B": {"kind": "person", "count": 1, "chunk_ids": ["c2", "c3"]},
    }
    node = {"canonical": "A", "aliases": ["B"]}
    assert member_chunk_ids_for_node(node, inventory) == ["c1", "c2", "c3"]


def test_find_artifact_links_matches_caption_substring_within_the_same_source_only():
    artifacts_by_source = {
        "src1": [{"artifact_id": "a1", "caption": "Table 3.1: Employment rates"}],
        "src2": [{"artifact_id": "a2", "caption": "Table 3.1: A different book's own table"}],
    }
    # Only src1's member chunk names Table 3.1 -- src2's own same-captioned
    # table must never be pulled in.
    matches = find_artifact_links(
        ["Table 3.1"], ["c_src1"], {"c_src1": "src1"}, artifacts_by_source
    )
    assert matches == ["a1"]


def test_find_artifact_links_refuses_a_numeric_prefix_collision():
    """Real-corpus regression (2026-07-28): a plain substring match let
    "Figure 9.1" match inside "Figure 9.10"'s caption -- 10 of 292 real
    figure/table links (3.4%) were exactly this. The fix is a boundary rule
    (the character right after the match must not be another digit), not a
    threshold, and it must not touch a genuine, non-colliding match."""
    artifacts_by_source = {
        "src1": [
            {"artifact_id": "a_prefix", "caption": "Figure 9.10: A completely different figure"},
            {"artifact_id": "a_exact", "caption": "Figure 9.1: The actual figure this name means"},
        ],
    }
    matches = find_artifact_links(
        ["Figure 9.1"], ["c_src1"], {"c_src1": "src1"}, artifacts_by_source
    )
    assert matches == ["a_exact"]


def test_load_alias_map_raises_when_absent(tmp_path):
    with pytest.raises(MissingAliasMapError):
        load_alias_map(tmp_path / "no_such_file.json")


def test_load_inventory_returns_empty_when_absent(tmp_path):
    assert load_inventory(tmp_path / "no_such_file.jsonl") == {}


# -- the whole pass ------------------------------------------------------------


def test_materialize_writes_prose_notes_with_answers_and_no_outbound_links(tmp_path):
    _build_fixture(tmp_path)
    result = run_materialize(**_dirs(tmp_path))

    assert result["notes_written"] == 3
    assert result["notes_skipped_no_answer"] == 0

    path = tmp_path / "data" / "vault" / "prose" / "src1_000_intro_001.md"
    frontmatter, body = _read_note(path)

    assert frontmatter["chunk_id"] == "src1_000_intro_001"
    assert frontmatter["answers"]["claim"] == "State formation through war."
    assert frontmatter["answers"]["names"] == [
        {"name": "Kevin Attell", "kind": "person"},
        {"name": "Table 3.1", "kind": "table"},
    ]
    assert frontmatter["frame_version"] == "0.1"
    assert frontmatter["interrogated"]["model"] == "stub"
    assert frontmatter["chapter"] == "Chapter 1"

    # The retired tag-axis block is gone (D4/D9/#414), never re-appears.
    for retired_field in (
        "schema_version",
        "role_in_argument",
        "field",
        "claim_type",
        "theory_school",
        "empirical_scope",
        "artifact_refs",
        "cited_by",
    ):
        assert retired_field not in frontmatter

    # D11: no outbound link anywhere in the note -- not in the body, and not
    # smuggled into the frontmatter's own `answers.names` (plain strings).
    full_text = path.read_text(encoding="utf-8")
    assert "[[" not in full_text
    assert isinstance(frontmatter["answers"]["names"][0]["name"], str)


def test_materialize_skips_a_chunk_with_no_answer_record(tmp_path):
    _build_fixture(tmp_path)
    # A third chunk in src1 that was never interrogated (e.g. a garble skip).
    chunks_path = tmp_path / "data" / "chunks" / "src1.jsonl"
    records = [json.loads(line) for line in chunks_path.read_text("utf-8").splitlines()]
    records.append({"chunk_id": "src1_002_body_003", "section": "Introduction", "text": "x"})
    with chunks_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    result = run_materialize(**_dirs(tmp_path))

    assert result["notes_skipped_no_answer"] == 1
    assert not (tmp_path / "data" / "vault" / "prose" / "src1_002_body_003.md").is_file()


def test_materialize_writes_one_artifact_note_per_persisted_record(tmp_path):
    _build_fixture(tmp_path)
    result = run_materialize(**_dirs(tmp_path))

    assert result["artifact_notes_written"] == 1
    path = tmp_path / "data" / "vault" / "artifacts" / "src1_art_3.1.md"
    frontmatter, _body = _read_note(path)
    assert frontmatter["artifact_id"] == "src1_art_3.1"
    assert frontmatter["caption"] == "Table 3.1: Employment rates by sector"
    assert "cited_by" not in frontmatter


def test_name_page_carries_cross_book_members_as_links_with_author_year_claim(tmp_path):
    _build_fixture(tmp_path)
    run_materialize(**_dirs(tmp_path))

    path = tmp_path / "data" / "vault" / "names" / "Kevin Attell.md"
    assert path.is_file(), f"expected a name page at {path}"
    frontmatter, body = _read_note(path)

    assert frontmatter == {
        "name": "Kevin Attell",
        "kind": "person",
        "aliases": [],
        "member_count": 2,
    }
    assert "[[src1_000_intro_001]]" in body
    assert "[[src2_000_intro_001]]" in body
    assert "Author One" in body and "2001" in body
    assert "Author Two" in body and "2002" in body
    assert "State formation through war." in body
    assert "Bellicist state building." in body


def test_materialize_writes_a_door_index_with_source_count(tmp_path):
    """Issue #634: Materialize writes `<vault_dir>/names.jsonl`, a sibling of
    `names/` (never a member of it), one row per surviving name page,
    carrying `source_count` -- the number of distinct sources the page's
    members span, which the frontmatter alone does not carry."""
    _build_fixture(tmp_path)
    run_materialize(**_dirs(tmp_path))

    vault_dir = tmp_path / "data" / "vault"
    index_path = vault_dir / "names.jsonl"
    assert index_path.is_file()
    assert index_path.parent == vault_dir, "the index is a sibling of names/, not inside it"

    rows = {
        row["name"]: row
        for row in (
            json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()
        )
    }

    # "Kevin Attell" is named in src1 AND src2 -- two distinct sources.
    assert rows["Kevin Attell"]["member_count"] == 2
    assert rows["Kevin Attell"]["source_count"] == 2
    assert rows["Kevin Attell"]["kind"] == "person"
    assert rows["Kevin Attell"]["filename"] == "Kevin Attell.md"

    # "Table 3.1" is named only in src1 -- one source.
    assert rows["Table 3.1"]["member_count"] == 1
    assert rows["Table 3.1"]["source_count"] == 1


def test_figure_table_name_page_links_the_matching_artifact_note(tmp_path):
    _build_fixture(tmp_path)
    run_materialize(**_dirs(tmp_path))

    path = tmp_path / "data" / "vault" / "names" / "Table 3.1.md"
    frontmatter, body = _read_note(path)

    assert frontmatter["kind"] == "table"
    assert frontmatter["member_count"] == 1
    assert "[[src1_art_3.1]]" in body
    assert "[[src1_000_intro_001]]" in body


def _build_cross_source_locator_fixture(root: Path) -> None:
    """Issue #445: "Table 4.1" named in TWO unrelated books -- the actual
    bug (identical locator surface strings collapsing across sources) and
    the fix under test (each book's own "Table 4.1" gets its own name page,
    linking only its own book's own artifact note)."""
    for source_id, artifact_caption in (
        ("src_a", "Table 4.1: A's own employment data"),
        ("src_b", "Table 4.1: B's own displacement figures"),
    ):
        chunk_id = f"{source_id}_000_intro_001"
        _write_jsonl(
            root / "data" / "chunks" / f"{source_id}.jsonl",
            [{"chunk_id": chunk_id, "section": "Introduction", "section_order": "0", "text": "x"}],
        )
        _write_json(
            root / "data" / "envelopes" / f"{source_id}.json",
            {
                "source_id": source_id,
                "thesis": "x",
                "toc": [{"title": "Chapter 1", "children": ["Introduction"]}],
                "scope": "x",
                "stated_argument": "x",
            },
        )
        _write_json(
            root / "data" / "source_meta" / f"{source_id}.json",
            {
                "author": {"value": f"Author {source_id}", "provenance": "title page"},
                "title": {"value": f"Book {source_id}", "provenance": "embedded metadata"},
                "date": {"value": 2020, "provenance": "embedded metadata"},
            },
        )
        _write_jsonl(
            root / "data" / "answers" / f"{source_id}.jsonl",
            [
                _answer_record(
                    chunk_id,
                    source_id,
                    "Introduction",
                    claim="A claim.",
                    names=[{"name": "Table 4.1", "kind": "table"}],
                )
            ],
        )
        _write_jsonl(
            root / "data" / "artifacts" / f"{source_id}.jsonl",
            [
                {
                    "artifact_id": f"{source_id}_art_4.1",
                    "source_id": source_id,
                    "section": "Chapter 1",
                    "caption": artifact_caption,
                }
            ],
        )

    # What `axial names build` + `axial names merge` now produce for this
    # corpus (issue #445): "Table 4.1" spans two sources, so each source
    # gets its own scoped inventory entry and its own un-aliased node --
    # never one node fused across both books.
    _write_jsonl(
        root / "data" / "names" / "inventory.jsonl",
        [
            {
                "surface": "Table 4.1 (src_a)",
                "kind": "table",
                "count": 1,
                "chunk_ids": ["src_a_000_intro_001"],
            },
            {
                "surface": "Table 4.1 (src_b)",
                "kind": "table",
                "count": 1,
                "chunk_ids": ["src_b_000_intro_001"],
            },
        ],
    )
    _write_json(
        root / "data" / "names" / "alias_map.json",
        {
            "version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "nodes": [
                {"canonical": "Table 4.1 (src_a)", "kind": "table", "aliases": []},
                {"canonical": "Table 4.1 (src_b)", "kind": "table", "aliases": []},
            ],
        },
    )


def test_source_scoped_locator_names_each_link_only_their_own_artifact(tmp_path):
    _build_cross_source_locator_fixture(tmp_path)

    result = run_materialize(**_dirs(tmp_path))

    assert result["name_pages"] == 2
    names_dir = tmp_path / "data" / "vault" / "names"
    page_a = names_dir / "Table 4.1 (src_a).md"
    page_b = names_dir / "Table 4.1 (src_b).md"
    assert page_a.is_file(), sorted(p.name for p in names_dir.glob("*.md"))
    assert page_b.is_file(), sorted(p.name for p in names_dir.glob("*.md"))

    frontmatter_a, body_a = _read_note(page_a)
    frontmatter_b, body_b = _read_note(page_b)

    assert frontmatter_a["member_count"] == 1
    assert frontmatter_b["member_count"] == 1
    # Each book's own name page links its own artifact note, never the
    # other book's identically-numbered one -- the whole point of scoping.
    assert "[[src_a_art_4.1]]" in body_a
    assert "[[src_b_art_4.1]]" not in body_a
    assert "[[src_b_art_4.1]]" in body_b
    assert "[[src_a_art_4.1]]" not in body_b


def test_rerun_over_unchanged_input_is_byte_identical_and_rewrites_nothing(tmp_path):
    _build_fixture(tmp_path)
    run_materialize(**_dirs(tmp_path))

    names_dir = tmp_path / "data" / "vault" / "names"
    before = {path.name: path.read_bytes() for path in sorted(names_dir.glob("*.md"))}

    second = run_materialize(**_dirs(tmp_path))

    after = {path.name: path.read_bytes() for path in sorted(names_dir.glob("*.md"))}
    assert before == after
    assert second["name_pages_written"] == 0
    assert second["name_pages_unchanged"] == 2
    assert second["name_pages_deleted"] == 0


def test_a_changed_alias_map_rewrites_only_the_affected_name_page_never_a_note(tmp_path):
    _build_fixture(tmp_path)
    run_materialize(**_dirs(tmp_path))

    # A third, wholly unrelated node -- present from the start of the
    # "changed" state below, so it is the control: present in both runs,
    # touched by neither edit, and must come out byte-identical.
    alias_map_path = tmp_path / "data" / "names" / "alias_map.json"
    alias_map = json.loads(alias_map_path.read_text(encoding="utf-8"))
    alias_map["nodes"].append(
        {"canonical": "Institution X", "kind": "institution/group", "aliases": []}
    )
    alias_map_path.write_text(json.dumps(alias_map), encoding="utf-8")
    run_materialize(**_dirs(tmp_path))

    prose_path = tmp_path / "data" / "vault" / "prose" / "src1_000_intro_001.md"
    prose_before = prose_path.read_bytes()
    table_page = tmp_path / "data" / "vault" / "names" / "Table 3.1.md"
    control_page = tmp_path / "data" / "vault" / "names" / "Institution X.md"
    control_before = control_page.read_bytes()

    # Merge "Table 3.1" as an alias of "Kevin Attell" -- an arbitrary but
    # valid alias-map edit that changes exactly one node's membership and
    # removes another's canonical; "Institution X" is untouched by it.
    alias_map = json.loads(alias_map_path.read_text(encoding="utf-8"))
    for node in alias_map["nodes"]:
        if node["canonical"] == "Kevin Attell":
            node["aliases"] = ["Table 3.1"]
    alias_map["nodes"] = [n for n in alias_map["nodes"] if n["canonical"] != "Table 3.1"]
    alias_map_path.write_text(json.dumps(alias_map), encoding="utf-8")

    result = run_materialize(**_dirs(tmp_path))

    # The prose note never depends on the alias map at all.
    assert prose_path.read_bytes() == prose_before
    # The old "Table 3.1" page is gone; its name is now an alias.
    assert not table_page.is_file()
    # The untouched control node's page is byte-identical -- it was not
    # rewritten by an edit to a different node.
    assert control_page.read_bytes() == control_before
    assert result["name_pages_deleted"] == 1
    assert result["name_pages_written"] == 1  # only "Kevin Attell" actually changed
    assert result["name_pages_unchanged"] == 1  # "Institution X"

    kevin_page = tmp_path / "data" / "vault" / "names" / "Kevin Attell.md"
    frontmatter, body = _read_note(kevin_page)
    assert frontmatter["aliases"] == ["Table 3.1"]
    # Still 2: src1's chunk already named "Kevin Attell" directly, so folding
    # in "Table 3.1" (whose only mention is that SAME chunk) adds no new
    # member -- the union, not the sum.
    assert frontmatter["member_count"] == 2


def test_materialize_raises_a_clear_error_when_the_alias_map_is_missing(tmp_path):
    _build_fixture(tmp_path)
    (tmp_path / "data" / "names" / "alias_map.json").unlink()

    with pytest.raises(MissingAliasMapError):
        run_materialize(**_dirs(tmp_path))


# -- CLI wiring smoke test -----------------------------------------------------


def _run_axial(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"  # poison: any text-gen LLM call crashes the run
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def test_names_materialize_cli_subcommand_is_wired(isolated_vault_root):
    root = isolated_vault_root
    _build_fixture(root)

    result = _run_axial(root, "names", "materialize")

    combined = result.stdout + result.stderr
    assert "invalid choice" not in combined and "unrecognized arguments" not in combined, (
        "expected a real 'axial names materialize' run, not an argparse "
        f"fallback:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "name_pages_written: 2" in result.stdout
    assert (root / "data" / "vault" / "names" / "Kevin Attell.md").is_file()
    assert (root / "data" / "vault" / "prose" / "src1_000_intro_001.md").is_file()
