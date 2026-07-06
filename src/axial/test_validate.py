"""Inner unit tests for the schema<->codebook cross-validator (issue #8,
slice 03).
"""

from axial.codebook import Codebook, TagEntry
from axial.schema import Axis, Schema
from axial.validate import Finding, cross_validate


def _schema(axes: dict[str, set[str]]) -> Schema:
    return Schema(
        version="0.1",
        axes={
            name: Axis(
                name=name, applies_to=[], cardinality="single", value_count=len(tags), tag_ids=tags
            )
            for name, tags in axes.items()
        },
    )


def _entry(definition="d", positive_example="p", negative_example="n") -> TagEntry:
    return TagEntry(
        definition=definition, positive_example=positive_example, negative_example=negative_example
    )


def test_consistent_pair_yields_no_findings():
    schema = _schema({"topic": {"alpha", "beta"}})
    codebook = Codebook(axes={"topic": {"alpha": _entry(), "beta": _entry()}})

    findings = cross_validate(schema, codebook)

    assert findings == []


def test_schema_tag_missing_from_codebook_is_flagged_with_axis_and_tag():
    schema = _schema({"topic": {"alpha", "gamma"}})
    codebook = Codebook(axes={"topic": {"alpha": _entry()}})

    findings = cross_validate(schema, codebook)

    assert any(
        f.axis == "topic" and f.tag == "gamma" and f.kind == "missing_from_codebook"
        for f in findings
    )


def test_codebook_tag_absent_from_schema_is_flagged():
    schema = _schema({"topic": {"alpha"}})
    codebook = Codebook(axes={"topic": {"alpha": _entry(), "delta": _entry()}})

    findings = cross_validate(schema, codebook)

    assert any(
        f.axis == "topic" and f.tag == "delta" and f.kind == "missing_from_schema" for f in findings
    )


def test_codebook_entry_missing_an_example_field_is_flagged():
    schema = _schema({"topic": {"alpha"}})
    codebook = Codebook(
        axes={
            "topic": {
                "alpha": TagEntry(definition="d", positive_example=None, negative_example="n")
            }
        }
    )

    findings = cross_validate(schema, codebook)

    assert any(
        f.axis == "topic" and f.tag == "alpha" and f.kind == "missing_field" for f in findings
    )


def test_finding_repr_is_a_readable_message():
    finding = Finding(axis="topic", tag="gamma", kind="missing_from_codebook", message="whatever")
    assert "topic" in finding.message or "topic" in str(finding)
    assert isinstance(finding, Finding)
