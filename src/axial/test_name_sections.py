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

import pytest

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


# --- the first live run's two failure modes, pinned --------------------------
#
# The classifier's first pass over the real 2,813 headings offered four
# back-matter labels and `body`, and put 11 endnote headings and 15 pieces of
# argument prose into `front matter`. Both are cuts, and both are wrong.


@pytest.mark.parametrize(
    "heading",
    [
        "NOTES",
        "Notes",
        "Notes:",
        "N O T E S",
        "NOTES TO PAGES 85-93",
        "Notes to p. 190",
        "Notes to pages 13-22",
        "Notes to pages 162- 70",
        "Notes on Fiscal Change in Syria: The Importance of Middle-Range Policies",
    ],
)
def test_an_endnote_heading_the_model_labels_endnotes_is_never_cut(tmp_path: Path, heading: str):
    """`endnotes` is a label the model may answer with, and answering it
    keeps the heading. The last case is a real chapter title that merely
    starts with the word, and it survives either way."""
    client = _FakeClient({heading: "endnotes"})

    cut = back_matter_sections(
        [heading], client=client, classes_path=tmp_path / "section_classes.json"
    )

    assert cut == frozenset()


def test_the_endnotes_label_is_recorded_rather_than_flattened_onto_body(tmp_path: Path):
    """The cache says `endnotes`, not `body`, so an operator can count what
    the classification actually found without re-asking."""
    classes = classify_sections(
        ["NOTES", "Chapter One"],
        client=_FakeClient({"NOTES": "endnotes"}),
        classes_path=tmp_path / "section_classes.json",
    )

    assert classes == {"NOTES": "endnotes", "Chapter One": BODY_CLASS}


@pytest.mark.parametrize(
    "heading",
    [
        "CONCLUSION",
        "Epilogue",
        "PROLOGUE",
        "OUTLINE OF THE ARGUMENT",
        "The Structure of the Book",
        "WHAT YOU WILL FIND HERE",
        "Part III",
        "P A R T I",
        "Civil-Military Relations",
        "EVOLUTION, RESTORATION, OR INNOVATION?",
    ],
)
def test_argument_prose_the_model_leaves_unlisted_is_never_cut(tmp_path: Path, heading: str):
    """A conclusion is argument. The prompt names each of these as body
    outright, so the model has no reason to reach for `front matter`."""
    client = _FakeClient()

    cut = back_matter_sections(
        [heading], client=client, classes_path=tmp_path / "section_classes.json"
    )

    assert cut == frozenset()


@pytest.mark.parametrize(
    "heading",
    [
        "This page intentionally left blank",
        "Copyright",
        "Cambridge Studies in Comparative Politics",
        "Acknowledgements",
        "Contents",
    ],
)
def test_real_front_matter_is_still_cut(tmp_path: Path, heading: str):
    """Tightening `front matter` must not empty it: the copyright line, the
    series page and the dedication are what it is for."""
    client = _FakeClient({heading: "front matter"})

    cut = back_matter_sections(
        [heading], client=client, classes_path=tmp_path / "section_classes.json"
    )

    assert cut == frozenset({heading})


def test_the_prompt_offers_endnotes_as_a_class_and_names_the_body_cases(tmp_path: Path):
    """The vocabulary is the fix. A prompt that only tells the model what
    NOT to list is what produced 11 miscut endnote headings on the first
    live run."""
    client = _FakeClient()
    classify_sections(
        ["Chapter One"], client=client, classes_path=tmp_path / "section_classes.json"
    )

    prompt = client.prompts[0]
    assert '"endnotes"' in prompt
    for body_case in ("conclusion", "epilogue", "prologue", "part divider", "chapter"):
        assert body_case in prompt.lower(), f"the prompt should name {body_case!r} as body"
    assert "before the argument begins" in prompt.lower()


def test_back_matter_sections_returns_only_the_four_cut_classes_never_endnotes(tmp_path: Path):
    client = _FakeClient(
        {
            "Bibliography": "bibliography",
            "Index": "index",
            "Acknowledgements": "front matter",
            "Appendix B": "appendix",
            "N O T E S": "endnotes",
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


def test_a_class_outside_the_five_is_read_as_body(tmp_path: Path):
    """Fail open: an answer naming something that is not one of the five
    classes keeps the heading, it never invents a sixth reason to cut."""
    client = _FakeClient({"Foreword": "prelims", "Chapter One": "chapter"})

    classes = classify_sections(
        ["Foreword", "Chapter One"],
        client=client,
        classes_path=tmp_path / "section_classes.json",
    )

    assert classes == {"Foreword": BODY_CLASS, "Chapter One": BODY_CLASS}


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
