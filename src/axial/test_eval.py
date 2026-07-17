"""Inner unit tests for the gold-set scoring harness (src/axial/eval.py,
issue #135; polities_touched set-based scoring, issue #215).

The outer acceptance test (tests/test_eval.py) drives `axial eval` end to
end through a subprocess and pins the exact report shape/values for one
hand-derived fixture. These unit tests exercise the pieces underneath it in
isolation: cell normalization, the workbook reader, the join/aggregation
logic (agreement denominators, both-sides tag counting, disagreement
ordering) and the two typed errors -- including edge cases the outer
fixture doesn't need to cover (an axis with zero Academic answers, a
whitespace-only "empty" cell, a chunk in the tagger output the sheet never
mentions). Also #215's `polities_touched` free-text cell parsing, canonical
alias folding (including the graceful-degradation fallback when the #205
map is absent), and set-based per-chunk/micro/macro scoring.
"""

from __future__ import annotations

import json

import pytest

from axial.eval import (
    EvalError,
    MissingChunksError,
    MissingReturnedSheetError,
    _build_polity_score,
    _build_report,
    _fold_polity_set,
    _load_academic_labels,
    _load_academic_polities,
    _load_polity_canonical_or_none,
    _normalize_cell,
    _parse_polities_cell,
    _polity_fold_key,
    _score_polity_chunk,
    _warn_unmatched,
    run_eval,
)
from axial.gold import AXIS_COLUMNS, SHEET_COLUMNS, build_workbook
from axial.polity_canonical import load_polity_canonical


def _record(
    chunk_id, field="state", scope="scope:general", claim="state-formation", school="bellicist"
):
    return {
        "chunk_id": chunk_id,
        "source": "src-a",
        "section": "Body",
        "chunk_text": f"text {chunk_id}",
        "field": field,
        "empirical_scope": scope,
        "role_in_argument": "role:claim",
        "claim_type": claim,
        "theory_school": school,
    }


class TestNormalizeCell:
    def test_none_is_none(self):
        assert _normalize_cell(None) is None

    def test_empty_string_is_none(self):
        assert _normalize_cell("") is None

    def test_whitespace_only_is_none(self):
        assert _normalize_cell("   ") is None

    def test_value_is_stripped(self):
        assert _normalize_cell("  state  ") == "state"

    def test_non_string_value_is_stringified(self):
        assert _normalize_cell(42) == "42"


class TestMissingReturnedSheetError:
    def test_is_eval_error(self):
        assert issubclass(MissingReturnedSheetError, EvalError)

    def test_message_names_labels_dir(self, tmp_path):

        sheet_path = tmp_path / "data" / "gold" / "labels" / "label_sheet.xlsx"
        error = MissingReturnedSheetError(sheet_path)
        assert "data/gold/labels/" in str(error)
        assert error.sheet_path == sheet_path


class TestBuildReport:
    def test_agreement_excludes_empty_academic_cells(self):
        tagger_records = [_record("c1", field="state"), _record("c2", field="violence")]
        academic = {
            "c1": {
                "field": "state",
                "empirical_scope": None,
                "claim_type": None,
                "theory_school": None,
            },
            "c2": {
                "field": None,
                "empirical_scope": None,
                "claim_type": None,
                "theory_school": None,
            },
        }
        vocabularies = {axis: [] for axis in AXIS_COLUMNS}

        report = _build_report(tagger_records, academic, vocabularies)

        # Only c1 answered `field`; it agrees -> 1/1.
        assert report["per_axis_agreement"]["field"] == 1.0
        # No chunk answered the other three axes -> zero denominator -> 0.0,
        # never a divide-by-zero crash.
        assert report["per_axis_agreement"]["empirical_scope"] == 0.0
        assert report["per_axis_agreement"]["claim_type"] == 0.0
        assert report["per_axis_agreement"]["theory_school"] == 0.0
        assert report["disagreements"] == []

    def test_disagreement_rows_and_no_false_positives(self):
        tagger_records = [_record("c1", field="state")]
        academic = {
            "c1": {
                "field": "violence",
                "empirical_scope": "scope:general",
                "claim_type": "state-formation",
                "theory_school": "bellicist",
            },
        }
        # `field`'s mismatched Academic value ("violence") must be in-vocab
        # here so this test exercises a plain disagreement, not the
        # out-of-vocab addition-candidate path (covered separately below).
        vocabularies = {axis: [] for axis in AXIS_COLUMNS}
        vocabularies["field"] = ["state", "violence"]

        report = _build_report(tagger_records, academic, vocabularies)

        assert report["disagreements"] == [
            {"chunk_id": "c1", "axis": "field", "tagger": "state", "academic": "violence"}
        ]
        # The three agreeing axes must not leak into disagreements.
        reported_axes = {row["axis"] for row in report["disagreements"]}
        assert "empirical_scope" not in reported_axes
        assert "claim_type" not in reported_axes
        assert "theory_school" not in reported_axes

    def test_disagreements_sorted_by_chunk_then_axis_order(self):
        tagger_records = [
            _record("c2", field="state", claim="state-formation"),
            _record("c1", field="state", claim="state-formation"),
        ]
        academic = {
            "c2": {
                "field": "violence",
                "empirical_scope": "scope:general",
                "claim_type": "state-capacity",
                "theory_school": "bellicist",
            },
            "c1": {
                "field": "violence",
                "empirical_scope": "scope:general",
                "claim_type": "state-capacity",
                "theory_school": "bellicist",
            },
        }
        # Both mismatched axes' Academic values must be in-vocab so this
        # test exercises plain disagreements, not addition candidates.
        vocabularies = {axis: [] for axis in AXIS_COLUMNS}
        vocabularies["field"] = ["state", "violence"]
        vocabularies["claim_type"] = ["state-formation", "state-capacity"]

        report = _build_report(tagger_records, academic, vocabularies)
        rows = [(row["chunk_id"], row["axis"]) for row in report["disagreements"]]
        # c1 sorts before c2; within a chunk, field precedes claim_type
        # (their order in AXIS_COLUMNS).
        assert rows == [
            ("c1", "field"),
            ("c1", "claim_type"),
            ("c2", "field"),
            ("c2", "claim_type"),
        ]

    def test_tag_counts_combine_both_sides(self):
        # Tagger and Academic both say "state" on c1 -> counted twice;
        # tagger says "violence" on c2, Academic gives no answer -> counted once.
        tagger_records = [_record("c1", field="state"), _record("c2", field="violence")]
        academic = {
            "c1": {
                "field": "state",
                "empirical_scope": None,
                "claim_type": None,
                "theory_school": None,
            },
            "c2": {
                "field": None,
                "empirical_scope": None,
                "claim_type": None,
                "theory_school": None,
            },
        }
        vocabularies = {axis: [] for axis in AXIS_COLUMNS}

        report = _build_report(tagger_records, academic, vocabularies)

        assert report["tag_counts"]["field"] == {"state": 2, "violence": 1}

    def test_never_applied_names_zero_combined_count_tags(self):
        tagger_records = [_record("c1", field="state")]
        academic = {
            "c1": {
                "field": "state",
                "empirical_scope": None,
                "claim_type": None,
                "theory_school": None,
            },
        }
        vocabularies = {
            "field": ["state", "violence", "ideology"],
            "empirical_scope": [],
            "claim_type": [],
            "theory_school": [],
        }

        report = _build_report(tagger_records, academic, vocabularies)

        assert report["never_applied"]["field"] == ["violence", "ideology"]

    def test_chunk_absent_from_sheet_treated_as_all_axes_unanswered(self):
        # A tagger chunk with no matching row on the returned sheet at all
        # (join miss) must not crash -- every axis is simply unanswered.
        tagger_records = [_record("c1")]
        academic = {}
        vocabularies = {axis: [] for axis in AXIS_COLUMNS}

        report = _build_report(tagger_records, academic, vocabularies)

        assert report["disagreements"] == []
        assert all(fraction == 0.0 for fraction in report["per_axis_agreement"].values())
        # The join miss itself must be surfaced, not silently absorbed.
        assert report["unmatched"]["chunks_only"] == ["c1"]
        assert report["unmatched"]["sheet_only"] == []

    def test_unmatched_names_sheet_rows_with_no_chunk_record(self):
        # A returned-sheet chunk_id with no matching tagger record at all
        # (e.g. the sheet answers a since-rewritten sample) -- the other
        # join-miss direction from the test above.
        tagger_records = [_record("c1")]
        academic = {
            "c1": {
                "field": "state",
                "empirical_scope": "scope:general",
                "claim_type": "state-formation",
                "theory_school": "bellicist",
            },
            "stale-c9": {
                "field": "state",
                "empirical_scope": "scope:general",
                "claim_type": "state-formation",
                "theory_school": "bellicist",
            },
        }
        vocabularies = {axis: [] for axis in AXIS_COLUMNS}

        report = _build_report(tagger_records, academic, vocabularies)

        assert report["unmatched"]["sheet_only"] == ["stale-c9"]
        assert report["unmatched"]["chunks_only"] == []

    def test_unmatched_both_directions_sorted(self):
        tagger_records = [_record("only-in-chunks-b"), _record("only-in-chunks-a")]
        academic = {
            "only-in-sheet-b": {
                "field": "state",
                "empirical_scope": None,
                "claim_type": None,
                "theory_school": None,
            },
            "only-in-sheet-a": {
                "field": "state",
                "empirical_scope": None,
                "claim_type": None,
                "theory_school": None,
            },
        }
        vocabularies = {axis: [] for axis in AXIS_COLUMNS}

        report = _build_report(tagger_records, academic, vocabularies)

        assert report["unmatched"]["sheet_only"] == ["only-in-sheet-a", "only-in-sheet-b"]
        assert report["unmatched"]["chunks_only"] == ["only-in-chunks-a", "only-in-chunks-b"]

    def test_out_of_vocab_academic_value_is_an_addition_candidate_not_a_disagreement(self):
        tagger_records = [_record("c1", field="state")]
        academic = {
            "c1": {
                "field": "unrecognized-new-field",  # outside the vocabulary below
                "empirical_scope": None,
                "claim_type": None,
                "theory_school": None,
            },
        }
        vocabularies = {axis: [] for axis in AXIS_COLUMNS}
        vocabularies["field"] = ["state", "violence"]

        report = _build_report(tagger_records, academic, vocabularies)

        assert report["addition_candidates"] == [
            {"chunk_id": "c1", "axis": "field", "value": "unrecognized-new-field"}
        ]
        # Not double-reported as a plain mismatch (plan's "not a plain
        # mismatch" -- see module docstring).
        assert report["disagreements"] == []
        # Agreement math is unaffected: still a non-match in the denominator.
        assert report["per_axis_agreement"]["field"] == 0.0

    def test_in_vocab_mismatch_stays_a_plain_disagreement_not_addition_candidate(self):
        tagger_records = [_record("c1", field="state")]
        academic = {
            "c1": {
                "field": "violence",  # in-vocab mismatch
                "empirical_scope": None,
                "claim_type": None,
                "theory_school": None,
            },
        }
        vocabularies = {axis: [] for axis in AXIS_COLUMNS}
        vocabularies["field"] = ["state", "violence"]

        report = _build_report(tagger_records, academic, vocabularies)

        assert report["disagreements"] == [
            {"chunk_id": "c1", "axis": "field", "tagger": "state", "academic": "violence"}
        ]
        assert report["addition_candidates"] == []


class TestWarnUnmatched:
    def test_no_warning_when_both_lists_empty(self, capsys):
        _warn_unmatched({"sheet_only": [], "chunks_only": []})
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_warns_on_sheet_only(self, capsys):
        _warn_unmatched({"sheet_only": ["stale-c9"], "chunks_only": []})
        captured = capsys.readouterr()
        assert captured.out == "", "the warning must go to stderr, not stdout"
        assert "stale-c9" in captured.err
        assert "1" in captured.err

    def test_warns_on_chunks_only(self, capsys):
        _warn_unmatched({"sheet_only": [], "chunks_only": ["c1", "c2"]})
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "c1" in captured.err
        assert "c2" in captured.err
        assert "2" in captured.err

    def test_warns_on_both_directions_independently(self, capsys):
        _warn_unmatched({"sheet_only": ["stale-c9"], "chunks_only": ["c1"]})
        captured = capsys.readouterr()
        assert "stale-c9" in captured.err
        assert "c1" in captured.err


class TestLoadAcademicLabels:
    def test_reads_values_and_blank_cells(self, tmp_path):
        vocabularies = {axis: ["state", "violence"] for axis in AXIS_COLUMNS}
        records = [_record("c1"), _record("c2")]
        workbook = build_workbook(records, vocabularies)
        worksheet = workbook.worksheets[0]
        field_col = SHEET_COLUMNS.index("field") + 1
        claim_col = SHEET_COLUMNS.index("claim_type") + 1
        # Row 2 (c1): fill both; row 3 (c2): leave field truly blank.
        worksheet.cell(row=2, column=field_col).value = "state"
        worksheet.cell(row=2, column=claim_col).value = "state-formation"
        worksheet.cell(row=3, column=field_col).value = None
        worksheet.cell(row=3, column=claim_col).value = "state-formation"

        sheet_path = tmp_path / "label_sheet.xlsx"
        workbook.save(sheet_path)

        labels = _load_academic_labels(sheet_path)

        assert labels["c1"]["field"] == "state"
        assert labels["c1"]["claim_type"] == "state-formation"
        assert labels["c2"]["field"] is None
        assert labels["c2"]["claim_type"] == "state-formation"


class TestRunEval:
    def test_missing_chunks_raises(self, tmp_path):
        gold_dir = tmp_path / "data" / "gold"
        with pytest.raises(MissingChunksError):
            run_eval(gold_dir=gold_dir)

    def test_missing_returned_sheet_raises_and_writes_no_report(self, tmp_path):
        gold_dir = tmp_path / "data" / "gold"
        chunks_dir = gold_dir / "chunks"
        chunks_dir.mkdir(parents=True)
        (chunks_dir / "c1.json").write_text(
            json.dumps(_record("c1"), indent=2, sort_keys=True), encoding="utf-8"
        )

        with pytest.raises(MissingReturnedSheetError) as excinfo:
            run_eval(gold_dir=gold_dir)

        assert "data/gold/labels/" in str(excinfo.value)
        assert not (gold_dir / "labels" / "eval_report.json").is_file()

    def test_end_to_end_writes_deterministic_report(self, tmp_path):
        from axial.gold import _axis_vocabularies
        from axial.tag import DEFAULT_DOMAIN_DIR

        gold_dir = tmp_path / "data" / "gold"
        chunks_dir = gold_dir / "chunks"
        chunks_dir.mkdir(parents=True)
        records = [_record("c1", field="state"), _record("c2", field="violence")]
        for record in records:
            (chunks_dir / f"{record['chunk_id']}.json").write_text(
                json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
            )

        vocabularies = _axis_vocabularies(DEFAULT_DOMAIN_DIR)
        workbook = build_workbook(records, vocabularies)
        worksheet = workbook.worksheets[0]
        field_col = SHEET_COLUMNS.index("field") + 1
        # Row 2 (c1) agrees; row 3 (c2) disagrees.
        worksheet.cell(row=2, column=field_col).value = "state"
        worksheet.cell(row=3, column=field_col).value = "ideology"

        labels_dir = gold_dir / "labels"
        labels_dir.mkdir(parents=True)
        workbook.save(labels_dir / "label_sheet.xlsx")

        report_path = run_eval(gold_dir=gold_dir, domain_dir=DEFAULT_DOMAIN_DIR)

        assert report_path == labels_dir / "eval_report.json"
        first = json.loads(report_path.read_text(encoding="utf-8"))

        second_path = run_eval(gold_dir=gold_dir, domain_dir=DEFAULT_DOMAIN_DIR)
        second = json.loads(second_path.read_text(encoding="utf-8"))

        assert first == second
        assert first["per_axis_agreement"]["field"] == 0.5

    def test_polity_score_falls_back_gracefully_when_canonical_map_absent(self, tmp_path):
        import shutil

        from axial.gold import _axis_vocabularies
        from axial.tag import DEFAULT_DOMAIN_DIR

        gold_dir = tmp_path / "data" / "gold"
        chunks_dir = gold_dir / "chunks"
        chunks_dir.mkdir(parents=True)
        record = _record("c1")
        record["polities_touched"] = ["USSR"]
        (chunks_dir / "c1.json").write_text(
            json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
        )

        vocabularies = _axis_vocabularies(DEFAULT_DOMAIN_DIR)
        workbook = build_workbook([record], vocabularies)
        worksheet = workbook.worksheets[0]
        polities_col = SHEET_COLUMNS.index("polities_touched") + 1
        worksheet.cell(row=2, column=polities_col).value = "Soviet Union"

        labels_dir = gold_dir / "labels"
        labels_dir.mkdir(parents=True)
        workbook.save(labels_dir / "label_sheet.xlsx")

        # A domain dir that has schema/codebook (so `_axis_vocabularies`
        # loads fine) but deliberately NO polity_canonical.yaml -- the
        # graceful-degradation path. This must not crash; USSR/Soviet Union
        # simply do not fold to the same key without the map (no alias fold
        # available), so it scores as a mismatch rather than raising.
        domain_dir = tmp_path / "domain-without-canonical-map"
        domain_dir.mkdir()
        shutil.copyfile(DEFAULT_DOMAIN_DIR / "schema.yaml", domain_dir / "schema.yaml")
        shutil.copyfile(DEFAULT_DOMAIN_DIR / "codebook.yaml", domain_dir / "codebook.yaml")

        report_path = run_eval(gold_dir=gold_dir, domain_dir=domain_dir)
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert "per_polity_score" in report
        row = report["per_polity_score"]["per_chunk"][0]
        assert row["chunk_id"] == "c1"
        assert row["f1"] == 0.0  # no fold available -> USSR != Soviet Union


class TestParsePolitiesCell:
    def test_semicolon_joined_splits_and_strips(self):
        assert _parse_polities_cell("Syria; Iraq") == ["Syria", "Iraq"]

    def test_single_value(self):
        assert _parse_polities_cell("Syria") == ["Syria"]

    def test_none_is_empty_list(self):
        assert _parse_polities_cell(None) == []

    def test_whitespace_only_is_empty_list(self):
        assert _parse_polities_cell("   ") == []

    def test_drops_empty_segments(self):
        assert _parse_polities_cell("Syria; ; Iraq;") == ["Syria", "Iraq"]


class TestLoadAcademicPolities:
    def test_reads_semicolon_cell_and_blank_cell(self, tmp_path):
        vocabularies = {axis: [] for axis in AXIS_COLUMNS}
        records = [_record("c1"), _record("c2")]
        workbook = build_workbook(records, vocabularies)
        worksheet = workbook.worksheets[0]
        polities_col = SHEET_COLUMNS.index("polities_touched") + 1
        worksheet.cell(row=2, column=polities_col).value = "Syria; Iraq"
        worksheet.cell(row=3, column=polities_col).value = None

        sheet_path = tmp_path / "label_sheet.xlsx"
        workbook.save(sheet_path)

        polities = _load_academic_polities(sheet_path)

        assert polities["c1"] == ["Syria", "Iraq"]
        assert polities["c2"] == []


def _small_canonical_map(tmp_path, extra_nodes: str = ""):
    yaml_text = (
        "version: 1\n"
        "nodes:\n"
        "  - canonical: Soviet Union\n"
        "    kind: historical\n"
        "    aliases: [USSR]\n"
        "  - canonical: Syria\n"
        "    kind: modern\n" + extra_nodes
    )
    domain_dir = tmp_path / "domain"
    domain_dir.mkdir()
    (domain_dir / "polity_canonical.yaml").write_text(yaml_text, encoding="utf-8")
    return load_polity_canonical(domain_dir)


class TestPolityFoldKey:
    def test_mapped_alias_folds_to_canonical(self, tmp_path):
        cmap = _small_canonical_map(tmp_path)
        assert _polity_fold_key("USSR", cmap) == _polity_fold_key("Soviet Union", cmap)

    def test_unmapped_verbatim_uses_casefold_whitespace_key(self, tmp_path):
        cmap = _small_canonical_map(tmp_path)
        assert _polity_fold_key("Lebanon", cmap) == _polity_fold_key("  lebanon  ", cmap)

    def test_no_map_falls_back_to_casefold_whitespace_for_every_polity(self):
        # Without a map, USSR and Soviet Union have no alias fold available
        # -- they compare as distinct (own-casefold) keys.
        assert _polity_fold_key("USSR", None) != _polity_fold_key("Soviet Union", None)
        assert _polity_fold_key("Syria", None) == _polity_fold_key("syria", None)


class TestFoldPolitySet:
    def test_folds_list_to_set_of_keys(self, tmp_path):
        cmap = _small_canonical_map(tmp_path)
        assert _fold_polity_set(["USSR"], cmap) == _fold_polity_set(["Soviet Union"], cmap)

    def test_empty_list_folds_to_empty_set(self, tmp_path):
        cmap = _small_canonical_map(tmp_path)
        assert _fold_polity_set([], cmap) == set()


class TestScorePolityChunk:
    def test_exact_match(self):
        result = _score_polity_chunk({"syria", "iraq"}, {"syria", "iraq"})
        assert result == {"tp": 2, "fp": 0, "fn": 0, "f1": 1.0}

    def test_extra_tagger_value_is_false_positive(self):
        result = _score_polity_chunk({"syria", "lebanon"}, {"syria"})
        assert result["tp"] == 1
        assert result["fp"] == 1
        assert result["fn"] == 0
        assert result["f1"] == pytest.approx(2 / 3)

    def test_missing_tagger_value_is_false_negative(self):
        result = _score_polity_chunk({"iraq"}, {"iraq", "turkey"})
        assert result["tp"] == 1
        assert result["fp"] == 0
        assert result["fn"] == 1
        assert result["f1"] == pytest.approx(2 / 3)

    def test_both_empty_is_perfect_match(self):
        result = _score_polity_chunk(set(), set())
        assert result == {"tp": 0, "fp": 0, "fn": 0, "f1": 1.0}

    def test_half_empty_tagger_only_is_zero_f1(self):
        result = _score_polity_chunk({"syria"}, set())
        assert result["tp"] == 0
        assert result["fp"] == 1
        assert result["fn"] == 0
        assert result["f1"] == 0.0

    def test_half_empty_academic_only_is_zero_f1(self):
        result = _score_polity_chunk(set(), {"syria"})
        assert result["tp"] == 0
        assert result["fp"] == 0
        assert result["fn"] == 1
        assert result["f1"] == 0.0


def _polity_record(chunk_id, polities):
    record = _record(chunk_id)
    record["polities_touched"] = polities
    return record


class TestBuildPolityScore:
    def test_micro_macro_and_both_empty_aggregate_correctly(self):
        # A trimmed variant of the outer test's own fixture (p1/p2/p3/p5,
        # no alias fold needed) -- see tests/eval/test_eval_polities.py's
        # module docstring for the hand-derived numbers.
        tagger_records = [
            _polity_record("p1", ["Syria", "Iraq"]),
            _polity_record("p2", ["Syria", "Lebanon"]),
            _polity_record("p3", ["Iraq"]),
            _polity_record("p5", []),
        ]
        academic_polities = {
            "p1": ["Syria", "Iraq"],
            "p2": ["Syria"],
            "p3": ["Iraq", "Turkey"],
            "p5": [],
        }

        section = _build_polity_score(tagger_records, academic_polities, cmap=None)

        assert section["micro"]["precision"] == pytest.approx(4 / 5)
        assert section["micro"]["recall"] == pytest.approx(4 / 5)
        assert section["micro"]["f1"] == pytest.approx(4 / 5)
        assert section["macro_f1"] == pytest.approx((1.0 + 2 / 3 + 2 / 3 + 1.0) / 4)
        assert section["both_empty_matches"] == 1
        per_chunk = {row["chunk_id"]: row for row in section["per_chunk"]}
        assert per_chunk["p1"]["f1"] == 1.0
        assert per_chunk["p5"]["f1"] == 1.0
        # Deterministic: sorted by chunk_id.
        assert [row["chunk_id"] for row in section["per_chunk"]] == sorted(per_chunk)

    def test_scope_excludes_tagger_chunk_with_no_sheet_row(self):
        tagger_records = [_polity_record("only-in-chunks", ["Syria"])]
        academic_polities: dict = {}  # no sheet row at all

        section = _build_polity_score(tagger_records, academic_polities, cmap=None)

        assert section["per_chunk"] == []
        assert section["both_empty_matches"] == 0
        assert section["micro"]["precision"] == 0.0
        assert section["micro"]["recall"] == 0.0
        assert section["micro"]["f1"] == 0.0

    def test_empty_academic_cell_on_returned_row_is_a_real_no_polity_answer(self):
        # A returned sheet row with a blank polities cell means "no engaged
        # polity" -- a real (both-empty) answer, NOT excluded like a
        # non-answer on the categorical axes.
        tagger_records = [_polity_record("p5", [])]
        academic_polities = {"p5": []}

        section = _build_polity_score(tagger_records, academic_polities, cmap=None)

        assert section["both_empty_matches"] == 1
        assert section["per_chunk"][0]["f1"] == 1.0

    def test_alias_fold_counts_as_true_positive(self, tmp_path):
        cmap = _small_canonical_map(tmp_path)
        tagger_records = [_polity_record("p4", ["USSR"])]
        academic_polities = {"p4": ["Soviet Union"]}

        section = _build_polity_score(tagger_records, academic_polities, cmap=cmap)

        row = section["per_chunk"][0]
        assert row == {"chunk_id": "p4", "tp": 1, "fp": 0, "fn": 0, "f1": 1.0}


class TestLoadPolityCanonicalOrNone:
    def test_returns_none_when_map_file_absent(self, tmp_path):
        domain_dir = tmp_path / "no-map-domain"
        domain_dir.mkdir()

        assert _load_polity_canonical_or_none(domain_dir) is None

    def test_returns_loaded_map_when_present(self, tmp_path):
        cmap = _small_canonical_map(tmp_path)
        loaded = _load_polity_canonical_or_none(tmp_path / "domain")

        assert loaded is not None
        assert loaded.version == cmap.version
