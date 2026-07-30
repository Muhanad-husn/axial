"""Inner unit tests for the back-matter section classification (issue #508
class B, spec §7.16).

One cached flash call classifies the corpus's DISTINCT section headings
once, following the source router's own classify-once precedent (#164). The
model call is stubbed here throughout -- the behaviour under test is which
heading ends up cut, what the prompt carries, and that a cached heading is
never re-asked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from axial.name_sections import (
    BODY_CLASS,
    DEFAULT_SECTION_CLASSES_PATH,
    back_matter_sections,
    classify_sections,
    load_section_classes,
)


_HEADING_LINE = re.compile(r"^(?P<n>[0-9]+)\. (?P<heading>.+)$")


class _FakeClient:
    """Reads the numbered heading block back out of the prompt and answers
    by heading TEXT, from a `{heading: class}` script -- so a test never has
    to know which batch a heading landed in or what number it got."""

    def __init__(self, script: dict[str, str] | None = None, extra: list[dict] | None = None):
        self.script = script or {}
        self.extra = extra or []
        self.prompts: list[str] = []
        self.pass_names: list[str | None] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.prompts.append(prompt)
        self.pass_names.append(pass_name)
        back_matter = [
            {"n": int(match.group("n")), "class": self.script[match.group("heading")]}
            for match in (_HEADING_LINE.match(line) for line in prompt.splitlines())
            if match is not None and match.group("heading") in self.script
        ]
        return json.dumps({"back_matter": back_matter + self.extra})


def test_the_default_cache_sits_beside_the_other_name_artifacts():
    assert DEFAULT_SECTION_CLASSES_PATH == Path("data/names/section_classes.json")


def test_classify_sections_records_the_class_the_model_named(tmp_path: Path):
    client = _FakeClient({"Bibliography": "bibliography", "Index": "index"})

    classes = classify_sections(
        ["Bibliography", "Chapter One", "Index"],
        client=client,
        classes_path=tmp_path / "section_classes.json",
    )

    assert classes == {
        "Bibliography": "bibliography",
        "Chapter One": BODY_CLASS,
        "Index": "index",
    }


def test_endnotes_are_not_back_matter_and_survive_the_glyph_spacing(tmp_path: Path):
    """Docling spaces some headings out per glyph. The heading reaches the
    model verbatim, the prompt names both the spacing case and the endnote
    rule, and a heading the model leaves unlisted stays body."""
    client = _FakeClient({"B I B L I O G R A P H Y": "bibliography"})

    classes = classify_sections(
        ["N O T E S", "B I B L I O G R A P H Y"],
        client=client,
        classes_path=tmp_path / "section_classes.json",
    )

    assert classes["N O T E S"] == BODY_CLASS
    assert classes["B I B L I O G R A P H Y"] == "bibliography"

    prompt = client.prompts[0]
    assert "N O T E S" in prompt
    assert "endnote" in prompt.lower()
    assert "letter" in prompt.lower() or "glyph" in prompt.lower()


def test_back_matter_sections_returns_only_the_four_cut_classes(tmp_path: Path):
    client = _FakeClient(
        {
            "Bibliography": "bibliography",
            "Index": "index",
            "Acknowledgements": "front matter",
            "Appendix B": "appendix",
        }
    )

    cut = back_matter_sections(
        ["Bibliography", "Index", "Acknowledgements", "Appendix B", "Chapter One", "N O T E S"],
        client=client,
        classes_path=tmp_path / "section_classes.json",
    )

    assert cut == frozenset({"Bibliography", "Index", "Acknowledgements", "Appendix B"})


def test_a_cached_heading_is_never_re_asked(tmp_path: Path):
    classes_path = tmp_path / "section_classes.json"
    first = _FakeClient({"Bibliography": "bibliography"})
    classify_sections(["Bibliography", "Chapter One"], client=first, classes_path=classes_path)

    second = _FakeClient({"Bibliography": "index", "Chapter One": "index"})
    classes = classify_sections(
        ["Bibliography", "Chapter One"], client=second, classes_path=classes_path
    )

    assert second.prompts == []
    assert classes["Bibliography"] == "bibliography"


def test_only_a_heading_the_cache_has_never_seen_is_asked_about(tmp_path: Path):
    classes_path = tmp_path / "section_classes.json"
    classify_sections(
        ["Bibliography", "Chapter One"],
        client=_FakeClient({"Bibliography": "bibliography"}),
        classes_path=classes_path,
    )

    client = _FakeClient({"Index": "index"})
    classes = classify_sections(
        ["Bibliography", "Chapter One", "Index"], client=client, classes_path=classes_path
    )

    assert len(client.prompts) == 1
    assert "Index" in client.prompts[0]
    assert "Bibliography" not in client.prompts[0]
    assert classes["Index"] == "index"
    assert classes["Bibliography"] == "bibliography"


def test_nothing_to_ask_makes_no_call_and_needs_no_client(tmp_path: Path):
    assert classify_sections([], classes_path=tmp_path / "section_classes.json") == {}


def test_the_cache_is_written_where_an_operator_can_read_it(tmp_path: Path):
    classes_path = tmp_path / "section_classes.json"

    classify_sections(
        ["Bibliography", "Chapter One"],
        client=_FakeClient({"Bibliography": "bibliography"}),
        classes_path=classes_path,
    )

    document = json.loads(classes_path.read_text(encoding="utf-8"))
    assert document["sections"] == {"Bibliography": "bibliography", "Chapter One": BODY_CLASS}
    assert load_section_classes(classes_path) == document["sections"]


def test_load_section_classes_tolerates_an_absent_or_damaged_cache(tmp_path: Path):
    assert load_section_classes(tmp_path / "nope.json") == {}
    damaged = tmp_path / "damaged.json"
    damaged.write_text("{not json", encoding="utf-8")
    assert load_section_classes(damaged) == {}


def test_an_index_the_batch_never_carried_is_ignored(tmp_path: Path):
    """The model can only ever cut a heading it was actually asked about."""
    client = _FakeClient(
        {"Bibliography": "bibliography"},
        extra=[{"n": 99, "class": "index"}, {"n": 0, "class": "index"}],
    )

    classes = classify_sections(
        ["Bibliography", "Chapter One"],
        client=client,
        classes_path=tmp_path / "section_classes.json",
    )

    assert classes == {"Bibliography": "bibliography", "Chapter One": BODY_CLASS}


def test_a_class_outside_the_four_is_read_as_body(tmp_path: Path):
    """Fail open: an answer naming something that is not one of the four cut
    classes keeps the heading, it never invents a fifth reason to cut."""
    client = _FakeClient({"N O T E S": "endnotes", "Chapter One": "chapter"})

    classes = classify_sections(
        ["N O T E S", "Chapter One"],
        client=client,
        classes_path=tmp_path / "section_classes.json",
    )

    assert classes == {"N O T E S": BODY_CLASS, "Chapter One": BODY_CLASS}


def test_headings_are_split_across_calls_to_bound_the_request(tmp_path: Path):
    client = _FakeClient()
    headings = [f"Chapter {n} " + "x" * 400 for n in range(200)]

    classes = classify_sections(
        headings, client=client, classes_path=tmp_path / "section_classes.json"
    )

    assert len(client.prompts) > 1
    assert set(classes) == set(headings)
    assert all(value == BODY_CLASS for value in classes.values())


def test_the_call_identifies_itself_as_its_own_pass(tmp_path: Path):
    from axial.llm import NAME_SECTIONS_PASS_NAME

    client = _FakeClient()
    classify_sections(
        ["Chapter One"], client=client, classes_path=tmp_path / "section_classes.json"
    )

    assert client.pass_names == [NAME_SECTIONS_PASS_NAME]
