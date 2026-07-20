"""Regression test for issue #272 (fix-lane behavioral bug).

The bug
-----------------------------------------------------------------------
`axial.xref` links ZERO chunk->artifact references corpus-wide.
`compose_xref_prompt` (src/axial/xref.py) presents the model with the
source's candidate artifacts as BARE opaque ids only:

    "\\n".join(f"- {artifact_id}" for artifact_id in artifact_ids)

e.g. "- src_art_85.8" -- never the artifact's own caption. The prompt asks
the model which artifacts a chunk "explicitly references (e.g. 'as Table 3
shows')", but a bare id like "src_art_85.8" carries no table/figure number a
prose sentence could ever match against. The model can't map a chunk's "see
Table 8.2" to the id whose CAPTION happens to read "Table 8.2 ...", so it
returns an empty `referenced_artifact_ids` for every chunk, and no pair is
ever emitted -- for any source, in production.

The fix this test locks (does not build)
-----------------------------------------------------------------------
Thread each artifact's caption into the prompt (e.g. "- {artifact_id}:
{caption}") so the list of known artifacts carries the very table/figure
number and wording a citing chunk uses. The existing id-filter
(`build_xref_pairs` against the real, known artifact-id set) is untouched:
a hallucinated/nonexistent id must still yield no pair.

Seam decision -- a caption-aware fake `LLMClient`, not the stub/env-var seam
-----------------------------------------------------------------------
tests/ingestion/test_xref.py's outer acceptance test already locks the
`AXIAL_STUB_XREF_TARGET` env-var seam, but that stub is deliberately
CONTENT-BLIND -- it references a fixed target id for every chunk regardless
of what the prompt says, by design (see that module's seam decision 2). That
seam is structurally incapable of proving THIS bug: it can't distinguish "the
model was shown the caption" from "the model wasn't", so it would stay green
before and after the fix and prove nothing about #272.

This test instead injects a caption-aware fake `LLMClient` straight into
`axial.xref.run_xref(client=...)`, exercising the REAL prompt-composition ->
client -> parse -> id-filter path end to end. The fake's xref-pass answer is
a pure, deterministic function of what actually landed in the prompt text it
was sent -- it returns the artifact_id only when BOTH of these substrings
are present in the prompt:
  - `_CAPTION_MARKER`, a phrase drawn from the artifact's own caption
    ("as a percentage of GNP") that appears NOWHERE in either chunk's own
    prose -- so its presence in the prompt is possible only via the
    known-artifacts block, and only once that block carries captions (the
    fix). Before the fix, this marker is never in the prompt, so the fake
    never returns the id -- reproducing #272's zero-links bug exactly, for
    the right reason.
  - `_CITATION_MARKER` ("outpacing growth"), present only in the CITING
    chunk's own text (and deliberately absent from the caption text itself,
    which already contains "Table 8.2" verbatim -- a marker built from that
    would trivially appear in every chunk's prompt once the caption is
    shared, proving nothing about per-chunk correlation) -- so even after
    the fix, the non-citing chunk (whose text lacks this marker) still gets
    no pair, exactly as a real per-chunk-relevance judgment would behave.
    This is what keeps the test from going green for the wrong reason once
    the caption block is shared across every chunk's prompt (as it always
    was, and still is): "GREEN" requires per-chunk
    correlation, not just caption-presence-somewhere-in-the-prompt.

A hallucinated-id fake (`_HallucinatingXrefClient`) pins the regression
control this fix must NOT touch: an artifact_id the model invents that is
absent from the source's real, known artifact set must still be filtered to
no pair, unconditionally -- this is `build_xref_pairs`'s own invariant
(PRD §8 P0-7), independent of the caption fix.

Fixture: a hand-built two-node tree (one section, one `table` artifact node
immediately followed by its `caption` block) -- mirrors
tests/ingestion/test_artifacts.py's own
`_build_single_captioned_figure_tree`/`_run_single_captioned_figure_case`
pattern (monkeypatching `axial.artifacts.extract`, issue #168's caption-
attachment machinery) so this test needs no docling run and no PDF fixture.
No real book text is used anywhere (DEC-23) -- every string here is
hand-authored for this test.

Chunk records are written directly to a private `chunks_dir` (bypassing
`axial.chunk.run_chunk_recursive` entirely -- xref only ever READS the
on-disk chunk artifact via `axial.chunk.read_chunks`, issue #154), so this
test controls the exact chunk text driving the caption-vs-no-caption
distinction without depending on any chunking behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

import axial.artifacts as artifacts_module
from axial.checkpoint import append_checkpoint_record
from axial.chunk import chunks_checkpoint_path
from axial.envelope import compute_source_id
from axial.llm import ARTIFACTS_PASS_NAME, XREF_PASS_NAME
from axial.schema import load_schema
from axial.xref import run_xref

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"

# The artifact's own caption -- deliberately NOT reproduced verbatim by
# either chunk's prose (mirrors a real table caption's register).
_CAPTION_TEXT = "Table 8.2 Military expenditure as a percentage of GNP, 1970-1990"

# A phrase drawn from the caption that appears in NEITHER chunk's own text.
# Its presence in the prompt sent to the model is possible ONLY through the
# known-artifacts block carrying the caption -- i.e. only once #272 is
# fixed.
_CAPTION_MARKER = "as a percentage of GNP"

# A phrase from the CITING chunk's own sentence, deliberately absent from
# the caption text itself (the caption already contains the literal digits
# "Table 8.2", so a marker built from THAT would trivially show up in every
# chunk's prompt once the caption is shared -- proving nothing about
# per-chunk correlation). This is the ONLY thing distinguishing the citing
# chunk's prompt from the non-citing chunk's prompt once the known-artifacts
# block (shared across every chunk) starts carrying the caption too.
_CITATION_MARKER = "outpacing growth"

_CITING_CHUNK_TEXT = (
    "As shown in Table 8.2, military expenditure rose steadily across the "
    "period under review, outpacing growth in most other categories of "
    "public spending."
)
_NONCITING_CHUNK_TEXT = (
    "This section instead reviews prior scholarship on state capacity and "
    "its relationship to bureaucratic reach in the postwar decades."
)


def _build_captioned_table_tree() -> dict:
    """One section holding one `table` artifact node immediately followed by
    its `caption` block -- mirrors tests/ingestion/test_artifacts.py's
    `_build_single_captioned_figure_tree` (issue #168 attach machinery),
    swapping the label to "table" (immaterial to attachment, which keys off
    the caption block's own label, not its preceding sibling's)."""
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
                        "label": "table",
                        "text": "<table data placeholder>",
                    },
                    {
                        "type": "prose",
                        "order": "1.2",
                        "label": "caption",
                        "text": _CAPTION_TEXT,
                    },
                ],
            },
        ]
    }


def _stub_artifact_payload() -> str:
    """A complete, schema-valid artifacts-pass response, built from the REAL
    loaded schema's own vocabulary at test time (mirrors
    tests/ingestion/test_artifacts.py's own `_stub_artifact_payload`) -- this
    test's target is xref's prompt, not artifact classification, so any
    in-schema role/field pair is fine."""
    schema = load_schema(DOMAIN_DIR)
    role = next(iter(schema.axes["artifact_role"].tag_ids))
    field_primary = next(iter(schema.axes["field"].tag_ids))
    return json.dumps({"artifact_role": role, "field": {"primary": field_primary, "secondary": []}})


class _CaptionAwareXrefClient:
    """Fake `LLMClient` answering both passes `run_xref` triggers internally.

    `pass_name == ARTIFACTS_PASS_NAME` (from `run_xref`'s own nested
    `run_artifacts` call): a fixed, schema-valid classification.

    `pass_name == XREF_PASS_NAME`: THIS is the seam the whole test hinges
    on. Returns the artifact_id only when the prompt it actually received
    contains BOTH `_CAPTION_MARKER` (proves the caption made it into the
    known-artifacts block -- the fix) AND `_CITATION_MARKER` (proves this
    particular chunk's own text is the one citing it). Every prompt sent for
    `pass_name == XREF_PASS_NAME` is recorded verbatim in `xref_prompts` so
    the test can inspect them directly if needed.
    """

    def __init__(self, artifact_payload: str, artifact_id: str) -> None:
        self._artifact_payload = artifact_payload
        self._artifact_id = artifact_id
        self.xref_prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        if pass_name == ARTIFACTS_PASS_NAME:
            return self._artifact_payload
        if pass_name == XREF_PASS_NAME:
            self.xref_prompts.append(prompt)
            if _CAPTION_MARKER in prompt and _CITATION_MARKER in prompt:
                return json.dumps({"referenced_artifact_ids": [self._artifact_id]})
            return json.dumps({"referenced_artifact_ids": []})
        raise AssertionError(f"unexpected pass_name {pass_name!r} sent to the fake client")


class _HallucinatingXrefClient:
    """Fake `LLMClient` that ALWAYS reports a nonexistent artifact_id from
    the xref pass, regardless of prompt content -- pins the regression
    control this fix must not touch: `build_xref_pairs`'s id-filter still
    drops a referenced id absent from the source's real artifact set
    (PRD §8 P0-7), independent of whether the prompt now carries captions."""

    def __init__(self, artifact_payload: str, hallucinated_id: str) -> None:
        self._artifact_payload = artifact_payload
        self._hallucinated_id = hallucinated_id

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        if pass_name == ARTIFACTS_PASS_NAME:
            return self._artifact_payload
        if pass_name == XREF_PASS_NAME:
            return json.dumps({"referenced_artifact_ids": [self._hallucinated_id]})
        raise AssertionError(f"unexpected pass_name {pass_name!r} sent to the fake client")


def _write_chunk_records(chunks_dir: Path, source_id: str, records: list[dict]) -> None:
    """Write `records` directly to `<chunks_dir>/<source_id>.jsonl`, the
    exact on-disk shape `axial.chunk.read_chunks` reads (issue #154) --
    bypasses `run_chunk_recursive` entirely since this test only needs
    control over chunk TEXT, not real chunking behavior."""
    path = chunks_checkpoint_path(source_id, chunks_dir)
    for record in records:
        append_checkpoint_record(path, record)


def test_chunk_citing_artifact_by_caption_gets_linked_to_it(tmp_path, monkeypatch):
    tree = _build_captioned_table_tree()
    monkeypatch.setattr(artifacts_module, "extract", lambda path: tree)

    source_path = tmp_path / "xref_caption_linking_source.txt"
    source_path.write_text("issue #272 xref artifact-caption linking test source", encoding="utf-8")
    source_id = compute_source_id(source_path)

    artifact_id = f"{source_id}_art_1.1"
    citing_chunk_id = f"{source_id}_chunk_citing"
    noncitng_chunk_id = f"{source_id}_chunk_noncitng"

    chunks_dir = tmp_path / "chunks"
    _write_chunk_records(
        chunks_dir,
        source_id,
        [
            {"chunk_id": noncitng_chunk_id, "section": "Findings", "text": _NONCITING_CHUNK_TEXT},
            {"chunk_id": citing_chunk_id, "section": "Findings", "text": _CITING_CHUNK_TEXT},
        ],
    )

    # --- Given: a chunk that cites an artifact by its caption ("Table 8.2")
    # and a real artifact whose caption reads "Table 8.2 ..." ---
    payload = _stub_artifact_payload()
    caption_client = _CaptionAwareXrefClient(payload, artifact_id)

    pairs = run_xref(
        source_path,
        client=caption_client,
        domain_dir=DOMAIN_DIR,
        chunks_dir=chunks_dir,
    )

    # Sanity: the fake actually saw one xref-pass prompt per chunk, and the
    # fake's decision genuinely depends on prompt content (proves this isn't
    # a tautological double -- see module docstring).
    assert len(caption_client.xref_prompts) == 2, (
        f"expected exactly one xref-pass prompt per chunk (2 chunks), got "
        f"{len(caption_client.xref_prompts)}: {caption_client.xref_prompts!r}"
    )

    # --- Then: the CITING chunk is linked to the artifact its prose names
    # by caption -- this is #272's whole point, and fails red today because
    # `compose_xref_prompt` never puts `_CAPTION_MARKER` (any part of the
    # artifact's caption) into the prompt at all. ---
    assert {"chunk_id": citing_chunk_id, "artifact_id": artifact_id} in pairs, (
        f"expected the chunk citing the artifact by its caption "
        f"('Table 8.2') to be linked to it ({artifact_id!r}) -- got pairs "
        f"{pairs!r}. This is issue #272: compose_xref_prompt shows the "
        f"model bare artifact ids only, never the caption text a citing "
        f"chunk's prose actually names, so the model can never make this "
        f"match and the pass links nothing, ever."
    )

    # --- And: the chunk that cites nothing still produces no pair, even
    # once the shared known-artifacts block carries the caption (this is
    # the regression control that must survive the fix: linking is still
    # per-chunk, not "every chunk gets every artifact once captions are
    # visible somewhere in the prompt"). ---
    noncitng_pairs = [pair for pair in pairs if pair.get("chunk_id") == noncitng_chunk_id]
    assert noncitng_pairs == [], (
        f"expected the non-citing chunk to produce NO pair (it references "
        f"no artifact), got {noncitng_pairs!r} -- full pairs: {pairs!r}"
    )

    # --- And: a referenced artifact_id absent from the source's real
    # artifacts (a hallucinated id) still produces no pair -- untouched by
    # this fix (PRD §8 P0-7's dangling-link filter, `build_xref_pairs`). ---
    hallucinated_id = f"{source_id}_art_999"
    hallucinating_client = _HallucinatingXrefClient(payload, hallucinated_id)

    dangling_pairs = run_xref(
        source_path,
        client=hallucinating_client,
        domain_dir=DOMAIN_DIR,
        chunks_dir=chunks_dir,
    )
    assert dangling_pairs == [], (
        f"expected NO pair when the model reports an artifact_id absent "
        f"from the source's real artifacts ({hallucinated_id!r} vs the "
        f"only real id {artifact_id!r}) -- the id-filter invariant must "
        f"hold regardless of the caption fix, got {dangling_pairs!r}"
    )
