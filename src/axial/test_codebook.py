"""Inner unit tests for the codebook loader (issue #8, slice 03)."""

import re

import pytest

from axial.codebook import (
    CodebookError,
    MalformedCodebookError,
    MissingCodebookFileError,
    NonMappingAxisError,
    NonMappingTagEntryError,
    load_codebook,
)


def _write_codebook(domain_dir, text):
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / "codebook.yaml").write_text(text, encoding="utf-8")


def test_loader_exposes_definition_and_examples_per_tag(tmp_path):
    _write_codebook(
        tmp_path,
        """
        axes:
          topic:
            alpha:
              definition: "Definition of alpha."
              positive_example: "A passage that is an example of alpha."
              negative_example: "A passage that is not an example of alpha."
        """,
    )

    codebook = load_codebook(tmp_path)

    entry = codebook.axes["topic"]["alpha"]
    assert entry.definition == "Definition of alpha."
    assert entry.positive_example == "A passage that is an example of alpha."
    assert entry.negative_example == "A passage that is not an example of alpha."


def test_loader_exposes_multiple_axes_and_tags(tmp_path):
    _write_codebook(
        tmp_path,
        """
        axes:
          topic:
            alpha:
              definition: "d1"
              positive_example: "p1"
              negative_example: "n1"
            beta:
              definition: "d2"
              positive_example: "p2"
              negative_example: "n2"
          other:
            gamma:
              definition: "d3"
              positive_example: "p3"
              negative_example: "n3"
        """,
    )

    codebook = load_codebook(tmp_path)

    assert set(codebook.axes["topic"].keys()) == {"alpha", "beta"}
    assert set(codebook.axes["other"].keys()) == {"gamma"}


def test_missing_codebook_yaml_raises_clear_typed_error(tmp_path):
    domain_dir = tmp_path / "empty-domain"
    domain_dir.mkdir()

    with pytest.raises(
        MissingCodebookFileError, match=re.escape(str(domain_dir / "codebook.yaml"))
    ):
        load_codebook(domain_dir)


def test_invalid_yaml_is_a_clear_typed_error_not_a_traceback(tmp_path):
    _write_codebook(
        tmp_path,
        """
        axes:
          topic: [this is not, valid: yaml: mapping
        """,
    )

    with pytest.raises(MalformedCodebookError, match=re.escape(str(tmp_path / "codebook.yaml"))):
        load_codebook(tmp_path)


def test_malformed_codebook_error_is_a_codebook_error(tmp_path):
    _write_codebook(tmp_path, "axes: [not, a, mapping, :::")

    with pytest.raises(CodebookError):
        load_codebook(tmp_path)


def test_non_mapping_axis_body_is_a_hard_error_naming_the_axis(tmp_path):
    _write_codebook(
        tmp_path,
        """
        axes:
          topic: just_a_string
        """,
    )

    with pytest.raises(NonMappingAxisError, match="topic"):
        load_codebook(tmp_path)


def test_non_mapping_tag_entry_is_a_hard_error_naming_axis_and_tag(tmp_path):
    _write_codebook(
        tmp_path,
        """
        axes:
          topic:
            alpha: just_a_string
        """,
    )

    with pytest.raises(NonMappingTagEntryError, match="alpha"):
        load_codebook(tmp_path)
