"""Issue #857: the committed schemes export to SKOS, and `about` cross-maps to ELSST.

`axial vocabulary export` writes every column of `config/vocabulary.yaml` as
SKOS Turtle: one `skos:ConceptScheme` per column, one `skos:Concept` per
category id, `skos:prefLabel` from `name`, `skos:definition` from `gloss`,
`skos:broader` from the parent. A category's `close_match` in the yaml
becomes `skos:closeMatch`; it is a published cross-reference, never a gate.
"""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDF, SKOS

from axial.cli import main
from axial.vocabulary import (
    DEFAULT_VOCABULARY_SCHEME_PATH,
    ROOT_LEVEL,
    load_vocabulary_scheme,
    scheme_columns,
)
from axial.vocabulary_skos import export_skos, read_skos

_NESTED_YAML = """
columns:
  about:
    version: "test-about-v1"
    categories:
      - id: war
        name: "war and violence"
        gloss: "answers about war"
        close_match: "https://elsst.cessda.eu/id/7/61b5e15a-e082-4efc-87c4-7238a729bb58"
        children:
          - id: civil-war
            name: "civil war"
            gloss: "answers about war inside one state"
      - id: states
        name: "state formation"
        gloss: "answers about how states form"
  move:
    version: "test-move-v1"
    categories:
      - id: concede
        name: "concede and narrow"
        gloss: "grants a point, then limits it"
"""


def _scheme(tmp_path: Path, text: str = _NESTED_YAML) -> Path:
    path = tmp_path / "vocabulary.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _categories_from_yaml(scheme_path: Path) -> dict[str, list[tuple]]:
    return {
        column: sorted(
            (c.id, c.name, c.gloss, c.parent_id)
            for c in load_vocabulary_scheme(column, scheme_path).categories
        )
        for column in scheme_columns(scheme_path)
    }


def test_export_writes_turtle_that_rdflib_parses_with_a_scheme_per_column(tmp_path):
    out = tmp_path / "vocabulary.ttl"
    export_skos(_scheme(tmp_path), out)

    graph = Graph().parse(out, format="turtle")
    schemes = set(graph.subjects(RDF.type, SKOS.ConceptScheme))
    assert len(schemes) == 2
    assert len(set(graph.subjects(RDF.type, SKOS.Concept))) == 4


def test_every_category_id_is_a_concept_with_label_definition_and_broader(tmp_path):
    out = tmp_path / "vocabulary.ttl"
    export_skos(_scheme(tmp_path), out)
    graph = Graph().parse(out, format="turtle")

    by_notation = {
        str(graph.value(concept, SKOS.notation)): concept
        for concept in graph.subjects(RDF.type, SKOS.Concept)
    }
    assert set(by_notation) == {"war", "civil-war", "states", "concede"}
    civil_war = by_notation["civil-war"]
    assert str(graph.value(civil_war, SKOS.prefLabel)) == "civil war"
    assert str(graph.value(civil_war, SKOS.definition)) == "answers about war inside one state"
    assert graph.value(civil_war, SKOS.broader) == by_notation["war"]
    assert (by_notation["war"], SKOS.topConceptOf, None) in graph
    assert graph.value(by_notation["war"], SKOS.broader) is None


def test_round_trip_yaml_to_turtle_to_yaml_is_lossless(tmp_path):
    scheme = _scheme(tmp_path)
    out = tmp_path / "vocabulary.ttl"
    export_skos(scheme, out)

    recovered = {
        column: sorted((c["id"], c["name"], c["gloss"], c["parent_id"]) for c in categories)
        for column, categories in read_skos(out).items()
    }
    assert recovered == _categories_from_yaml(scheme)


def test_a_close_match_in_the_yaml_becomes_skos_close_match_and_nothing_else_does(tmp_path):
    out = tmp_path / "vocabulary.ttl"
    export_skos(_scheme(tmp_path), out)
    graph = Graph().parse(out, format="turtle")

    matches = list(graph.subject_objects(SKOS.closeMatch))
    assert len(matches) == 1
    assert matches[0][1] == URIRef(
        "https://elsst.cessda.eu/id/7/61b5e15a-e082-4efc-87c4-7238a729bb58"
    )
    assert str(graph.value(matches[0][0], SKOS.notation)) == "war"


def test_the_committed_file_round_trips_and_every_id_is_a_concept(tmp_path):
    out = tmp_path / "vocabulary.ttl"
    export_skos(DEFAULT_VOCABULARY_SCHEME_PATH, out)
    graph = Graph().parse(out, format="turtle")

    notations = {str(n) for n in graph.objects(None, SKOS.notation)}
    expected = _categories_from_yaml(DEFAULT_VOCABULARY_SCHEME_PATH)
    for column, categories in expected.items():
        assert {c[0] for c in categories} <= notations, column
    assert {
        column: sorted((c["id"], c["name"], c["gloss"], c["parent_id"]) for c in cats)
        for column, cats in read_skos(out).items()
    } == expected


def test_about_and_move_are_committed_flat_and_dated():
    about = load_vocabulary_scheme("about", DEFAULT_VOCABULARY_SCHEME_PATH)
    move = load_vocabulary_scheme("move", DEFAULT_VOCABULARY_SCHEME_PATH)

    assert len(about.at_level(ROOT_LEVEL)) == 10
    assert len(move.at_level(ROOT_LEVEL)) == 13
    assert about.max_level == ROOT_LEVEL and move.max_level == ROOT_LEVEL
    assert "draft" not in about.version.lower() and "draft" not in move.version.lower()


def test_cli_export_writes_the_turtle_file(tmp_path, capsys):
    out = tmp_path / "out" / "vocabulary.ttl"
    code = main(
        ["vocabulary", "export", "--scheme-path", str(_scheme(tmp_path)), "--out", str(out)]
    )

    assert code == 0
    assert out.is_file()
    printed = capsys.readouterr().out
    assert "4 concept(s)" in printed
    assert "1 closeMatch" in printed
