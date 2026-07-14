"""Outer acceptance test for issue #135 (P0-10, feat/eval slice 01: gold-set
scoring harness).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a returned label_sheet.xlsx under data/gold/labels/ whose four axis
      columns carry the Academic's labels
And   matching tagger chunk records under data/gold/chunks/ (some axes
      agreeing, some disagreeing, two schema tags never applied by either
      party)
When  the user runs `axial eval`
Then  it exits 0 and writes a scoring report under data/gold/labels/
And   the report gives per-axis raw agreement for field, empirical_scope,
      claim_type and theory_school computed only over Academic-labeled
      chunks (an empty Academic cell excludes that chunk/axis pair from the
      denominator)
And   the report gives per-tag application counts and names the schema tags
      that were never applied
And   the report lists each disagreeing chunk with its chunk_id, axis,
      tagger value and Academic value
And   with no returned sheet present under data/gold/labels/ it exits
      non-zero telling the operator to place the returned label_sheet.xlsx
      there
And   re-running is deterministic and makes no LLM call

See specs/PRODUCT.md §8 (P0-10), §10 (success metrics & eval), §6 (`eval/`
module), §7.5 (label sheet), §11 step 6. Plan: plans/eval/01-score-gold-set.md.
Issue: #135.

Arrange -- seed both sides of the join directly, no LLM
-----------------------------------------------------------------------
`axial eval` is offline by construction: it reads the tagger's own sampled
chunk records (already written by `axial gold sample`, #53) and the
Academic's returned answer key (already written by hand, off this pipeline
entirely, per §7.6's handoff). This test seeds both directly:
  - the tagger side: JSON chunk records under data/gold/chunks/ in the exact
    flat shape `axial gold sample` writes (`gold.RECORD_FIELDS`,
    `json.dumps(..., indent=2, sort_keys=True)`);
  - the Academic side: a workbook built with `gold.build_workbook` (the same
    function `axial gold sheet` uses), then the four axis cells overwritten
    per-row with the Academic's own labels -- some agreeing with the
    tagger, some disagreeing, and one chunk's `field`/`claim_type` cells
    left truly empty (an Academic non-answer, which must be excluded from
    that axis's agreement denominator rather than counted as either an
    agreement or a disagreement).

The two never-applied tags asserted below (`war-and-state` for claim_type,
`criminological` for theory_school) are picked so neither the tagger NOR the
Academic ever uses them across the fixture -- this is deliberate so the
assertion holds regardless of whether the implementer's "tag coverage" pass
counts tagger applications, Academic applications, or both; the test does
not lock that interpretation, only that a truly-unused schema tag is
surfaced by name.

Isolation -- the isolated staging root (issue #68)
-----------------------------------------------------------------------
Runs `axial eval` with `cwd` set to `isolated_vault_root`, which also copies
`config/domains/syria/{schema,codebook}.yaml` into the root so the default
domain dir (the tag-coverage vocabulary source) resolves under the staging
cwd. The real `data/` tree is never touched.

Report contract -- locked here, built to by the implementer
-----------------------------------------------------------------------
This test pins the scoring report to `data/gold/labels/eval_report.json`, a
machine-readable JSON document shaped:

    {
      "per_axis_agreement": {"field": 0.75, "empirical_scope": 0.8, ...},
      "tag_counts": {"field": {...}, "empirical_scope": {...}, ...},
      "never_applied": {"field": [...], ..., "claim_type": ["war-and-state", ...]},
      "disagreements": [
        {"chunk_id": "...", "axis": "...", "tagger": "...", "academic": "..."},
        ...
      ]
    }

This is the locked behavioral contract for this slice: the implementer
builds `src/axial/eval.py` to produce exactly this shape.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

from axial.gold import AXIS_COLUMNS, SHEET_COLUMNS, _axis_vocabularies, build_workbook

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CODEBOOK_PATH = REPO_ROOT / "config" / "domains" / "syria" / "codebook.yaml"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)

# Column index (1-based) of each axis column in the sheet, derived from the
# real SHEET_COLUMNS layout -- never hardcoded, so this test does not
# duplicate/lock the column ordering (tests/test_gold_sheet.py already does).
AXIS_COLUMN_INDEX = {
    name: idx + 1 for idx, name in enumerate(SHEET_COLUMNS) if name in AXIS_COLUMNS
}

# The tagger's own output, in the exact flat shape `axial gold sample`
# writes (gold.RECORD_FIELDS). Five chunks: c1 and c5 agree with the
# Academic on every axis; c2 and c3 each carry exactly one disagreement per
# axis (spread across all four axes between them); c4 carries an Academic
# non-answer on field and claim_type.
TAGGER_RECORDS = [
    {
        "chunk_id": "eval-fixture-c1",
        "source": "eval-fixture-source-a",
        "section": "Introduction",
        "chunk_text": "Synthetic prose about state formation for chunk one.",
        "field": "state",
        "empirical_scope": "scope:general",
        "role_in_argument": "role:claim",
        "claim_type": "state-formation",
        "theory_school": "bellicist",
    },
    {
        "chunk_id": "eval-fixture-c2",
        "source": "eval-fixture-source-a",
        "section": "Chapter One",
        "chunk_text": "Synthetic prose about civilian targeting for chunk two.",
        "field": "violence",
        "empirical_scope": "scope:country-case",
        "role_in_argument": "role:evidence",
        "claim_type": "civilian-targeting",
        "theory_school": "micro-sociological",
    },
    {
        "chunk_id": "eval-fixture-c3",
        "source": "eval-fixture-source-b",
        "section": "Analysis",
        "chunk_text": "Synthetic prose about ideology as system for chunk three.",
        "field": "ideology",
        "empirical_scope": "scope:comparative",
        "role_in_argument": "role:synthesis",
        "claim_type": "ideology-as-system",
        "theory_school": "discursive",
    },
    {
        "chunk_id": "eval-fixture-c4",
        "source": "eval-fixture-source-b",
        "section": "Findings",
        "chunk_text": "Synthetic prose about state capacity for chunk four.",
        "field": "state",
        "empirical_scope": "scope:general",
        "role_in_argument": "role:claim",
        "claim_type": "state-capacity",
        "theory_school": "bellicist",
    },
    {
        "chunk_id": "eval-fixture-c5",
        "source": "eval-fixture-source-c",
        "section": "Conclusion",
        "chunk_text": "Synthetic prose about violence logic for chunk five.",
        "field": "violence",
        "empirical_scope": "scope:sub-national",
        "role_in_argument": "role:evidence",
        "claim_type": "violence-logic",
        "theory_school": "institutionalist-state-centered",
    },
]

# The Academic's returned labels, per chunk. `None` means the Academic left
# the cell truly empty -- must be excluded from that axis's denominator, not
# counted as a disagreement.
ACADEMIC_LABELS = {
    "eval-fixture-c1": {
        "field": "state",
        "empirical_scope": "scope:general",
        "claim_type": "state-formation",
        "theory_school": "bellicist",
    },
    "eval-fixture-c2": {
        "field": "violence",
        "empirical_scope": "scope:regional",  # disagrees with tagger's scope:country-case
        "claim_type": "civilian-targeting",
        "theory_school": "structuralist",  # disagrees with tagger's micro-sociological
    },
    "eval-fixture-c3": {
        "field": "state",  # disagrees with tagger's ideology
        "empirical_scope": "scope:comparative",
        "claim_type": "ideology-as-practice",  # disagrees with tagger's ideology-as-system
        "theory_school": "discursive",
    },
    "eval-fixture-c4": {
        "field": None,  # Academic non-answer -- excluded from the field denominator
        "empirical_scope": "scope:general",
        "claim_type": None,  # Academic non-answer -- excluded from the claim_type denominator
        "theory_school": "bellicist",
    },
    "eval-fixture-c5": {
        "field": "violence",
        "empirical_scope": "scope:sub-national",
        "claim_type": "violence-logic",
        "theory_school": "institutionalist-state-centered",
    },
}

# Known-precise expected agreement fractions, hand-derived from the table
# above: field = 3/4 (c4 excluded), empirical_scope = 4/5, claim_type = 3/4
# (c4 excluded), theory_school = 4/5.
EXPECTED_AGREEMENT = {
    "field": 0.75,
    "empirical_scope": 0.8,
    "claim_type": 0.75,
    "theory_school": 0.8,
}

# Every mismatch in the table above, one per axis, spread across c2 and c3.
EXPECTED_DISAGREEMENTS = [
    {
        "chunk_id": "eval-fixture-c2",
        "axis": "empirical_scope",
        "tagger": "scope:country-case",
        "academic": "scope:regional",
    },
    {
        "chunk_id": "eval-fixture-c2",
        "axis": "theory_school",
        "tagger": "micro-sociological",
        "academic": "structuralist",
    },
    {
        "chunk_id": "eval-fixture-c3",
        "axis": "field",
        "tagger": "ideology",
        "academic": "state",
    },
    {
        "chunk_id": "eval-fixture-c3",
        "axis": "claim_type",
        "tagger": "ideology-as-system",
        "academic": "ideology-as-practice",
    },
]

# Real schema tags used by NEITHER the tagger NOR the Academic anywhere in
# the fixture above (verified against config/domains/syria/codebook.yaml).
NEVER_APPLIED_CLAIM_TYPE_TAG = "war-and-state"
NEVER_APPLIED_THEORY_SCHOOL_TAG = "criminological"


def _codebook_vocab(axis: str) -> set[str]:
    document = yaml.safe_load(CODEBOOK_PATH.read_text(encoding="utf-8"))
    return set(document["axes"][axis].keys())


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


def _seed_returned_sheet(root: Path) -> None:
    """Build the returned answer-key workbook with the real `gold.build_workbook`
    (the same function `axial gold sheet` uses), then overwrite each row's
    four axis cells with the Academic's labels (ACADEMIC_LABELS), including
    leaving some cells truly empty. Saved under data/gold/labels/ -- the
    Academic's return location (`gold.LABELS_RETURN_DIR`)."""
    domain_dir = REPO_ROOT / "config" / "domains" / "syria"
    vocabularies = _axis_vocabularies(domain_dir)

    # build_workbook pre-fills field/empirical_scope from the passed records
    # (the tagger's own guess) and leaves claim_type/theory_school blank
    # (blind axes) -- exactly what a freshly-generated, not-yet-labeled sheet
    # looks like.
    workbook = build_workbook(TAGGER_RECORDS, vocabularies)
    worksheet = workbook.worksheets[0]

    for row_index, record in enumerate(TAGGER_RECORDS, start=2):
        academic = ACADEMIC_LABELS[record["chunk_id"]]
        for axis, column in AXIS_COLUMN_INDEX.items():
            # openpyxl's `cell(..., value=None)` treats None as "leave
            # unset" rather than "clear" -- an explicit `.value =` write is
            # required to truly blank a cell (Academic non-answer).
            worksheet.cell(row=row_index, column=column).value = academic[axis]

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


def test_eval_scores_returned_labels_against_tagger_output(isolated_vault_root):
    root = isolated_vault_root
    _seed_chunk_records(root)
    _seed_returned_sheet(root)

    # Sanity-check the never-applied tags really are real schema vocabulary
    # (protects this test against codebook drift silently making the
    # assertion meaningless).
    claim_type_vocab = _codebook_vocab("claim_type")
    theory_school_vocab = _codebook_vocab("theory_school")
    assert NEVER_APPLIED_CLAIM_TYPE_TAG in claim_type_vocab
    assert NEVER_APPLIED_THEORY_SCHOOL_TAG in theory_school_vocab

    result = _run_eval(root)
    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial eval` on a seeded returned sheet + "
        f"chunk records, got {result.returncode}\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    report = _load_report(root)

    # Per-axis raw agreement, computed only over Academic-labeled chunks.
    assert "per_axis_agreement" in report, (
        f"expected the report to carry a 'per_axis_agreement' key, got keys {sorted(report)}"
    )
    agreement = report["per_axis_agreement"]
    for axis, expected_fraction in EXPECTED_AGREEMENT.items():
        assert axis in agreement, (
            f"expected per_axis_agreement to report the {axis!r} axis, got keys {sorted(agreement)}"
        )
        actual = agreement[axis]
        assert actual == expected_fraction or abs(actual - expected_fraction) < 1e-9, (
            f"expected {axis!r} raw agreement to be {expected_fraction} "
            f"(hand-derived from the seeded fixture: some axes agree, some "
            f"disagree, one Academic cell is empty and excluded), got "
            f"{actual!r}"
        )

    # Tag coverage: names the never-applied schema tags.
    assert "never_applied" in report, (
        f"expected the report to carry a 'never_applied' key surfacing "
        f"schema tags no chunk ever used, got keys {sorted(report)}"
    )
    never_applied = report["never_applied"]
    assert NEVER_APPLIED_CLAIM_TYPE_TAG in never_applied.get("claim_type", []), (
        f"expected the never-applied claim_type tag {NEVER_APPLIED_CLAIM_TYPE_TAG!r} "
        f"(used by neither the tagger nor the Academic in this fixture) to "
        f"be named in never_applied['claim_type'], got "
        f"{never_applied.get('claim_type')!r}"
    )
    assert NEVER_APPLIED_THEORY_SCHOOL_TAG in never_applied.get("theory_school", []), (
        f"expected the never-applied theory_school tag "
        f"{NEVER_APPLIED_THEORY_SCHOOL_TAG!r} (used by neither the tagger "
        f"nor the Academic in this fixture) to be named in "
        f"never_applied['theory_school'], got "
        f"{never_applied.get('theory_school')!r}"
    )

    # Tag coverage: per-tag application counts are reported at all (the
    # exact counting convention -- tagger-only, Academic-only, or combined --
    # is an implementation choice this outer test does not lock).
    assert "tag_counts" in report, (
        f"expected the report to carry a 'tag_counts' key with per-tag "
        f"application counts, got keys {sorted(report)}"
    )

    # Disagreements: exactly the seeded mismatches, each naming chunk_id,
    # axis, tagger value and Academic value.
    assert "disagreements" in report, (
        f"expected the report to carry a 'disagreements' key, got keys {sorted(report)}"
    )
    disagreements = report["disagreements"]

    def _row_key(row: dict) -> tuple:
        return (row.get("chunk_id"), row.get("axis"), row.get("tagger"), row.get("academic"))

    actual_rows = {_row_key(row) for row in disagreements}
    expected_rows = {_row_key(row) for row in EXPECTED_DISAGREEMENTS}
    assert expected_rows <= actual_rows, (
        f"expected every seeded disagreement {expected_rows} to appear as a "
        f"disagreement row (chunk_id, axis, tagger, academic), got rows "
        f"{actual_rows} -- missing {expected_rows - actual_rows}"
    )
    # No agreement pair is misreported as a disagreement.
    agreeing_pairs = {
        (record["chunk_id"], axis)
        for record in TAGGER_RECORDS
        for axis in ("field", "empirical_scope", "claim_type", "theory_school")
        if (record["chunk_id"], axis)
        not in {(row["chunk_id"], row["axis"]) for row in EXPECTED_DISAGREEMENTS}
        and ACADEMIC_LABELS[record["chunk_id"]][axis] is not None
    }
    reported_pairs = {(row.get("chunk_id"), row.get("axis")) for row in disagreements}
    bogus = reported_pairs & agreeing_pairs
    assert not bogus, (
        f"expected no chunk/axis pair that actually agrees to be reported "
        f"as a disagreement, but found {bogus} in the report's disagreements"
    )

    # Determinism: re-running produces an identical report and still makes
    # no LLM call (the same exploding-provider env is reused by _run_eval).
    second = _run_eval(root)
    _assert_not_argparse_fallback(second)
    assert second.returncode == 0, (
        f"expected exit code 0 for the second (re-run) `axial eval`, got "
        f"{second.returncode}\nstdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    )
    second_report = _load_report(root)
    assert second_report == report, (
        "expected re-running `axial eval` to reproduce an identical scoring "
        "report (Gherkin: deterministic re-run), but the report changed "
        f"between runs.\nfirst:  {report!r}\nsecond: {second_report!r}"
    )


def test_eval_without_returned_sheet_fails_clearly(isolated_vault_root):
    root = isolated_vault_root
    _seed_chunk_records(root)
    # Deliberately no label_sheet.xlsx under data/gold/labels/.

    result = _run_eval(root)
    _assert_not_argparse_fallback(result)

    assert result.returncode != 0, (
        f"expected a non-zero exit code for `axial eval` with no returned "
        f"sheet under data/gold/labels/, got 0\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "data/gold/labels" in combined or "data\\gold\\labels" in combined, (
        f"expected the error message to name data/gold/labels/ (where the "
        f"operator must place the returned label_sheet.xlsx), got stdout: "
        f"{result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert not _report_path(root).is_file(), (
        "expected no scoring report to be written when the returned sheet is missing"
    )
