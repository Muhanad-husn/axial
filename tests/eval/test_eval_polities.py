"""Outer acceptance test for issue #215 (score `polities_touched` in the eval
harness -- a free-text, many-valued facet).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a returned label_sheet.xlsx under data/gold/labels/ whose
      `polities_touched` cells carry the Academic's corrected polity lists
      (semicolon-separated free text, per gold.build_workbook), including
      one row where the Academic's list agrees exactly, one with an extra
      tagger polity, one with a missing tagger polity, one where the
      tagger's and Academic's surface strings differ but both resolve to
      the SAME node in the shipped #205 canonical alias map (`USSR` vs
      `Soviet Union`), and one where BOTH sides list no polity at all
And   matching tagger chunk records under data/gold/chunks/ carrying each
      chunk's own `polities_touched` list
And   the real, shipped #205 canonical polity map
      (config/domains/syria/polity_canonical.yaml) staged under the
      isolated root's domain dir
When  the user runs `axial eval`
Then  it exits 0 and the scoring report carries a `per_polity_score`
      section computed as SET-based per-chunk precision/recall/F1 over the
      tagger's vs. the Academic's polity lists
And   both lists are folded through the canonical alias map before
      comparison, so `USSR` (tagger) and `Soviet Union` (Academic) count as
      the SAME polity -- a true positive, not a false-positive-plus-
      false-negative
And   the pooled TP/FP/FN across every chunk (micro) yields the report's
      `per_polity_score.micro` precision/recall/f1
And   the mean of each chunk's own per-chunk F1 (macro) yields
      `per_polity_score.macro_f1`
And   a chunk where BOTH sides list no polity counts as a perfect
      per-chunk match (f1 == 1.0), is counted in
      `per_polity_score.both_empty_matches`, and contributes nothing to the
      pooled micro TP/FP/FN
And   `per_polity_score.per_chunk` carries one row per chunk naming at
      least its `chunk_id` and per-chunk `f1`
And   re-running is deterministic and reproduces an identical
      `per_polity_score` section

See specs/PRODUCT.md §6 (`polities_touched` Appendix C/G facet), §7.5 (the
label sheet's pre-labeled free-text `polities_touched` column), §11 step 7
(the #205 canonical map). Issue: #215. Builds on the #135 eval harness
(tests/eval/test_eval.py, src/axial/eval.py) and the #205 canonical map
(src/axial/polity_canonical.py).

Arrange -- same offline seam as #135, plus the canonical map
-----------------------------------------------------------------------
`axial eval` is offline by construction (see tests/eval/test_eval.py's own
module docstring for the full explanation of why): this test seeds the
tagger side directly as JSON chunk records under data/gold/chunks/
(`gold.RECORD_FIELDS`) and the Academic side as a workbook built with the
real `gold.build_workbook`, then overwrites each row's `polities_touched`
cell with the Academic's corrected value. On top of #135's seam, this test
ALSO stages the real, shipped `config/domains/syria/polity_canonical.yaml`
under the isolated root's domain dir -- `isolated_vault_root`
(tests/conftest.py) copies only schema.yaml/codebook.yaml, not the
canonical map, so it is staged separately here (mirrors
tests/ingestion/test_polity_canonical_map.py's own `_stage_domain_files` +
explicit canonical-map write pattern). Using the REAL shipped map (not a
synthetic stand-in) is deliberate: it proves the alias fold this test
locks actually exercises the shipped USSR -> Soviet Union cluster, not a
test-only fixture that could drift from what ships.

Fixture -- five chunks, one per set-comparison case (hand-derived numbers)
-----------------------------------------------------------------------
    chunk | tagger list      | academic list     | tp | fp | fn | f1
    p1    | [Syria, Iraq]    | [Syria, Iraq]      | 2  | 0  | 0  | 1.0
    p2    | [Syria, Lebanon] | [Syria]            | 1  | 1  | 0  | 2/3
    p3    | [Iraq]           | [Iraq, Turkey]     | 1  | 0  | 1  | 2/3
    p4    | [USSR]           | [Soviet Union]     | 1  | 0  | 0  | 1.0  (alias fold)
    p5    | []               | []                 | 0  | 0  | 0  | 1.0  (both-empty)

Every polity name above (Syria, Iraq, Lebanon, Turkey, Soviet Union) is a
real, alias-free standalone node in the shipped canonical map, verified
directly against config/domains/syria/polity_canonical.yaml -- so p1-p3's
tp/fp/fn hold whether or not the alias fold is even applied; only p4
actually exercises it (`USSR` only resolves to the same node as
`Soviet Union` via the map's own shipped alias, per module docstring of
axial.polity_canonical: "Soviet Union ... aliases: [USSR]").

Derived aggregates (re-derive by hand if this fixture ever changes):
  - Pooled micro TP=5, FP=1, FN=1 (p5 contributes nothing to the pool) ->
    micro precision = 5/6, recall = 5/6, f1 = 5/6.
  - macro_f1 = mean(1.0, 2/3, 2/3, 1.0, 1.0) = 13/15 (~0.866666667).
  - both_empty_matches = 1 (p5 only).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from axial.gold import SHEET_COLUMNS, _axis_vocabularies, build_workbook

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"
_DOMAIN_DIR_PARTS = ("config", "domains", "syria")

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# argparse's fallback error for an as-yet-nonexistent subcommand/flag -- any
# of these substrings in the combined output means the target subcommand's
# logic was never actually exercised (mirrors tests/eval/test_eval.py and
# every other CLI-subprocess acceptance test in this repo).
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)

# The polities column's 1-based sheet index, derived from the real
# SHEET_COLUMNS layout -- never hardcoded, so this test does not duplicate/
# lock the column ordering (tests/test_gold_sheet.py already does that).
POLITIES_COLUMN_INDEX = SHEET_COLUMNS.index("polities_touched") + 1

# Shared axis values across every fixture chunk -- deliberately all
# agreeing (this slice scores `polities_touched` only; the four-axis
# agreement math is #135's contract, not this test's). Every value below is
# real schema vocabulary already exercised by tests/eval/test_eval.py.
_SHARED_FIELD = "state"
_SHARED_SCOPE = "scope:general"
_SHARED_ROLE = "role:evidence"
_SHARED_CLAIM_TYPE = "state-formation"
_SHARED_THEORY_SCHOOL = "bellicist"

# The tagger's own output, in the exact flat shape `axial gold sample`
# writes (gold.RECORD_FIELDS). One chunk per set-comparison case -- see
# module docstring's fixture table for the hand-derived tp/fp/fn/f1.
TAGGER_RECORDS = [
    {
        "chunk_id": "eval-polities-fixture-p1",
        "source": "eval-polities-fixture-source-a",
        "section": "Introduction",
        "chunk_text": "Synthetic prose about interstate diplomacy for chunk p1.",
        "field": _SHARED_FIELD,
        "empirical_scope": _SHARED_SCOPE,
        "polities_touched": ["Syria", "Iraq"],
        "role_in_argument": _SHARED_ROLE,
        "claim_type": _SHARED_CLAIM_TYPE,
        "theory_school": _SHARED_THEORY_SCHOOL,
    },
    {
        "chunk_id": "eval-polities-fixture-p2",
        "source": "eval-polities-fixture-source-a",
        "section": "Chapter One",
        "chunk_text": "Synthetic prose about cross-border alliance for chunk p2.",
        "field": _SHARED_FIELD,
        "empirical_scope": _SHARED_SCOPE,
        "polities_touched": ["Syria", "Lebanon"],
        "role_in_argument": _SHARED_ROLE,
        "claim_type": _SHARED_CLAIM_TYPE,
        "theory_school": _SHARED_THEORY_SCHOOL,
    },
    {
        "chunk_id": "eval-polities-fixture-p3",
        "source": "eval-polities-fixture-source-b",
        "section": "Analysis",
        "chunk_text": "Synthetic prose about border contestation for chunk p3.",
        "field": _SHARED_FIELD,
        "empirical_scope": _SHARED_SCOPE,
        "polities_touched": ["Iraq"],
        "role_in_argument": _SHARED_ROLE,
        "claim_type": _SHARED_CLAIM_TYPE,
        "theory_school": _SHARED_THEORY_SCHOOL,
    },
    {
        "chunk_id": "eval-polities-fixture-p4",
        "source": "eval-polities-fixture-source-b",
        "section": "Findings",
        "chunk_text": "Synthetic prose about Cold War-era state capacity for chunk p4.",
        "field": _SHARED_FIELD,
        "empirical_scope": _SHARED_SCOPE,
        "polities_touched": ["USSR"],
        "role_in_argument": _SHARED_ROLE,
        "claim_type": _SHARED_CLAIM_TYPE,
        "theory_school": _SHARED_THEORY_SCHOOL,
    },
    {
        "chunk_id": "eval-polities-fixture-p5",
        "source": "eval-polities-fixture-source-c",
        "section": "Conclusion",
        "chunk_text": "Synthetic prose about general theory with no named polity for chunk p5.",
        "field": _SHARED_FIELD,
        "empirical_scope": _SHARED_SCOPE,
        "polities_touched": [],
        "role_in_argument": _SHARED_ROLE,
        "claim_type": _SHARED_CLAIM_TYPE,
        "theory_school": _SHARED_THEORY_SCHOOL,
    },
]

# The Academic's returned `polities_touched` correction, per chunk -- an
# empty list means the Academic left the cell truly empty (agrees with "no
# engaged polity", per gold.py's Academic-facing README:
# "An empty cell means the tagger found no engaged polity -- leave it empty
# if that's correct.").
ACADEMIC_POLITIES = {
    "eval-polities-fixture-p1": ["Syria", "Iraq"],
    "eval-polities-fixture-p2": ["Syria"],
    "eval-polities-fixture-p3": ["Iraq", "Turkey"],
    "eval-polities-fixture-p4": ["Soviet Union"],
    "eval-polities-fixture-p5": [],
}

# Hand-derived per-chunk tp/fp/fn/f1 -- see module docstring's fixture table.
EXPECTED_PER_CHUNK = {
    "eval-polities-fixture-p1": {"tp": 2, "fp": 0, "fn": 0, "f1": 1.0},
    "eval-polities-fixture-p2": {"tp": 1, "fp": 1, "fn": 0, "f1": 2 / 3},
    "eval-polities-fixture-p3": {"tp": 1, "fp": 0, "fn": 1, "f1": 2 / 3},
    "eval-polities-fixture-p4": {"tp": 1, "fp": 0, "fn": 0, "f1": 1.0},
    "eval-polities-fixture-p5": {"tp": 0, "fp": 0, "fn": 0, "f1": 1.0},
}

# Pooled across every chunk (p5 contributes nothing -- both-empty is
# reported separately, never folded into the pooled TP/FP/FN).
EXPECTED_MICRO_TP = 5
EXPECTED_MICRO_FP = 1
EXPECTED_MICRO_FN = 1
EXPECTED_MICRO_PRECISION = 5 / 6
EXPECTED_MICRO_RECALL = 5 / 6
EXPECTED_MICRO_F1 = 5 / 6

# mean(1.0, 2/3, 2/3, 1.0, 1.0) == 13/15.
EXPECTED_MACRO_F1 = 13 / 15

EXPECTED_BOTH_EMPTY_MATCHES = 1

_FLOAT_TOLERANCE = 1e-9


def _gold_dir(root: Path) -> Path:
    return root / "data" / "gold"


def _chunks_dir(root: Path) -> Path:
    return _gold_dir(root) / "chunks"


def _labels_dir(root: Path) -> Path:
    return _gold_dir(root) / "labels"


def _sheet_path(root: Path) -> Path:
    return _labels_dir(root) / "label_sheet.xlsx"


def _report_path(root: Path) -> Path:
    return _labels_dir(root) / "eval_report.json"


def _seed_chunk_records(root: Path) -> None:
    chunks_dir = _chunks_dir(root)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    for record in TAGGER_RECORDS:
        (chunks_dir / f"{record['chunk_id']}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
        )


def _seed_real_polity_canonical_map(root: Path) -> None:
    """Copy the REAL shipped canonical map (issue #205,
    config/domains/syria/polity_canonical.yaml) into the isolated root's
    domain dir. `isolated_vault_root` (tests/conftest.py) only copies
    schema.yaml/codebook.yaml, not the canonical map, so it is staged here
    separately (mirrors tests/ingestion/test_polity_canonical_map.py's own
    `_stage_domain_files` + explicit canonical-map write pattern). The real
    map is used deliberately, not a synthetic fixture -- see module
    docstring."""
    domain_dir = root.joinpath(*_DOMAIN_DIR_PARTS)
    domain_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        DOMAIN_DIR / "polity_canonical.yaml",
        domain_dir / "polity_canonical.yaml",
    )


def _seed_returned_sheet(root: Path) -> None:
    """Build the returned answer-key workbook with the real
    `gold.build_workbook` (the same function `axial gold sheet` uses), then
    overwrite each row's `polities_touched` cell with the Academic's
    corrected list (ACADEMIC_POLITIES), joined the same way the sheet
    itself joins it ("; "-separated) -- or explicitly blanked for a
    both-empty chunk (openpyxl's `cell(..., value=None)` kwarg leaves a
    cell unset rather than clearing it; an explicit `.value =` write, as
    below, is required to truly blank it -- mirrors
    tests/eval/test_eval.py's own axis-cell blanking)."""
    vocabularies = _axis_vocabularies(DOMAIN_DIR)
    workbook = build_workbook(TAGGER_RECORDS, vocabularies)
    worksheet = workbook.worksheets[0]

    for row_index, record in enumerate(TAGGER_RECORDS, start=2):
        academic_list = ACADEMIC_POLITIES[record["chunk_id"]]
        cell = worksheet.cell(row=row_index, column=POLITIES_COLUMN_INDEX)
        cell.value = "; ".join(academic_list) if academic_list else None

    labels_dir = _labels_dir(root)
    labels_dir.mkdir(parents=True, exist_ok=True)
    workbook.save(_sheet_path(root))


def _run_eval(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"  # any run that reaches an LLM is a bug
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", "eval", *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `eval` behavior path, not an argparse fallback "
            f"(found {marker!r}) -- the `axial eval` subcommand does not "
            f"exist yet or was never reached:\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


def _load_report(root: Path) -> dict:
    report_path = _report_path(root)
    assert report_path.is_file(), (
        f"expected `axial eval` to write a scoring report to {report_path}, but it does not exist"
    )
    return json.loads(report_path.read_text(encoding="utf-8"))


def _assert_close(actual: float, expected: float, label: str) -> None:
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"expected {label} to be numeric, got {actual!r}"
    )
    assert abs(actual - expected) < _FLOAT_TOLERANCE, (
        f"expected {label} to be {expected}, got {actual!r}"
    )


def _assert_per_polity_score(report: dict) -> None:
    assert "per_polity_score" in report, (
        f"expected the report to carry a 'per_polity_score' key scoring the "
        f"many-valued polities_touched facet (set-based per-chunk "
        f"precision/recall/F1, micro + macro aggregation, #215), got keys "
        f"{sorted(report)}"
    )
    section = report["per_polity_score"]

    assert "micro" in section, (
        f"expected per_polity_score to carry a 'micro' key (pooled "
        f"TP/FP/FN precision/recall/f1 across every chunk), got keys "
        f"{sorted(section)}"
    )
    micro = section["micro"]
    for key, expected in (
        ("precision", EXPECTED_MICRO_PRECISION),
        ("recall", EXPECTED_MICRO_RECALL),
        ("f1", EXPECTED_MICRO_F1),
    ):
        assert key in micro, (
            f"expected per_polity_score.micro to carry {key!r}, got keys {sorted(micro)}"
        )
        _assert_close(micro[key], expected, f"per_polity_score.micro.{key}")

    assert "macro_f1" in section, (
        f"expected per_polity_score to carry a 'macro_f1' key (mean of "
        f"each chunk's own per-chunk F1), got keys {sorted(section)}"
    )
    _assert_close(section["macro_f1"], EXPECTED_MACRO_F1, "per_polity_score.macro_f1")

    assert "both_empty_matches" in section, (
        f"expected per_polity_score to carry a 'both_empty_matches' count "
        f"(chunks where both the tagger and the Academic list no polity, "
        f"surfaced rather than silently dropped), got keys {sorted(section)}"
    )
    assert section["both_empty_matches"] == EXPECTED_BOTH_EMPTY_MATCHES, (
        f"expected per_polity_score.both_empty_matches to be "
        f"{EXPECTED_BOTH_EMPTY_MATCHES} (only chunk p5 has both sides "
        f"empty), got {section['both_empty_matches']!r}"
    )

    assert "per_chunk" in section, (
        f"expected per_polity_score to carry a 'per_chunk' key listing one "
        f"scoring row per chunk, got keys {sorted(section)}"
    )
    per_chunk_rows = {
        row["chunk_id"]: row
        for row in section["per_chunk"]
        if isinstance(row, dict) and "chunk_id" in row
    }
    assert set(per_chunk_rows) >= set(EXPECTED_PER_CHUNK), (
        f"expected per_polity_score.per_chunk to carry a row for every "
        f"seeded chunk {sorted(EXPECTED_PER_CHUNK)}, got chunk_ids "
        f"{sorted(per_chunk_rows)}"
    )
    for chunk_id, expected_row in EXPECTED_PER_CHUNK.items():
        row = per_chunk_rows[chunk_id]
        assert "f1" in row, (
            f"expected per_chunk row {chunk_id!r} to carry an 'f1' key, got keys {sorted(row)}"
        )
        _assert_close(row["f1"], expected_row["f1"], f"per_chunk[{chunk_id!r}].f1")


def test_eval_scores_polities_touched_as_set_based_metric(isolated_vault_root):
    root = isolated_vault_root
    _seed_chunk_records(root)
    _seed_real_polity_canonical_map(root)
    _seed_returned_sheet(root)

    result = _run_eval(root)
    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial eval` on a seeded returned sheet + "
        f"chunk records + the real #205 canonical map, got {result.returncode}"
        f"\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    report = _load_report(root)
    _assert_per_polity_score(report)

    # Determinism: re-running reproduces an identical per_polity_score
    # section and still makes no LLM call (the same exploding-provider env
    # is reused by _run_eval). #135's own outer test already locks
    # whole-report determinism; this is a lighter, section-scoped re-assert.
    second = _run_eval(root)
    _assert_not_argparse_fallback(second)
    assert second.returncode == 0, (
        f"expected exit code 0 for the second (re-run) `axial eval`, got "
        f"{second.returncode}\nstdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    )
    second_report = _load_report(root)
    assert second_report.get("per_polity_score") == report.get("per_polity_score"), (
        "expected re-running `axial eval` to reproduce an identical "
        "per_polity_score section, but it changed between runs.\n"
        f"first:  {report.get('per_polity_score')!r}\n"
        f"second: {second_report.get('per_polity_score')!r}"
    )
