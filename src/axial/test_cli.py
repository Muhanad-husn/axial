"""Inner unit tests for the axial CLI skeleton (issue #6, slice 01)."""

import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - repo requires-python >=3.13
    import tomli as tomllib

import axial

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _declared_version() -> str:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def test_version_matches_pyproject():
    assert axial.__version__ == _declared_version()


def test_build_parser_recognises_version_flag():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["--version"])
    assert args.version is True


def test_main_returns_zero_for_version(capsys):
    from axial.cli import main

    exit_code = main(["--version"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert f"axial {axial.__version__}" in captured.out


def _write_minimal_schema(domain_dir):
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / "schema.yaml").write_text(
        """
        version: 0.9
        axes:
          field:
            applies_to: [prose, artifact]
            cardinality: single
            values: [state, violence, ideology]
        """,
        encoding="utf-8",
    )


def test_build_parser_recognises_schema_show_subcommand():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["schema", "show", "config/domains/syria"])

    assert args.command == "schema"
    assert args.schema_command == "show"
    assert args.domain_dir == "config/domains/syria"


def test_main_schema_show_prints_axis_cardinality_count_and_version(tmp_path, capsys):
    from axial.cli import main

    domain_dir = tmp_path / "some-domain"
    _write_minimal_schema(domain_dir)

    exit_code = main(["schema", "show", str(domain_dir)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "field" in captured.out
    assert "single" in captured.out
    assert "3" in captured.out
    assert "0.9" in captured.out


def test_main_schema_show_against_missing_domain_dir_is_nonzero_and_names_path(capsys):
    from axial.cli import main

    exit_code = main(["schema", "show", "no/such/domain-dir"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "schema.yaml" in captured.err or "schema.yaml" in captured.out


def test_build_parser_recognises_artifacts_subcommand():
    """Issue #429: the artifacts pass makes no LLM call and needs no domain
    frame, so `--domain` is gone from this subcommand -- it now takes only
    the source path."""
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["artifacts", "some-source.pdf"])

    assert args.command == "artifacts"
    assert args.source_path == "some-source.pdf"


def test_main_artifacts_prints_error_and_returns_nonzero_on_artifacts_error(monkeypatch, capsys):
    import axial.cli as cli_mod
    from axial.artifacts import ArtifactsError

    def _boom(source_path):
        raise ArtifactsError("simulated artifacts failure")

    monkeypatch.setattr(cli_mod, "run_artifacts", _boom)

    exit_code = cli_mod.main(["artifacts", "some-source.pdf"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "simulated artifacts failure" in captured.err


def test_build_parser_recognises_brief_show_subcommand():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["brief", "show", "config/briefs/dev/fixture-syria-displacement.yaml"])

    assert args.command == "brief"
    assert args.brief_command == "show"
    assert args.brief_path == "config/briefs/dev/fixture-syria-displacement.yaml"


def test_main_brief_show_prints_case_request_lens_and_brief_id(tmp_path, capsys):
    from axial.cli import main

    brief_path = tmp_path / "some_brief.yaml"
    brief_path.write_text('case: "Syria"\nrequest: "A question"\n', encoding="utf-8")

    exit_code = main(["brief", "show", str(brief_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Syria" in captured.out
    assert "A question" in captured.out
    assert "brief_id" in captured.out


def test_main_brief_show_against_missing_file_is_nonzero_and_names_path(capsys):
    from axial.cli import main

    exit_code = main(["brief", "show", "no/such/brief.yaml"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "brief.yaml" in captured.err


def test_main_brief_show_against_missing_case_is_nonzero_and_names_case(tmp_path, capsys):
    from axial.cli import main

    brief_path = tmp_path / "malformed_brief.yaml"
    brief_path.write_text('request: "A question"\n', encoding="utf-8")

    exit_code = main(["brief", "show", str(brief_path)])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "case" in captured.err


def test_build_parser_gate_run_parses_without_dry_run_flag(tmp_path):
    """Issue #387 made `trusted` resolve from the corpus pin alone, leaving
    `--dry-run` with no behaviour to gate -- it must not be `required`
    anymore, or the trusted-tier invocation we are about to run and log
    would have to pass a flag whose own help text claims the opposite of
    what actually happened."""
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["gate", "run", "attribution-fidelity", "--records", str(tmp_path)])

    assert args.command == "gate"
    assert args.gate_command == "run"
    assert args.gate == "attribution-fidelity"
    assert args.records == str(tmp_path)
    assert args.dry_run is False


def test_build_parser_gate_run_still_accepts_dry_run_flag(tmp_path):
    """Backward compatibility: any existing caller or doc line that still
    passes `--dry-run` must keep parsing cleanly."""
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        ["gate", "run", "attribution-fidelity", "--dry-run", "--records", str(tmp_path)]
    )

    assert args.dry_run is True


# ---------------------------------------------------------------------------
# `axial names escalations` (issue #461): read-only listing, no queue
# ---------------------------------------------------------------------------


def _write_jsonl(path, records):
    import json

    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_build_parser_recognises_names_escalations_subcommand(tmp_path):
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "names",
            "escalations",
            "--decisions-path",
            str(tmp_path / "d.jsonl"),
            "--inventory-path",
            str(tmp_path / "i.jsonl"),
            "--json",
        ]
    )

    assert args.command == "names"
    assert args.names_command == "escalations"
    assert args.decisions_path == str(tmp_path / "d.jsonl")
    assert args.inventory_path == str(tmp_path / "i.jsonl")
    assert args.as_json is True


def test_main_names_escalations_lists_an_escalated_surface_with_co_members_and_sources(
    tmp_path, capsys
):
    from axial.cli import main

    decisions_path = tmp_path / "merge_decisions.jsonl"
    inventory_path = tmp_path / "inventory.jsonl"
    _write_jsonl(
        decisions_path,
        [
            {
                "batch_key": "k1",
                "cluster_label": 0,
                "members": ["Adam Smith", "Anthony D. Smith"],
                "nodes": [],
                "escalated": ["Adam Smith", "Anthony D. Smith"],
            },
            {
                # Fully decided, nothing escalated -- must not appear.
                "batch_key": "k2",
                "cluster_label": 1,
                "members": ["Slavery", "slavery"],
                "nodes": [{"canonical": "Slavery", "aliases": ["slavery"]}],
                "escalated": [],
            },
        ],
    )
    _write_jsonl(
        inventory_path,
        [
            {
                "surface": "Adam Smith",
                "kind": "person",
                "count": 2,
                "chunk_ids": ["book-one_1_intro_001"],
            },
            {
                "surface": "Anthony D. Smith",
                "kind": "person",
                "count": 1,
                "chunk_ids": ["book-two_1_intro_001"],
            },
        ],
    )

    exit_code = main(
        [
            "names",
            "escalations",
            "--decisions-path",
            str(decisions_path),
            "--inventory-path",
            str(inventory_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Adam Smith" in captured.out
    assert "Anthony D. Smith" in captured.out
    assert "book-one" in captured.out
    assert "book-two" in captured.out
    assert "person: 2" in captured.out
    assert "Slavery" not in captured.out


def test_main_names_escalations_json_flag_emits_machine_readable_array(tmp_path, capsys):
    import json

    from axial.cli import main

    decisions_path = tmp_path / "merge_decisions.jsonl"
    _write_jsonl(
        decisions_path,
        [
            {
                "batch_key": "k1",
                "cluster_label": 0,
                "members": ["a", "b"],
                "nodes": [],
                "escalated": ["a"],
            }
        ],
    )

    exit_code = main(
        [
            "names",
            "escalations",
            "--decisions-path",
            str(decisions_path),
            "--inventory-path",
            str(tmp_path / "no-such-inventory.jsonl"),
            "--json",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    # Issue #735: escalations_to_json now carries a `stale` flag (the
    # surface isn't in the inventory here, so it's stale) -- updated to
    # match the new shape, not a behavior regression.
    assert payload == [
        {
            "surface": "a",
            "kind": None,
            "cluster_label": 0,
            "co_members": ["b"],
            "source_ids": [],
            "stale": True,
        }
    ]


def test_main_names_escalations_survives_non_utf8_stdout_json_and_text(tmp_path, monkeypatch):
    """Real-corpus regression (issue #461 follow-up): surfaces in this corpus
    are transliterated Arabic/Turkish scholarship, so a character outside
    cp1252 (e.g. the macron in `an-Nizam` -> `an-Nizām`) is the normal
    case. Windows' default console/redirect codec is cp1252, not UTF-8; a
    stdout stream opened with that codec must not crash, in both --json and
    plain-text output. This has to drive a real codec-restricted stream --
    pytest's capsys is UTF-8 and would pass even on the broken code."""
    import io
    import json as json_module
    import sys

    from axial.cli import main

    decisions_path = tmp_path / "merge_decisions.jsonl"
    _write_jsonl(
        decisions_path,
        [
            {
                "batch_key": "k1",
                "cluster_label": 0,
                "members": ["an-Nizām", "b"],
                "nodes": [],
                "escalated": ["an-Nizām"],
            }
        ],
    )

    def run_with_cp1252_stdout(extra_args):
        raw = io.BytesIO()
        wrapper = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", newline="")
        monkeypatch.setattr(sys, "stdout", wrapper)
        exit_code = main(
            [
                "names",
                "escalations",
                "--decisions-path",
                str(decisions_path),
                "--inventory-path",
                str(tmp_path / "no-such-inventory.jsonl"),
                *extra_args,
            ]
        )
        wrapper.flush()
        return exit_code, raw.getvalue()

    exit_code, raw_bytes = run_with_cp1252_stdout(["--json"])
    assert exit_code == 0
    payload = json_module.loads(raw_bytes.decode("utf-8"))
    assert payload[0]["surface"] == "an-Nizām"

    exit_code, raw_bytes = run_with_cp1252_stdout([])
    assert exit_code == 0
    assert "an-Nizām" in raw_bytes.decode("utf-8")


# ---------------------------------------------------------------------------
# `axial vocabulary examine` (issue #805, derived-vocabulary slice 01):
# read-only census over the twelve sentence-valued answer columns
# ---------------------------------------------------------------------------


def test_build_parser_recognises_vocabulary_examine_subcommand(tmp_path):
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "vocabulary",
            "examine",
            "--columns",
            "mechanism",
            "--thresholds",
            "0.45,0.55",
            "--answers-dir",
            str(tmp_path / "answers"),
        ]
    )

    assert args.command == "vocabulary"
    assert args.vocabulary_command == "examine"
    assert args.columns == "mechanism"
    assert args.thresholds == "0.45,0.55"
    assert args.answers_dir == str(tmp_path / "answers")


def _write_vocabulary_answers(answers_dir):
    """A small `mechanism` population: five paraphrases of one recurring
    mechanism, spread across three sources (so at least one group reaches a
    second source), plus three one-off, unrelated sentences that must never
    join any group."""
    answers_dir.mkdir(parents=True, exist_ok=True)

    repeated = [
        "Extraction of rural surplus funds the central state's own army.",
        "The state's army is funded by extracting surplus from the countryside.",
        "Rural surplus, once extracted, pays for the central army.",
        "Central military spending draws on surplus taken from rural producers.",
        "The army is paid for out of surplus the state extracts from villages.",
    ]
    unrelated = [
        "A shared script does not make two nationalisms the same movement.",
        "Colonial borders were drawn without consulting the tribes they split.",
        "Print capitalism let a reading public imagine itself as a nation.",
    ]

    _write_jsonl(
        answers_dir / "alpha-2020.jsonl",
        [
            {"chunk_id": "alpha-2020_1", "source_id": "alpha-2020",
             "answers": {"mechanism": repeated[0]}},
            {"chunk_id": "alpha-2020_2", "source_id": "alpha-2020",
             "answers": {"mechanism": repeated[1]}},
            {"chunk_id": "alpha-2020_3", "source_id": "alpha-2020",
             "answers": {"mechanism": unrelated[0]}},
            # An abstention and the issue #810 literal-"[]" bug: both must
            # be excluded from the population, not clustered.
            {"chunk_id": "alpha-2020_4", "source_id": "alpha-2020",
             "answers": {"mechanism": "not-in-passage"}},
        ],
    )
    _write_jsonl(
        answers_dir / "beta-2021.jsonl",
        [
            {"chunk_id": "beta-2021_1", "source_id": "beta-2021",
             "answers": {"mechanism": repeated[2]}},
            {"chunk_id": "beta-2021_2", "source_id": "beta-2021",
             "answers": {"mechanism": repeated[3]}},
            {"chunk_id": "beta-2021_3", "source_id": "beta-2021",
             "answers": {"mechanism": unrelated[1]}},
            {"chunk_id": "beta-2021_4", "source_id": "beta-2021",
             "answers": {"mechanism": "[]"}},
        ],
    )
    _write_jsonl(
        answers_dir / "gamma-2022.jsonl",
        [
            {"chunk_id": "gamma-2022_1", "source_id": "gamma-2022",
             "answers": {"mechanism": repeated[4]}},
            {"chunk_id": "gamma-2022_2", "source_id": "gamma-2022",
             "answers": {"mechanism": unrelated[2]}},
        ],
    )
    return repeated, unrelated


def _fake_topic_encoder(topic_by_sentence):
    """A deterministic stand-in for the real MiniLM encoder: every sentence
    maps to a one-hot vector keyed on which topic it belongs to, so sentences
    that "say the same thing in different words" land on the identical
    vector (cosine distance 0) and unrelated sentences land on orthogonal
    vectors (cosine distance 1) -- no real embedding, no model call, and the
    clustering that runs on top of it is real."""
    import numpy as np

    topics = sorted(set(topic_by_sentence.values()))
    index_by_topic = {topic: index for index, topic in enumerate(topics)}
    call_count = {"n": 0}

    def encode(texts):
        call_count["n"] += 1
        vectors = np.zeros((len(texts), len(topics)))
        for row, text in enumerate(texts):
            vectors[row, index_by_topic[topic_by_sentence[text]]] = 1.0
        return vectors

    encode.call_count = call_count
    return encode


def test_main_vocabulary_examine_reports_the_sweep_and_the_top_groups(tmp_path, capsys, monkeypatch):
    """The acceptance test (plan's gherkin, verbatim in intent): a store
    with notes from more than one source, whose `mechanism` answers include
    several paraphrases of the same mechanism and several unrelated ones.
    Real clustering runs (scipy, from the `distill` group); only the
    encoder is a fake, injected by monkeypatching the same seam
    `axial.argmap.build.bag_passages` already exposes."""
    pytest.importorskip("scipy")
    import axial.vocabulary as vocabulary_mod
    from axial.cli import main

    answers_dir = tmp_path / "answers"
    repeated, unrelated = _write_vocabulary_answers(answers_dir)

    topic_by_sentence = {sentence: "extraction" for sentence in repeated}
    for index, sentence in enumerate(unrelated):
        topic_by_sentence[sentence] = f"unrelated-{index}"

    fake_encode = _fake_topic_encoder(topic_by_sentence)
    monkeypatch.setattr(vocabulary_mod, "_default_encoder", lambda: fake_encode)

    before = sorted(str(p) for p in tmp_path.rglob("*"))

    exit_code = main(
        [
            "vocabulary",
            "examine",
            "--columns",
            "mechanism",
            "--answers-dir",
            str(answers_dir),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    # Names the column, its answered-value count, and its distinct-string
    # count.
    assert "mechanism: 8 answered value(s)" in captured.out
    assert "8 distinct string(s)" in captured.out

    # Per swept threshold: group count, share in a group of 2+, largest
    # group size, cross-source group count.
    assert "threshold=0.35" in captured.out
    assert "threshold=0.55" in captured.out
    assert "threshold=0.75" in captured.out
    assert "group(s)" in captured.out
    assert "in a group of 2+" in captured.out
    assert "largest group" in captured.out
    assert "cross-source group(s)" in captured.out

    # The go/no-go bar (plan conditions 1 and 3) quantifies over groups of
    # 5+ members specifically -- printed on every threshold row. At every
    # swept threshold here the repeated group (5 members, 3 sources) is the
    # only one that clears the floor, and it is cross-source.
    assert captured.out.count("1 group(s) with 5+ member(s), 1 of those cross-source") == 5

    # Names the sampling threshold (0.55, the live claim path's own
    # threshold and the centre of the default sweep), then prints the
    # largest groups at that threshold as their member sentences -- here
    # 4 groups exist in total (one group of 5 paraphrases, three unrelated
    # singletons), all under the ten printed.
    assert "sampling threshold for the 4 largest group(s): 0.55" in captured.out
    for sentence in repeated:
        assert sentence in captured.out
    for sentence in unrelated:
        assert sentence in captured.out

    # Zero model calls: the fake encoder was the only thing that produced a
    # vector.
    assert fake_encode.call_count["n"] >= 1

    # Writes nothing under the answer store or anywhere else in the tmp
    # tree -- no pipeline artifact, not even a new empty directory.
    after = sorted(str(p) for p in tmp_path.rglob("*"))
    assert after == before
