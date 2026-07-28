"""Outer acceptance test for issue #30, slice 01 (artifact collection);
rewritten for issue #429, which retires the artifacts pass's LLM call and
its `artifact_role`/`field` axes.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given an extracted fixture source containing at least one artifact node (a
      table or figure)
When  the user runs `axial artifacts <fixture>`
Then  it exits 0 and emits one record per artifact node as JSON
And   each record carries a stable artifact_id and source/section provenance
And   the pass makes no LLM call (no `AXIAL_LLM_PROVIDER` is required at all)

See specs/PRODUCT.md §5 stage 5 ("Artifact classification & routing... makes
no LLM call; retrievable is a rule over caption presence") and §8 P0-5 for
the source of truth.

Why #429 rewrote this file's contract: two independent runs over the same
real source disagreed on `artifact_role` for 48.5% of artifacts and flipped
the keep/discard bit on 13.1% of them -- the artifact record carries no
content beyond ids, section and caption, so `artifact_role`/`field` were the
pass's entire output and neither reproduced. The axis, the classification
call, and this file's old hard-error-on-out-of-schema-role contract are all
gone; `retrievable` is decided downstream by `axial.vault.
build_artifact_frontmatter` as a rule over caption presence, not asserted
here (this file's own contract ends at the artifacts-pass stdout, same as
before).

Fixture reuse: tests/fixtures/extract/prose_and_table.pdf (see
tests/test_extract.py and its _generate.py) is a two-section fixture --
"Introduction" (two paragraphs, then one bordered-grid table) followed by
"Discussion" (two paragraphs, no artifact). _generate.py's
`make_prose_and_table_pdf` adds exactly one `Table` flowable to the whole
document, so this fixture carries exactly one artifact node, nested under
the "Introduction" section (extract.py's tree-builder nests trailing content
under the most recent heading until the next one) -- never under
"Discussion".

Seam decision (carried over from the original test) -- artifact_id: locking
the prefix and stability, not the exact order suffix
-----------------------------------------------------------------------
`artifact_id` is `<source_id>_art_<order>`, where `source_id` is
`axial.envelope.compute_source_id`'s deterministic filename-stem +
content-hash id (computable here directly, without running extraction) and
`order` is the artifact node's own dotted position string from
extract.py's tree-builder (e.g. "1.3"). This test asserts the locked PREFIX
(`f"{source_id}_art_"`) and a dotted-digits SHAPE for the remainder, plus
STABILITY across two consecutive runs on the same fixture -- but does not
hardcode the exact order suffix (see the original test's own note on why:
a real docling conversion is not pinned to a specific node-count/order by
any other locked test).

Arrange-mechanism change (issue #45, tree-cache) -- no behavioral assertion
changed
-----------------------------------------------------------------------
This test's PURPOSE is artifact collection (artifact_id/provenance) -- it
consumes the structural tree only as input, it never asserts anything about
extraction/tree shape itself. `axial artifacts` calls `axial.extract.extract`
directly, which reuses a persisted tree verbatim at
data/trees/<source_id>.json instead of re-running docling. So this test
pre-places the committed REAL tree fixture
(tests/fixtures/extract/prose_and_table_tree.json) before every run, exactly
as it would look after a real extraction, only without paying for one.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import axial.artifacts as artifacts_module
import axial.chunk as chunk_module
from axial.chunk import run_chunk_recursive
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "extract"
TREES_DIR = REPO_ROOT / "data" / "trees"

PROSE_AND_TABLE_PDF = FIXTURES_DIR / "prose_and_table.pdf"
PROSE_AND_TABLE_TREE_FIXTURE = FIXTURES_DIR / "prose_and_table_tree.json"

# This fixture's only artifact node (a single bordered-grid table) sits
# under this section's heading, verbatim (see module docstring, "Fixture
# reuse").
EXPECTED_SECTION = "Introduction"

# argparse's fallback error for an as-yet-nonexistent subcommand, e.g.
# "axial: error: argument command: invalid choice: 'artifacts' (choose
# from 'schema', 'intake', 'extract', 'envelope', 'chunk', 'vault')". Any of
# these substrings in the combined output means the target subcommand's
# logic was never actually exercised -- the process failed before real
# behavior ran. Reject that generic failure mode explicitly so this test
# can only pass once real `artifacts` behavior exists.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_artifacts(*args: str) -> subprocess.CompletedProcess:
    """No `AXIAL_LLM_PROVIDER` env var is set here at all (issue #429): the
    artifacts pass makes no LLM call, so there is nothing to stub."""
    return subprocess.run(
        ["uv", "run", "axial", "artifacts", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `artifacts` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `artifacts` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _parse_artifact_records(stdout: str) -> list[dict]:
    """Parse artifact records from `axial artifacts`'s stdout, tolerating any
    of the three stdout shapes this test locks: a bare JSON array, a JSON
    object with an "artifacts" array, or newline-delimited JSON (one record
    per line)."""
    stripped = stdout.strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None

    if data is not None:
        if isinstance(data, dict):
            assert "artifacts" in data, (
                f"expected a top-level 'artifacts' key when artifacts stdout "
                f"is a JSON object, got keys: {sorted(data.keys())}; stdout: {stdout!r}"
            )
            records = data["artifacts"]
        else:
            records = data
        assert isinstance(records, list), (
            f"expected artifact records to be a JSON array (bare, or under "
            f"an 'artifacts' key), got {type(records).__name__}: {records!r}"
        )
        return records

    records = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"expected artifacts stdout to be either one parseable JSON "
                f"document (a bare array, or an object with a top-level "
                f"'artifacts' array) or newline-delimited JSON (one artifact "
                f"record object per line); line {line!r} failed to parse "
                f"({exc}). Full stdout: {stdout!r}"
            ) from None
    return records


def _expected_source_id() -> str:
    """This fixture's deterministic source_id, computed directly (no
    extraction needed) via the same function the artifacts pass must reuse
    for its `artifact_id` prefix."""
    return compute_source_id(PROSE_AND_TABLE_PDF)


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    data/trees/<source_id>.json (source_id via
    axial.envelope.compute_source_id) so `axial.extract.extract` reuses it
    verbatim instead of running docling."""
    source_id = compute_source_id(source_pdf)
    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def test_artifacts_emits_one_record_per_artifact_node_with_id_and_provenance_and_no_llm_call():
    source_id = _expected_source_id()
    _place_tree_fixture(PROSE_AND_TABLE_PDF, PROSE_AND_TABLE_TREE_FIXTURE)

    # --- first run: no LLM provider configured at all -- must still succeed ---
    first = _run_artifacts(str(PROSE_AND_TABLE_PDF))
    _assert_not_argparse_fallback(first)
    assert first.returncode == 0, (
        f"expected exit code 0 for `axial artifacts` on a fixture source "
        f"with an artifact node -- no LLM provider is configured at all, "
        f"proving the pass makes no LLM call (issue #429) -- got "
        f"{first.returncode}\nstdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    )

    first_records = _parse_artifact_records(first.stdout)
    assert len(first_records) == 1, (
        f"expected exactly one artifact record (this fixture carries exactly "
        f"one artifact node -- see module docstring, 'Fixture reuse'), got "
        f"{len(first_records)}; stdout: {first.stdout!r}"
    )

    record = first_records[0]
    assert isinstance(record, dict), (
        f"expected the artifact record to be a JSON object, got {type(record).__name__}: {record!r}"
    )

    artifact_id = record.get("artifact_id")
    assert isinstance(artifact_id, str) and artifact_id.strip(), (
        f"expected the artifact record to carry a non-empty string "
        f"'artifact_id', got {artifact_id!r} (full record: {record!r})"
    )
    assert re.fullmatch(rf"{re.escape(source_id)}_art_[0-9]+(\.[0-9]+)*", artifact_id), (
        f"expected artifact_id to match '<source_id>_art_<order>' "
        f"(source_id={source_id!r}, order a dotted-digits string per "
        f"extract.py), got {artifact_id!r}"
    )

    assert record.get("source_id") == source_id, (
        f"expected the artifact record to carry 'source_id' == {source_id!r} "
        f"(source provenance, PRD §7.2), got {record.get('source_id')!r} "
        f"(full record: {record!r})"
    )
    assert record.get("section") == EXPECTED_SECTION, (
        f"expected the artifact record to carry 'section' == "
        f"{EXPECTED_SECTION!r} (this fixture's enclosing section's own "
        f"verbatim heading -- section provenance, PRD §7.2), got "
        f"{record.get('section')!r} (full record: {record!r})"
    )

    # --- issue #429: no `artifact_role`/`field` key at all -- the pass
    # makes no LLM call, so it has nothing to classify with. ---
    assert "artifact_role" not in record, (
        f"expected no 'artifact_role' key at all (issue #429: the artifacts "
        f"pass makes no LLM call), got: {record!r}"
    )
    assert "field" not in record, f"expected no 'field' key at all (issue #429), got: {record!r}"

    # --- second run: same fixture -- artifact_id must be stable ---
    second = _run_artifacts(str(PROSE_AND_TABLE_PDF))
    _assert_not_argparse_fallback(second)
    assert second.returncode == 0, (
        f"expected exit code 0 on a repeat `axial artifacts` run over the "
        f"same fixture, got {second.returncode}\n"
        f"stdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    )

    second_records = _parse_artifact_records(second.stdout)
    assert len(second_records) == 1, (
        f"expected exactly one artifact record on the repeat run too, got "
        f"{len(second_records)}; stdout: {second.stdout!r}"
    )
    assert second_records[0].get("artifact_id") == artifact_id, (
        f"expected a stable/deterministic artifact_id across repeat runs on "
        f"the same input (PRD §8 P0-5 read together with P0-4's 'stable' "
        f"precedent for chunk_id), got {artifact_id!r} on the first run and "
        f"{second_records[0].get('artifact_id')!r} on the second run"
    )


# ===========================================================================
# Outer acceptance test for issue #168 (source-router slice 03:
# artifact-caption-routing), rewritten for issue #429 (no LLM call).
#
# Locked behavioral contract (DEC-1) -- do not edit once committed red.
#
# Spec: plans/source-router/03-artifact-caption-routing.md; PRD §7.8 (source
# router), §5 stage 5 / §7.2 (artifact notes). The artifact pass collects
# artifact-routed blocks (table/picture become vault artifact notes as
# today); a `caption` block attaches to its figure/table -- its text rides
# on that artifact's own record rather than being lost or chunked.
# Apparatus-routed blocks (document_index, footnote) are never picked up as
# artifacts.
#
# Acceptance criterion (issue #168 plan)
# ---------------------------------------------------------------------
# Given a persisted tree with a captioned figure, a table, a
#       table-of-contents (document_index), and an endnotes (footnote)
#       section
# When  the operator runs `axial artifacts` on the source
# Then  the figure and the table each become one vault artifact note
# And   the figure's artifact note carries its caption text (attached, not
#       lost)
# And   no artifact note is produced for the document_index or footnote
#       blocks
# And   the caption is absent from data/chunks/<source_id>.jsonl
#       (established in slice 02, still true)
#
# Seam decision -- bypassing docling entirely via a monkeypatched
# `axial.artifacts.extract`, calling `run_artifacts` directly
# ---------------------------------------------------------------------
# `run_artifacts` imports `extract` directly into its own module namespace,
# so monkeypatching `axial.artifacts.extract` redirects every call to a fake
# returning a hand-built, synthetic extraction tree -- no real PDF, no
# docling, no network.
# ===========================================================================

_ROUTING_PROSE_BODY = (
    "Ordinary prose sentinel discussing the excavation's overall stratigraphic "
    "sequence across the three seasons of fieldwork in careful detail."
)
_ROUTING_TABLE_BODY = (
    "Table sentinel: quarterly summary of measured artifact counts across "
    "the three excavation trenches, tallied by depth and material type."
)
_ROUTING_FIGURE_BODY = "Figure node placeholder text (docling picture item)."
_ROUTING_CAPTION_BODY = (
    "Caption sentinel: aerial photograph of the northern excavation trench "
    "taken during the spring survey season by the site photographer."
)
_ROUTING_TOC_BODY = (
    "Table-of-contents sentinel entry: Chapter One .. 1, Chapter Two .. 40, "
    "Appendix .. 88, listing every part of the report in reading order."
)
_ROUTING_FOOTNOTE_BODY = (
    "Footnote sentinel: see supplementary note four for the full derivation "
    "of the radiocarbon calibration used throughout this report."
)


def _build_caption_routing_tree() -> dict:
    """A tree with, in one prose section: ordinary prose, a table, a
    captioned figure (caption immediately follows the figure -- the natural
    reading-order adjacency), and a document_index (TOC) block; and, in a
    second section, a footnote (endnotes) block -- mirroring the Gherkin's
    "captioned figure, a table, a table-of-contents, and an endnotes
    section" verbatim."""
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Findings",
                "label": "section_header",
                "children": [
                    {
                        "type": "prose",
                        "order": "1.1",
                        "label": "text",
                        "text": _ROUTING_PROSE_BODY,
                    },
                    {
                        "type": "artifact",
                        "order": "1.2",
                        "label": "table",
                        "text": _ROUTING_TABLE_BODY,
                    },
                    {
                        "type": "artifact",
                        "order": "1.3",
                        "label": "picture",
                        "text": _ROUTING_FIGURE_BODY,
                    },
                    {
                        "type": "prose",
                        "order": "1.4",
                        "label": "caption",
                        "text": _ROUTING_CAPTION_BODY,
                    },
                    {
                        "type": "prose",
                        "order": "1.5",
                        "label": "document_index",
                        "text": _ROUTING_TOC_BODY,
                    },
                ],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Endnotes",
                "label": "section_header",
                "children": [
                    {
                        "type": "prose",
                        "order": "2.1",
                        "label": "footnote",
                        "text": _ROUTING_FOOTNOTE_BODY,
                    },
                ],
            },
        ]
    }


def _record_contains_text(value: object, text: str) -> bool:
    """Recursively scan `value` (a JSON-shaped artifact record: nested
    dicts/lists/strings) for `text` appearing as a substring of any string
    it contains."""
    if isinstance(value, str):
        return text in value
    if isinstance(value, dict):
        return any(_record_contains_text(v, text) for v in value.values())
    if isinstance(value, list):
        return any(_record_contains_text(v, text) for v in value)
    return False


def test_captioned_figure_and_table_become_artifact_notes_apparatus_excluded(tmp_path, monkeypatch):
    tree = _build_caption_routing_tree()
    monkeypatch.setattr(artifacts_module, "extract", lambda path: tree)

    source_path = tmp_path / "artifact_caption_routing_source.txt"
    source_path.write_text("issue 168 artifact caption routing test source", encoding="utf-8")
    source_id = compute_source_id(source_path)

    records = artifacts_module.run_artifacts(source_path)

    assert isinstance(records, list), (
        f"expected run_artifacts to return a list, got {type(records).__name__}: {records!r}"
    )

    table_artifact_id = f"{source_id}_art_1.2"
    figure_artifact_id = f"{source_id}_art_1.3"

    # --- exactly one artifact note per figure/table; the TOC and footnote
    # blocks never become artifact notes at all ------------------------------
    assert len(records) == 2, (
        f"expected exactly one artifact note for the table and one for the "
        f"figure (two total) -- the document_index and footnote blocks must "
        f"never become artifact notes, and the caption must attach to the "
        f"figure rather than becoming a THIRD, standalone artifact note -- "
        f"got {len(records)} records: {records!r}"
    )

    ids_seen = {r.get("artifact_id") for r in records}
    assert ids_seen == {table_artifact_id, figure_artifact_id}, (
        f"expected artifact_ids {{{table_artifact_id!r}, {figure_artifact_id!r}}} "
        f"(table + figure only), got {sorted(ids_seen)!r}. Full records: {records!r}"
    )

    table_record = next(r for r in records if r.get("artifact_id") == table_artifact_id)
    figure_record = next(r for r in records if r.get("artifact_id") == figure_artifact_id)

    # --- the figure's artifact note carries its caption text (attached,
    # not lost) --------------------------------------------------------
    assert _record_contains_text(figure_record, _ROUTING_CAPTION_BODY), (
        f"expected the figure's own artifact record to carry its caption's "
        f"text SOMEWHERE among its own string values (PRD/plan: 'the "
        f"caption attached, not lost'). Figure record: {figure_record!r}"
    )

    # --- the caption must not leak onto the UNRELATED table's record too
    # (it is adjacent to the figure only, in this fixture) ------------------
    assert not _record_contains_text(table_record, _ROUTING_CAPTION_BODY), (
        f"expected the caption's text to attach to the FIGURE only (it is "
        f"adjacent to the figure, not the table, in this fixture), but "
        f"found it on the table's own record too: {table_record!r}"
    )

    # --- no artifact note for the document_index or footnote blocks --------
    for record in records:
        assert not _record_contains_text(record, _ROUTING_TOC_BODY), (
            f"expected the document_index (TOC) block's own text to never "
            f"appear on any artifact record (it is apparatus, never "
            f"artifact-noted), but found it on: {record!r}"
        )
        assert not _record_contains_text(record, _ROUTING_FOOTNOTE_BODY), (
            f"expected the footnote (endnotes) block's own text to never "
            f"appear on any artifact record (it is apparatus, never "
            f"artifact-noted), but found it on: {record!r}"
        )

    # --- the caption is absent from data/chunks/<source_id>.jsonl
    # (established in slice 02, still true) ------------------------------
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(json.dumps(tree), encoding="utf-8")
    monkeypatch.setattr(chunk_module, "tree_path", lambda source_id: tree_file)
    monkeypatch.setattr(chunk_module, "load_persisted_tree", lambda path: tree)

    chunks_dir = tmp_path / "chunks"
    chunk_records = run_chunk_recursive(source_path, chunks_dir=chunks_dir)

    leaked_caption = [r for r in chunk_records if _ROUTING_CAPTION_BODY in r.get("text", "")]
    assert not leaked_caption, (
        f"expected the caption to remain absent from the emitted chunks "
        f"(slice 02's own invariant, still true): found it in {leaked_caption!r}"
    )


# ===========================================================================
# Regression test for issue #172 follow-up (PR #180 fix-lane): a fallback-
# path 'FigureCaption' block must attach to its preceding artifact.
# Rewritten for issue #429 (no LLM call, no client).
#
# Locked behavioral contract (DEC-1) -- do not edit once committed red.
# ===========================================================================

_ATTACH_FIGURE_BODY = (
    "Attach-regression figure sentinel: cross-section diagram of the "
    "eastern trench wall showing the three distinct stratigraphic layers."
)
_ATTACH_CAPTION_BODY = (
    "Attach-regression caption sentinel: cross-section diagram annotated "
    "with layer boundaries, drawn by the site surveyor after the final dig."
)


def _build_single_captioned_figure_tree(caption_label: str) -> dict:
    """A minimal tree: one section holding one picture immediately followed
    by one caption block carrying `caption_label` as its own `label` --
    isolates the attach/no-attach behavior for exactly that label spelling,
    independent of any TOC/footnote apparatus noise."""
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Findings",
                "label": "section_header",
                "children": [
                    {
                        "type": "artifact",
                        "order": "1.1",
                        "label": "picture",
                        "text": _ATTACH_FIGURE_BODY,
                    },
                    {
                        "type": "prose",
                        "order": "1.2",
                        "label": caption_label,
                        "text": _ATTACH_CAPTION_BODY,
                    },
                ],
            },
        ]
    }


def _run_single_captioned_figure_case(tmp_path, monkeypatch, caption_label: str):
    """Shared arrange+act for the attach-regression cases below: builds a
    single-picture-plus-caption tree with `caption_label`, runs
    `run_artifacts` against it via the monkeypatched-`extract` seam, and
    returns `(records, source_id)` for the caller's own label-specific
    assertions."""
    tree = _build_single_captioned_figure_tree(caption_label)
    monkeypatch.setattr(artifacts_module, "extract", lambda path: tree)

    source_path = tmp_path / f"attach_regression_source_{caption_label}.txt"
    source_path.write_text(
        f"issue #172 follow-up attach-regression source ({caption_label})",
        encoding="utf-8",
    )
    source_id = compute_source_id(source_path)

    records = artifacts_module.run_artifacts(source_path)
    return records, source_id


def test_fallback_figurecaption_label_attaches_to_preceding_figure(tmp_path, monkeypatch):
    """The FALLBACK-path spelling ('FigureCaption', raw Unstructured
    element.category) must attach to its preceding figure exactly like the
    docling lowercase 'caption' spelling does -- not become its own
    standalone artifact record."""
    records, source_id = _run_single_captioned_figure_case(tmp_path, monkeypatch, "FigureCaption")

    figure_artifact_id = f"{source_id}_art_1.1"

    assert len(records) == 1, (
        f"expected exactly ONE artifact record (the figure, with the "
        f"'FigureCaption' block's text attached) -- not a second, standalone "
        f"artifact record for the caption block itself -- got {len(records)} "
        f"records: {records!r}"
    )

    figure_record = records[0]
    assert figure_record.get("artifact_id") == figure_artifact_id, (
        f"expected the sole artifact record to be the figure "
        f"({figure_artifact_id!r}), got {figure_record.get('artifact_id')!r} "
        f"-- full record: {figure_record!r}"
    )

    assert _record_contains_text(figure_record, _ATTACH_CAPTION_BODY), (
        f"expected the figure's own artifact record to carry the "
        f"'FigureCaption' block's text SOMEWHERE among its own string "
        f"values (attached, not lost, not standalone) -- got: "
        f"{figure_record!r}"
    )


def test_docling_lowercase_caption_label_still_attaches_to_preceding_figure(tmp_path, monkeypatch):
    """Regression guard: the existing docling lowercase 'caption' spelling
    must keep attaching identically -- this sibling case must stay GREEN
    both before and after the fallback-label fix above, proving the fix
    cannot regress the primary path while it corrects the fallback one."""
    records, source_id = _run_single_captioned_figure_case(tmp_path, monkeypatch, "caption")

    figure_artifact_id = f"{source_id}_art_1.1"

    assert len(records) == 1, (
        f"expected exactly ONE artifact record (the figure, with the "
        f"lowercase 'caption' block's text attached), got {len(records)} "
        f"records: {records!r}"
    )

    figure_record = records[0]
    assert figure_record.get("artifact_id") == figure_artifact_id, (
        f"expected the sole artifact record to be the figure "
        f"({figure_artifact_id!r}), got {figure_record.get('artifact_id')!r} "
        f"-- full record: {figure_record!r}"
    )

    assert _record_contains_text(figure_record, _ATTACH_CAPTION_BODY), (
        f"expected the figure's own artifact record to carry the lowercase "
        f"'caption' block's text SOMEWHERE among its own string values, "
        f"got: {figure_record!r}"
    )
