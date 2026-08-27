"""Inner unit tests for the derived-vocabulary BUILD pass (issue #806,
slice 02 of `plans/derived-vocabulary/`): assigning a whole answer column
against a category scheme frozen in `config/vocabulary.yaml`, and
persisting that assignment under `data/vocabulary/`.

Slice 01's `test_vocabulary.py` covers the read-only examine pass and stays
untouched apart from `PopulationEntry`'s new `element_index`. Every test
here injects its own fake client (the same `client=None` seam
`examine_vocabulary` already exposes), so no test makes a network call.

`_ScriptedAssignClient` reads the numbered values back out of the prompt it
was handed and assigns each by a value -> category-name lookup, rather than
returning a positional queue of canned responses. That is deliberate: the
one property this slice has to prove is WHICH values reached the model on a
second and third run, and a queue cannot express that -- `asked_values`
can.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

import pytest

import axial.vocabulary as vocabulary_mod
from axial.vocabulary import (
    ASSIGNMENTS_FILENAME,
    DEFAULT_VOCABULARY_SCHEME_PATH,
    BUILD_PASS_NAME,
    EXAMINE_PASS_NAME,
    MANIFEST_FILENAME,
    ROOT_LEVEL,
    SchemeVersionMismatchError,
    VocabularySchemeError,
    build_vocabulary,
    compute_answers_pin,
    format_vocabulary_build_report,
    load_vocabulary_scheme,
    read_column,
)

# ---------------------------------------------------------------------------
# Fixtures: a tiny answer store, a scheme file, and a client that assigns by
# reading its own prompt
# ---------------------------------------------------------------------------

# Five paraphrases of one mechanism across three sources, plus three
# one-offs that no category covers.
EXTRACTION = [
    "Extraction of rural surplus funds the central state's own army.",
    "The state's army is funded by extracting surplus from the countryside.",
    "Rural surplus, once extracted, pays for the central army.",
    "Central military spending draws on surplus taken from rural producers.",
    "The army is paid for out of surplus the state extracts from villages.",
]
ONE_OFFS = [
    "A shared script does not make two nationalisms the same movement.",
    "Colonial borders were drawn without consulting the tribes they split.",
    "Print capitalism let a reading public imagine itself as a nation.",
]

WAR_AND_STATE = "war and state formation"
IDENTITY = "identity construction and boundary-making"


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_answers(answers_dir: Path) -> None:
    """Three sources, eight answered `mechanism` values, two excluded (an
    abstention and issue #810's literal `"[]"`)."""
    _write_jsonl(
        answers_dir / "alpha-2020.jsonl",
        [
            {"chunk_id": "alpha-2020_1", "source_id": "alpha-2020",
             "answers": {"mechanism": EXTRACTION[0]}},
            {"chunk_id": "alpha-2020_2", "source_id": "alpha-2020",
             "answers": {"mechanism": EXTRACTION[1]}},
            {"chunk_id": "alpha-2020_3", "source_id": "alpha-2020",
             "answers": {"mechanism": ONE_OFFS[0]}},
            {"chunk_id": "alpha-2020_4", "source_id": "alpha-2020",
             "answers": {"mechanism": "not-in-passage"}},
        ],
    )
    _write_jsonl(
        answers_dir / "beta-2021.jsonl",
        [
            {"chunk_id": "beta-2021_1", "source_id": "beta-2021",
             "answers": {"mechanism": EXTRACTION[2]}},
            {"chunk_id": "beta-2021_2", "source_id": "beta-2021",
             "answers": {"mechanism": EXTRACTION[3]}},
            {"chunk_id": "beta-2021_3", "source_id": "beta-2021",
             "answers": {"mechanism": ONE_OFFS[1]}},
            {"chunk_id": "beta-2021_4", "source_id": "beta-2021",
             "answers": {"mechanism": "[]"}},
        ],
    )
    _write_jsonl(
        answers_dir / "gamma-2022.jsonl",
        [
            {"chunk_id": "gamma-2022_1", "source_id": "gamma-2022",
             "answers": {"mechanism": EXTRACTION[4]}},
            {"chunk_id": "gamma-2022_2", "source_id": "gamma-2022",
             "answers": {"mechanism": ONE_OFFS[2]}},
        ],
    )


def _write_new_source(answers_dir: Path) -> list[str]:
    """One further source landing after a build: two values the earlier
    build never saw."""
    values = [
        "Conscription for a long war built the tax bureaucracy that outlived it.",
        "A census taken to raise troops became the register the state governed by.",
    ]
    _write_jsonl(
        answers_dir / "delta-2023.jsonl",
        [
            {"chunk_id": "delta-2023_1", "source_id": "delta-2023",
             "answers": {"mechanism": values[0]}},
            {"chunk_id": "delta-2023_2", "source_id": "delta-2023",
             "answers": {"mechanism": values[1]}},
        ],
    )
    return values


_SCHEME_YAML = """
columns:
  mechanism:
    version: "test-v1"
    categories:
      - id: war-and-state-formation
        name: "war and state formation"
        gloss: "warfare drives state-building, extraction and institutional change"
      - id: identity-construction-and-boundary-making
        name: "identity construction and boundary-making"
        gloss: "ethnic, national or religious categories are made and politicised"
"""


def _write_scheme(path: Path, text: str = _SCHEME_YAML) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


_NUMBERED = re.compile(r"^(\d+)\.\s(.*)$")


class _ScriptedAssignClient:
    """A minimal `LLMClient` that assigns by reading the numbered values out
    of the prompt it is handed, via a value -> category-name lookup. A value
    with no entry comes back as `"none"` (a real refusal). Records every
    value it was ever asked about in `asked_values`, in order, which is the
    property the reuse and incremental tests turn on."""

    def __init__(self, assign_by_value: dict[str, str], model: str = "fake/assign"):
        self._assign_by_value = dict(assign_by_value)
        self._model = model
        self.asked_values: list[str] = []
        self.prompts: list[str] = []
        self._calls: dict[str, int] = collections.defaultdict(int)
        self._cost: dict[str, float] = collections.defaultdict(float)

    def complete(self, prompt, pass_name=None):
        self.prompts.append(prompt)
        self._calls[pass_name] += 1
        self._cost[pass_name] += 0.001
        assignments = []
        for line in prompt.splitlines():
            match = _NUMBERED.match(line)
            if match is None:
                continue
            number, value = int(match.group(1)), match.group(2)
            self.asked_values.append(value)
            assignments.append({"n": number, "category": self._assign_by_value.get(value, "none")})
        return json.dumps({"assignments": assignments})

    def model_for_pass(self, pass_name=None):
        return self._model

    def calls_for_pass(self, pass_name=None):
        return self._calls.get(pass_name, 0)

    def cost_for_pass(self, pass_name=None):
        return self._cost.get(pass_name) if self._calls.get(pass_name, 0) else None


def _extraction_client(**extra: str) -> _ScriptedAssignClient:
    lookup = {value: WAR_AND_STATE for value in EXTRACTION}
    lookup.update(extra)
    return _ScriptedAssignClient(lookup)


def _build(tmp_path, client, **kwargs):
    return build_vocabulary(
        answers_dir=kwargs.pop("answers_dir", tmp_path / "answers"),
        columns=kwargs.pop("columns", ["mechanism"]),
        scheme_path=kwargs.pop("scheme_path", tmp_path / "vocabulary.yaml"),
        vocabulary_dir=kwargs.pop("vocabulary_dir", tmp_path / "vocabulary"),
        client=client,
        **kwargs,
    )


def _read_assignments(vocabulary_dir: Path, column: str = "mechanism") -> list[dict]:
    path = vocabulary_dir / column / ASSIGNMENTS_FILENAME
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _read_manifest(vocabulary_dir: Path, column: str = "mechanism") -> dict:
    return json.loads((vocabulary_dir / column / MANIFEST_FILENAME).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The scheme file: a tree, read from configuration, never inferred
# ---------------------------------------------------------------------------


def test_load_scheme_reads_a_flat_v1_scheme_with_null_parents_at_depth_one(tmp_path):
    scheme = load_vocabulary_scheme("mechanism", _write_scheme(tmp_path / "vocabulary.yaml"))

    assert scheme.column == "mechanism"
    assert scheme.version == "test-v1"
    assert [category.id for category in scheme.categories] == [
        "war-and-state-formation",
        "identity-construction-and-boundary-making",
    ]
    assert all(category.parent_id is None for category in scheme.categories)
    assert all(category.level == ROOT_LEVEL for category in scheme.categories)
    assert scheme.max_level == ROOT_LEVEL


def test_load_scheme_parses_a_nested_scheme_and_gives_each_child_its_parent_id(tmp_path):
    """The founder's 2026-08-28 ruling: the vocabulary is a tree. The
    committed v1 scheme is depth 1, but the FILE's shape must already admit
    a second level, so adding one is an edit plus a version bump and never
    a migration."""
    nested = """
columns:
  mechanism:
    version: "test-v2"
    categories:
      - id: war-and-state-formation
        name: "war and state formation"
        gloss: "warfare drives state-building"
        children:
          - id: fiscal-extraction-for-war
            name: "fiscal extraction for war"
            gloss: "war costs are met by building the machinery that taxes"
          - id: conscription-and-manpower
            name: "conscription and manpower"
            gloss: "raising troops reshapes the institutions that raise them"
"""
    scheme = load_vocabulary_scheme("mechanism", _write_scheme(tmp_path / "v.yaml", nested))

    by_id = {category.id: category for category in scheme.categories}
    assert by_id["war-and-state-formation"].parent_id is None
    assert by_id["war-and-state-formation"].level == 1
    assert by_id["fiscal-extraction-for-war"].parent_id == "war-and-state-formation"
    assert by_id["fiscal-extraction-for-war"].level == 2
    assert by_id["conscription-and-manpower"].parent_id == "war-and-state-formation"
    assert scheme.max_level == 2
    # The version covers the WHOLE tree, not one level of it.
    assert scheme.version == "test-v2"
    assert len(scheme.at_level(1)) == 1
    assert len(scheme.at_level(2)) == 2


def test_load_scheme_for_a_column_with_no_scheme_fails_naming_the_column(tmp_path):
    scheme_path = _write_scheme(tmp_path / "vocabulary.yaml")

    with pytest.raises(VocabularySchemeError) as excinfo:
        load_vocabulary_scheme("comparison", scheme_path)

    assert "comparison" in str(excinfo.value)
    assert str(scheme_path) in str(excinfo.value)


def test_load_scheme_from_a_missing_file_fails_naming_the_file(tmp_path):
    with pytest.raises(VocabularySchemeError) as excinfo:
        load_vocabulary_scheme("mechanism", tmp_path / "absent.yaml")

    assert "absent.yaml" in str(excinfo.value)


def test_load_scheme_rejects_a_column_with_no_version(tmp_path):
    text = """
columns:
  mechanism:
    categories:
      - id: a
        name: "a"
        gloss: "a"
"""
    with pytest.raises(VocabularySchemeError) as excinfo:
        load_vocabulary_scheme("mechanism", _write_scheme(tmp_path / "v.yaml", text))

    assert "version" in str(excinfo.value)


def test_load_scheme_rejects_a_duplicate_category_id(tmp_path):
    """A category id is what every downstream join records; two categories
    sharing one would make an assignment ambiguous under the very id that
    is supposed to be stable."""
    text = """
columns:
  mechanism:
    version: "test-v1"
    categories:
      - id: a
        name: "first"
        gloss: "one"
      - id: a
        name: "second"
        gloss: "two"
"""
    with pytest.raises(VocabularySchemeError) as excinfo:
        load_vocabulary_scheme("mechanism", _write_scheme(tmp_path / "v.yaml", text))

    assert "'a'" in str(excinfo.value) or '"a"' in str(excinfo.value)


def test_load_scheme_rejects_a_duplicate_category_name(tmp_path):
    """The model assigns by NAME (that is what `ASSIGN_PROMPT` renders), so
    two categories sharing a name cannot be told apart in a response. This
    is the exact defect slice 01's own run had -- all twenty `mechanism`
    categories came back named "Causal mechanism"."""
    text = """
columns:
  mechanism:
    version: "test-v1"
    categories:
      - id: a
        name: "Causal mechanism"
        gloss: "one"
      - id: b
        name: "Causal mechanism"
        gloss: "two"
"""
    with pytest.raises(VocabularySchemeError) as excinfo:
        load_vocabulary_scheme("mechanism", _write_scheme(tmp_path / "v.yaml", text))

    assert "Causal mechanism" in str(excinfo.value)


def test_the_committed_scheme_file_holds_mechanism_at_depth_one():
    """The real `config/vocabulary.yaml`, not a fixture: the twenty
    categories slice 01's corrected run proposed for `mechanism`, each with
    a distinct id and a distinct name, all at depth 1."""
    scheme = load_vocabulary_scheme("mechanism", DEFAULT_VOCABULARY_SCHEME_PATH)

    assert len(scheme.categories) == 20
    assert scheme.max_level == ROOT_LEVEL
    assert all(category.parent_id is None for category in scheme.categories)
    assert len({category.id for category in scheme.categories}) == 20
    assert len({category.name for category in scheme.categories}) == 20
    assert all(category.gloss.strip() for category in scheme.categories)
    assert scheme.version


def test_the_build_spends_under_its_own_pass_name(tmp_path):
    """At seven columns the build is roughly $1 and ~648 calls. Landing
    that on the examine line -- a 400-value sample pass -- would misprice
    per-pass cost by an order of magnitude for whoever reads it next."""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    client = _extraction_client()

    stats = _build(tmp_path, client)

    assert BUILD_PASS_NAME != EXAMINE_PASS_NAME
    assert client.calls_for_pass(BUILD_PASS_NAME) == 1
    assert client.calls_for_pass(EXAMINE_PASS_NAME) == 0
    # And the figures the report prints are read off the same pass.
    assert stats.columns[0].calls == 1
    assert stats.columns[0].cost == pytest.approx(0.001)


def test_the_committed_config_pins_the_build_pass_to_the_examine_tier():
    """Its own pass name, the SAME tier -- pinned, never defaulted. An
    unnamed pass falls through to whatever `llm_tier` happens to be, which
    is a routing change wearing a cost-reporting fix's clothes."""
    from axial.yaml_loader import SAFE_LOADER

    import yaml

    document = yaml.load(
        Path("config/pipeline.yaml").read_text(encoding="utf-8"), Loader=SAFE_LOADER
    )
    model_by_pass = document["llm"]["model_by_pass"]

    assert model_by_pass[BUILD_PASS_NAME] == model_by_pass[EXAMINE_PASS_NAME]


# ---------------------------------------------------------------------------
# The pin: content-keyed over the rendered input
# ---------------------------------------------------------------------------


def test_the_pin_is_content_keyed_over_the_answers_and_nothing_else(tmp_path):
    answers_dir = tmp_path / "answers"
    _write_answers(answers_dir)
    population, _ = read_column(vocabulary_mod.load_answer_records(answers_dir), "mechanism")

    first = compute_answers_pin(population)

    # Same answers, read again: same pin.
    population_again, _ = read_column(
        vocabulary_mod.load_answer_records(answers_dir), "mechanism"
    )
    assert compute_answers_pin(population_again) == first

    # One value edited: a different pin.
    edited = list(population)
    edited[0] = vocabulary_mod.PopulationEntry(
        "a different sentence entirely", edited[0].chunk_id, edited[0].source_id, 0
    )
    assert compute_answers_pin(edited) != first

    # A further source's values: a different pin again.
    assert compute_answers_pin(list(population) + [edited[0]]) != first


# ---------------------------------------------------------------------------
# The build: every answered value lands, with a category or a refusal
# ---------------------------------------------------------------------------


def test_build_assigns_every_answered_value_and_records_a_refusal_as_a_refusal(tmp_path):
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    client = _extraction_client()

    stats = _build(tmp_path, client)

    records = _read_assignments(tmp_path / "vocabulary")
    assert len(records) == 8

    assigned = [r for r in records if r["category_id"] is not None]
    refused = [r for r in records if r["refused"]]
    assert len(assigned) == 5
    assert {r["category_id"] for r in assigned} == {"war-and-state-formation"}
    assert len(refused) == 3
    # A refusal is a RECORD, not an absence: it carries the value, the note
    # it came from and an explicit null category.
    assert all(r["category_id"] is None for r in refused)
    assert all(r["value"] in ONE_OFFS for r in refused)
    assert {r["chunk_id"] for r in refused} == {
        "alpha-2020_3",
        "beta-2021_3",
        "gamma-2022_2",
    }

    result = stats.columns[0]
    assert result.answered_count == 8
    assert result.excluded_count == 2
    assert result.assigned_count == 5
    assert result.refused_count == 3
    assert result.unanswered_count == 0
    assert result.complete is True


def test_an_out_of_scheme_name_is_recorded_apart_from_a_refusal(tmp_path):
    """A model that answers with a string naming no committed category has
    not refused: it has answered wrongly, and the two must not read the
    same. A refusal is a fact about how well the scheme fits the corpus,
    which is a thing a person decides about; an unrecognised name is a
    defect -- a wrong case, a truncation, a hallucination -- and it is paid
    for once and then frozen, because a persisted record satisfies the next
    run's reuse check whatever it holds."""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    lookup = {value: WAR_AND_STATE for value in EXTRACTION}
    # The right words, the wrong case: no committed category carries this
    # name, and the other two one-offs come back as the prompt's own "none".
    lookup[ONE_OFFS[0]] = "War and state formation"
    client = _ScriptedAssignClient(lookup)

    stats = _build(tmp_path, client)

    by_chunk = {record["chunk_id"]: record for record in _read_assignments(tmp_path / "vocabulary")}
    unrecognised = by_chunk["alpha-2020_3"]
    assert unrecognised["category_id"] is None
    assert unrecognised["refused"] is False
    assert unrecognised["out_of_scheme"] == "War and state formation"

    for chunk_id in ("beta-2021_3", "gamma-2022_2"):
        refusal = by_chunk[chunk_id]
        assert refusal["category_id"] is None
        assert refusal["refused"] is True
        assert "out_of_scheme" not in refusal

    result = stats.columns[0]
    assert result.assigned_count == 5
    assert result.refused_count == 2
    assert result.out_of_scheme_count == 1
    assert result.out_of_scheme_names == ["War and state formation"]
    # Every answered value still lands: nothing is dropped by being named
    # apart.
    assert result.assigned_count + result.refused_count + result.out_of_scheme_count == 8


def test_a_capitalised_refusal_token_is_still_a_refusal(tmp_path):
    """"None" is the same word the prompt asks for, and reading it as an
    unrecognised category name would raise a false alarm on the one signal
    this distinction exists to make trustworthy."""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    lookup = {value: WAR_AND_STATE for value in EXTRACTION}
    lookup[ONE_OFFS[0]] = "None"

    stats = _build(tmp_path, _ScriptedAssignClient(lookup))

    assert stats.columns[0].refused_count == 3
    assert stats.columns[0].out_of_scheme_count == 0
    assert stats.columns[0].out_of_scheme_names == []


def test_the_manifest_and_the_report_name_the_out_of_scheme_strings(tmp_path):
    """The count and the strings both go in the manifest, not only in the
    console: the run that first sees them scrolls away, and every later run
    reuses the artifact and reports from it."""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    lookup = {value: WAR_AND_STATE for value in EXTRACTION}
    lookup[ONE_OFFS[0]] = "War and state formation"
    lookup[ONE_OFFS[1]] = "identity construction"

    stats = _build(tmp_path, _ScriptedAssignClient(lookup))

    manifest = _read_manifest(tmp_path / "vocabulary")
    assert manifest["refused_count"] == 1
    assert manifest["out_of_scheme_count"] == 2
    assert manifest["out_of_scheme_names"] == [
        "War and state formation",
        "identity construction",
    ]

    report = format_vocabulary_build_report(stats)
    assert "2 out-of-scheme" in report
    assert "War and state formation" in report
    assert "identity construction" in report


def test_a_reused_build_still_reports_the_out_of_scheme_count(tmp_path):
    """The freezing is the point: a reused artifact makes no call and can
    never correct itself, so the run that reuses it must keep saying what
    is in it."""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    lookup = {value: WAR_AND_STATE for value in EXTRACTION}
    lookup[ONE_OFFS[0]] = "War and state formation"
    _build(tmp_path, _ScriptedAssignClient(lookup))

    second = _ScriptedAssignClient(lookup)
    stats = _build(tmp_path, second)

    assert second.asked_values == []
    assert stats.columns[0].reused is True
    assert stats.columns[0].out_of_scheme_count == 1
    assert stats.columns[0].out_of_scheme_names == ["War and state formation"]
    assert "War and state formation" in format_vocabulary_build_report(stats)


def test_every_assignment_record_is_keyed_by_chunk_column_element_and_level(tmp_path):
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")

    _build(tmp_path, _extraction_client())

    records = _read_assignments(tmp_path / "vocabulary")
    for record in records:
        assert record["column"] == "mechanism"
        assert record["chunk_id"]
        assert record["source_id"]
        assert record["element_index"] == 0
        assert record["level"] == ROOT_LEVEL
    # Every key is distinct.
    keys = {(r["chunk_id"], r["column"], r["element_index"], r["level"]) for r in records}
    assert len(keys) == len(records)


def test_a_list_valued_column_gets_one_record_per_element(tmp_path):
    """`about` and `arguing_against` are asked for as JSON lists, so one
    note contributes several values and `element_index` is what tells them
    apart under one `chunk_id`."""
    answers_dir = tmp_path / "answers"
    _write_jsonl(
        answers_dir / "alpha-2020.jsonl",
        [
            {
                "chunk_id": "alpha-2020_1",
                "source_id": "alpha-2020",
                "answers": {"arguing_against": ["first opponent claim", "second opponent claim"]},
            }
        ],
    )
    text = """
columns:
  arguing_against:
    version: "test-v1"
    categories:
      - id: only
        name: "only"
        gloss: "everything"
"""
    _write_scheme(tmp_path / "vocabulary.yaml", text)
    client = _ScriptedAssignClient({"first opponent claim": "only", "second opponent claim": "only"})

    _build(tmp_path, client, columns=["arguing_against"])

    records = _read_assignments(tmp_path / "vocabulary", "arguing_against")
    assert [(r["chunk_id"], r["element_index"]) for r in records] == [
        ("alpha-2020_1", 0),
        ("alpha-2020_1", 1),
    ]


def test_the_manifest_records_the_scheme_version_the_pin_and_per_category_counts(tmp_path):
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")

    stats = _build(tmp_path, _extraction_client())

    manifest = _read_manifest(tmp_path / "vocabulary")
    assert manifest["column"] == "mechanism"
    assert manifest["scheme_version"] == "test-v1"
    assert manifest["answers_pin"] == stats.columns[0].answers_pin
    assert manifest["answered_count"] == 8
    assert manifest["assigned_count"] == 5
    assert manifest["refused_count"] == 3
    assert manifest["unanswered_count"] == 0
    assert manifest["complete"] is True
    assert manifest["max_level"] == ROOT_LEVEL

    by_id = {entry["category_id"]: entry for entry in manifest["categories"]}
    # Both categories are reported, including the one nothing was filed
    # under -- an empty category is a finding, not a row to drop.
    assert set(by_id) == {"war-and-state-formation", "identity-construction-and-boundary-making"}
    war = by_id["war-and-state-formation"]
    assert war["member_count"] == 5
    assert war["source_count"] == 3
    assert war["parent_id"] is None
    assert war["level"] == ROOT_LEVEL
    assert war["name"] == WAR_AND_STATE
    assert by_id["identity-construction-and-boundary-making"]["member_count"] == 0


# ---------------------------------------------------------------------------
# Reuse: an unchanged corpus and an unchanged scheme re-assign nothing
# ---------------------------------------------------------------------------


def test_a_second_build_over_an_unchanged_corpus_reuses_and_makes_zero_model_calls(tmp_path):
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    _build(tmp_path, _extraction_client())

    second_client = _extraction_client()
    stats = _build(tmp_path, second_client)

    assert second_client.calls_for_pass(EXAMINE_PASS_NAME) == 0
    assert second_client.asked_values == []
    result = stats.columns[0]
    assert result.reused is True
    assert result.newly_assigned_count == 0
    assert "reused" in format_vocabulary_build_report(stats).lower()


def test_a_second_build_leaves_the_artifact_byte_identical(tmp_path):
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    _build(tmp_path, _extraction_client())
    column_dir = tmp_path / "vocabulary" / "mechanism"
    before_assignments = (column_dir / ASSIGNMENTS_FILENAME).read_bytes()
    before_manifest = (column_dir / MANIFEST_FILENAME).read_bytes()

    _build(tmp_path, _extraction_client())

    assert (column_dir / ASSIGNMENTS_FILENAME).read_bytes() == before_assignments
    assert (column_dir / MANIFEST_FILENAME).read_bytes() == before_manifest


def test_a_model_swap_alone_does_not_re_assign(tmp_path):
    """Content-keyed like the decision logs: the pin covers the rendered
    input, so a different model on the second run reuses everything."""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    _build(tmp_path, _ScriptedAssignClient({v: WAR_AND_STATE for v in EXTRACTION}, "model/one"))

    other = _ScriptedAssignClient({v: WAR_AND_STATE for v in EXTRACTION}, "model/two")
    stats = _build(tmp_path, other)

    assert other.asked_values == []
    assert stats.columns[0].reused is True


# ---------------------------------------------------------------------------
# Incremental: a further source's answers assign, and only those
# ---------------------------------------------------------------------------


def test_a_further_source_assigns_only_its_own_values(tmp_path):
    answers_dir = tmp_path / "answers"
    _write_answers(answers_dir)
    _write_scheme(tmp_path / "vocabulary.yaml")
    _build(tmp_path, _extraction_client())
    before_lines = (
        (tmp_path / "vocabulary" / "mechanism" / ASSIGNMENTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    )

    new_values = _write_new_source(answers_dir)
    client = _extraction_client(**{value: WAR_AND_STATE for value in new_values})
    stats = _build(tmp_path, client)

    # Only the two new values ever reached the model.
    assert client.asked_values == new_values
    result = stats.columns[0]
    assert result.reused is False
    assert result.newly_assigned_count == 2
    assert result.reused_assignment_count == 8
    assert result.answered_count == 10

    # Every assignment already on disk is byte-identical to what it was.
    after_lines = (
        (tmp_path / "vocabulary" / "mechanism" / ASSIGNMENTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(after_lines) == 10
    for line in before_lines:
        assert line in after_lines


def test_an_edited_answer_is_re_assigned_but_its_neighbours_are_not(tmp_path):
    """The pin moves when any answer moves, but reuse is per value: only
    the value that actually changed goes back to the model."""
    answers_dir = tmp_path / "answers"
    _write_answers(answers_dir)
    _write_scheme(tmp_path / "vocabulary.yaml")
    _build(tmp_path, _extraction_client())

    replacement = "A census taken to raise troops became the register the state governed by."
    _write_jsonl(
        answers_dir / "gamma-2022.jsonl",
        [
            {"chunk_id": "gamma-2022_1", "source_id": "gamma-2022",
             "answers": {"mechanism": replacement}},
            {"chunk_id": "gamma-2022_2", "source_id": "gamma-2022",
             "answers": {"mechanism": ONE_OFFS[2]}},
        ],
    )
    client = _extraction_client(**{replacement: WAR_AND_STATE})
    stats = _build(tmp_path, client)

    assert client.asked_values == [replacement]
    assert stats.columns[0].newly_assigned_count == 1
    records = {r["chunk_id"]: r for r in _read_assignments(tmp_path / "vocabulary")}
    assert records["gamma-2022_1"]["value"] == replacement
    assert records["gamma-2022_1"]["category_id"] == "war-and-state-formation"


def test_a_removed_answer_drops_out_of_the_artifact_without_a_model_call(tmp_path):
    answers_dir = tmp_path / "answers"
    _write_answers(answers_dir)
    _write_scheme(tmp_path / "vocabulary.yaml")
    _build(tmp_path, _extraction_client())

    (answers_dir / "gamma-2022.jsonl").unlink()
    client = _extraction_client()
    stats = _build(tmp_path, client)

    assert client.asked_values == []
    assert stats.columns[0].newly_assigned_count == 0
    assert stats.columns[0].answered_count == 6
    assert len(_read_assignments(tmp_path / "vocabulary")) == 6


# ---------------------------------------------------------------------------
# The frozen scheme: two versions never mix in one artifact
# ---------------------------------------------------------------------------


def test_a_build_against_a_different_scheme_version_refuses_naming_both(tmp_path):
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    _build(tmp_path, _extraction_client())

    _write_scheme(tmp_path / "vocabulary.yaml", _SCHEME_YAML.replace("test-v1", "test-v2"))
    client = _extraction_client()
    with pytest.raises(SchemeVersionMismatchError) as excinfo:
        _build(tmp_path, client)

    message = str(excinfo.value)
    assert "test-v1" in message
    assert "test-v2" in message
    assert "mechanism" in message
    # Zero model calls, and the artifact on disk is untouched.
    assert client.asked_values == []
    assert _read_manifest(tmp_path / "vocabulary")["scheme_version"] == "test-v1"


def test_force_re_assigns_the_whole_column_under_the_new_scheme_version(tmp_path):
    """Refusing by default is right and stays. But `axial map build`
    refuses by default and re-spends behind an explicit flag, and without
    the same flag here the operator's only remedy is moving a directory by
    hand -- a remedy described in an exception message. `--force` is what
    the issue's "a scheme edit must re-assign" asks for, as a deliberate
    act."""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    _build(tmp_path, _extraction_client())

    _write_scheme(tmp_path / "vocabulary.yaml", _SCHEME_YAML.replace("test-v1", "test-v2"))
    client = _extraction_client()
    stats = _build(tmp_path, client, force=True)

    assert len(client.asked_values) == 8
    assert stats.columns[0].reused is False
    assert stats.columns[0].newly_assigned_count == 8
    assert stats.columns[0].reused_assignment_count == 0
    assert _read_manifest(tmp_path / "vocabulary")["scheme_version"] == "test-v2"
    assert len(_read_assignments(tmp_path / "vocabulary")) == 8


def test_force_sets_the_paid_artifact_aside_rather_than_deleting_it(tmp_path):
    """The old assignment is the only record of what each note was filed
    under and it was paid for, so `--force` moves it to a timestamped
    sibling -- the remedy the exception message already described, and the
    same promise `axial map build --force` makes about a paid ledger."""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    _build(tmp_path, _extraction_client())
    before = (tmp_path / "vocabulary" / "mechanism" / ASSIGNMENTS_FILENAME).read_bytes()

    _write_scheme(tmp_path / "vocabulary.yaml", _SCHEME_YAML.replace("test-v1", "test-v2"))
    stats = _build(tmp_path, _extraction_client(), force=True)

    aside = stats.columns[0].forced_aside
    assert aside is not None
    assert aside.parent == tmp_path / "vocabulary"
    assert (aside / ASSIGNMENTS_FILENAME).read_bytes() == before
    assert json.loads((aside / MANIFEST_FILENAME).read_text(encoding="utf-8"))[
        "scheme_version"
    ] == "test-v1"
    assert str(aside) in format_vocabulary_build_report(stats)


def test_force_re_asks_even_when_nothing_changed(tmp_path):
    """`--force` means rebuild, not "get past the version check": an
    unchanged pin and an unchanged scheme re-assign too, which is what
    makes it the remedy for an artifact that is wrong rather than stale."""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    _build(tmp_path, _extraction_client())

    client = _extraction_client()
    stats = _build(tmp_path, client, force=True)

    assert len(client.asked_values) == 8
    assert stats.columns[0].reused is False
    assert stats.columns[0].forced_aside is not None


def test_a_build_without_force_leaves_no_aside_directory(tmp_path):
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")

    stats = _build(tmp_path, _extraction_client())

    assert stats.columns[0].forced_aside is None
    assert [path.name for path in (tmp_path / "vocabulary").iterdir()] == ["mechanism"]


# ---------------------------------------------------------------------------
# An unanswered value is a failed run, not a result
# ---------------------------------------------------------------------------


def test_an_unanswered_value_is_never_persisted_as_a_hole_and_fails_the_build(
    tmp_path, monkeypatch
):
    """`_assign_batch`'s own key validation should make this unreachable --
    it re-asks a batch that does not return exactly the indexes it was
    asked about. The guard is here anyway, and tested through the same
    assignment path, because slice 01's first corpus run lost assignments
    exactly this way and read 50.7% where the truth was 88.5%."""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")

    real_assign_all = vocabulary_mod._assign_all

    def _lossy(client, pass_name, scheme_text, sample, workers=1):
        assignments = real_assign_all(client, pass_name, scheme_text, sample, workers)
        assignments.pop(1, None)
        return assignments

    monkeypatch.setattr(vocabulary_mod, "_assign_all", _lossy)

    stats = _build(tmp_path, _extraction_client())

    result = stats.columns[0]
    assert result.unanswered_count == 1
    assert result.complete is False
    assert stats.complete is False
    # The hole is absent from the artifact rather than written as a null
    # assignment, so the next run asks about it again instead of reusing a
    # value nobody ever answered.
    records = _read_assignments(tmp_path / "vocabulary")
    assert len(records) == 7
    assert _read_manifest(tmp_path / "vocabulary")["complete"] is False
    assert "unanswered" in format_vocabulary_build_report(stats)


def test_an_incomplete_artifact_is_not_reused_and_its_hole_is_re_asked(tmp_path, monkeypatch):
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")

    real_assign_all = vocabulary_mod._assign_all

    def _lossy(client, pass_name, scheme_text, sample, workers=1):
        assignments = real_assign_all(client, pass_name, scheme_text, sample, workers)
        assignments.pop(1, None)
        return assignments

    monkeypatch.setattr(vocabulary_mod, "_assign_all", _lossy)
    _build(tmp_path, _extraction_client())
    monkeypatch.setattr(vocabulary_mod, "_assign_all", real_assign_all)

    client = _extraction_client()
    stats = _build(tmp_path, client)

    assert client.asked_values == [EXTRACTION[0]]
    assert stats.columns[0].reused is False
    assert stats.columns[0].complete is True
    assert len(_read_assignments(tmp_path / "vocabulary")) == 8


# ---------------------------------------------------------------------------
# Assignment plumbing reused from slice 01
# ---------------------------------------------------------------------------


def test_assignment_batches_at_the_slice_01_batch_size_with_global_numbering(tmp_path):
    """`_assign_all` is slice 01's loop, not a second one: values beyond
    `BATCH_SIZE` land in a further call, numbered globally so the merged
    result is a single index space."""
    answers_dir = tmp_path / "answers"
    values = [f"mechanism sentence number {i}" for i in range(vocabulary_mod.BATCH_SIZE + 5)]
    _write_jsonl(
        answers_dir / "alpha-2020.jsonl",
        [
            {"chunk_id": f"alpha-2020_{i}", "source_id": "alpha-2020",
             "answers": {"mechanism": value}}
            for i, value in enumerate(values)
        ],
    )
    _write_scheme(tmp_path / "vocabulary.yaml")
    client = _ScriptedAssignClient({value: WAR_AND_STATE for value in values})

    stats = _build(tmp_path, client, workers=1)

    assert client.calls_for_pass(BUILD_PASS_NAME) == 2
    assert client.asked_values == values
    assert stats.columns[0].assigned_count == len(values)
    assert len(_read_assignments(tmp_path / "vocabulary")) == len(values)


def test_assignment_across_several_workers_produces_the_same_result_as_one(tmp_path):
    answers_dir = tmp_path / "answers"
    values = [f"mechanism sentence number {i}" for i in range(vocabulary_mod.BATCH_SIZE * 3)]
    _write_jsonl(
        answers_dir / "alpha-2020.jsonl",
        [
            {"chunk_id": f"alpha-2020_{i}", "source_id": "alpha-2020",
             "answers": {"mechanism": value}}
            for i, value in enumerate(values)
        ],
    )
    _write_scheme(tmp_path / "vocabulary.yaml")
    client = _ScriptedAssignClient({value: WAR_AND_STATE for value in values})

    stats = _build(tmp_path, client, workers=4)

    assert client.calls_for_pass(BUILD_PASS_NAME) == 3
    assert sorted(client.asked_values) == sorted(values)
    assert stats.columns[0].assigned_count == len(values)
    records = _read_assignments(tmp_path / "vocabulary")
    # Every record got its OWN value's assignment, not a neighbour's: with
    # batches running concurrently, a renumbered or mis-merged batch would
    # show up here as a value filed under the wrong chunk.
    by_chunk = {record["chunk_id"]: record["value"] for record in records}
    for i, value in enumerate(values):
        assert by_chunk[f"alpha-2020_{i}"] == value


def test_the_model_only_ever_sees_the_committed_scheme_not_a_proposal(tmp_path):
    """The scheme is an INPUT here. `build` never proposes: the only prompt
    it sends is the assign prompt, carrying the committed names and
    glosses."""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml")
    client = _extraction_client()

    _build(tmp_path, client)

    assert len(client.prompts) == 1
    prompt = client.prompts[0]
    assert "recurring KINDS" not in prompt
    assert WAR_AND_STATE in prompt
    assert "warfare drives state-building, extraction and institutional change" in prompt


def test_a_column_with_no_answers_writes_an_empty_artifact_without_a_model_call(tmp_path):
    (tmp_path / "answers").mkdir(parents=True, exist_ok=True)
    _write_scheme(tmp_path / "vocabulary.yaml")
    client = _extraction_client()

    stats = _build(tmp_path, client)

    assert client.asked_values == []
    assert stats.columns[0].answered_count == 0
    assert _read_assignments(tmp_path / "vocabulary") == []
    assert _read_manifest(tmp_path / "vocabulary")["complete"] is True


def test_build_refuses_a_scheme_deeper_than_the_level_it_assigns(tmp_path):
    """Depth 2 is not built in this slice (#806's own "what this slice must
    not do"). A committed scheme carrying a second level must be named, not
    half-honoured -- assigning only its roots and reporting success would
    silently drop half the scheme."""
    nested = _SCHEME_YAML.rstrip() + """
        children:
          - id: fiscal-extraction-for-war
            name: "fiscal extraction for war"
            gloss: "war costs are met by building the machinery that taxes"
"""
    _write_answers(tmp_path / "answers")
    _write_scheme(tmp_path / "vocabulary.yaml", nested)
    client = _extraction_client()

    with pytest.raises(VocabularySchemeError) as excinfo:
        _build(tmp_path, client)

    assert "mechanism" in str(excinfo.value)
    assert client.asked_values == []
