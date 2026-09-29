"""Issue #857: the committed category schemes as SKOS Turtle.

`export_skos` writes every column of `config/vocabulary.yaml` as one
`skos:ConceptScheme` and every category as a `skos:Concept` in it:
`skos:notation` carries the id, `skos:prefLabel` the name, `skos:definition`
the gloss, `skos:broader` the parent. A category's `close_match` in the yaml
(an ELSST concept, for `about`) becomes `skos:closeMatch`. Nothing in the
pipeline reads it back; it is a published cross-reference, never a gate.

`read_skos` recovers id, name, gloss and parent per column, which is what
makes the round trip checkable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, SKOS

from axial.vocabulary import _scheme_document, load_vocabulary_scheme, scheme_columns

AXIAL_VOCABULARY = Namespace("urn:axial:vocabulary:")
DEFAULT_SKOS_EXPORT_PATH = Path("data/vocabulary/vocabulary.ttl")


@dataclass(frozen=True)
class SkosExportStats:
    out_path: Path
    columns: list[str]
    concept_count: int
    close_match_count: int


def _close_matches(raw_categories: Any) -> dict[str, str]:
    matches: dict[str, str] = {}
    for entry in raw_categories or []:
        if entry.get("close_match"):
            matches[entry["id"]] = str(entry["close_match"]).strip()
        matches.update(_close_matches(entry.get("children")))
    return matches


def export_skos(scheme_path: Path, out_path: Path) -> SkosExportStats:
    """Write the whole scheme file at `scheme_path` as Turtle to `out_path`."""
    document = _scheme_document(scheme_path)
    graph = Graph()
    graph.bind("skos", SKOS)
    graph.bind("owl", OWL)
    graph.bind("axv", AXIAL_VOCABULARY)

    columns = scheme_columns(scheme_path)
    concept_count = close_match_count = 0
    for column in columns:
        scheme = load_vocabulary_scheme(column, scheme_path)
        matches = _close_matches(document["columns"][column].get("categories"))
        scheme_uri = AXIAL_VOCABULARY[column]
        graph.add((scheme_uri, RDF.type, SKOS.ConceptScheme))
        graph.add((scheme_uri, SKOS.prefLabel, Literal(column)))
        graph.add((scheme_uri, OWL.versionInfo, Literal(scheme.version)))

        for category in scheme.categories:
            concept = AXIAL_VOCABULARY[f"{column}:{category.id}"]
            graph.add((concept, RDF.type, SKOS.Concept))
            graph.add((concept, SKOS.inScheme, scheme_uri))
            graph.add((concept, SKOS.notation, Literal(category.id)))
            graph.add((concept, SKOS.prefLabel, Literal(category.name, lang="en")))
            graph.add((concept, SKOS.definition, Literal(category.gloss, lang="en")))
            if category.parent_id is None:
                graph.add((concept, SKOS.topConceptOf, scheme_uri))
                graph.add((scheme_uri, SKOS.hasTopConcept, concept))
            else:
                graph.add(
                    (concept, SKOS.broader, AXIAL_VOCABULARY[f"{column}:{category.parent_id}"])
                )
            if category.id in matches:
                graph.add((concept, SKOS.closeMatch, URIRef(matches[category.id])))
                close_match_count += 1
            concept_count += 1

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=out_path, format="turtle", encoding="utf-8")
    return SkosExportStats(out_path, columns, concept_count, close_match_count)


def read_skos(path: Path) -> dict[str, list[dict[str, str | None]]]:
    """Each scheme's categories in the Turtle at `path`, as id, name, gloss
    and parent id, keyed by column."""
    graph = Graph().parse(path, format="turtle")
    schemes: dict[str, list[dict[str, str | None]]] = {}
    for scheme_uri in graph.subjects(RDF.type, SKOS.ConceptScheme):
        column = str(graph.value(scheme_uri, SKOS.prefLabel))
        categories = []
        for concept in graph.subjects(SKOS.inScheme, scheme_uri):
            parent = graph.value(concept, SKOS.broader)
            categories.append(
                {
                    "id": str(graph.value(concept, SKOS.notation)),
                    "name": str(graph.value(concept, SKOS.prefLabel)),
                    "gloss": str(graph.value(concept, SKOS.definition)),
                    "parent_id": None if parent is None else str(graph.value(parent, SKOS.notation)),
                }
            )
        schemes[column] = categories
    return schemes
