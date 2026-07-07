"""Structural extraction: run docling on a validated source and normalize its
document model into the locked hierarchical tree (PRD §5 stage 2, §8 P0-2).

Docling exposes a source's body as a flat, reading-order stream of items
(section headers/titles, text, tables, pictures, ...), not an already-nested
tree. This module normalizes that flat stream into the locked contract: a
root object with a `children` list, where every node under the root
(recursively) carries `type` ("prose" or "artifact") and `order` (a stable,
dotted source-position string). Section headers/titles open a section node;
subsequent items become its children until the next section header/title,
giving the tree genuine nesting (root -> section -> content).

Fallback (PRD §8 P0-2, second bullet): if docling fails or produces
degenerate (empty/structureless) output for a source, Unstructured runs as
a fallback for that source, producing the same tree shape via the same
title/header-opens-a-section grouping rule; the fallback is logged to
stderr naming the source and the reason. A fault-injection seam
(`AXIAL_FORCE_DOCLING_FAILURE`, see tests/test_extract_fallback.py) lets
this be exercised deterministically without needing docling to genuinely
fail.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import PictureItem, SectionHeaderItem, TableItem, TitleItem
from docling_core.types.doc.document import DoclingDocument
from unstructured.documents.elements import (
    CheckBox,
    Element,
    FigureCaption,
    Formula,
    Image,
    PageBreak,
    Table as UnstructuredTable,
    TableChunk,
    Title,
)
from unstructured.partition.docx import partition_docx
from unstructured.partition.pdf import partition_pdf

from axial.intake import IntakeError, intake

_ARTIFACT_TYPES = (TableItem, PictureItem)
_SECTION_TYPES = (TitleItem, SectionHeaderItem)

# Fault-injection seam (locked by tests/test_extract_fallback.py): lets tests
# force the docling step to fail or degenerate deterministically, without
# needing docling to genuinely misbehave on a real source.
FORCE_FAILURE_ENV_VAR = "AXIAL_FORCE_DOCLING_FAILURE"

# Unstructured element classes that map to the locked "artifact" node type:
# tables and non-text visual elements.
_UNSTRUCTURED_ARTIFACT_TYPES = (
    UnstructuredTable,
    TableChunk,
    Image,
    FigureCaption,
    Formula,
    CheckBox,
)
# Only Title elements open a section node, matching docling's
# TitleItem/SectionHeaderItem. Unstructured's `Header` is running/page-header
# furniture (e.g. a Word section header), not a heading over body content --
# treating it as a section-opener would nest unrelated body prose under it.
# It still classifies as an ordinary "prose" leaf node below (not an artifact),
# it just never opens a section.
_UNSTRUCTURED_SECTION_TYPES = (Title,)


class ExtractError(Exception):
    """Base class for all structural-extraction errors."""


class SourceValidationError(ExtractError):
    """Raised when the source fails intake validation (missing/unsupported/no text layer)."""

    def __init__(self, cause: IntakeError):
        self.cause = cause
        super().__init__(str(cause))


class ConversionError(ExtractError):
    """Raised when docling fails to convert a validated source into a document model."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"failed to convert {path} with docling: {reason}")


def _classify(item: Any) -> str:
    """Map a docling doc item to the locked node `type`: 'prose' or 'artifact'."""
    return "artifact" if isinstance(item, _ARTIFACT_TYPES) else "prose"


def _leaf_node(item: Any, order: str) -> dict:
    """Build a locked-contract node ({type, order, ...}) for a single docling item."""
    node: dict = {"type": _classify(item), "order": order}
    text = getattr(item, "text", None)
    if text:
        node["text"] = text
    label = getattr(item, "label", None)
    if label is not None:
        node["label"] = str(label)
    return node


def _build_tree(
    items: Iterable[Any],
    is_section: Callable[[Any], bool],
    leaf_node: Callable[[Any, str], dict],
) -> dict:
    """Shared tree-builder: group a flat, reading-order item stream into the
    locked `{children, type, order}` tree. A "section" item opens a node that
    subsequent items nest under until the next section item; items before the
    first section stay at the top level (root -> section -> content).

    Used by both the docling path (`normalize`) and the Unstructured fallback
    path (`_normalize_unstructured`) so both emit the identical tree shape.
    """
    root: dict = {"children": []}
    current_section: dict | None = None
    top_index = 0
    child_index = 0

    for item in items:
        if is_section(item):
            top_index += 1
            child_index = 0
            current_section = leaf_node(item, str(top_index))
            current_section["children"] = []
            root["children"].append(current_section)
            continue

        if current_section is None:
            top_index += 1
            root["children"].append(leaf_node(item, str(top_index)))
            continue

        child_index += 1
        order = f"{current_section['order']}.{child_index}"
        current_section["children"].append(leaf_node(item, order))

    return root


def _build_converter() -> DocumentConverter:
    """Build a DocumentConverter with OCR disabled.

    OCR is a stated product non-goal (PRD §3, "No OCR path") and intake
    already guarantees a real, born-digital text layer before extract runs.
    Disabling it also avoids RapidOCR's model download from modelscope.cn on
    first run -- the flakiest of docling's model dependencies -- without
    affecting prose/table detection, which come from the PDF text layer and
    the layout/TableFormer models respectively.
    """
    pipeline_options = PdfPipelineOptions(do_ocr=False)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )


def convert(path: Path) -> DoclingDocument:
    """Run docling's DocumentConverter over `path`, returning its document model."""
    converter = _build_converter()
    result = converter.convert(str(path))
    return result.document


def normalize(document: DoclingDocument) -> dict:
    """Normalize a docling document into the locked `{children, type, order}` tree."""
    items = (item for item, _level in document.iterate_items())
    return _build_tree(items, lambda item: isinstance(item, _SECTION_TYPES), _leaf_node)


def is_degenerate(document: DoclingDocument) -> bool:
    """Flag a docling result as degenerate: empty/structureless output with no
    items at all, which downstream normalization can't turn into a useful tree.
    """
    for _item, _level in document.iterate_items():
        return False
    return True


def _forced_failure_mode() -> str | None:
    """Read the `AXIAL_FORCE_DOCLING_FAILURE` fault-injection seam (see
    tests/test_extract_fallback.py): unset/"" means no forced failure."""
    mode = os.environ.get(FORCE_FAILURE_ENV_VAR, "")
    return mode or None


def _convert_with_seam(path: Path) -> DoclingDocument:
    """Run docling's real conversion, unless the fault-injection seam is set --
    in which case short-circuit *before* calling docling's real `.convert()`,
    so forced-failure tests stay fast and need no docling model weights."""
    mode = _forced_failure_mode()
    if mode == "exception":
        raise ConversionError(
            path, "forced docling failure via AXIAL_FORCE_DOCLING_FAILURE=exception"
        )
    if mode == "degenerate":
        return DoclingDocument(name="forced-degenerate")
    return convert(path)


def _classify_unstructured(element: Element) -> str:
    """Map an Unstructured element to the locked node `type`: 'prose' or 'artifact'."""
    return "artifact" if isinstance(element, _UNSTRUCTURED_ARTIFACT_TYPES) else "prose"


def _unstructured_leaf_node(element: Element, order: str) -> dict:
    """Build a locked-contract node ({type, order, ...}) for an Unstructured element."""
    node: dict = {"type": _classify_unstructured(element), "order": order}
    text = str(element).strip()
    if text:
        node["text"] = text
    category = getattr(element, "category", None)
    if category:
        node["label"] = str(category)
    return node


def _partition_with_unstructured(path: Path) -> list[Element]:
    """Partition `path` with Unstructured's fast (text-first) strategy: pdfminer
    text extraction only -- no OCR, no hi_res layout models, no tesseract --
    matching intake's born-digital-only guarantee.
    """
    if path.suffix.lower() == ".docx":
        return partition_docx(filename=str(path))
    return partition_pdf(filename=str(path), strategy="fast")


def _normalize_unstructured(elements: list[Element]) -> dict:
    """Normalize an Unstructured element stream into the same locked
    `{children, type, order}` tree shape as `normalize()`."""
    items = (element for element in elements if not isinstance(element, PageBreak))
    return _build_tree(
        items,
        lambda element: isinstance(element, _UNSTRUCTURED_SECTION_TYPES),
        _unstructured_leaf_node,
    )


def _log_fallback(path: Path, reason: str) -> None:
    """Log the fallback event to stderr (never stdout, which stays pure JSON).

    Must give evidence that (a) docling failed/degenerated, (b) Unstructured
    was used as a result, and (c) the source file is named -- the per-source
    judgment record P1-3 depends on later.
    """
    print(
        f"fallback: docling failed for {path.name} ({reason}); using unstructured as fallback",
        file=sys.stderr,
    )


def extract(path: str | Path) -> dict:
    """Run structural extraction on `path`: validate (reusing intake), convert
    with docling, and normalize. If docling fails or returns degenerate
    (empty/structureless) output, fall back to Unstructured for that source
    and log the fallback (PRD §8 P0-2).
    """
    try:
        source = intake(path)
    except IntakeError as exc:
        raise SourceValidationError(exc) from exc

    try:
        document = _convert_with_seam(source.path)
    except Exception as exc:  # docling can raise a variety of internal errors
        return _fallback(source.path, f"docling raised an exception: {exc}")

    if is_degenerate(document):
        return _fallback(source.path, "docling returned degenerate (empty/structureless) output")

    return normalize(document)


def _fallback(path: Path, reason: str) -> dict:
    """Log the fallback and run the Unstructured adapter in docling's place."""
    _log_fallback(path, reason)
    try:
        elements = _partition_with_unstructured(path)
    except Exception as exc:
        raise ConversionError(
            path, f"docling failed ({reason}) and the unstructured fallback also failed: {exc}"
        ) from exc
    return _normalize_unstructured(elements)
