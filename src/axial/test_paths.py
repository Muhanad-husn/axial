"""Inner unit tests for the name-page path budget (issue #411, Materialize):
`axial.paths.name_page_filename`/`name_page_path`. Mirrors
`axial.query.test_reader`'s own `_WINDOWS_MAX_PATH` monkeypatch seam for
`budgeted_chunk_filename`/`budgeted_artifact_filename`, so the over-budget
path is exercised deterministically regardless of the OS or the test's own
tmp dir depth."""

from __future__ import annotations

import axial.paths
from axial.paths import name_page_filename, name_page_path

# Low enough that `path_overage` is positive for any real name under a real
# tmp_path -- same convention `axial.query.test_reader` uses.
_TEST_MAX_PATH = 25


def test_name_page_filename_is_verbatim_for_an_ordinary_short_name(tmp_path):
    directory = tmp_path / "names"
    assert name_page_filename(directory, "Ba'ath Party") == "Ba'ath Party.md"


def test_name_page_filename_sanitizes_illegal_windows_characters(tmp_path):
    directory = tmp_path / "names"
    filename = name_page_filename(directory, 'Question: "Who"/What?')
    assert filename == "Question- -Who--What-.md"
    assert not any(char in filename for char in '<>:"/\\|?*')


def test_name_page_filename_truncates_and_hashes_when_over_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(axial.paths, "_WINDOWS_MAX_PATH", _TEST_MAX_PATH)
    directory = tmp_path / "names"

    name = "!Kung San of Namibia and Botswana"
    filename = name_page_filename(directory, name)

    assert filename != f"{name}.md"
    assert filename.endswith(".md")
    # 8 hex chars + "-" + ".md" -- the content hash suffix survives the
    # shrink verbatim; only the readable name prefix is ever shortened.
    stem = filename[: -len(".md")]
    assert len(stem.rsplit("-", 1)[-1]) == 8


def test_name_page_filename_is_deterministic_given_the_same_name(tmp_path):
    directory = tmp_path / "names"
    assert name_page_filename(directory, "Same Name") == name_page_filename(directory, "Same Name")


def test_name_page_filename_forces_a_hash_suffix_on_a_used_collision(tmp_path):
    """Two different canonical names that sanitize to the identical
    filename (an illegal character folded to the same '-') must not
    silently overwrite each other on disk: the second claim of an already-
    `used` filename is forced to the content-hashed form instead, even
    though it would otherwise fit comfortably under budget."""
    directory = tmp_path / "names"
    used: set[str] = set()

    first = name_page_filename(directory, "A/B", used)
    second = name_page_filename(directory, "A:B", used)

    assert first == "A-B.md"
    assert second != first
    assert second.endswith(".md")
    assert first.casefold() in used and second.casefold() in used


def test_name_page_filename_no_collision_without_a_used_case_insensitive_match(tmp_path):
    directory = tmp_path / "names"
    used: set[str] = set()

    first = name_page_filename(directory, "USA", used)
    second = name_page_filename(directory, "usa", used)

    # Windows filenames are case-insensitive: "USA.md" and "usa.md" are the
    # SAME file, so the second claim must be forced to a distinct name.
    assert first == "USA.md"
    assert second != first


def test_name_page_path_joins_the_vault_names_directory(tmp_path):
    vault_dir = tmp_path / "vault"
    path = name_page_path(vault_dir, "Kevin Attell")
    assert path == vault_dir / "names" / "Kevin Attell.md"
