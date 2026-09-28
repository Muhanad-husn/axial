"""Issue #855: the argument map's relations are a vocabulary column.

`relations.jsonl` holds one free-text `relation` label and one `says`
sentence per relation between two positions. `axial vocabulary examine
--column relation` and `axial vocabulary build --column relation` run over
them through the same machinery the answer columns use (#805/#806), and the
build files every relation under a committed kind, written BESIDE its free
label, keyed by `(from_position_id, to_position_id, relation)`.

Every test injects a fake client; none makes a network call. Relation text
here is invented, never book text.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

import pytest

import axial.vocabulary as vocabulary_mod
from axial.cli import main
from axial.vocabulary import (
    ASSIGNMENTS_FILENAME,
    BUILD_PASS_NAME,
    CHECK_PASS_NAME,
    DEFAULT_VOCABULARY_SCHEME_PATH,
    EXAMINE_PASS_NAME,
    MANIFEST_FILENAME,
    RELATION_COLUMN,
    ROOT_LEVEL,
    NoRelationsError,
    build_vocabulary,
    examine_vocabulary,
    load_relation_records,
    load_vocabulary_scheme,
    read_column,
    relation_kind_examples,
)

# ---------------------------------------------------------------------------
# Fixtures: a tiny map directory and a client that assigns by reading its
# own prompt
# ---------------------------------------------------------------------------

POSITIONS = [
    {"position_id": "pos-1", "argument": "War made the state.", "size": 2,
     "sources": ["alpha-2020"], "authors": ["alpha"], "chunk_ids": ["alpha-2020_1"]},
    {"position_id": "pos-2", "argument": "Trade made the state.", "size": 1,
     "sources": ["beta-2021"], "authors": ["beta"], "chunk_ids": ["beta-2021_1"]},
    {"position_id": "pos-3", "argument": "Religion made the state.", "size": 1,
     "sources": ["gamma-2022"], "authors": ["gamma"], "chunk_ids": ["gamma-2022_1"]},
]

RELATIONS = [
    {"from_position_id": "pos-1", "to_position_id": "pos-2", "relation": "contradicts",
     "says": "a1 denies that trade rather than war built the state."},
    {"from_position_id": "pos-2", "to_position_id": "pos-3", "relation": "supports",
     "says": "a2 gives a reason to accept a3's account."},
    {"from_position_id": "pos-3", "to_position_id": "pos-1", "relation": "redirects explanation",
     "says": "a3 moves the cause of state formation away from war."},
]

CONFLICT = "conflict"
INFERENCE = "inference or support"

_SCHEME_YAML = """
columns:
  relation:
    version: "test-relation-v1"
    categories:
      - id: inference
        name: "inference or support"
        gloss: "one argument gives a reason for another"
      - id: conflict
        name: "conflict"
        gloss: "one argument attacks, denies or undercuts another"
      - id: preference
        name: "preference"
        gloss: "one argument is ranked above another"
"""


def _write_jsonl(path: Path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_map(map_dir: Path, relations=RELATIONS) -> Path:
    _write_jsonl(map_dir / "positions.jsonl", POSITIONS)
    _write_jsonl(map_dir / "relations.jsonl", relations)
    return map_dir


def _write_scheme(path: Path, text: str = _SCHEME_YAML) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


_NUMBERED = re.compile(r"^(\d+)\.\s(.*)$")


class _PromptReadingClient:
    """Proposes `categories` on a propose prompt; on an assign prompt reads
    each numbered value back and assigns it by the label it starts with.
    Records every assigned value in `asked_values`."""

    def __init__(self, category_by_label, categories=(), models=None):
        self._category_by_label = dict(category_by_label)
        self._categories = list(categories)
        self._models = models or {}
        self.asked_values: list[str] = []
        self.prompts: list[str] = []
        self._calls: dict[str, int] = collections.defaultdict(int)
        self._cost: dict[str, float] = collections.defaultdict(float)

    def complete(self, prompt, pass_name=None):
        self.prompts.append(prompt)
        self._calls[pass_name] += 1
        self._cost[pass_name] += 0.001
        if "say what recurring KINDS" in prompt:
            return json.dumps({"categories": self._categories})
        assignments = []
        for line in prompt.splitlines():
            match = _NUMBERED.match(line)
            if match is None:
                continue
            number, value = int(match.group(1)), match.group(2)
            self.asked_values.append(value)
            label = value.split(" -- ", 1)[0]
            assignments.append({"n": number, "category": self._category_by_label.get(label, "none")})
        return json.dumps({"assignments": assignments})

    def model_for_pass(self, pass_name=None):
        return self._models.get(pass_name, "fake/assign")

    def calls_for_pass(self, pass_name=None):
        return self._calls.get(pass_name, 0)

    def cost_for_pass(self, pass_name=None):
        return self._cost.get(pass_name) if self._calls.get(pass_name, 0) else None


def _kind_client() -> _PromptReadingClient:
    return _PromptReadingClient(
        {"contradicts": CONFLICT, "redirects explanation": CONFLICT, "supports": INFERENCE}
    )


def _build(tmp_path: Path, client, relations_dir: Path | None = None):
    if relations_dir is None:
        relations_dir = _write_map(tmp_path / "map" / "pin")
    return build_vocabulary(
        columns=[RELATION_COLUMN],
        scheme_path=_write_scheme(tmp_path / "vocabulary.yaml"),
        vocabulary_dir=tmp_path / "vocabulary",
        relations_dir=relations_dir,
        client=client,
    )


def _read_assignments(vocabulary_dir: Path) -> list[dict]:
    path = vocabulary_dir / RELATION_COLUMN / ASSIGNMENTS_FILENAME
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# Reading relations as a population
# ---------------------------------------------------------------------------


def test_a_relation_is_read_as_its_label_plus_its_says_sentence(tmp_path):
    """The model has to see what the relation SAYS, not just the two or
    three words of its label: 504 labels over 1,472 relations means most
    labels are one-offs, and the sentence is what places them."""
    records = load_relation_records(_write_map(tmp_path / "map"))
    population, excluded = read_column(records, RELATION_COLUMN)

    assert excluded == 0
    assert [entry.value for entry in population] == [
        "contradicts -- a1 denies that trade rather than war built the state.",
        "supports -- a2 gives a reason to accept a3's account.",
        "redirects explanation -- a3 moves the cause of state formation away from war.",
    ]
    assert population[0].relation_key == ("pos-1", "pos-2", "contradicts")


def test_a_relation_carries_the_books_on_both_of_its_ends_as_its_source(tmp_path):
    """A relation has no book of its own; the two positions it joins do.
    The examine/build reports count distinct sources per category, so a
    relation's source is the books on both ends -- a kind that recurs only
    between one pair of books reads as one source, never as many."""
    records = load_relation_records(_write_map(tmp_path / "map"))
    population, _ = read_column(records, RELATION_COLUMN)

    assert population[0].source_id == "alpha-2020+beta-2021"


def test_a_relation_with_no_label_or_a_repeated_key_is_excluded_and_counted(tmp_path):
    relations = RELATIONS + [
        {"from_position_id": "pos-1", "to_position_id": "pos-3", "relation": "", "says": "x"},
        dict(RELATIONS[0]),
    ]
    records = load_relation_records(_write_map(tmp_path / "map", relations))
    population, excluded = read_column(records, RELATION_COLUMN)

    assert len(population) == 3
    assert excluded == 2


def test_a_missing_relations_file_is_refused_by_name(tmp_path):
    with pytest.raises(NoRelationsError) as excinfo:
        load_relation_records(tmp_path / "nowhere")
    assert "relations.jsonl" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def test_build_files_every_relation_under_a_kind_beside_its_free_label(tmp_path):
    stats = _build(tmp_path, _kind_client())

    records = _read_assignments(tmp_path / "vocabulary")
    by_key = {
        (r["from_position_id"], r["to_position_id"], r["relation"]): r for r in records
    }
    assert set(by_key) == {
        ("pos-1", "pos-2", "contradicts"),
        ("pos-2", "pos-3", "supports"),
        ("pos-3", "pos-1", "redirects explanation"),
    }
    # The kind is written beside the free label, never over it.
    assert by_key[("pos-1", "pos-2", "contradicts")]["category_id"] == "conflict"
    assert by_key[("pos-1", "pos-2", "contradicts")]["relation"] == "contradicts"
    assert by_key[("pos-2", "pos-3", "supports")]["category_id"] == "inference"
    assert all(r["level"] == ROOT_LEVEL for r in records)
    assert all(r["column"] == RELATION_COLUMN for r in records)

    column = stats.columns[0]
    assert column.assigned_count == 3
    assert column.complete
    manifest = json.loads(
        (tmp_path / "vocabulary" / RELATION_COLUMN / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["scheme_version"] == "test-relation-v1"


def test_a_second_relation_build_over_the_same_map_asks_nothing(tmp_path):
    _build(tmp_path, _kind_client())
    second = _kind_client()
    stats = _build(tmp_path, second)

    assert second.asked_values == []
    assert second.calls_for_pass(BUILD_PASS_NAME) == 0
    assert stats.columns[0].reused


def test_a_relation_added_to_the_map_is_the_only_one_asked_about(tmp_path):
    _build(tmp_path, _kind_client())
    added = {"from_position_id": "pos-2", "to_position_id": "pos-1", "relation": "contradicts",
             "says": "a2 denies a1."}
    map_dir = _write_map(tmp_path / "map" / "pin", RELATIONS + [added])

    second = _kind_client()
    _build(tmp_path, second, relations_dir=map_dir)

    assert second.asked_values == ["contradicts -- a2 denies a1."]
    assert len(_read_assignments(tmp_path / "vocabulary")) == 4


def test_answer_columns_still_build_without_a_map(tmp_path):
    """Adding the relation column must not make every build need a map."""
    answers = tmp_path / "answers"
    _write_jsonl(
        answers / "alpha-2020.jsonl",
        [{"chunk_id": "alpha-2020_1", "source_id": "alpha-2020",
          "answers": {"mechanism": "War funds the army."}}],
    )
    scheme = _write_scheme(
        tmp_path / "v.yaml",
        _SCHEME_YAML
        + """
  mechanism:
    version: "m-v1"
    categories:
      - id: war
        name: "war"
        gloss: "war"
""",
    )
    client = _PromptReadingClient({"War funds the army.": "war"})
    stats = build_vocabulary(
        answers_dir=answers,
        columns=["mechanism"],
        scheme_path=scheme,
        vocabulary_dir=tmp_path / "vocabulary",
        relations_dir=tmp_path / "no-map-here",
        client=client,
    )
    assert stats.columns[0].column == "mechanism"


def test_cli_builds_the_relation_column(tmp_path, monkeypatch, capsys):
    map_dir = _write_map(tmp_path / "map" / "pin")
    scheme = _write_scheme(tmp_path / "vocabulary.yaml")
    client = _kind_client()
    monkeypatch.setattr(vocabulary_mod, "get_client", lambda *a, **kw: client)

    code = main(
        [
            "vocabulary", "build", "--column", RELATION_COLUMN,
            "--relations-dir", str(map_dir),
            "--scheme-path", str(scheme),
            "--vocabulary-dir", str(tmp_path / "vocabulary"),
        ]
    )

    assert code == 0
    assert "relation" in capsys.readouterr().out
    assert len(_read_assignments(tmp_path / "vocabulary")) == 3


def test_cli_names_a_missing_map_instead_of_crashing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vocabulary_mod, "get_client", lambda *a, **kw: _kind_client())
    code = main(
        [
            "vocabulary", "build", "--column", RELATION_COLUMN,
            "--relations-dir", str(tmp_path / "nowhere"),
            "--scheme-path", str(_write_scheme(tmp_path / "vocabulary.yaml")),
            "--vocabulary-dir", str(tmp_path / "vocabulary"),
        ]
    )
    assert code == 1
    assert "relations.jsonl" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Examine
# ---------------------------------------------------------------------------


def test_examine_runs_over_relations_exactly_as_over_an_answer_column(tmp_path):
    client = _PromptReadingClient(
        {"contradicts": "denial", "redirects explanation": "denial", "supports": "denial"},
        categories=[{"name": "denial", "gloss": "one argument denies another"}],
        models={EXAMINE_PASS_NAME: "fake/examine", CHECK_PASS_NAME: "fake/check"},
    )
    stats = examine_vocabulary(
        columns=[RELATION_COLUMN],
        propose_n=2,
        assign_n=1,
        seed=0,
        relations_dir=_write_map(tmp_path / "map"),
        client=client,
    )

    column = stats.columns[0]
    assert column.column == RELATION_COLUMN
    assert column.answered_count == 3
    assert column.propose_sample_size == 2
    assert column.assign_sample_size == 1
    assert column.assignment_rate == 1.0
    assert "The column is `relation`" in client.prompts[0]


def test_cli_examines_the_relation_column(tmp_path, monkeypatch, capsys):
    client = _PromptReadingClient(
        {},
        categories=[{"name": "denial", "gloss": "one argument denies another"}],
        models={EXAMINE_PASS_NAME: "fake/examine", CHECK_PASS_NAME: "fake/check"},
    )
    monkeypatch.setattr(vocabulary_mod, "get_client", lambda *a, **kw: client)

    code = main(
        [
            "vocabulary", "examine", "--column", RELATION_COLUMN,
            "--relations-dir", str(_write_map(tmp_path / "map")),
            "--propose-n", "2", "--assign-n", "1",
        ]
    )

    assert code == 0
    assert "relation: 3 answered value(s)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The committed seed, and what the map build is offered from it
# ---------------------------------------------------------------------------


def test_the_committed_relation_seed_is_aifs_three_genera_marked_draft():
    scheme = load_vocabulary_scheme(RELATION_COLUMN, DEFAULT_VOCABULARY_SCHEME_PATH)

    assert [category.id for category in scheme.at_level(ROOT_LEVEL)] == [
        "inference",
        "conflict",
        "preference",
    ]
    assert "draft" in scheme.version.lower()


def test_the_map_build_is_offered_only_kinds_below_the_genera(tmp_path):
    """The three genera are the standard's top level, not labels a reader
    of two arguments would coin. Offering "conflict" as an example label is
    the D8 collapse risk in its plainest form, so only the corpus's own
    kinds -- the children -- are ever offered, and a genera-only scheme
    offers nothing."""
    assert relation_kind_examples(_write_scheme(tmp_path / "flat.yaml")) == []

    nested = _SCHEME_YAML.replace(
        '        gloss: "one argument attacks, denies or undercuts another"\n',
        '        gloss: "one argument attacks, denies or undercuts another"\n'
        "        children:\n"
        "          - id: redirects-explanation\n"
        '            name: "redirects explanation"\n'
        '            gloss: "moves the cause somewhere else"\n',
    )
    examples = relation_kind_examples(_write_scheme(tmp_path / "nested.yaml", nested))
    assert [category.name for category in examples] == ["redirects explanation"]


def test_no_scheme_file_means_no_examples(tmp_path):
    assert relation_kind_examples(tmp_path / "absent.yaml") == []
