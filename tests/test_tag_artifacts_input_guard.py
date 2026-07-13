"""Outer acceptance test for issue #132 (shared non-prose input guard,
lifted into the tag and artifacts passes).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a per-chunk record fed to the tag pass, and a per-node artifact record
      fed to the artifacts pass, one of which (in each pass's own input
      stream) is oversized / OCR-garbled non-prose -- the same shape as the
      real tilly index chunk that motivated issue #111's xref guard
      (> 30,000 chars, or > 40% non-alpha)
When  `axial.tag.run_tag` / `axial.artifacts.run_artifacts` process that
      stream
Then  each pass COMPLETES without raising (no stall, no exception)
And   the offending chunk/artifact is skipped BEFORE any LLM call is made
      for it -- zero prompts ever carry its text, and it produces zero
      tagged/classified records
And   the skip is logged to stderr, naming the skipped chunk/artifact's own
      identity and a reason
And   every OTHER (normal) chunk/artifact on either side of the offending
      one is still processed as usual -- proving the guard skips only the
      offending item, never the whole pass

See GitHub issue #132: only `axial.xref.run_xref` (issue #111) and
`axial.chunk.run_chunk` (issue #118) currently guard their per-item loop
against oversized/garbled non-prose before making an LLM call
(`axial.xref._non_prose_skip_reason`, `_XREF_MAX_CHUNK_CHARS = 30000`,
`_XREF_MAX_NON_ALPHA_RATIO = 0.4`, xref.py ~54-55/165-177/328-335, mirrored
verbatim into chunk.py by #118). `axial.tag.run_tag`'s per-chunk loop
(tag.py ~1083) and `axial.artifacts.run_artifacts`'s per-node loop
(artifacts.py ~477, `complete_json` ~497) have NO such guard today, and both
run BEFORE xref in the pipeline (tag -> artifacts -> xref), so xref's own
guard never protects them: an oversized/garbled chunk or artifact reaching
either pass today is sent straight to the LLM. The fix (built by the
implementer, not this test) lifts the guard + thresholds into one neutral,
shared module and applies the identical deterministic skip-and-log guard --
no LLM call, no checkpoint churn -- at the top of both passes' per-item
loops, mirroring xref's own precedent.

As of this commit neither pass has any such guard, so this test is expected
to fail red for exactly that reason: the oversized chunk/artifact currently
DOES get an LLM call, currently DOES produce a tagged/classified record, and
nothing is logged to stderr about skipping it. It must not fail on an import
error, a fixture-arrangement error, or a call-signature mismatch -- only on
the guard-behavior assertions below.

Seam decision 1 -- bypassing chunk.py/docling entirely via monkeypatched
`axial.tag.run_chunk` / `axial.artifacts.extract`, calling `run_tag` /
`run_artifacts` directly
-----------------------------------------------------------------------
Mirrors tests/test_xref_input_guard.py's seam decision (which monkeypatches
`axial.xref.run_chunk`/`run_artifacts` to supply synthetic records with no
docling/network) and tests/test_chunk_input_guard.py's seam decision 1
(which monkeypatches `axial.chunk.extract` to supply a synthetic extraction
tree). `axial.tag.run_tag` imports `run_chunk` directly into its own module
namespace, so monkeypatching the module attribute `axial.tag.run_chunk`
redirects every call to a fake returning hand-built, synthetic chunk
records -- deliberately bypassing chunk.py's OWN guard (#118) entirely, so
this test isolates the TAG pass's own guard, never chunk.py's (already
locked green). Likewise `axial.artifacts.run_artifacts` imports `extract`
directly, so monkeypatching `axial.artifacts.extract` supplies a synthetic
extraction tree with no docling/network, isolating the ARTIFACTS pass's own
guard.

Seam decision 2 -- the artifacts pass's guarded input is the artifact
node's own `text` field
-----------------------------------------------------------------------
The tag pass's per-item text is unambiguous: `chunk_record["text"]`,
identical to xref's and chunk's own guarded input. The artifacts pass has
no analogous "chunk_record" -- it walks `(node, section)` pairs directly
from the extraction tree (`axial.artifacts._artifact_nodes_with_section`).
`axial.extract._leaf_node` already populates a `text` field on ANY node
(prose or artifact) whenever the underlying docling item exposes one
(`text = getattr(item, "text", None); if text: node["text"] = text`) -- for
a table/figure, this is the artifact's own OCR/extracted text content, the
same species of OCR-garbled material #111 guards against for prose back-
matter. `node["text"]` is therefore the one per-iteration textual payload
genuinely available to the artifacts loop, and is this test's guarded
input for that pass -- constructed directly on synthetic artifact nodes
here (via the monkeypatched `extract`), with no real docling/table-OCR
involved.

Seam decision 3 -- real domain (`config/domains/syria`) schema/codebook,
loaded at test time, never hardcoded
-----------------------------------------------------------------------
Unlike xref (schema-free) and chunk (schema-free), both the tag and
artifacts passes require a loaded domain schema/codebook to run at all
(`load_schema`/`load_codebook`, called unconditionally near the top of
`run_tag`/`run_artifacts`, before either per-item loop). This test uses the
real, git-tracked `config/domains/syria` domain -- the same default every
other in-process `run_tag`/`run_artifacts` acceptance test already relies on
(e.g. tests/test_tag_domain_dir_config.py's `run_tag`-driven arms) -- rather
than inventing a fixture domain, since this issue is about the guard, not
about domain-directory resolution. Every LLM-response literal this test
constructs is either `StubLLMClient._CANNED_TAG_RESPONSE` (the tag pass's
own existing canned response, already a real member of every Syria axis --
see `src/axial/llm.py`'s own comment on it) or built from `load_schema`'s
OWN loaded axis vocabulary at test time (`next(iter(schema.axes[...]
.tag_ids))`, mirroring tests/test_tag_vocab_reask.py's
`_baseline_tag_payload` seam decision 2), never a hardcoded tag id assumed
correct.

Seam decision 4 -- counting LLM clients that always answer validly, so the
ONLY variable under test is whether the guard fires
-----------------------------------------------------------------------
Mirrors tests/test_xref_input_guard.py's `_CountingClient` exactly: a fake
client that counts every call made and asserts the pass name on each one,
returning a WELL-FORMED, schema-valid response every time. Since the
canned response is always valid, `apply_correction_reask`'s bounded
correction path (issue #102) never fires for either pass, so a clean call
count of "one call per NON-guarded item" is a direct, implementation-
agnostic proof that the guarded item's own turn never reached the LLM at
all -- the same "skip before the call" proof xref's and chunk's own guard
tests already use.

Test hygiene: every path this test touches (the synthetic source files)
lives under pytest's own tmp_path, outside this repo entirely -- nothing
here reads or writes any real data/ directory (both `run_chunk` and
`extract` are monkeypatched out entirely), and no real LLM/network/docling
call is ever made. The autouse `tests/conftest.py` tree/envelope isolation
fixture is therefore inert for this test (never triggered), consistent with
tests/test_xref_input_guard.py's and tests/test_chunk_input_guard.py's own
hygiene notes.
"""

from __future__ import annotations

import json

import axial.artifacts as artifacts_module
import axial.tag as tag_module
from axial.envelope import compute_source_id
from axial.llm import ARTIFACTS_PASS_NAME, TAG_PASS_NAME, StubLLMClient
from axial.schema import Schema, load_schema

DOMAIN_DIR = "config/domains/syria"

# A prose-shaped chunk/artifact text, deliberately well under both
# thresholds -- the "normal" item on either side of the guarded one.
PROSE_TEXT_A = "As shown above, the prose here discusses the argument in detail."
PROSE_TEXT_B = "A second passage of ordinary prose, again citing the same figure."
NORMAL_ARTIFACT_TEXT_A = "Table 1: summary statistics for the primary sample."
NORMAL_ARTIFACT_TEXT_B = "Figure 2: a simple bar chart of the reported outcomes."

# An OCR'd index/table-dump: > 30,000 chars, dominated by "term, page, page"
# soup (mostly digits, commas, spaces -> well over the non-alpha threshold
# too) -- the identical fixture literal tests/test_xref_input_guard.py and
# tests/test_chunk_input_guard.py already use for the equivalent guard in
# their own passes.
GUARDED_TEXT = "Abbasid, 12, 45, 78; Cairo, 3, 9, 210; " * 900
assert len(GUARDED_TEXT) > 30000
assert (sum(1 for c in GUARDED_TEXT if not c.isalpha()) / len(GUARDED_TEXT)) > 0.4


# --- tag pass -----------------------------------------------------------


def _fake_run_chunk(chunk_records):
    def fake(path, **kwargs):
        return chunk_records

    return fake


class _TagCountingClient:
    """Fake LLMClient: counts every tag-pass call made, always answering
    with the well-formed, schema-valid canned tag response (issue #132
    module docstring, seam decision 4). Must NEVER be called for a guarded
    (skipped) chunk."""

    def __init__(self):
        self.prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        assert pass_name == TAG_PASS_NAME, (
            f"expected pass_name={TAG_PASS_NAME!r}, got {pass_name!r}"
        )
        self.prompts.append(prompt)
        return StubLLMClient._CANNED_TAG_RESPONSE

    @property
    def call_count(self) -> int:
        return len(self.prompts)


def test_tag_pass_skips_oversized_non_prose_chunk_never_sent_to_llm(tmp_path, monkeypatch, capsys):
    chunk_records = [
        {"chunk_id": "prose-a", "section": "Introduction", "text": PROSE_TEXT_A},
        {"chunk_id": "index-822", "section": "Back Matter", "text": GUARDED_TEXT},
        {"chunk_id": "prose-b", "section": "Conclusion", "text": PROSE_TEXT_B},
    ]
    monkeypatch.setattr(tag_module, "run_chunk", _fake_run_chunk(chunk_records))

    source_path = tmp_path / "tag_guard_source.txt"
    source_path.write_text("tag guard test source", encoding="utf-8")

    client = _TagCountingClient()
    records = tag_module.run_tag(source_path, client=client, domain_dir=DOMAIN_DIR)

    assert isinstance(records, list), (
        f"expected run_tag to return a list, got {type(records).__name__}: {records!r}"
    )

    guarded_records = [r for r in records if r.get("chunk_id") == "index-822"]
    assert not guarded_records, (
        f"expected ZERO tagged records for the oversized/garbled chunk "
        f"'index-822' (issue #132, mirroring #111's xref guard), but found: "
        f"{guarded_records!r}"
    )

    assert client.call_count == 2, (
        f"expected exactly 2 LLM calls (the two normal prose chunks only); "
        f"the 40KB index chunk must be skipped before any LLM call is made "
        f"for its own turn, got {client.call_count}"
    )
    assert GUARDED_TEXT not in "".join(client.prompts), (
        "the oversized index chunk's text must never reach a tag-pass LLM prompt"
    )

    kept_chunk_ids = {r.get("chunk_id") for r in records}
    assert kept_chunk_ids == {"prose-a", "prose-b"}, (
        f"expected both normal prose chunks to still produce a tagged "
        f"record, got chunk_ids present: {sorted(kept_chunk_ids)!r}. Full "
        f"records: {records!r}"
    )

    err = capsys.readouterr().err
    assert "skip" in err.lower() and "index-822" in err, (
        f"expected the skipped chunk to be logged to stderr naming it and a "
        f"reason (mirroring xref's 'xref: skipping chunk ...: <reason>' "
        f"shape), got: {err!r}"
    )


def test_tag_pass_source_of_only_guarded_chunk_completes_with_zero_records(
    tmp_path, monkeypatch, capsys
):
    """Pathological edge: a source whose only chunk is non-prose back-matter
    skips everything and returns zero tagged records without stalling or
    raising -- mirrors tests/test_xref_input_guard.py's equivalent edge
    case."""
    chunk_records = [{"chunk_id": "index-only", "section": "Back Matter", "text": GUARDED_TEXT}]
    monkeypatch.setattr(tag_module, "run_chunk", _fake_run_chunk(chunk_records))

    source_path = tmp_path / "tag_guard_only_source.txt"
    source_path.write_text("only back-matter", encoding="utf-8")

    client = _TagCountingClient()
    records = tag_module.run_tag(source_path, client=client, domain_dir=DOMAIN_DIR)

    assert client.call_count == 0, "no prose chunk -> no tag-pass LLM call at all"
    assert records == [], "no prose chunk -> no tagged records"


# --- artifacts pass -------------------------------------------------------


def _valid_artifact_payload(schema: Schema) -> str:
    """A complete, schema-valid artifacts-pass response, built from the
    REAL loaded schema's own vocabulary at test time (module docstring,
    seam decision 3) -- never a hardcoded tag id."""
    role = next(iter(schema.axes["artifact_role"].tag_ids))
    field_primary = next(iter(schema.axes["field"].tag_ids))
    return json.dumps({"artifact_role": role, "field": {"primary": field_primary, "secondary": []}})


class _ArtifactsCountingClient:
    """Fake LLMClient: counts every artifacts-pass call made, always
    answering with a well-formed, schema-valid classification (module
    docstring, seam decision 4). Must NEVER be called for a guarded
    (skipped) artifact."""

    def __init__(self, payload: str):
        self.prompts: list[str] = []
        self._payload = payload

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        assert pass_name == ARTIFACTS_PASS_NAME, (
            f"expected pass_name={ARTIFACTS_PASS_NAME!r}, got {pass_name!r}"
        )
        self.prompts.append(prompt)
        return self._payload

    @property
    def call_count(self) -> int:
        return len(self.prompts)


def _build_synthetic_artifact_tree():
    """Three artifact nodes under one top-level section: two normal-sized
    ones flanking a MIDDLE oversized/garbled one -- mirroring
    tests/test_chunk_input_guard.py's own "guarded item sandwiched between
    two normal ones" fixture shape."""
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Findings",
                "children": [
                    {
                        "type": "artifact",
                        "order": "1.1",
                        "label": "table",
                        "text": NORMAL_ARTIFACT_TEXT_A,
                    },
                    {"type": "artifact", "order": "1.2", "label": "table", "text": GUARDED_TEXT},
                    {
                        "type": "artifact",
                        "order": "1.3",
                        "label": "figure",
                        "text": NORMAL_ARTIFACT_TEXT_B,
                    },
                ],
            }
        ]
    }


def test_artifacts_pass_skips_oversized_non_prose_artifact_never_sent_to_llm(
    tmp_path, monkeypatch, capsys
):
    schema = load_schema(DOMAIN_DIR)
    payload = _valid_artifact_payload(schema)

    monkeypatch.setattr(artifacts_module, "extract", lambda path: _build_synthetic_artifact_tree())

    source_path = tmp_path / "artifacts_guard_source.txt"
    source_path.write_text("artifacts guard test source", encoding="utf-8")
    source_id = compute_source_id(source_path)

    guarded_artifact_id = f"{source_id}_art_1.2"
    kept_artifact_ids = {f"{source_id}_art_1.1", f"{source_id}_art_1.3"}

    client = _ArtifactsCountingClient(payload)
    records = artifacts_module.run_artifacts(source_path, client=client, domain_dir=DOMAIN_DIR)

    assert isinstance(records, list), (
        f"expected run_artifacts to return a list, got {type(records).__name__}: {records!r}"
    )

    guarded_records = [r for r in records if r.get("artifact_id") == guarded_artifact_id]
    assert not guarded_records, (
        f"expected ZERO classified records for the oversized/garbled "
        f"artifact {guarded_artifact_id!r} (issue #132, mirroring #111's "
        f"xref guard), but found: {guarded_records!r}"
    )

    assert client.call_count == 2, (
        f"expected exactly 2 LLM calls (the two normal artifacts only); the "
        f"oversized/garbled artifact must be skipped before any LLM call is "
        f"made for its own turn, got {client.call_count}"
    )
    assert GUARDED_TEXT not in "".join(client.prompts), (
        "the oversized/garbled artifact's text must never reach an artifacts-pass LLM prompt"
    )

    kept_ids_seen = {r.get("artifact_id") for r in records}
    assert kept_ids_seen == kept_artifact_ids, (
        f"expected both normal artifacts to still produce a classified "
        f"record, got artifact_ids present: {sorted(kept_ids_seen)!r}. Full "
        f"records: {records!r}"
    )

    err = capsys.readouterr().err
    assert "skip" in err.lower() and guarded_artifact_id in err, (
        f"expected the skipped artifact to be logged to stderr naming its "
        f"own identity and a reason (mirroring xref's 'xref: skipping chunk "
        f"...: <reason>' shape), got: {err!r}"
    )


def test_artifacts_pass_source_of_only_guarded_artifact_completes_with_zero_records(
    tmp_path, monkeypatch, capsys
):
    """Pathological edge: a source whose only artifact is oversized/garbled
    skips everything and returns zero classified records without stalling
    or raising -- mirrors tests/test_xref_input_guard.py's and
    tests/test_chunk_input_guard.py's equivalent edge case."""
    schema = load_schema(DOMAIN_DIR)
    payload = _valid_artifact_payload(schema)

    tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Back Matter",
                "children": [
                    {"type": "artifact", "order": "1.1", "label": "table", "text": GUARDED_TEXT},
                ],
            }
        ]
    }
    monkeypatch.setattr(artifacts_module, "extract", lambda path: tree)

    source_path = tmp_path / "artifacts_guard_only_source.txt"
    source_path.write_text("only a garbled artifact", encoding="utf-8")

    client = _ArtifactsCountingClient(payload)
    records = artifacts_module.run_artifacts(source_path, client=client, domain_dir=DOMAIN_DIR)

    assert client.call_count == 0, "no normal artifact -> no artifacts-pass LLM call at all"
    assert records == [], "no normal artifact -> no classified records"
