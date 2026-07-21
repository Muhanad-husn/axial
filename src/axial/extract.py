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

import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable

from axial.intake import IntakeError, holdings_judged, intake
from axial.llm import LLMClient, LLMError, get_client

if TYPE_CHECKING:
    # Only used as type annotations; kept out of the runtime import path so
    # importing this module doesn't force docling/unstructured (and torch) to
    # load. See the lazy accessors below for the runtime equivalents.
    from docling.document_converter import DocumentConverter
    from docling_core.types.doc.document import DoclingDocument
    from unstructured.documents.elements import Element

# Fault-injection seam (locked by tests/test_extract_fallback.py): lets tests
# force the docling step to fail or degenerate deterministically, without
# needing docling to genuinely misbehave on a real source.
FORCE_FAILURE_ENV_VAR = "AXIAL_FORCE_DOCLING_FAILURE"

# Persisted structural-tree cache (PRD §5 stage 2, §7.4, §8 P0-2): one JSON
# per source in data/trees/, keyed by source_id (the same deterministic id
# used for the envelope, axial.envelope.compute_source_id). Mirrors
# axial.envelope.ENVELOPES_DIR's repo-root/cwd-relative constant exactly.
TREES_DIR = Path("data/trees")

_artifact_types: tuple[type, ...] | None = None
_section_types: tuple[type, ...] | None = None
_unstructured_artifact_types: tuple[type, ...] | None = None
_unstructured_section_types: tuple[type, ...] | None = None


def _get_artifact_types() -> tuple[type, ...]:
    """Lazily build the docling isinstance tuple so importing this module
    doesn't force docling to load."""
    global _artifact_types
    if _artifact_types is None:
        from docling_core.types.doc import PictureItem, TableItem

        _artifact_types = (TableItem, PictureItem)
    return _artifact_types


def _get_section_types() -> tuple[type, ...]:
    """Lazily build the docling isinstance tuple so importing this module
    doesn't force docling to load."""
    global _section_types
    if _section_types is None:
        from docling_core.types.doc import SectionHeaderItem, TitleItem

        _section_types = (TitleItem, SectionHeaderItem)
    return _section_types


def _get_unstructured_artifact_types() -> tuple[type, ...]:
    """Lazily build the unstructured isinstance tuple -- element classes that
    map to the locked "artifact" node type: tables and non-text visual
    elements -- so importing this module doesn't force unstructured to load.
    """
    global _unstructured_artifact_types
    if _unstructured_artifact_types is None:
        from unstructured.documents.elements import (
            CheckBox,
            FigureCaption,
            Formula,
            Image,
            Table as UnstructuredTable,
            TableChunk,
        )

        _unstructured_artifact_types = (
            UnstructuredTable,
            TableChunk,
            Image,
            FigureCaption,
            Formula,
            CheckBox,
        )
    return _unstructured_artifact_types


def _get_unstructured_section_types() -> tuple[type, ...]:
    """Lazily build the unstructured isinstance tuple. Only Title elements
    open a section node, matching docling's TitleItem/SectionHeaderItem.
    Unstructured's `Header` is running/page-header furniture (e.g. a Word
    section header), not a heading over body content -- treating it as a
    section-opener would nest unrelated body prose under it. It still
    classifies as an ordinary "prose" leaf node below (not an artifact), it
    just never opens a section.
    """
    global _unstructured_section_types
    if _unstructured_section_types is None:
        from unstructured.documents.elements import Title

        _unstructured_section_types = (Title,)
    return _unstructured_section_types


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
    return "artifact" if isinstance(item, _get_artifact_types()) else "prose"


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


# --- Post-extract text normalization (PRD §7.4, issue #188 Slice A) --------
#
# A deterministic, model-free pass that repairs decoding defects in a block's
# `text` before the tree is persisted. Organized as independent transforms,
# each a no-op when its target defect is absent, so a clean-font source
# passes through materially unchanged. Shared by both extraction paths
# (docling's `normalize()` and the Unstructured `_normalize_unstructured()`
# fallback) via `normalize_tree_text`, invoked once in `extract()` just
# before `persist_tree`.

_SOFT_HYPHEN = "­"

# Curated allowlist (never a blanket `/word` strip -- §7.4 safety principle):
# leaked glyph names mapped to their intended character.
_GLYPH_NAME_MAP = {
    "/asper": "ʿ",  # ayn
    "/lenis": "ʾ",  # hamza
}
_GLYPH_NAME_PATTERN = re.compile(
    "|".join(re.escape(name) + r"(?![\w-])" for name in _GLYPH_NAME_MAP), flags=re.IGNORECASE
)
# Font-internal glyph codes (e.g. `H1234`, `Q12`) that leak into text with no
# recoverable meaning: dropped outright.
_FONT_INTERNAL_CODE_PATTERN = re.compile(r"\bH\d{3,4}\b|\bQ\d{2}\b")

_DOTLESS_I = "ı"  # ı

_SPACE_BEFORE_PUNCT_PATTERN = re.compile(r"[ \t]+([,.;:!?])")
_WHITESPACE_RUN_PATTERN = re.compile(r"\s+")

# Private-Use-Area offset glyphs (§7.4): a font leaks a glyph at
# `U+F700 + real_codepoint`; recoverable when the offset lands on a usable
# printable character, dropped otherwise.
_PUA_OFFSET_BASE = 0xF700
_PUA_OFFSET_RANGE = range(0xF700, 0xF900)


def _strip_soft_hyphens(text: str) -> str:
    """Tier 1: strip soft-hyphens (U+00AD). No-op when absent."""
    return text.replace(_SOFT_HYPHEN, "")


def _remove_detached_sk_marks(text: str) -> str:
    """Tier 2: drop detached combining marks (Unicode category Sk -- a
    macron, acute, diaeresis, or cedilla left stranded by decoding, with
    nothing adjacent to reattach to). No-op when absent."""
    if not any(unicodedata.category(ch) == "Sk" for ch in text):
        return text
    return "".join(ch for ch in text if unicodedata.category(ch) != "Sk")


def _decode_pua_offset_glyphs(text: str) -> str:
    """Tier 2: decode recoverable Private-Use-Area offset glyphs via
    `chr(c - 0xF700)`; drop unrecoverable ones. No-op when absent."""
    if not any(ord(ch) in _PUA_OFFSET_RANGE for ch in text):
        return text
    out = []
    for ch in text:
        code = ord(ch)
        if code not in _PUA_OFFSET_RANGE:
            out.append(ch)
            continue
        candidate = chr(code - _PUA_OFFSET_BASE)
        if candidate.isprintable():
            out.append(candidate)
        # else: unrecoverable -- drop the glyph entirely.
    return "".join(out)


def _repair_glyph_names(text: str) -> str:
    """Tier 2: curated allowlist of leaked glyph names (`/asper` -> ayn,
    `/lenis` -> hamza) and font-internal codes (`H####`/`Q##`, dropped).
    Matches ONLY these specific curated names/patterns -- never a blanket
    `/word` strip -- so legitimate slash-words (`and/or`,
    `threat/opportunity`, `/reliefweb`, `/p111`) survive verbatim."""
    text = _GLYPH_NAME_PATTERN.sub(lambda m: _GLYPH_NAME_MAP[m.group(0).lower()], text)
    text = _FONT_INTERNAL_CODE_PATTERN.sub("", text)
    return text


def _normalize_dotless_i(text: str) -> str:
    """Tier 2: normalize dotless-i (U+0131) to ASCII 'i'. No-op when absent."""
    return text.replace(_DOTLESS_I, "i")


def _collapse_whitespace(text: str) -> str:
    """Tier 1: collapse runs of whitespace to a single space and remove
    space-before-punctuation. Run last so it also cleans up any residual
    double-space left behind by a Tier 2 drop (e.g. a removed font-internal
    code). No-op when the text is already clean."""
    text = _WHITESPACE_RUN_PATTERN.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT_PATTERN.sub(r"\1", text)
    return text


def normalize_text(text: str) -> str:
    """Compose the Tier 1 (whitespace) + Tier 2 (glyph) transforms into a
    single normalizer over one block's `text`. Each transform is
    independent and a no-op when its target defect is absent, so a
    clean-font string passes through materially unchanged (§7.4)."""
    text = _strip_soft_hyphens(text)
    text = _decode_pua_offset_glyphs(text)
    text = _remove_detached_sk_marks(text)
    text = _repair_glyph_names(text)
    text = _normalize_dotless_i(text)
    text = _collapse_whitespace(text)
    return text


def normalize_tree_text(tree: dict) -> dict:
    """Walk a `_build_tree`-shaped tree dict, normalizing every node's
    `text` value in place (§7.4 P0-2b). Every other field (`type`, `order`,
    `label`, the `children` nesting) is preserved exactly -- only `text` is
    eligible to change. Pure function: no I/O, no docling/Unstructured
    dependency, so it's directly unit-testable against synthetic trees."""

    def _walk(node: dict) -> None:
        if "text" in node:
            node["text"] = normalize_text(node["text"])
        for child in node.get("children", []):
            _walk(child)

    _walk(tree)
    return tree


def _build_converter() -> DocumentConverter:
    """Build a DocumentConverter with OCR disabled.

    OCR is a stated product non-goal (PRD §3, "No OCR path") and intake
    already guarantees a real, born-digital text layer before extract runs.
    Disabling it also avoids RapidOCR's model download from modelscope.cn on
    first run -- the flakiest of docling's model dependencies -- without
    affecting prose/table detection, which come from the PDF text layer and
    the layout/TableFormer models respectively.
    """
    # Local import: defers docling's (torch-backed) load until a conversion
    # actually runs.
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

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
    return _build_tree(items, lambda item: isinstance(item, _get_section_types()), _leaf_node)


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
        # Local import: defers docling's (torch-backed) load; only needed on
        # this forced-failure test path.
        from docling_core.types.doc.document import DoclingDocument

        return DoclingDocument(name="forced-degenerate")
    return convert(path)


def _classify_unstructured(element: Element) -> str:
    """Map an Unstructured element to the locked node `type`: 'prose' or 'artifact'."""
    return "artifact" if isinstance(element, _get_unstructured_artifact_types()) else "prose"


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
    # Local import: defers unstructured's load until the fallback path
    # actually runs.
    from unstructured.partition.docx import partition_docx
    from unstructured.partition.pdf import partition_pdf

    if path.suffix.lower() == ".docx":
        return partition_docx(filename=str(path))
    return partition_pdf(filename=str(path), strategy="fast")


def _normalize_unstructured(elements: list[Element]) -> dict:
    """Normalize an Unstructured element stream into the same locked
    `{children, type, order}` tree shape as `normalize()`."""
    # Local import: defers unstructured's load until the fallback path
    # actually runs.
    from unstructured.documents.elements import PageBreak

    items = (element for element in elements if not isinstance(element, PageBreak))
    return _build_tree(
        items,
        lambda element: isinstance(element, _get_unstructured_section_types()),
        _unstructured_leaf_node,
    )


def tree_path(source_id: str, trees_dir: Path = TREES_DIR) -> Path:
    """The persisted-tree path for `source_id` (PRD §7.4: 'One JSON per
    source in data/trees/, keyed by source_id')."""
    return trees_dir / f"{source_id}.json"


def load_persisted_tree(path: Path) -> dict:
    """Read a persisted structural tree back verbatim."""
    return json.loads(path.read_text(encoding="utf-8"))


def persist_tree(tree: dict, path: Path) -> None:
    """Write the structural tree JSON, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tree), encoding="utf-8")


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


def _intake_client(path: Path) -> LLMClient | None:
    """The client `intake()` needs to make this source's one model-backed
    judgment -- the §7.11 holdings check plus the §7.13 title-page read, one
    call for both -- or `None` when this call must not pay for it (§8 P0-1b,
    issue #303).

    Wiring it unconditionally would be wrong: `extract()` runs on every
    pipeline pass over every source, including the persisted-tree cache hits
    that are the common case, and the judgment is a reasoning-ON call. The
    §7.12 record is what makes it affordable -- it persists the judgment, so
    a source already judged (`holdings_judged`) is never re-judged and no
    client is even constructed for it.

    A client that cannot be built -- no API key configured, as in offline CI
    -- degrades to `None` with a warning, exactly as a failed check degrades
    inside `holdings.probe`: P0-1b forbids this check halting intake, and an
    unavailable model must not stop a source from being extracted. The
    source stays unjudged in the record and is judged on a later pass.
    """
    # Local import: avoids the circular import (axial.envelope imports
    # `extract` from this module at its own module top).
    from axial.envelope import MissingSourceError, compute_source_id

    try:
        source_id = compute_source_id(path)
    except (MissingSourceError, OSError):
        # Not a readable file: `intake()` is about to raise its own typed
        # error for it, which is the error the caller must see.
        return None

    if holdings_judged(source_id):
        return None

    try:
        return get_client()
    except LLMError as exc:
        print(
            f"holdings/bibliographic check unavailable for {path.name}: {exc}",
            file=sys.stderr,
        )
        return None


def extract(path: str | Path) -> dict:
    """Run structural extraction on `path`: validate (reusing intake), convert
    with docling, and normalize. If docling fails or returns degenerate
    (empty/structureless) output, fall back to Unstructured for that source
    and log the fallback (PRD §8 P0-2).

    Intake here is the pipeline's intake (PRD §5 stage 1): a source that has
    not yet been judged gets its §7.11 holdings check and §7.13 title-page
    read on this call, once, persisted into the §7.12 record -- see
    `_intake_client` for why that is conditional. A raised flag changes
    nothing about the extraction that follows (§7.11 is flag-only).

    The resulting tree is produced once per source_id and persisted to
    `data/trees/<source_id>.json` (PRD §7.4, §8 P0-2): a source whose
    source_id already has a persisted tree is read back verbatim here,
    without ever running docling/Unstructured again.

    The `AXIAL_FORCE_DOCLING_FAILURE` fault-injection seam (see
    tests/test_extract_fallback.py) exists purely to exercise the
    docling-failure/fallback path deterministically on demand; honoring the
    persisted-tree cache under it (reading a stale/real tree instead of
    forcing the failure, or writing the synthetic forced-failure result over
    a source's real cached tree) would defeat the seam and corrupt the real
    cache for every other caller of that same source. So while the seam is
    active, both the cache read and the cache write are skipped for this
    call; the source's real persisted tree (if any) is left untouched.
    """
    try:
        source = intake(path, client=_intake_client(Path(path)))
    except IntakeError as exc:
        raise SourceValidationError(exc) from exc

    # Local import: avoids a circular import (axial.envelope imports
    # `extract` from this module at its own module top).
    from axial.envelope import compute_source_id

    source_id = compute_source_id(source.path)
    out_path = tree_path(source_id, TREES_DIR)
    forced = _forced_failure_mode() is not None

    if not forced and out_path.exists():
        return load_persisted_tree(out_path)

    try:
        document = _convert_with_seam(source.path)
    except Exception as exc:  # docling can raise a variety of internal errors
        tree = normalize_tree_text(_fallback(source.path, f"docling raised an exception: {exc}"))
        if not forced:
            persist_tree(tree, out_path)
        return tree

    if is_degenerate(document):
        tree = normalize_tree_text(
            _fallback(source.path, "docling returned degenerate (empty/structureless) output")
        )
        if not forced:
            persist_tree(tree, out_path)
        return tree

    tree = normalize_tree_text(normalize(document))
    if not forced:
        persist_tree(tree, out_path)
    return tree


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
