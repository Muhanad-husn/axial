"""Outer acceptance test for issue #411 (Phase A v1 slice 06 -- Materialize:
the vault writer, spec §7.17, P0-8).

**The name pages this file used to also lock down are retired outright
(DEC-75, issue #853).** Everything below about a name page -- one per
surviving canonical, its frontmatter, its member links, the figure/table
artifact join, the door index (`names.jsonl`) and its atomic-write
guarantees, and the selective-rewrite-on-a-changed-alias-map behaviour --
is gone along with the pages: the final output never read one. What
survives is the locked contract below.

Given slice 02's per-note interrogation answers on disk
      (`data/answers/<source_id>.jsonl`) and slice 05's reversible alias map
      (`data/names/alias_map.json`, `axial.merge_names`)
When  the operator runs `axial names materialize`
Then  every chunk that has an interrogation answer record gets a prose note
      carrying that answer record as frontmatter -- in place of the retired
      tag/xref axis block -- with NO outbound links anywhere in the note
And   every persisted artifacts-pass record gets an artifact note under
      `data/vault/artifacts/`, via the existing, untouched
      `axial.vault.write_artifact_note` (issue #429's shape)
And   the relational store (`data/vault/notes.db`, DEC-62) carries
      `note_names` rows for every member a surviving canonical's alias-map
      node reaches, spanning however many sources actually name it
And   Materialize writes **no** `data/vault/names/` directory and no
      `data/vault/names.jsonl` door index (DEC-75, issue #853)
And   re-running against an unchanged alias map reproduces byte-identical
      prose and artifact notes
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

from axial.query import store as note_store

from axial.materialize import MissingAliasMapError, load_alias_map, load_inventory, run_materialize

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

# `member_chunk_ids_for_node` and `find_artifact_links` -- the figure/table
# artifact join, and the name-page member union it fed -- are retired along
# with the name pages they served (DEC-75, issue #853).


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


def test_materialize_writes_no_names_directory_or_door_index(tmp_path):
    """DEC-75 (issue #853): the name pages, and the door index
    (`data/vault/names.jsonl`) that used to sit beside them, are retired
    outright. Materialize must leave no trace of either, even for a corpus
    whose alias map carries cross-book, figure/table-kind names that used to
    produce plenty of both."""
    _build_fixture(tmp_path)
    result = run_materialize(**_dirs(tmp_path))

    vault_dir = tmp_path / "data" / "vault"
    assert not (vault_dir / "names").exists()
    assert not (vault_dir / "names.jsonl").exists()
    for retired_key in ("name_pages", "name_pages_written", "name_pages_unchanged", "name_pages_deleted"):
        assert retired_key not in result


def test_note_names_carries_cross_book_membership_in_the_store(tmp_path):
    """The replacement for the retired name page's own cross-book member
    links (DEC-75, issue #853): `note_names` carries one row per (chunk,
    canonical) pair, so "Kevin Attell" -- named in both src1 and src2 --
    resolves to a door spanning two distinct sources through the store
    alone, with no page ever written."""
    _build_fixture(tmp_path)
    run_materialize(**_dirs(tmp_path))

    connection = note_store.connect(tmp_path / "data" / "vault")
    try:
        doors = note_store.doors(connection, ["Kevin Attell", "Table 3.1"])
    finally:
        connection.close()

    assert doors["Kevin Attell"].member_count == 2
    assert doors["Kevin Attell"].source_count == 2
    assert doors["Kevin Attell"].kind == "person"
    # "Table 3.1" is named only in src1 -- one source.
    assert doors["Table 3.1"].member_count == 1
    assert doors["Table 3.1"].source_count == 1


def test_rerun_over_unchanged_input_leaves_prose_and_artifact_notes_byte_identical(tmp_path):
    _build_fixture(tmp_path)
    run_materialize(**_dirs(tmp_path))

    def _snapshot() -> dict[str, bytes]:
        vault_dir = tmp_path / "data" / "vault"
        return {
            str(path.relative_to(vault_dir)): path.read_bytes()
            for directory in ("prose", "artifacts")
            for path in sorted((vault_dir / directory).glob("*.md"))
        }

    before = _snapshot()
    run_materialize(**_dirs(tmp_path))
    after = _snapshot()

    assert before == after
    assert before, "fixture setup: there must be at least one note to compare"


def test_a_changed_alias_map_never_touches_a_prose_note(tmp_path):
    """The one part of the retired selective-rewrite test (DEC-75, issue
    #853) that still applies without a name page to selectively rewrite:
    prose notes never depended on the alias map at all, and still don't --
    only the store's own `note_names`/`names` tables move."""
    _build_fixture(tmp_path)
    run_materialize(**_dirs(tmp_path))

    prose_path = tmp_path / "data" / "vault" / "prose" / "src1_000_intro_001.md"
    prose_before = prose_path.read_bytes()

    alias_map_path = tmp_path / "data" / "names" / "alias_map.json"
    alias_map = json.loads(alias_map_path.read_text(encoding="utf-8"))
    for node in alias_map["nodes"]:
        if node["canonical"] == "Kevin Attell":
            node["aliases"] = ["Table 3.1"]
    alias_map["nodes"] = [n for n in alias_map["nodes"] if n["canonical"] != "Table 3.1"]
    alias_map_path.write_text(json.dumps(alias_map), encoding="utf-8")

    run_materialize(**_dirs(tmp_path))

    assert prose_path.read_bytes() == prose_before


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
    assert "store_note_names:" in result.stdout
    assert not (root / "data" / "vault" / "names").exists()
    assert (root / "data" / "vault" / "prose" / "src1_000_intro_001.md").is_file()
    assert (root / "data" / "vault" / "notes.db").is_file()
