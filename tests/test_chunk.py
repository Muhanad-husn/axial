"""Outer acceptance test for issue #151, slice 01 of the chunk-redesign
subproject (charter #148): the embedding-based chunk stage.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fixture source whose persisted tree has (a) a normal prose section,
      (b) a legitimate section far larger than `max`, and (c) a high-non-alpha
      "garbage" section
When  the user runs `axial chunk <fixture>` with a deterministic stub embedder
Then  it exits 0 and writes data/chunks/<source_id>.jsonl with one JSON
      object per line
And   every record's `text` length is <= `max`, and >= `min` except a
      section's last chunk or a whole section shorter than `min`
And   each record carries chunk_id (`<source_id>_<section order>_<slug>_<NNN>`),
      section (verbatim heading), section_order (the tree node order), and text
And   the oversized legitimate section is split into multiple in-band records
      (never dropped)
And   the garbage section contributes no records and the skip + reason are
      logged
And   no text-generating LLM call is made during the run (chunk critical path
      is LLM-free)

This REPLACES the old LLM-echo outer test (issue #17 slice 05): the P0-4
rewrite (#150) retires that contract wholesale -- the chunk stage no longer
reads a stored envelope, no longer calls a text-generating LLM at all, and no
longer emits records to stdout. See specs/PRODUCT.md §5 stage 4 ("Semantic
chunking (embedding-based, LLM-independent)."), §7.7 ("On-disk chunk
artifact"), and §8 P0-4 for the source of truth. See
plans/chunk-redesign/01-chunk-stage.md for the slice plan this test encodes.

Seam decision 1 -- the embedder injection seam: `AXIAL_EMBEDDER=stub`
-----------------------------------------------------------------------
Nothing in the repo today imports a sentence-embedding library (verified by
grep); this slice adds one, plus an injectable embedder so tests never hit
the network or download a real model. Mirroring the established
`AXIAL_LLM_PROVIDER` env-var convention (src/axial/llm.py's
`PROVIDER_ENV_VAR`), this test locks a new, analogous seam: the env var
`AXIAL_EMBEDDER`, set to `"stub"` for a deterministic, offline, no-network
embedder. This test does not dictate the stub's internal embedding function
(e.g. a hash-based vector) -- only that selecting it makes `axial chunk` run
end-to-end with zero network access and a reproducible split. The
implementer must wire this env var; an unset/absent `AXIAL_EMBEDDER` is not
exercised by this test and is left to the implementer's own default.

Seam decision 2 -- zero-LLM-call proof: reuse the `explode` poison provider
-----------------------------------------------------------------------
This slice's whole point (PRD §5 stage 4, "no text-generating LLM call in
the chunk critical path") is directly testable with the SAME poison-provider
trick tests/test_envelope.py already locked: this test runs `axial chunk`
with `AXIAL_LLM_PROVIDER=explode` (src/axial/llm.py's `ExplodingLLMClient`,
which raises only when `.complete()` is actually invoked -- selecting it is
always safe). If the chunk critical path ever calls a text-generating LLM
for any reason -- even indirectly, e.g. an accidental envelope read/rebuild,
or an embedding call routed through the generative client by mistake -- the
process crashes and this test's exit-code-0 assertion fails. A clean exit 0
under `explode` is therefore a direct behavioral proof of "LLM-free chunk
critical path", not an inference from the absence of a log line.

Seam decision 3 -- band constants imported from the implementation, not
hardcoded here
-----------------------------------------------------------------------
The slice plan leaves `[min, max]`'s exact values to the implementer
("sensible starting points, documented in the module, not asserted as
final"). This test therefore imports the band's own constants from
`axial.chunk` -- `CHUNK_MIN` and `CHUNK_MAX` (character counts, matching
§7.7's "`text` length") -- and asserts the *property* (every record's `text`
length falls in `[CHUNK_MIN, CHUNK_MAX]`, modulo the documented exceptions)
rather than a magic number. The implementer must export both names at
module level from `axial.chunk`. This import happens at module top level, so
if the new chunk module (or its band constants) does not exist yet, this
whole test file fails to collect -- a loud, correct-reason red, not a
same-file typo: it means the seam this test depends on has not been built.
The oversized "legitimate" fixture section is sized as `CHUNK_MAX * 5`
characters of generated prose (see `_build_oversized_section_text` below),
so it must require a split regardless of the exact `CHUNK_MAX` value the
implementer picks.

Seam decision 4 -- the fixture tree, and why "size never triggers a skip"
matters here
-----------------------------------------------------------------------
The stage reads a *persisted* structural tree only (PRD §5 stage 4: "The
stage reads the persisted structural tree only"), not a PDF through docling.
This test builds that tree by hand, matching the locked node shape
(src/axial/extract.py's `_build_tree`/`tree_path`/`persist_tree`: a root
`{"children": [...]}`, where each top-level section node carries `type`,
`order`, `text` (the verbatim heading), and `children`; each child prose leaf
carries `type == "prose"` and `text`), and pre-places it at
`data/trees/<source_id>.json` for a small, real, committed fixture PDF (the
existing `tests/fixtures/envelope/thesis_paper.pdf`, reused here purely as a
byte source to compute a real `source_id` -- see
`axial.envelope.compute_source_id` -- never for its own tree shape, which
this test overwrites entirely). Because `axial.extract.extract`'s
persisted-tree cache is checked BEFORE docling ever runs (verified by
reading src/axial/extract.py), placing the fixture tree at the exact
computed `source_id` path makes `axial chunk` consume this fabricated tree
verbatim, offline, without a real docling conversion.

The fabricated tree carries exactly three top-level sections:
  1. "Overview" -- ordinary prose, unremarkable size.
  2. "Field Survey Findings" -- legitimate prose, but built to
     `CHUNK_MAX * 5` characters, deliberately far larger than any plausible
     `max`. PRD §8 P0-4 and §7.7 both state, without qualification, that
     size alone never triggers a skip for a legitimate section -- only a
     deliberate split. This is the crux fact this slice exists to fix (the
     old, retired LLM-echo mechanism could not safely handle a section this
     large at all): this test asserts the oversized section yields MULTIPLE
     records, none exceeding `CHUNK_MAX`, proving the split actually
     happened rather than the section being silently dropped or truncated.
  3. "Numeric Annex" -- a high-non-alphabetic "garbage" section (a synthetic
     stand-in for an OCR'd index/page-number listing: near-entirely digits,
     commas, and semicolons, well under `_ALPHA-heavy` territory). Chosen to
     be a heading that does NOT appear in axial.chunk's/xref's existing
     back-matter title exclusion list (`_BACK_MATTER_TITLES`, e.g. "index",
     "bibliography") -- that is an unrelated, orthogonal mechanism (issue
     #113) this test must not accidentally exercise instead of the
     non-alpha-ratio guard this slice's Gherkin actually names. This section
     is kept deliberately modest in size (a few thousand characters) so its
     skip can only be explained by its non-alphabetic content, never by
     size -- keeping the "size never skips; only non-alpha ratio does"
     distinction unambiguous.

Seam decision 5 -- cross-test isolation
-----------------------------------------------------------------------
This test runs the CLI from the real repo root (`REPO_ROOT`, matching every
other subprocess-based outer test in this suite) so `data/trees/` and
`data/chunks/` resolve to the real, cwd-relative default paths
(`axial.extract.TREES_DIR`, `axial.chunk.CHUNKS_DIR`) exactly as they would
in production -- consistent with how the retired test_chunk.py and
test_envelope.py already isolate `data/trees/`/`data/envelopes/`. Both
`data/trees/` and `data/chunks/` are protected by the autouse
`_isolate_persisted_tree_and_envelope_state` fixture in tests/conftest.py
(extended by this same issue to snapshot/restore `*.jsonl` files too, not
just `*.json`), so the fabricated tree this test places and the chunk
artifact `axial chunk` writes are both restored/removed after the test,
never leaking into a later test that computes the same `source_id`.

Assumptions this test locks as the contract the implementer must meet
(not dictated verbatim by the PRD/plan, but required to make this an
executable test)
-----------------------------------------------------------------------
  - `axial chunk <source_path>` still takes a source *file* path (unchanged
    CLI shape) but its behavior changes: exit 0 with NOTHING required on
    stdout, and the JSONL artifact written to
    `data/chunks/<source_id>.jsonl` is the actual contract surface (PRD
    §7.7). This test does not assert stdout is empty (a summary/log line
    there is fine) -- only that the on-disk artifact is correct.
  - `chunk_id`'s slug component is some lowercase, hyphen/alnum "slug" of
    the section heading -- this test does not lock the exact slugify
    algorithm (already established elsewhere, e.g. `axial.chunk._slugify` in
    the old module), only the overall `<source_id>_<order>_<slug>_<NNN>`
    shape via a permissive regex, per §7.7's own template.
  - Within one section, `NNN` is a zero-padded, 1-based, strictly
    increasing position counter (matching §7.7's own `chunk_id` template and
    the pre-existing, unchanged convention in the old module) -- this test
    asserts monotonic increase, not that positions start at a specific
    literal value beyond 1.
  - The chunk artifact's records appear in section-then-position order
    (PRD §7.7, "one line per chunk, in section-then-position order") --
    this test asserts section 1's records all precede section 2's in the
    file (section 3 contributes none).
  - The garbage-section skip is logged to stderr, naming the section's own
    heading -- this test asserts the heading text and a skip-indicating
    word appear in stderr, without locking an exact log message string
    (only the module's own docstring/implementation should own that
    wording).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from axial.chunk import CHUNK_MAX, CHUNK_MIN
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
TREES_DIR = REPO_ROOT / "data" / "trees"
CHUNKS_DIR = REPO_ROOT / "data" / "chunks"

# Reused purely as a byte source to compute a real, deterministic source_id
# (axial.envelope.compute_source_id hashes the file's own bytes) -- never for
# its own tree shape, which this test overwrites entirely with a fabricated
# tree built to this slice's own three-section spec (see module docstring,
# seam decision 4).
FIXTURE_PDF = FIXTURES_DIR / "thesis_paper.pdf"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
EMBEDDER_ENV_VAR = "AXIAL_EMBEDDER"

NORMAL_SECTION_HEADING = "Overview"
OVERSIZED_SECTION_HEADING = "Field Survey Findings"
GARBAGE_SECTION_HEADING = "Numeric Annex"

KNOWN_SECTION_ORDERS = {
    NORMAL_SECTION_HEADING: "1",
    OVERSIZED_SECTION_HEADING: "2",
    GARBAGE_SECTION_HEADING: "3",
}

# argparse's fallback error for an as-yet-nonexistent subcommand/argument --
# any of these substrings in the combined output means the target
# subcommand's real logic was never actually exercised (mirrors the retired
# test_chunk.py's identical guard).
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)

# A handful of distinct filler sentences, cycled to build the oversized
# "legitimate" section up to CHUNK_MAX * 5 characters (seam decision 3).
# Ordinary, low-non-alpha-ratio English prose -- must never itself qualify as
# "garbage" content.
_FILLER_SENTENCES = [
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


def _build_oversized_section_text(min_chars: int) -> str:
    """Generate ordinary, legitimate prose at least `min_chars` characters
    long by cycling `_FILLER_SENTENCES`."""
    sentences: list[str] = []
    total = 0
    index = 0
    while total < min_chars:
        sentence = _FILLER_SENTENCES[index % len(_FILLER_SENTENCES)]
        sentences.append(sentence)
        total += len(sentence) + 1
        index += 1
    return " ".join(sentences)


def _build_garbage_section_text() -> str:
    """A synthetic, high-non-alphabetic "garbage" section: a page-number-style
    listing (digits, commas, semicolons), the shape PRD §5 stage 4 names as
    the motivating example ("e.g. an OCR'd index"). Kept modest in size (well
    under the oversized section above) so its skip can only be explained by
    its non-alphabetic content, never by size."""
    entries = [f"{n * 3}, {n * 3 + 1}-{n * 3 + 2}" for n in range(1, 400)]
    return "; ".join(entries)


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


def _build_fixture_tree(oversized_text: str, garbage_text: str) -> dict:
    """The fabricated persisted-tree fixture: three top-level sections
    matching this slice's acceptance criterion (normal / oversized-legitimate
    / garbage) -- see module docstring, seam decision 4."""
    return {
        "children": [
            _section(
                "1",
                NORMAL_SECTION_HEADING,
                [
                    "Field teams conducted a short survey of provincial administration "
                    "following the ceasefire, focused on service delivery and local "
                    "governance capacity.",
                    "This section summarizes the survey's scope and method before the "
                    "detailed findings that follow.",
                ],
            ),
            _section("2", OVERSIZED_SECTION_HEADING, [oversized_text]),
            _section("3", GARBAGE_SECTION_HEADING, [garbage_text]),
        ]
    }


def _place_fixture_tree(source_id: str) -> Path:
    """Write the fabricated tree fixture to data/trees/<source_id>.json, so
    `axial chunk` (via `axial.extract.extract`'s persisted-tree cache) reads
    it verbatim instead of running docling."""
    oversized_text = _build_oversized_section_text(CHUNK_MAX * 5)
    garbage_text = _build_garbage_section_text()
    tree = _build_fixture_tree(oversized_text, garbage_text)

    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(json.dumps(tree), encoding="utf-8")
    return tree_path


def _run_chunk(source_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"  # poison: any text-gen LLM call crashes the run
    env[EMBEDDER_ENV_VAR] = "stub"  # deterministic, offline, no network/model download
    return subprocess.run(
        ["uv", "run", "axial", "chunk", str(source_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `chunk` behavior path, not an argparse fallback "
            f"(found {marker!r}) -- this means the `chunk` subcommand's real "
            f"logic was never reached:\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


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


# Matches only the "<slug>_<NNN>" tail of a chunk_id -- NOT the whole
# chunk_id jointly with source_id/order. source_id itself is a
# `<filename-stem>-<hex-digest>` string (axial.envelope.compute_source_id)
# that can itself contain underscores and hyphens, so a single regex trying
# to jointly carve source_id/order/slug/NNN out of the full chunk_id string
# would be ambiguous by construction. Since this test already knows the
# real source_id (computed the same way the implementation must) and the
# fixture's own section_order values, chunk_id's prefix
# (`<source_id>_<section_order>_`) is checked with a plain `str.startswith`
# instead, and only the remaining `<slug>_<NNN>` tail is parsed with this
# regex, which is unambiguous (NNN is always exactly 3 digits anchored at
# the end).
_SLUG_NNN_RE = re.compile(r"^(?P<slug>[a-z0-9-]+)_(?P<nnn>\d{3})$")


@pytest.fixture
def chunk_fixture_source():
    """Compute this fixture's source_id, pre-place the fabricated tree, and
    clean up both the tree and the chunk artifact afterward (belt-and-braces
    on top of tests/conftest.py's autouse directory-snapshot isolation)."""
    source_id = compute_source_id(FIXTURE_PDF)
    tree_path = _place_fixture_tree(source_id)
    chunk_path = CHUNKS_DIR / f"{source_id}.jsonl"

    yield source_id, chunk_path

    tree_path.unlink(missing_ok=True)
    chunk_path.unlink(missing_ok=True)


def test_chunk_writes_bounded_jsonl_artifact_with_provenance_and_no_llm_call(
    chunk_fixture_source,
):
    source_id, chunk_path = chunk_fixture_source

    result = _run_chunk(FIXTURE_PDF)
    _assert_not_argparse_fallback(result)

    # --- exit 0, with AXIAL_LLM_PROVIDER=explode: proves the chunk critical
    # path made zero text-generating LLM calls (seam decision 2). ---
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial chunk` against a fixture tree with "
        f"the stub embedder and the poison `explode` LLM provider configured "
        f"-- a nonzero exit here most likely means either the chunk critical "
        f"path called a text-generating LLM (PRD §5 stage 4, 'no "
        f"text-generating LLM call in the chunk critical path') or the "
        f"AXIAL_EMBEDDER=stub seam does not exist yet.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # --- the on-disk artifact exists at the deterministic, source_id-keyed
    # path (PRD §7.7). ---
    assert chunk_path.exists(), (
        f"expected `axial chunk` to write {chunk_path} (PRD §7.7, "
        f"'<source_id>.jsonl'), but it does not exist.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    records = _read_jsonl(chunk_path)
    assert records, f"expected at least one chunk record in {chunk_path}, got none"

    # --- group records by section, preserving file order, and check that
    # section-then-position order holds (PRD §7.7). ---
    seen_section_orders_in_order: list[str] = []
    by_section: dict[str, list[dict]] = {}
    seen_chunk_ids: set[str] = set()

    for record in records:
        assert isinstance(record, dict), (
            f"expected each chunk record to be a JSON object, got {record!r}"
        )

        for field in ("chunk_id", "section", "section_order", "text"):
            assert field in record, (
                f"expected every chunk record to carry {field!r} (PRD §7.7's "
                f"invariant contract), missing from record: {record!r}"
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
            f"= {expected_prefix!r} (PRD §7.7), got {chunk_id!r}"
        )
        tail_match = _SLUG_NNN_RE.match(chunk_id[len(expected_prefix) :])
        assert tail_match is not None, (
            f"expected chunk_id's tail (after {expected_prefix!r}) to match "
            f"<slug>_<NNN> (PRD §7.7's "
            f"<source_id>_<section order>_<slug>_<NNN> template), got "
            f"{chunk_id!r}"
        )

        assert isinstance(text, str) and text, (
            f"expected non-empty string 'text', got {text!r} (record: {record!r})"
        )
        assert len(text) <= CHUNK_MAX, (
            f"expected every record's text length <= CHUNK_MAX ({CHUNK_MAX}) "
            f"with NO exception (PRD §7.7/§8 P0-4, MAX side never exceeded), "
            f"got {len(text)} chars for chunk_id {chunk_id!r} in section "
            f"{section!r}"
        )

        if section_order not in seen_section_orders_in_order:
            seen_section_orders_in_order.append(section_order)
        by_section.setdefault(section_order, []).append(record)

    # --- section-then-position order: every record of an earlier section
    # precedes every record of a later section in the file (PRD §7.7). ---
    assert seen_section_orders_in_order == sorted(seen_section_orders_in_order), (
        f"expected chunk records in section-then-position order (PRD §7.7), "
        f"but section_order values first appeared in file order "
        f"{seen_section_orders_in_order}, which is not sorted"
    )

    # --- MIN-side band property, with the two documented exceptions: the
    # last chunk of a section, or a whole section shorter than CHUNK_MIN. ---
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
                f"have text length >= CHUNK_MIN ({CHUNK_MIN}) -- PRD §7.7/§8 "
                f"P0-4, MIN side merges adjacent below-min chunks forward -- "
                f"got {len(record['text'])} chars for chunk_id "
                f"{record['chunk_id']!r} (position {position} of "
                f"{len(section_records)} in section_order {section_order!r})"
            )

        # --- NNN is a zero-padded, 1-based, strictly increasing position
        # counter within the section (matches PRD §7.7's own chunk_id
        # template). ---
        section_prefix = f"{source_id}_{section_order}_"
        nnns = [
            int(_SLUG_NNN_RE.match(r["chunk_id"][len(section_prefix) :]).group("nnn"))
            for r in section_records
        ]
        assert nnns == list(range(1, len(nnns) + 1)), (
            f"expected chunk_id's NNN component to be a 1-based, strictly "
            f"increasing position counter within section_order "
            f"{section_order!r}, got {nnns}"
        )

    # --- the oversized legitimate section was SPLIT, never dropped (PRD
    # §5 stage 4, §8 P0-4: 'a section larger than max ... is split into
    # multiple in-band chunks -- never emitted whole, never skipped for
    # size'). ---
    oversized_order = KNOWN_SECTION_ORDERS[OVERSIZED_SECTION_HEADING]
    oversized_records = by_section.get(oversized_order, [])
    assert len(oversized_records) >= 2, (
        f"expected the oversized legitimate section ({OVERSIZED_SECTION_HEADING!r}, "
        f"built to CHUNK_MAX * 5 = {CHUNK_MAX * 5} characters) to be split "
        f"into multiple in-band chunk records, got {len(oversized_records)} "
        f"-- PRD §5 stage 4/§8 P0-4 require a section this large to be split, "
        f"never emitted whole and never dropped for size"
    )

    # --- the garbage section contributed NO records (PRD §5 stage 4, §8
    # P0-4: skipped, not split, not emitted). ---
    garbage_order = KNOWN_SECTION_ORDERS[GARBAGE_SECTION_HEADING]
    garbage_records = by_section.get(garbage_order, [])
    assert garbage_records == [], (
        f"expected the high-non-alphabetic 'garbage' section "
        f"({GARBAGE_SECTION_HEADING!r}) to contribute zero chunk records "
        f"(PRD §5 stage 4, 'skipped by a deliberate, logged rule'), got "
        f"{len(garbage_records)}: {garbage_records!r}"
    )

    # --- the garbage-section skip + its reason are logged (PRD §7.7,
    # 'the skip and its reason are logged, so a reader can always
    # distinguish a deliberate skip from a silent loss'). Only the heading
    # + a skip-indicating word are locked here; the exact wording is left to
    # the implementer (see module docstring, "Assumptions"). ---
    combined_output = (result.stdout + result.stderr).lower()
    assert GARBAGE_SECTION_HEADING.lower() in combined_output, (
        f"expected the garbage section's own heading ({GARBAGE_SECTION_HEADING!r}) "
        f"to appear in the run's logged output, naming which section was "
        f"skipped and why (PRD §7.7).\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert "skip" in combined_output, (
        f"expected the run's logged output to indicate a skip occurred for "
        f"the garbage section (PRD §7.7, 'the skip and its reason are "
        f"logged').\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
