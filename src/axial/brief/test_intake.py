"""Inner unit tests for the brief intake module (issue #247, slice 01).

Co-located under src/axial/brief/ per the repo's existing test layout
(mirrors src/axial/test_*.py for other stages).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from axial.brief import (
    Brief,
    BriefContent,
    BriefError,
    EmptyFieldError,
    MalformedBriefError,
    MissingBriefFileError,
    MissingFieldError,
    NonMappingBriefError,
    NonStringFieldError,
    UnknownFieldError,
    compute_brief_id,
    load_brief,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEV_BRIEFS_DIR = REPO_ROOT / "config" / "briefs" / "dev"


def _write_brief(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_load_brief_well_formed_returns_case_request_and_none_lens(tmp_path: Path):
    path = _write_brief(
        tmp_path,
        "well_formed.yaml",
        'case: "  Syria  "\nrequest: "  How did displacement reshape local authority?  "\n',
    )
    brief = load_brief(path)

    assert isinstance(brief, Brief)
    assert brief.case == "Syria"
    assert brief.request == "How did displacement reshape local authority?"
    assert brief.lens is None
    assert brief.brief_id


def test_load_brief_well_formed_with_lens(tmp_path: Path):
    path = _write_brief(
        tmp_path,
        "with_lens.yaml",
        'case: "Lebanon"\nrequest: "How did sectarian power-sharing evolve?"\nlens: "institutional"\n',
    )
    brief = load_brief(path)

    assert brief.lens == "institutional"


def test_load_brief_missing_file_raises(tmp_path: Path):
    with pytest.raises(MissingBriefFileError):
        load_brief(tmp_path / "does_not_exist.yaml")


def test_load_brief_unparseable_yaml_raises_malformed(tmp_path: Path):
    path = _write_brief(tmp_path, "bad.yaml", "case: [unterminated\n")
    with pytest.raises(MalformedBriefError):
        load_brief(path)


def test_load_brief_non_mapping_top_level_raises(tmp_path: Path):
    path = _write_brief(tmp_path, "list.yaml", "- one\n- two\n")
    with pytest.raises(NonMappingBriefError):
        load_brief(path)


@pytest.mark.parametrize(
    "body, expected_field",
    [
        ('request: "x"\n', "case"),
        ('case: ""\nrequest: "x"\n', "case"),
        ('case: "  "\nrequest: "x"\n', "case"),
        ('case: "x"\n', "request"),
        ('case: "x"\nrequest: ""\n', "request"),
    ],
)
def test_load_brief_rejects_missing_or_empty_required_fields(
    tmp_path: Path, body: str, expected_field: str
):
    path = _write_brief(tmp_path, "malformed.yaml", body)
    with pytest.raises((MissingFieldError, EmptyFieldError)) as excinfo:
        load_brief(path)
    assert expected_field in str(excinfo.value)


def test_load_brief_non_string_case_raises_named(tmp_path: Path):
    path = _write_brief(tmp_path, "bad_case_type.yaml", 'case: 123\nrequest: "x"\n')
    with pytest.raises(NonStringFieldError) as excinfo:
        load_brief(path)
    assert "case" in str(excinfo.value)


def test_load_brief_non_string_lens_raises_named(tmp_path: Path):
    path = _write_brief(tmp_path, "bad_lens_type.yaml", 'case: "x"\nrequest: "y"\nlens: 42\n')
    with pytest.raises(NonStringFieldError) as excinfo:
        load_brief(path)
    assert "lens" in str(excinfo.value)


def test_load_brief_rejects_unknown_top_level_keys(tmp_path: Path):
    path = _write_brief(
        tmp_path,
        "typo.yaml",
        'case: "x"\nrequest: "y"\nlens: "z"\nrequets: "typo"\n',
    )
    with pytest.raises(UnknownFieldError) as excinfo:
        load_brief(path)
    assert "requets" in str(excinfo.value)


def test_load_brief_failure_emits_no_partial_brief(tmp_path: Path):
    """A malformed brief must never leak fragments of its own content (e.g.
    the request text) into the raised error -- only the field name."""
    sentinel = "SENTINEL_REQUEST_TEXT_ABC123"
    path = _write_brief(tmp_path, "malformed.yaml", f'request: "{sentinel}"\n')
    with pytest.raises(MissingFieldError) as excinfo:
        load_brief(path)
    assert sentinel not in str(excinfo.value)


def test_compute_brief_id_deterministic_same_process():
    content = BriefContent(case="Syria", request="How did displacement reshape local authority?")
    assert compute_brief_id(content) == compute_brief_id(content)


def test_compute_brief_id_deterministic_across_fresh_loads(tmp_path: Path):
    body = 'case: "Syria"\nrequest: "How did displacement reshape local authority?"\n'
    path_a = _write_brief(tmp_path, "a.yaml", body)
    path_b = _write_brief(tmp_path, "b.yaml", body)

    assert load_brief(path_a).brief_id == load_brief(path_b).brief_id


def test_compute_brief_id_content_sensitive_to_request_change():
    base = BriefContent(case="Syria", request="How did displacement reshape local authority?")
    changed = BriefContent(case="Syria", request="How did displacement reshape local authority!")
    assert compute_brief_id(base) != compute_brief_id(changed)


def test_compute_brief_id_content_sensitive_to_lens_addition():
    without_lens = BriefContent(case="Syria", request="A question")
    with_lens = BriefContent(case="Syria", request="A question", lens="institutional")
    assert compute_brief_id(without_lens) != compute_brief_id(with_lens)


def test_compute_brief_id_ignores_key_order(tmp_path: Path):
    path_a = _write_brief(tmp_path, "order_a.yaml", 'case: "Syria"\nrequest: "A question"\n')
    path_b = _write_brief(tmp_path, "order_b.yaml", 'request: "A question"\ncase: "Syria"\n')
    assert load_brief(path_a).brief_id == load_brief(path_b).brief_id


def test_compute_brief_id_ignores_surrounding_whitespace(tmp_path: Path):
    path_a = _write_brief(tmp_path, "ws_a.yaml", 'case: "Syria"\nrequest: "A question"\n')
    path_b = _write_brief(tmp_path, "ws_b.yaml", 'case: "  Syria  "\nrequest: "  A question  "\n')
    assert load_brief(path_a).brief_id == load_brief(path_b).brief_id


def test_brief_id_is_filesystem_safe_and_fixed_length():
    id_one = compute_brief_id(BriefContent(case="Syria", request="A question"))
    id_two = compute_brief_id(BriefContent(case="Lebanon", request="A different question"))

    unsafe_chars = set('/\\:*?"<>| ')
    assert not (unsafe_chars & set(id_one))
    assert len(id_one) == len(id_two)
    assert len(id_one) > 0


def test_brief_error_hierarchy():
    for cls in (
        MissingBriefFileError,
        MalformedBriefError,
        NonMappingBriefError,
        UnknownFieldError,
        MissingFieldError,
        EmptyFieldError,
        NonStringFieldError,
    ):
        assert issubclass(cls, BriefError)


@pytest.mark.parametrize(
    "fixture_path",
    sorted(DEV_BRIEFS_DIR.glob("*.yaml")) if DEV_BRIEFS_DIR.is_dir() else [],
)
def test_every_dev_fixture_brief_loads_and_validates(fixture_path: Path):
    brief = load_brief(fixture_path)
    assert brief.case
    assert brief.request
    assert brief.brief_id


def test_at_least_two_dev_fixture_briefs_exist():
    assert DEV_BRIEFS_DIR.is_dir()
    assert len(list(DEV_BRIEFS_DIR.glob("*.yaml"))) >= 2


def test_syria_displacement_fixture_matches_pinned_content():
    """This exact path + content is pinned by the outer acceptance test
    (tests/analysis/test_brief_intake.py)."""
    path = DEV_BRIEFS_DIR / "fixture-syria-displacement.yaml"
    brief = load_brief(path)
    assert brief.case == "Syria"
    assert brief.request == "How did displacement reshape local authority?"
