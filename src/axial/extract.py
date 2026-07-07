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

The Unstructured fallback on docling failure/degenerate output (PRD §8 P0-2)
is out of scope for this slice; see slice 03.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import PictureItem, SectionHeaderItem, TableItem, TitleItem
from docling_core.types.doc.document import DoclingDocument

from axial.intake import IntakeError, intake

_ARTIFACT_TYPES = (TableItem, PictureItem)
_SECTION_TYPES = (TitleItem, SectionHeaderItem)


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
    root: dict = {"children": []}
    current_section: dict | None = None
    top_index = 0
    child_index = 0

    for item, _level in document.iterate_items():
        if isinstance(item, _SECTION_TYPES):
            top_index += 1
            child_index = 0
            current_section = _leaf_node(item, str(top_index))
            current_section["children"] = []
            root["children"].append(current_section)
            continue

        if current_section is None:
            top_index += 1
            root["children"].append(_leaf_node(item, str(top_index)))
            continue

        child_index += 1
        order = f"{current_section['order']}.{child_index}"
        current_section["children"].append(_leaf_node(item, order))

    return root


def extract(path: str | Path) -> dict:
    """Run structural extraction on `path`: validate (reusing intake), convert, normalize."""
    try:
        source = intake(path)
    except IntakeError as exc:
        raise SourceValidationError(exc) from exc

    try:
        document = convert(source.path)
    except Exception as exc:  # docling can raise a variety of internal errors
        raise ConversionError(source.path, str(exc)) from exc

    return normalize(document)
