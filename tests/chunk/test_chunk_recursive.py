"""Outer acceptance test for issue #165, slice 06 of the chunk-redesign
subproject (charter #148): deterministic recursive/structural splitting on a
separator hierarchy (paragraph `\n\n` -> line `\n` -> sentence -> char).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source with a known paragraph structure -- some sections with clear
      `\n\n` breaks, and one section that is a single wall of text with no
      `\n\n`
When  `axial.chunk.run_chunk_recursive` runs against it
Then  it writes data/chunks/<source_id>.jsonl with the §7.7 fields and stable
      chunk_ids, every chunk <= max and (modulo the section-tail exception)
      >= min, splitting the wall-of-text section by falling through
      `\n\n` -> `\n` -> sentence -> char
And   it makes zero LLM calls and zero embedding-model calls
And   `axial chunk examine` reports on the recursive artifact through the
      same stats surface

See specs/PRODUCT.md §5 stage 4 / §7.7 / §8 P0-4 for the source of truth on
the shared chunk artifact and band guard, and
plans/chunk-redesign/06-recursive-mechanism.md (this slice's own plan) for
the recursive-mechanism contract this test encodes.

Migration note (issue #191, spec-drift, founder-adjudicated)
-----------------------------------------------------------------------
Slice 06 originally shipped recursive/structural as a SECOND,
operator-selectable mechanism behind an env-var seam
(`AXIAL_CHUNK_MECHANISM=recursive`, mirroring `axial.chunk`'s own
`AXIAL_EMBEDDER` / `get_embedder` seam), with the embedding-based mechanism
remaining the unset/default. Issue #191 escalated from "flip the default"
to full removal: the founder adjudicated recursive/structural as the SOLE
chunk mechanism after a head-to-head over six real sources (~100x cheaper,
quality a wash) -- the embedding apparatus and the `AXIAL_CHUNK_MECHANISM`
selector seam are retired outright. This test is migrated accordingly:
there is no longer a selector to set (recursive is not "selected", it is
the only mechanism), and the third Gherkin clause this file used to lock
("with the mechanism unset, `axial chunk` still runs the embedding-based
default") is retired along with the mechanism it named -- that behavior no
longer exists to test. Band guard, section-tail behavior, disk-first
artifact shape, and examine parity are unchanged and still locked here.

Seam decision 1 -- calling `run_chunk_recursive` directly, not through the
CLI's mechanism dispatch
-----------------------------------------------------------------------
This test author commit was originally written (and first turned green)
while `src/axial/cli.py`'s `chunk` subcommand still dispatched on
`get_chunk_mechanism()` (unset -> the then-not-yet-retired embedding
default) -- so going through the bare CLI would have exercised the
embedding-based default (which calls a real sentence-embedding model unless
`AXIAL_EMBEDDER=stub` is set), not the recursive mechanism this test is
about. Calling `axial.chunk.run_chunk_recursive` directly sidesteps that
dispatch entirely, proving the recursive mechanism's own contract
regardless of what the CLI's default is wired to -- which is exactly what
lets this same test stay correct, unmodified, now that the implementer has
removed the embedding apparatus and `get_chunk_mechanism` seam outright
(issue #191): `run_chunk_recursive` is unaffected either way.

Seam decision 2 -- zero-embedding/zero-LLM proof: poison the remaining
construction seam directly, in-process
-----------------------------------------------------------------------
`run_chunk_recursive` never imports or references an embedder or an LLM
client at all (verified by reading `src/axial/chunk.py`) -- the "zero
embedding-model / zero LLM calls" contract holds by construction: issue
#191 removed the `Embedder` protocol, `HashingEmbedder`, `FastEmbedEmbedder`,
and `get_embedder` from `axial.chunk` outright, so there is no embedder
construction seam left to poison at all. This test still poisons
`axial.chunk.get_client` (`raising=False`, a genuine no-op today since
`axial.chunk` never imports it -- kept defensively in case a future
refactor introduces one) as a regression check on the LLM-client half of
this contract: if a future change to `run_chunk_recursive` or
`_write_chunk_sections` ever accidentally reached that seam, this test
fails loudly.

Seam decision 3 -- the fixture tree, and why the wall-of-text section is
built from a SINGLE leaf child
-----------------------------------------------------------------------
The recursive stage reads a persisted structural tree only (mirroring
tests/chunk/test_chunk.py's own seam decision 4): this test fabricates one
by hand and pre-places it at `data/trees/<source_id>.json` for the same
committed fixture PDF `tests/fixtures/envelope/thesis_paper.pdf` already
reused as a byte source elsewhere in this suite (never for its own tree
shape).

`run_chunk_recursive` joins a section's routed body lines with `\n\n` (one
real docling paragraph break per block) -- but this test does not lock that
join choice as its own contract. Instead, the "wall of text" section is
built from EXACTLY ONE leaf child carrying one continuous string with NO
`\n` characters anywhere inside it (not even a single line break) -- so no
matter what separator a join uses to combine multiple blocks, this section
is not multiple blocks, and no separator is ever inserted into it. This
guarantees the section's assembled body text truly contains no `\n\n` (and
no `\n` at all), so a paragraph-level (or even line-level) split cannot
fire on it by construction -- the ONLY way this section can still yield
multiple in-band chunks is if the recursive splitter actually fell through
to the sentence or char level, which is exactly what this test's Gherkin
requires it to prove. The section is sized to `CHUNK_MAX * 4` characters of
ordinary, real-sentence prose (periods present, so a sentence-level
fallback can succeed without needing to fall all the way to a raw char
split) -- comfortably forcing at least one MAX-side split regardless of the
implementer's exact `CHUNK_MAX` value.

The "Overview" section, by contrast, is built from several SEPARATE leaf
children (distinct paragraphs) -- giving the tree a section with genuine
inter-block structure for the join step to insert its own separator
between, satisfying the Gherkin's "some sections with clear `\n\n` breaks"
clause, without this test dictating the exact separator character used.

Seam decision 4 -- isolation via an isolated tmp cwd, not the real repo root
-----------------------------------------------------------------------
Because this test poisons a module-level attribute (`axial.chunk.get_client`)
via `monkeypatch`, it must run in-process, so it runs from a freshly
created, empty `tmp_path` cwd instead of shelling out to the CLI against the
real repo root: `axial.extract.TREES_DIR` / `axial.chunk.CHUNKS_DIR` both
resolve as plain, cwd-relative paths, so `monkeypatch.chdir(tmp_path)` makes
`data/trees/` and `data/chunks/` resolve under the isolated tmp root, never
touching the real repo's `data/` tree at all (no reliance on
tests/conftest.py's autouse snapshot/restore fixture is needed here).

Seam decision 5 -- band constants and chunk_id shape imported, not hardcoded
-----------------------------------------------------------------------
Mirroring tests/chunk/test_chunk.py's seam decision 3, this test imports
`CHUNK_MIN`/`CHUNK_MAX` from `axial.chunk` rather than hardcoding the band,
and asserts the chunk_id *shape* (`<source_id>_<section order>_<slug>_<NNN>`)
via the same permissive tail regex tests/chunk/test_chunk.py already locked,
not an exact slugify algorithm.

Out of scope for this file (left to inner unit tests per the slice plan)
-----------------------------------------------------------------------
This test does not assert exactly which hierarchy level (paragraph vs. line
vs. sentence vs. char) fired for any given fixture section -- only that the
wall-of-text section (which by construction cannot split at the paragraph or
line level) still yields multiple in-band chunks, proving SOME fall-through
occurred.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from axial.chunk import CHUNK_MAX, CHUNK_MIN, run_chunk_recursive
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_PDF = REPO_ROOT / "tests" / "fixtures" / "envelope" / "thesis_paper.pdf"

NORMAL_SECTION_HEADING = "Overview"
WALL_OF_TEXT_HEADING = "Continuous Field Notes"

KNOWN_SECTION_ORDERS = {
    NORMAL_SECTION_HEADING: "1",
    WALL_OF_TEXT_HEADING: "2",
}

# Matches only the "<slug>_<NNN>" tail of a chunk_id, mirroring
# tests/chunk/test_chunk.py's own regex exactly (see that file's comment for
# why a single regex over the WHOLE chunk_id would be ambiguous).
_SLUG_NNN_RE = re.compile(r"^(?P<slug>[a-z0-9-]+)_(?P<nnn>\d{3})$")

# Several DISTINCT paragraphs (no internal newlines each) giving the
# "Overview" section genuine inter-block structure (seam decision 3).
_OVERVIEW_PARAGRAPHS = [
    "Field teams conducted a short survey of provincial administration "
    "following the ceasefire, focused on service delivery and local "
    "governance capacity.",
    "This section summarizes the survey's scope and method before the "
    "detailed findings that follow.",
    "Respondents were drawn from municipal offices across three neighboring districts.",
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
    (axial.extract.TREES_DIR's own cwd-relative default), so
    `run_chunk_recursive` (via its persisted-tree cache) reads it verbatim
    instead of running docling."""
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
    """Defense-in-depth poison of the one remaining construction/use seam a
    text-generating LLM client could be reached through (seam decision 2):
    `axial.chunk.get_client` raises `AssertionError` if ever called.
    `raising=False` here is a genuine no-op today (the chunk module never
    imports `get_client` at all) -- kept defensively in case a future
    refactor introduces one.

    The embedder side of this proof (`axial.chunk.get_embedder` /
    `HashingEmbedder.encode`) no longer applies: issue #191 removed the
    `Embedder` protocol, `HashingEmbedder`, `FastEmbedEmbedder`, and
    `get_embedder` from `axial.chunk` entirely, so there is no embedder
    construction seam left to poison -- the recursive/structural mechanism
    constructs no embedder by construction (it never imports the concept),
    not merely by avoiding use of one already built."""

    def _poison(*_args, **_kwargs):
        raise AssertionError(
            "the recursive chunk mechanism must make NO text-generating "
            "LLM call -- this seam was reached during a "
            "`run_chunk_recursive` run"
        )

    monkeypatch.setattr("axial.chunk.get_client", _poison, raising=False)


def test_recursive_mechanism_writes_bounded_artifact_with_zero_model_calls_and_examine_parity(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)

    source_id = compute_source_id(FIXTURE_PDF)
    _place_fixture_tree(tmp_path, source_id)

    _poison_embedding_and_llm_seams(monkeypatch)

    records = run_chunk_recursive(FIXTURE_PDF)

    chunk_path = tmp_path / "data" / "chunks" / f"{source_id}.jsonl"
    assert chunk_path.exists(), (
        f"expected `run_chunk_recursive` to write {chunk_path} "
        f"(PRD §7.7, '<source_id>.jsonl'), but it does not exist."
    )

    on_disk_records = _read_jsonl(chunk_path)
    assert on_disk_records == records, (
        "expected the returned records to match the on-disk artifact exactly"
    )
    assert records, f"expected at least one chunk record in {chunk_path}, got none"

    seen_chunk_ids: set[str] = set()
    by_section: dict[str, list[dict]] = {}
    seen_section_orders_in_order: list[str] = []

    for record in records:
        assert isinstance(record, dict), (
            f"expected each chunk record to be a JSON object, got {record!r}"
        )

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

        assert isinstance(chunk_id, str) and chunk_id, (
            f"expected a non-empty string chunk_id, got {chunk_id!r}"
        )
        assert chunk_id not in seen_chunk_ids, (
            f"expected chunk_ids to be unique, got a duplicate: {chunk_id!r}"
        )
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

        assert isinstance(text, str) and text, (
            f"expected non-empty string 'text', got {text!r} (record: {record!r})"
        )
        assert len(text) <= CHUNK_MAX, (
            f"expected every record's text length <= CHUNK_MAX ({CHUNK_MAX}) "
            f"with NO exception (recursive descent's MAX-side guarantee), "
            f"got {len(text)} chars for chunk_id {chunk_id!r} in section "
            f"{section!r}"
        )

        if section_order not in seen_section_orders_in_order:
            seen_section_orders_in_order.append(section_order)
        by_section.setdefault(section_order, []).append(record)

    # --- section-then-position order (PRD §7.7). ---
    assert seen_section_orders_in_order == sorted(seen_section_orders_in_order), (
        f"expected chunk records in section-then-position order (PRD §7.7), "
        f"but section_order values first appeared in file order "
        f"{seen_section_orders_in_order}, which is not sorted"
    )

    # --- MIN-side band property, with the documented section-tail /
    # whole-section-short exception. ---
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
        f"(paragraph -> line -> sentence -> char), got {len(wall_records)} -- "
        f"a single record here would mean the section was emitted whole"
    )

    # --- examine parity: `axial chunk examine` reports on this recursive
    # artifact through the SAME stats surface (`examine_chunks`/
    # `format_examine_report`), with no error. This goes through the real
    # CLI -- `examine` never touches an embedder or LLM client, so it is
    # unaffected by which chunk mechanism produced the artifact it reads. ---
    from axial.cli import main

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
        f"the same `examine_chunks`/`format_examine_report` surface.\n"
        f"stdout: {examine_captured.out!r}"
    )
    assert source_id in examine_captured.out, (
        f"expected the recursive artifact's own source_id ({source_id!r}) to "
        f"be named in the examine report.\nstdout: {examine_captured.out!r}"
    )
