"""Tests for the one-off sim-case source_id remap (axial.remap_sim_source_ids)."""

from __future__ import annotations

import json
from pathlib import Path

from axial.envelope import compute_source_id
from axial.remap_sim_source_ids import (
    apply_file,
    build_hash_map,
    format_report,
    migrate,
    plan_file,
)


def _write_source(sources_dir: Path, name: str, content: bytes) -> str:
    """Write a raw source file and return the source_id it produces."""
    sources_dir.mkdir(parents=True, exist_ok=True)
    path = sources_dir / name
    path.write_bytes(content)
    return compute_source_id(path)


def _write_case(cases_dir: Path, name: str, old_ids: list[str]) -> Path:
    cases_dir.mkdir(parents=True, exist_ok=True)
    path = cases_dir / name
    payload = {
        "case_id": name.removesuffix(".json"),
        "question": "does this remap correctly?",
        "required_citation_source_ids": old_ids,
        "notes": "unrelated prose that must survive untouched",
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_build_hash_map_keys_by_hash_suffix(tmp_path: Path):
    sources_dir = tmp_path / "sources"
    tidy_id = _write_source(sources_dir, "Tidy Stem One.pdf", b"alpha content")

    hash_map = build_hash_map(sources_dir)

    assert hash_map[tidy_id[-12:]] == tidy_id


def test_happy_path_remap_rewrites_stale_id(tmp_path: Path):
    sources_dir = tmp_path / "sources"
    new_id = _write_source(
        sources_dir, "Over-Stating the Arab State (Z-Library).pdf", b"ayubi content"
    )
    hash_suffix = new_id[-12:]
    old_id = f"ayubi-over-stating-the-arab-state-{hash_suffix}"

    cases_dir = tmp_path / "cases"
    case_path = _write_case(cases_dir, "P1-01.json", [old_id])

    reports = migrate(cases_dir, sources_dir, apply=True)

    assert len(reports) == 1
    assert reports[0].remapped == {old_id: new_id}
    assert reports[0].unmapped == []

    payload = json.loads(case_path.read_text(encoding="utf-8"))
    assert payload["required_citation_source_ids"] == [new_id]
    # everything else in the file is untouched
    assert payload["notes"] == "unrelated prose that must survive untouched"


def test_remap_preserves_formatting_outside_the_changed_ids(tmp_path: Path):
    sources_dir = tmp_path / "sources"
    new_id = _write_source(sources_dir, "tidy-stem.pdf", b"beta content")
    old_id = f"stale-stem-{new_id[-12:]}"

    cases_dir = tmp_path / "cases"
    case_path = _write_case(cases_dir, "P1-01.json", [old_id])
    before = case_path.read_text(encoding="utf-8")

    migrate(cases_dir, sources_dir, apply=True)

    after = case_path.read_text(encoding="utf-8")
    assert after == before.replace(f'"{old_id}"', f'"{new_id}"')


def test_migrate_is_idempotent(tmp_path: Path):
    sources_dir = tmp_path / "sources"
    new_id = _write_source(sources_dir, "tidy-stem.pdf", b"gamma content")
    old_id = f"stale-stem-{new_id[-12:]}"

    cases_dir = tmp_path / "cases"
    _write_case(cases_dir, "P1-01.json", [old_id])

    first = migrate(cases_dir, sources_dir, apply=True)
    assert first[0].remapped == {old_id: new_id}

    second = migrate(cases_dir, sources_dir, apply=True)
    assert second[0].remapped == {}
    assert second[0].unmapped == []


def test_unmapped_id_is_reported_not_dropped(tmp_path: Path):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()  # empty corpus: nothing rebuilt yet

    cases_dir = tmp_path / "cases"
    old_id = "somebody-not-yet-rebuilt-abc123def456"
    case_path = _write_case(cases_dir, "P1-01.json", [old_id])
    before = case_path.read_text(encoding="utf-8")

    reports = migrate(cases_dir, sources_dir, apply=True)

    assert reports[0].remapped == {}
    assert reports[0].unmapped == [old_id]
    assert case_path.read_text(encoding="utf-8") == before  # nothing mangled

    rendered = format_report(reports)
    assert "WARNING" in rendered
    assert old_id in rendered


def test_dry_run_makes_no_writes(tmp_path: Path):
    sources_dir = tmp_path / "sources"
    new_id = _write_source(sources_dir, "tidy-stem.pdf", b"delta content")
    old_id = f"stale-stem-{new_id[-12:]}"

    cases_dir = tmp_path / "cases"
    case_path = _write_case(cases_dir, "P1-01.json", [old_id])
    before = case_path.read_text(encoding="utf-8")

    reports = migrate(cases_dir, sources_dir, apply=False)

    assert reports[0].remapped == {old_id: new_id}  # plan still computed
    assert case_path.read_text(encoding="utf-8") == before  # but nothing written


def test_apply_file_is_a_noop_when_nothing_remapped(tmp_path: Path):
    cases_dir = tmp_path / "cases"
    case_path = _write_case(cases_dir, "P1-01.json", ["already-current-abc123def456"])
    report = plan_file(case_path, hash_map={})

    assert apply_file(report) is False
