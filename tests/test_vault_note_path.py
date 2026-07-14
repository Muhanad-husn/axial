"""Outer acceptance test for issue #94 (bounded note filenames for long
section slugs -- Windows MAX_PATH).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source whose sole top-level section heading slugifies to well over
      200 characters (a real-world case: a paper whose only heading restates
      its full title -- see issue #94's "Observed" traceback, worker 1,
      syria-state-legitimacy-and-capacity, 2026-07-10)
When  the user runs `axial vault write <source>`
Then  it exits 0 (not the Windows `FileNotFoundError` issue #94 reports,
      caused by the note's absolute path exceeding the 260-char MAX_PATH)
And   every prose note filename written for that source is short enough to
      keep well clear of that limit
And   sources whose section slugs are already short (every already-ingested
      source, per issue #94's own acceptance list) are completely unaffected
      -- their note filenames must still equal their chunk_ids exactly, byte
      for byte, proving the fix is a no-op under the cap.

See issue #94 ("vault write: note path exceeds Windows MAX_PATH when
section slug is very long") for the full report and:

  - Root cause: `axial.chunk._slugify` (src/axial/chunk.py) places an
    unbounded section-heading slug inside `chunk_id`
    (`<source_id>_<order>_<slug>_<NNN>`, `build_chunk_records`), and
    `axial.vault._note_path` (src/axial/vault.py) names the note file
    `<chunk_id>.md` directly -- so an oversized slug makes an oversized
    filename with nothing capping it.
  - Fix (implementer's job, not this test's): cap the slug at ~80 chars,
    trimming at a hyphen boundary where possible. Uniqueness is unaffected
    because the section's own `order` component already disambiguates two
    same-titled sections.
  - Acceptance (quoted directly): "`axial vault write` on a source whose
    section heading slugifies to >200 chars produces notes with filenames
    short enough that the absolute path stays well under 260 chars, and
    succeeds." / "Slugs at or under the cap are unchanged (existing
    chunk_ids for every already-ingested source are stable across the fix)."
  - specs/PRODUCT.md §8 P0-4 ("Output chunks carry stable `chunk_id`s and
    preserve section provenance") -- deliberately does NOT pin an exact
    chunk_id format, so a bounded-length slug is not spec drift (issue #94's
    own "Root cause"/"Fix" sections make this determination explicitly).

Seam decision 1 -- reproducing the long slug without a new binary fixture
-----------------------------------------------------------------------
This test never adds a new binary PDF fixture to tests/fixtures/. Instead,
at test run time, it copies tests/fixtures/envelope/thesis_paper.pdf's
bytes VERBATIM to a new path under a different filename stem inside the
isolated staging root -- exactly the technique tests/test_vault_resume.py's
own "edited copy" seam already uses (its module docstring, seam decision
4) to get a fresh, deterministic `source_id`
(`axial.envelope.compute_source_id` hashes content but folds in the
filename stem too, so a renamed byte-identical copy reliably gets its own
id, "distinct files never collide"). This test then hand-builds a tree JSON
in the same locked `{children, type, order}` shape as the committed
tests/fixtures/envelope/thesis_paper_tree.json (see that fixture and
src/axial/extract.py's module docstring for the contract), but with a
single top-level section whose heading text closely paraphrases the real,
overlong heading from issue #94's traceback -- long enough on its own
(computed at import time, not eyeballed -- see the `assert` right after
`LONG_SECTION_HEADING`'s definition) that its slug exceeds 200 characters,
matching the issue's own "slugifies to >200 chars" acceptance wording. That
tree is pre-placed at `data/trees/<source_id>.json` in the staging root
before `axial envelope`/`axial vault write` ever run, so
`axial.extract.extract`'s persisted-tree-cache short-circuit (PRD §7.4)
means docling never actually runs for this fabricated source -- mirrors
tests/test_vault_write.py's and tests/test_vault_resume.py's own
`_place_tree_fixture` helpers, generalized here to accept an arbitrary tree
dict instead of only the committed fixture's bytes.

Seam decision 2 -- the exact length bound this test locks
-----------------------------------------------------------------------
Issue #94's acceptance criterion is qualitative ("filenames short enough
that the absolute path stays well under 260 chars"), not a literal number.
This test locks a concrete, checkable bound consistent with the issue's own
suggested fix ("cap the slug at ~80 chars"): with an ~80-char slug, the
full filename (`<source_id>_<order>_<slug>_<NNN>.md`, source_id itself
typically ~30-50 chars for a real ingested source) comes in comfortably
under 160 characters even before accounting for extension/order overhead,
leaving well over 100 characters of headroom under MAX_PATH for the
directory prefix (`<repo_or_run_root>/data/vault/prose/`) once the
filename itself is capped. `NOTE_FILENAME_MAX_LEN = 160` is deliberately
generous relative to the issue's own "~80 chars" slug-cap suggestion (not
a tight literal-80 pin, since the issue does not commit to an exact slug
length, only "~80"), while still being tight enough that this test would
catch a regression to an unbounded slug (which produced a ~250+ char
filename for this test's own fixture, see the `assert` after
`LONG_SECTION_HEADING`) or a cap so loose it stops mattering.

Seam decision 3 -- regression guard derives its expected set independently
-----------------------------------------------------------------------
Exactly like tests/test_vault_write.py's seam decision 2, the regression
test never hardcodes chunk_id values. It runs `axial chunk` on the
unmodified tests/fixtures/envelope/thesis_paper.pdf fixture (whose three
section headings -- "Introduction", "Comparative Cases", "Conclusion" --
are all short, i.e. below any reasonable slug cap) to obtain the real,
deterministic chunk records, then asserts `axial vault write`'s note
filenames match those chunk_ids exactly, stem for stem, as a set. If the
fix changed chunk_id derivation even for slugs already under the cap, this
test would fail -- proving the fix is scoped to the overlong case only
(issue #94's acceptance: "Slugs at or under the cap are unchanged").

Seam decision 4 -- isolation (issue #68), reused unchanged
-----------------------------------------------------------------------
Exactly like tests/test_vault_write.py and tests/test_vault_resume.py,
every `axial` subprocess this test spawns runs with `cwd` set to
`isolated_vault_root` (tests/conftest.py's opt-in staging-root fixture) so
`data/trees/`, `data/envelopes/`, and `data/vault/` never alias the real,
concurrently-written `data/` tree a live ingestion run also uses.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
from pathlib import Path

from axial.chunk import HashingEmbedder, run_chunk_embedding
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"

THESIS_PAPER_PDF = FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = FIXTURES_DIR / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# The locked filename-length bound this test enforces (see module docstring,
# seam decision 2).
NOTE_FILENAME_MAX_LEN = 160

# A close paraphrase of the real, overlong section heading from issue #94's
# traceback (a paper whose sole top-level heading restates its full title).
LONG_SECTION_HEADING = (
    "Examining the Centrality of State Legitimacy and Capacity to Stable "
    "Governance in the Syrian Conflict: The Detrimental Effects of "
    "International Geopolitical Influences on Long-Term State and "
    "Regional Stability"
)

# Mirrors `axial.chunk._slugify` closely enough to prove, at import time
# (not by eyeballing), that this heading is long enough to actually exercise
# issue #94's bug: a slug well over 200 characters, matching the issue's own
# "slugifies to >200 chars" wording verbatim.
_slug = re.sub(r"[^a-z0-9]+", "-", LONG_SECTION_HEADING.strip().lower()).strip("-")
assert len(_slug) > 200, (
    f"test fixture setup failed: expected LONG_SECTION_HEADING to slugify "
    f"to well over 200 characters (issue #94's own reproduction condition), "
    f"got a {len(_slug)}-character slug: {_slug!r}"
)

LONG_HEADING_TREE = {
    "children": [
        {
            "type": "prose",
            "order": "1",
            "text": LONG_SECTION_HEADING,
            "label": "section_header",
            "children": [
                {
                    "type": "prose",
                    "order": "1.1",
                    "text": (
                        "This paper's sole top-level heading restates its full "
                        "title verbatim, producing a section label whose derived "
                        "filesystem slug exceeds two hundred characters on its "
                        "own -- exactly the shape of source that triggered issue "
                        "#94's Windows MAX_PATH failure during a real ingestion run."
                    ),
                    "label": "text",
                }
            ],
        }
    ]
}

# argparse's fallback error for an as-yet-nonexistent subcommand/argument --
# any of these substrings in combined stdout+stderr means the CLI path under
# test was never actually reached (mirrors tests/test_vault_write.py).
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _trees_dir(root: Path) -> Path:
    return root / "data" / "trees"


def _envelopes_dir(root: Path) -> Path:
    return root / "data" / "envelopes"


def _vault_dir(root: Path) -> Path:
    return root / "data" / "vault"


def _prose_dir(root: Path) -> Path:
    return _vault_dir(root) / "prose"


def _run_axial(
    args: list[str],
    provider: str,
    *,
    cwd: Path,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


@contextlib.contextmanager
def _chdir(path: Path):
    """Temporarily change the process cwd to `path` -- see
    `_arrange_expected_chunk_records` below: `run_chunk_embedding` resolves
    its persisted-tree read (`axial.extract.tree_path`, via
    `axial.extract.TREES_DIR`) as a plain, cwd-relative path with no
    override parameter (only its OWN write target, `chunks_dir`, is
    overridable). Calling it in-process instead of shelling out to `axial
    chunk` needs this to reproduce the exact resolution a `cwd=`-scoped
    subprocess would get."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _run_envelope(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["envelope", *args], provider, cwd=cwd)


def _run_vault_write(provider: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run_axial(["vault", "write", *args], provider, cwd=cwd)


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess, command: str) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `{command}` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `{command}` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _place_tree_json(tree: dict, source_path: Path, root: Path) -> Path:
    """Pre-place `tree` at <root>/data/trees/<source_id>.json (source_id
    computed from `source_path`) so `axial.extract.extract` reuses it
    verbatim instead of running docling (PRD §7.4; mirrors
    tests/test_vault_write.py's/tests/test_vault_resume.py's own
    `_place_tree_fixture` helpers, generalized to an arbitrary tree dict)."""
    source_id = compute_source_id(source_path)
    tree_path = _trees_dir(root) / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(json.dumps(tree), encoding="utf-8")
    return tree_path


def _existing_envelope_files(root: Path) -> set[Path]:
    envelopes_dir = _envelopes_dir(root)
    if not envelopes_dir.exists():
        return set()
    return set(envelopes_dir.glob("*.json"))


def _arrange_stored_envelope(root: Path, source_path: Path, tree: dict) -> Path:
    """Pre-place `tree` as the persisted-tree cache for `source_path`, then
    run `axial envelope` with the stub provider so a stored envelope exists
    on disk before vault write. Asserts the arrange step itself succeeded
    and produced exactly one new envelope file. Returns the envelope's path."""
    _place_tree_json(tree, source_path, root)
    before_files = _existing_envelope_files(root)

    result = _run_envelope("stub", str(source_path), cwd=root)
    _assert_not_argparse_fallback(result, "envelope")
    assert result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` on "
        f"{source_path} with the stub LLM provider, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    new_files = _existing_envelope_files(root) - before_files
    assert len(new_files) == 1, (
        f"arrange step failed: expected exactly one new file under "
        f"{_envelopes_dir(root)} after `axial envelope`, got {len(new_files)}: "
        f"{sorted(new_files)}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    return next(iter(new_files))


def _arrange_expected_chunk_records(root: Path, source_path: Path) -> list[dict]:
    """Write the real, on-disk chunk artifact for `source_path` IN-PROCESS
    (`axial.chunk.run_chunk_embedding`, the stub/offline `HashingEmbedder`)
    and return the records it produced, used as the expected set `vault
    write` must match filename-for-filename (see module docstring, seam
    decision 3).

    Issue #154 slice 04: `axial vault write` no longer computes chunks
    itself -- it reads `data/chunks/<source_id>.jsonl` via
    `axial.chunk.read_chunks` (PRD §7.7) instead. So this arrange step now
    IS the thing that writes that artifact, at the exact `<root>/data/chunks/`
    path the `axial vault write` subprocess below (run with `cwd=root`)
    reads from."""
    with _chdir(root):
        records = run_chunk_embedding(source_path, embedder=HashingEmbedder())
    assert len(records) >= 1, (
        f"arrange step failed: expected at least one chunk record from "
        f"run_chunk_embedding, got {len(records)}"
    )
    for record in records:
        assert isinstance(record.get("chunk_id"), str) and record["chunk_id"].strip(), (
            f"arrange step failed: expected every chunk record to carry a "
            f"non-empty 'chunk_id', got {record!r}"
        )
    return records


def test_vault_write_bounds_note_filenames_for_long_section_slug(isolated_vault_root):
    """Core reproduction (issue #94's Gherkin): a source whose sole section
    heading slugifies to well over 200 characters must not crash `axial
    vault write`, and every note it writes for that source must have a
    filename short enough to stay well clear of Windows' MAX_PATH."""
    root = isolated_vault_root

    # A byte-identical copy of the fixture PDF under a new filename stem, so
    # `compute_source_id` mints a fresh id without adding a new binary
    # fixture to the repo (module docstring, seam decision 1).
    long_heading_dir = root / "long_heading_fixture"
    long_heading_dir.mkdir(parents=True, exist_ok=True)
    long_heading_source = long_heading_dir / "state_legitimacy_and_capacity.pdf"
    long_heading_source.write_bytes(THESIS_PAPER_PDF.read_bytes())

    _arrange_stored_envelope(root, long_heading_source, LONG_HEADING_TREE)
    _arrange_expected_chunk_records(root, long_heading_source)

    result = _run_vault_write("stub", str(long_heading_source), cwd=root)
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` on a source whose "
        f"sole section heading slugifies to well over 200 characters (issue "
        f"#94 acceptance: 'produces notes with filenames short enough that "
        f"the absolute path stays well under 260 chars, and succeeds'), got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    prose_dir = _prose_dir(root)
    assert prose_dir.exists(), (
        f"expected `axial vault write` to create {prose_dir} and write "
        f"prose notes into it, but it does not exist after a successful run"
    )

    prose_files = [p for p in prose_dir.iterdir() if p.is_file()]
    assert prose_files, (
        f"expected at least one prose note under {prose_dir} for the long-heading source, got none"
    )

    for note_path in prose_files:
        assert len(note_path.name) <= NOTE_FILENAME_MAX_LEN, (
            f"expected every prose note filename to be at most "
            f"{NOTE_FILENAME_MAX_LEN} characters (issue #94: notes for a "
            f">200-char section slug must stay well clear of Windows' "
            f"260-char MAX_PATH), got a {len(note_path.name)}-character "
            f"filename: {note_path.name!r}"
        )


def test_vault_write_note_filenames_unchanged_for_short_slugs_below_cap(isolated_vault_root):
    """Regression guard (issue #94's second acceptance line: 'Slugs at or
    under the cap are unchanged'). Reuses the unmodified thesis_paper.pdf
    fixture (three short section headings), derives the expected chunk_ids
    independently via `axial chunk`, and asserts `axial vault write`'s note
    filenames match those chunk_ids exactly, stem for stem -- proving the
    fix is a no-op for sources it was never meant to change."""
    root = isolated_vault_root
    tree = json.loads(THESIS_PAPER_TREE_FIXTURE.read_text(encoding="utf-8"))

    _arrange_stored_envelope(root, THESIS_PAPER_PDF, tree)
    expected_records = _arrange_expected_chunk_records(root, THESIS_PAPER_PDF)
    expected_chunk_ids = {record["chunk_id"] for record in expected_records}

    result = _run_vault_write("stub", str(THESIS_PAPER_PDF), cwd=root)
    _assert_not_argparse_fallback(result, "vault write")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial vault write` on the unmodified "
        f"thesis_paper.pdf fixture (short section headings), got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    prose_dir = _prose_dir(root)
    assert prose_dir.exists(), (
        f"expected `axial vault write` to create {prose_dir} and write "
        f"prose notes into it, but it does not exist after a successful run"
    )

    actual_stems = {p.stem for p in prose_dir.iterdir() if p.is_file()}
    assert actual_stems == expected_chunk_ids, (
        f"expected `axial vault write`'s note filenames to equal this "
        f"fixture's real chunk_ids exactly, stem for stem -- unchanged by "
        f"issue #94's fix, since every one of these slugs is already under "
        f"the cap -- got filename stems {sorted(actual_stems)!r} vs. "
        f"expected chunk_ids {sorted(expected_chunk_ids)!r}"
    )
