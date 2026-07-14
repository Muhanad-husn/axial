"""Outer acceptance test for issue #165, slice 06 of the chunk-redesign
subproject (charter #148): a second, operator-selectable chunk mechanism --
deterministic recursive/structural splitting on a separator hierarchy
(paragraph `\n\n` -> line `\n` -> sentence -> char) -- living behind the
existing `_chunk_section_text` seam and chosen by a new env-var selector that
mirrors `axial.chunk`'s own `AXIAL_EMBEDDER` / `get_embedder` seam.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source with a known paragraph structure -- some sections with clear
      `\n\n` breaks, and one section that is a single wall of text with no
      `\n\n`
When  the operator selects the recursive mechanism and runs `axial chunk`
Then  it writes data/chunks/<source_id>.jsonl with the §7.7 fields and stable
      chunk_ids, every chunk <= max and (modulo the section-tail exception)
      >= min, splitting the wall-of-text section by falling through
      `\n\n` -> `\n` -> sentence -> char
And   it makes zero LLM calls and zero embedding-model calls
And   with the mechanism unset, `axial chunk` still runs the embedding-based
      default
And   `axial chunk examine` reports on the recursive artifact through the
      same stats surface

See specs/PRODUCT.md §5 stage 4 / §7.7 / §8 P0-4 for the source of truth on
the shared chunk artifact and band guard, and
plans/chunk-redesign/06-recursive-mechanism.md (this slice's own plan) for
the recursive-mechanism contract this test encodes.

Seam decision 1 -- the selector: `AXIAL_CHUNK_MECHANISM=recursive`
-----------------------------------------------------------------------
Per the slice plan's own "Decisions to make in this slice" section, this is
an env var mirroring `axial.chunk.EMBEDDER_ENV_VAR` (`AXIAL_EMBEDDER`)
exactly: `AXIAL_CHUNK_MECHANISM=recursive` selects the recursive mechanism;
unset, empty, or any other value falls back to today's embedding-based
default (byte-identical -- the plan is explicit the default must not change).
This test locks the exact env-var NAME and the exact selecting VALUE as the
contract -- neither is left to the implementer's discretion, since without a
fixed name/value there is no way for an operator (or this test) to ever
select the mechanism at all.

Seam decision 2 -- zero-embedding/zero-LLM proof: poison the construction
seams directly, in-process
-----------------------------------------------------------------------
No poison ("explode"-style) embedder seam like `axial.llm`'s
`AXIAL_LLM_PROVIDER=explode` exists for embedders. Mirroring
tests/test_chunk_examine.py's `test_chunk_examine_constructs_no_embedder_or_
llm_client` (the same proof already used to lock "examine costs nothing"),
this test invokes `axial.cli.main(["chunk", ...])` IN-PROCESS (not a
subprocess -- a subprocess couldn't observe a monkeypatch) with
`axial.chunk.get_embedder`, `axial.chunk.HashingEmbedder.encode`, and
`axial.chunk.get_client` (defensively, `raising=False`, in case a future
refactor imports it there) all monkeypatched to raise `AssertionError` the
instant any is called. This is belt-and-braced with the SAME poison-provider
trick tests/test_chunk.py's slice-01 outer test already locked
(`AXIAL_LLM_PROVIDER=explode`, `axial.llm.ExplodingLLMClient`, which raises
only when `.complete()` is actually invoked): if the recursive path ever
constructs/uses an embedder, or ever reaches a text-generating LLM call for
any reason, the run raises/crashes and this test's exit-code-0 assertion
fails. Today (before this slice exists), `AXIAL_CHUNK_MECHANISM` is not
recognized by the module at all, so `axial chunk` silently falls back to the
embedding-based default -- which DOES call `HashingEmbedder.encode` -- so
this test is expected to fail LOUDLY via the poisoned `encode`/`get_embedder`
seam (an `AssertionError` propagating out of `axial.cli.main`, since it is
not a `ChunkError` the CLI handler catches), not via a fixture/import error.
That is the correct-reason red this slice must turn green.

Seam decision 3 -- the fixture tree, and why the wall-of-text section is
built from a SINGLE leaf child
-----------------------------------------------------------------------
The recursive stage reads a persisted structural tree only (mirroring
tests/test_chunk.py's own seam decision 4): this test fabricates one by hand
and pre-places it at `data/trees/<source_id>.json` for the same committed
fixture PDF `tests/fixtures/envelope/thesis_paper.pdf` already reused as a
byte source elsewhere in this suite (never for its own tree shape).

The plan's own pre-flight decision notes that exactly how a section's body
gets a literal `\n\n` to split on depends on which join the implementer picks
for the recursive path (today's embedding path joins body lines with a
single `\n`; the plan's likely choice is `\n\n` per docling block). This test
does not lock that join choice. Instead, the "wall of text" section is built
from EXACTLY ONE leaf child carrying one continuous string with NO `\n`
characters anywhere inside it (not even a single line break) -- so no matter
what separator the implementer's join uses to combine multiple blocks, this
section is not multiple blocks, and no separator is ever inserted into it.
This guarantees the section's assembled body text truly contains no `\n\n`
(and no `\n` at all) regardless of the join decision, so a paragraph-level
(or even line-level) split cannot fire on it by construction -- the ONLY way
this section can still yield multiple in-band chunks is if the recursive
splitter actually fell through to the sentence or char level, which is
exactly what this test's Gherkin requires it to prove. The section is sized
to `CHUNK_MAX * 4` characters of ordinary, real-sentence prose (periods
present, so a sentence-level fallback can succeed without needing to fall
all the way to a raw char split) -- comfortably forcing at least one MAX-side
split regardless of the implementer's exact `CHUNK_MAX` value.

The "Overview" section, by contrast, is built from several SEPARATE leaf
children (distinct paragraphs) -- giving the tree a section with genuine
inter-block structure for the join step to insert its own separator between,
satisfying the Gherkin's "some sections with clear `\n\n` breaks" clause,
without this test dictating the exact separator character used.

Seam decision 4 -- isolation via an isolated tmp cwd, not the real repo root
-----------------------------------------------------------------------
Because this test poisons module-level attributes (`axial.chunk.get_embedder`
etc.) via `monkeypatch`, it must run in-process, so (mirroring
tests/test_chunk_cache.py's identical reasoning) it runs from a freshly
created, empty `tmp_path` cwd instead of shelling out to the CLI against the
real repo root: `axial.extract.TREES_DIR` / `axial.chunk.CHUNKS_DIR` both
resolve as plain, cwd-relative paths, so `monkeypatch.chdir(tmp_path)` makes
`data/trees/` and `data/chunks/` resolve under the isolated tmp root, never
touching the real repo's `data/` tree at all (no reliance on
tests/conftest.py's autouse snapshot/restore fixture is needed here).

Seam decision 5 -- band constants and chunk_id shape imported, not hardcoded
-----------------------------------------------------------------------
Mirroring tests/test_chunk.py's seam decision 3, this test imports
`CHUNK_MIN`/`CHUNK_MAX` from `axial.chunk` rather than hardcoding the band,
and asserts the chunk_id *shape* (`<source_id>_<section order>_<slug>_<NNN>`)
via the same permissive tail regex tests/test_chunk.py already locked, not an
exact slugify algorithm.

Out of scope for this file (left to inner unit tests per the slice plan)
-----------------------------------------------------------------------
This test does not assert exactly which hierarchy level (paragraph vs. line
vs. sentence vs. char) fired for any given fixture section -- only that the
wall-of-text section (which by construction cannot split at the paragraph or
line level) still yields multiple in-band chunks, proving SOME fall-through
occurred. It also does not assert byte-identity of the default (unset
selector) embedding path's output against a pre-slice baseline (an inner-test
concern per the plan) -- only that the default path still runs at all,
producing the artifact, when the selector is unset.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from axial.chunk import CHUNK_MAX, CHUNK_MIN
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_PDF = REPO_ROOT / "tests" / "fixtures" / "envelope" / "thesis_paper.pdf"

# The exact selector contract this slice must implement (seam decision 1).
MECHANISM_ENV_VAR = "AXIAL_CHUNK_MECHANISM"
MECHANISM_RECURSIVE_VALUE = "recursive"

LLM_PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

NORMAL_SECTION_HEADING = "Overview"
WALL_OF_TEXT_HEADING = "Continuous Field Notes"

KNOWN_SECTION_ORDERS = {
    NORMAL_SECTION_HEADING: "1",
    WALL_OF_TEXT_HEADING: "2",
}

# Matches only the "<slug>_<NNN>" tail of a chunk_id, mirroring
# tests/test_chunk.py's own regex exactly (see that file's comment for why a
# single regex over the WHOLE chunk_id would be ambiguous).
_SLUG_NNN_RE = re.compile(r"^(?P<slug>[a-z0-9-]+)_(?P<nnn>\d{3})$")

# Several DISTINCT paragraphs (no internal newlines each) giving the
# "Overview" section genuine inter-block structure (seam decision 3).
_OVERVIEW_PARAGRAPHS = [
    "Field teams conducted a short survey of provincial administration "
    "following the ceasefire, focused on service delivery and local "
    "governance capacity.",
    "This section summarizes the survey's scope and method before the "
    "detailed findings that follow.",
    "Respondents were drawn from municipal offices across three "
    "neighboring districts.",
]

# Ordinary, real-sentence filler prose (periods present) with NO newlines
# anywhere, cycled to build the "wall of text" section up to CHUNK_MAX * 4
# characters (seam decision 3) as one single continuous string.
_WALL_OF_TEXT_SENTENCES = [
    "The regional administration reorganized its provincial offices after the ceasefire.",
    "Local councils began coordinating water distribution across contested districts.",
    "Field teams recorded shifting patterns of return migration along the northern corridor.",
    "Provincial budgets for reconstruction were revised twice during the survey period.",
    "Interviews with municipal officials described uneven access to basic services.",
    "Displacement figures varied considerably between the eastern and western sub-districts.",
    "Local markets reopened gradually as security conditions improved through the spring.",
    "Aid coordination meetings shifted from the capital to regional hubs over time.",
    "Survey respondents cited road access as the most persistent obstacle to recovery.",
    "Cross-border trade resumed unevenly, concentrated around a small number of crossings.",
]


def _build_wall_of_text(min_chars: int) -> str:
    """A single continuous string, at least `min_chars` characters, with NO
    newline of any kind inside it -- see seam decision 3 for why this is
    what makes the fall-through proof join-choice-agnostic."""
    sentences: list[str] = []
    total = 0
    index = 0
    while total < min_chars:
        sentence = _WALL_OF_TEXT_SENTENCES[index % len(_WALL_OF_TEXT_SENTENCES)]
        sentences.append(sentence)
        total += len(sentence) + 1
        index += 1
    text = " ".join(sentences)
    assert "\n" not in text, "internal fixture bug: wall-of-text must contain no newlines"
    return text


def _leaf(order: str, text: str) -> dict:
    return {"type": "prose", "order": order, "text": text}


def _section(order: str, heading: str, body_texts: list[str]) -> dict:
    return {
        "type": "prose",
        "order": order,
        "text": heading,
        "label": "section_header",
        "children": [_leaf(f"{order}.{i + 1}", body) for i, body in enumerate(body_texts)],
    }


def _build_fixture_tree() -> dict:
    """The fabricated persisted-tree fixture: one section with genuine
    multi-paragraph structure, and one "wall of text" section built from a
    SINGLE leaf child with no internal newlines (seam decision 3)."""
    wall_of_text = _build_wall_of_text(CHUNK_MAX * 4)
    return {
        "children": [
            _section("1", NORMAL_SECTION_HEADING, _OVERVIEW_PARAGRAPHS),
            _section("2", WALL_OF_TEXT_HEADING, [wall_of_text]),
        ]
    }


def _place_fixture_tree(root: Path, source_id: str) -> Path:
    """Write the fabricated tree fixture to <root>/data/trees/<source_id>.json
    (axial.extract.TREES_DIR's own cwd-relative default), so `axial chunk`
    (via its persisted-tree cache) reads it verbatim instead of running
    docling."""
    tree = _build_fixture_tree()
    tree_path = root / "data" / "trees" / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(json.dumps(tree), encoding="utf-8")
    return tree_path


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"expected {path} to be one JSON object per line (PRD §7.7), "
                f"but line {line_no} failed to parse ({exc}): {line!r}"
            ) from None
    return records


def _poison_embedding_and_llm_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    """Poison every construction/use seam an embedder or LLM client could be
    reached through (seam decision 2): the FIRST one reached raises
    `AssertionError` naming this slice's own zero-cost contract."""

    def _poison(*_args, **_kwargs):
        raise AssertionError(
            "the recursive chunk mechanism must construct NO embedder and "
            "make NO embedding-model `encode` calls, and NO text-generating "
            "LLM call (plan 06: 'Zero LLM and zero embedding-model calls on "
            "the recursive path -- the embedder and its cache are never "
            "constructed when this mechanism is selected') -- this seam was "
            "reached during a recursive-mechanism `axial chunk` run"
        )

    monkeypatch.setattr("axial.chunk.get_embedder", _poison, raising=False)
    monkeypatch.setattr("axial.chunk.HashingEmbedder.encode", _poison, raising=False)
    monkeypatch.setattr("axial.chunk.get_client", _poison, raising=False)


def test_recursive_mechanism_writes_bounded_artifact_with_zero_model_calls_and_examine_parity(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)

    source_id = compute_source_id(FIXTURE_PDF)
    _place_fixture_tree(tmp_path, source_id)

    monkeypatch.setenv(MECHANISM_ENV_VAR, MECHANISM_RECURSIVE_VALUE)
    monkeypatch.setenv(LLM_PROVIDER_ENV_VAR, "explode")  # poison: any text-gen LLM call crashes
    _poison_embedding_and_llm_seams(monkeypatch)

    from axial.cli import main

    exit_code = main(["chunk", str(FIXTURE_PDF)])
    captured = capsys.readouterr()

    assert exit_code == 0, (
        f"expected exit code 0 for `axial chunk` with "
        f"{MECHANISM_ENV_VAR}={MECHANISM_RECURSIVE_VALUE!r} against a fixture "
        f"tree, with AXIAL_LLM_PROVIDER=explode and the embedder/LLM-client "
        f"construction seams poisoned to raise if ever called -- a nonzero "
        f"exit (or an uncaught exception) here most likely means the "
        f"recursive mechanism does not exist yet, so the run fell back to "
        f"the embedding-based default and called the poisoned embedder, or "
        f"made a real LLM call (plan 06's whole point: the recursive path "
        f"must never construct an embedder or call an LLM at all).\n"
        f"stdout: {captured.out!r}\nstderr: {captured.err!r}"
    )

    chunk_path = tmp_path / "data" / "chunks" / f"{source_id}.jsonl"
    assert chunk_path.exists(), (
        f"expected `axial chunk` (recursive mechanism) to write {chunk_path} "
        f"(PRD §7.7, '<source_id>.jsonl'), but it does not exist.\n"
        f"stdout: {captured.out!r}\nstderr: {captured.err!r}"
    )

    records = _read_jsonl(chunk_path)
    assert records, f"expected at least one chunk record in {chunk_path}, got none"

    seen_chunk_ids: set[str] = set()
    by_section: dict[str, list[dict]] = {}
    seen_section_orders_in_order: list[str] = []

    for record in records:
        assert isinstance(record, dict), f"expected each chunk record to be a JSON object, got {record!r}"

        for field in ("chunk_id", "section", "section_order", "text"):
            assert field in record, (
                f"expected every chunk record to carry {field!r} (PRD §7.7's "
                f"invariant contract, unchanged by the recursive mechanism), "
                f"missing from record: {record!r}"
            )

        chunk_id = record["chunk_id"]
        section = record["section"]
        section_order = record["section_order"]
        text = record["text"]

        assert isinstance(chunk_id, str) and chunk_id, f"expected a non-empty string chunk_id, got {chunk_id!r}"
        assert chunk_id not in seen_chunk_ids, f"expected chunk_ids to be unique, got a duplicate: {chunk_id!r}"
        seen_chunk_ids.add(chunk_id)

        assert section in KNOWN_SECTION_ORDERS, (
            f"expected 'section' to be one of this fixture's verbatim "
            f"headings {sorted(KNOWN_SECTION_ORDERS)}, got {section!r} "
            f"(record: {record!r})"
        )
        assert section_order == KNOWN_SECTION_ORDERS[section], (
            f"expected 'section_order' to be the tree node's own order "
            f"{KNOWN_SECTION_ORDERS[section]!r} for section {section!r}, "
            f"got {section_order!r} (record: {record!r})"
        )

        expected_prefix = f"{source_id}_{section_order}_"
        assert chunk_id.startswith(expected_prefix), (
            f"expected chunk_id to start with <source_id>_<section_order>_ "
            f"= {expected_prefix!r} (PRD §7.7's shared chunk_id scheme), got "
            f"{chunk_id!r}"
        )
        tail_match = _SLUG_NNN_RE.match(chunk_id[len(expected_prefix) :])
        assert tail_match is not None, (
            f"expected chunk_id's tail (after {expected_prefix!r}) to match "
            f"<slug>_<NNN>, got {chunk_id!r}"
        )

        assert isinstance(text, str) and text, f"expected non-empty string 'text', got {text!r} (record: {record!r})"
        assert len(text) <= CHUNK_MAX, (
            f"expected every record's text length <= CHUNK_MAX ({CHUNK_MAX}) "
            f"with NO exception (recursive descent's MAX-side guarantee, "
            f"same as the embedding path's), got {len(text)} chars for "
            f"chunk_id {chunk_id!r} in section {section!r}"
        )

        if section_order not in seen_section_orders_in_order:
            seen_section_orders_in_order.append(section_order)
        by_section.setdefault(section_order, []).append(record)

    # --- section-then-position order (PRD §7.7), same invariant as the
    # embedding path. ---
    assert seen_section_orders_in_order == sorted(seen_section_orders_in_order), (
        f"expected chunk records in section-then-position order (PRD §7.7), "
        f"but section_order values first appeared in file order "
        f"{seen_section_orders_in_order}, which is not sorted"
    )

    # --- MIN-side band property, with the documented section-tail /
    # whole-section-short exception (same reused `_enforce_min` contract as
    # the embedding path -- plan 06: "same two-sided band, different cut"). ---
    for section_order, section_records in by_section.items():
        total_section_chars = sum(len(r["text"]) for r in section_records)
        for position, record in enumerate(section_records):
            is_last_in_section = position == len(section_records) - 1
            whole_section_short = total_section_chars < CHUNK_MIN
            if is_last_in_section or whole_section_short:
                continue
            assert len(record["text"]) >= CHUNK_MIN, (
                f"expected every non-last chunk of a section (in a section "
                f"whose total text is not itself shorter than CHUNK_MIN) to "
                f"have text length >= CHUNK_MIN ({CHUNK_MIN}), got "
                f"{len(record['text'])} chars for chunk_id "
                f"{record['chunk_id']!r} (position {position} of "
                f"{len(section_records)} in section_order {section_order!r})"
            )

    # --- the wall-of-text section (no `\n\n`, no `\n` at all -- see seam
    # decision 3) was still SPLIT into multiple in-band records, proving the
    # recursive hierarchy fell through to sentence/char level rather than
    # stalling at the paragraph/line level for lack of a separator to find. ---
    wall_order = KNOWN_SECTION_ORDERS[WALL_OF_TEXT_HEADING]
    wall_records = by_section.get(wall_order, [])
    assert len(wall_records) >= 2, (
        f"expected the wall-of-text section ({WALL_OF_TEXT_HEADING!r}, a "
        f"single continuous run of CHUNK_MAX * 4 = {CHUNK_MAX * 4} characters "
        f"with NO newline anywhere in it) to be split into multiple in-band "
        f"chunk records by falling through the separator hierarchy "
        f"(paragraph -> line -> sentence -> char, plan 06), got "
        f"{len(wall_records)} -- a single record here would mean the section "
        f"was emitted whole (or the recursive mechanism does not exist)"
    )

    # --- examine parity (plan 06's fourth Gherkin clause): `axial chunk
    # examine` reports on this recursive artifact through the SAME stats
    # surface (`examine_chunks`/`format_examine_report`), with no error. ---
    examine_exit_code = main(["chunk", "examine"])
    examine_captured = capsys.readouterr()

    assert examine_exit_code == 0, (
        f"expected `axial chunk examine` to exit 0 against the "
        f"recursive-mechanism artifact just written -- a nonzero exit means "
        f"`examine` cannot read the recursive artifact through its existing "
        f"stats surface.\nstdout: {examine_captured.out!r}\n"
        f"stderr: {examine_captured.err!r}"
    )

    expected_total = len(records)
    assert str(expected_total) in examine_captured.out, (
        f"expected `axial chunk examine`'s report to include this recursive "
        f"artifact's own total chunk count ({expected_total}), reported via "
        f"the same `examine_chunks`/`format_examine_report` surface the "
        f"embedding path already uses.\nstdout: {examine_captured.out!r}"
    )
    assert source_id in examine_captured.out, (
        f"expected the recursive artifact's own source_id ({source_id!r}) to "
        f"be named in the examine report.\nstdout: {examine_captured.out!r}"
    )


def test_default_mechanism_unset_still_runs_embedding_based_chunk(tmp_path, monkeypatch):
    """Plan 06's third Gherkin clause: with the selector unset, `axial chunk`
    still runs the embedding-based default (byte-identity against a
    pre-slice baseline is an inner-test concern -- this is the lighter,
    outer-level "it still runs at all" assertion). No embedder/LLM seam is
    poisoned here -- the default path legitimately calls the embedder."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(MECHANISM_ENV_VAR, raising=False)

    source_id = compute_source_id(FIXTURE_PDF)
    _place_fixture_tree(tmp_path, source_id)

    from axial.cli import main

    exit_code = main(["chunk", str(FIXTURE_PDF)])

    assert exit_code == 0, (
        f"expected exit code 0 for `axial chunk` with "
        f"{MECHANISM_ENV_VAR} unset (the default, embedding-based mechanism, "
        f"unchanged by this slice), got {exit_code}"
    )

    chunk_path = tmp_path / "data" / "chunks" / f"{source_id}.jsonl"
    assert chunk_path.exists(), (
        f"expected the default (unset-selector) `axial chunk` run to still "
        f"write {chunk_path}, exactly as before this slice"
    )

    records = _read_jsonl(chunk_path)
    assert records, (
        "expected the default (unset-selector) embedding-based mechanism to "
        "still produce at least one chunk record, unchanged by this slice "
        "adding a second, opt-in mechanism"
    )
