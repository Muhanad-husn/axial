"""Inner unit tests for the axial CLI skeleton (issue #6, slice 01)."""

import sys
from pathlib import Path

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
            "--propose-n",
            "40",
            "--assign-n",
            "40",
            "--answers-dir",
            str(tmp_path / "answers"),
        ]
    )

    assert args.command == "vocabulary"
    assert args.vocabulary_command == "examine"
    assert args.columns == "mechanism"
    assert args.propose_n == 40
    assert args.assign_n == 40
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


class _FakeVocabExamineClient:
    """A minimal `LLMClient` for the CLI acceptance test: canned responses
    queued per pass name, in the order the propose/assign/check calls are
    expected to ask for them. Mirrors `axial.vocabulary.test_vocabulary.
    _FakeVocabClient`, duplicated here (small, self-contained) rather than
    imported across test modules -- no other test module in this repo
    imports fixtures from another one."""

    def __init__(self, responses_by_pass, models):
        self._responses = {name: list(queue) for name, queue in responses_by_pass.items()}
        self._models = models
        self.prompts_by_pass = {}
        self._calls = {}
        self._cost = {}

    def complete(self, prompt, pass_name=None):
        self.prompts_by_pass.setdefault(pass_name, []).append(prompt)
        self._calls[pass_name] = self._calls.get(pass_name, 0) + 1
        self._cost[pass_name] = self._cost.get(pass_name, 0.0) + 0.001
        queue = self._responses.get(pass_name)
        if not queue:
            raise AssertionError(f"_FakeVocabExamineClient: no response left for pass {pass_name!r}")
        return queue.pop(0)

    def model_for_pass(self, pass_name=None):
        return self._models.get(pass_name, "fake/default")

    def calls_for_pass(self, pass_name=None):
        return self._calls.get(pass_name, 0)

    def cost_for_pass(self, pass_name=None):
        return self._cost.get(pass_name) if self._calls.get(pass_name, 0) else None


def test_main_vocabulary_examine_reports_the_categorisation_and_the_agreement_rate(
    tmp_path, capsys, monkeypatch
):
    """The acceptance test (plan's gherkin, verbatim in intent): a store
    with notes from more than one source, whose `mechanism` answers include
    several paraphrases of the same mechanism and several unrelated ones,
    and a model client that names categories when asked to propose and
    assigns values when asked to assign. No test makes a model call -- the
    client is injected by monkeypatching the same seam `axial.vocabulary.
    examine_vocabulary`'s own `client=None` default resolves through
    (`axial.vocabulary.get_client`)."""
    import json

    import axial.vocabulary as vocabulary_mod
    from axial.cli import main

    answers_dir = tmp_path / "answers"
    repeated, unrelated = _write_vocabulary_answers(answers_dir)
    # 8 answered values total (5 repeated + 3 unrelated); the abstention and
    # the issue #810 "[]" literal are excluded from the population.

    propose_response = json.dumps(
        {
            "categories": [
                {
                    "name": "Extraction funds central coercion",
                    "gloss": "rural surplus, once extracted, pays for the state's own army",
                }
            ]
        }
    )
    # F5 (PR #815 review): under seed 0, `draw_vocabulary_samples` puts
    # indices 1, 2 and 4 of the held-out sample on a repeated-mechanism
    # sentence and index 3 on one of the three deliberately unrelated ones
    # (verified against `draw_vocabulary_samples` directly -- see the PR
    # review). Scripting index 3 back as "none" makes the unrelated
    # sentences do real work: the printed assignment rate and largest-
    # category share come out at 75%, not the vacuous 100% every ratio
    # showed before, and the "none" case still exercises the CLI's own
    # rendering of a real refusal.
    assign_response = json.dumps(
        {
            "assignments": [
                {"n": 1, "category": "Extraction funds central coercion"},
                {"n": 2, "category": "Extraction funds central coercion"},
                {"n": 3, "category": "none"},
                {"n": 4, "category": "Extraction funds central coercion"},
            ]
        }
    )
    check_response = json.dumps(
        {
            "assignments": [
                {"n": 1, "category": "Extraction funds central coercion"},
                {"n": 2, "category": "Extraction funds central coercion"},
                {"n": 3, "category": "none"},
                {"n": 4, "category": "Extraction funds central coercion"},
            ]
        }
    )

    client = _FakeVocabExamineClient(
        responses_by_pass={
            vocabulary_mod.EXAMINE_PASS_NAME: [propose_response, assign_response],
            vocabulary_mod.CHECK_PASS_NAME: [check_response],
        },
        models={
            vocabulary_mod.EXAMINE_PASS_NAME: "z-ai/glm-5.2",
            vocabulary_mod.CHECK_PASS_NAME: "deepseek/deepseek-v4-pro",
        },
    )
    monkeypatch.setattr(vocabulary_mod, "get_client", lambda *a, **kw: client)

    before = sorted(str(p) for p in tmp_path.rglob("*"))

    exit_code = main(
        [
            "vocabulary",
            "examine",
            "--columns",
            "mechanism",
            "--propose-n",
            "4",
            "--assign-n",
            "4",
            "--answers-dir",
            str(answers_dir),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    # Names the column, its answered-value count, its distinct-string
    # count, and how many values were excluded as abstentions.
    assert "mechanism: 8 answered value(s)" in captured.out
    assert "8 distinct string(s)" in captured.out
    assert "2 excluded (abstention/[]/empty)" in captured.out

    # Lists every category the model named, with its gloss, its member
    # count and the number of distinct sources its members come from.
    assert "Extraction funds central coercion" in captured.out
    assert "rural surplus, once extracted, pays for the state's own army" in captured.out
    assert "3 member(s)" in captured.out

    # The share of the held-out sample assigned, the count of categories
    # with 5+ members, how many of those span 2+ sources, and the largest
    # category's share -- 3 of the 4 held-out values (the repeated
    # mechanism), 1 the deliberately unrelated sentence scripted as "none".
    assert "assignment rate on held-out sample: 75.0%" in captured.out
    assert "categories with 5+ members: 0" in captured.out
    assert "spanning 2+ sources: 0" in captured.out
    assert "largest category share (of the held-out sample): 75.0%" in captured.out

    # The share of a subsample on which a second, different model agrees
    # with the first about which category a value belongs to -- the overall
    # rate counts the shared "none" as agreement (4 of 4); the restricted
    # rate is over the 3 entries the first model actually placed.
    assert "two-model agreement overall (subsample of 4): 100.0%" in captured.out
    assert (
        "two-model agreement where the first model assigned a category (n=3): 100.0%"
        in captured.out
    )

    # The model, the call count and the cost per column.
    assert "z-ai/glm-5.2" in captured.out
    assert "deepseek/deepseek-v4-pro" in captured.out
    assert "2 call(s)" in captured.out  # examine: 1 propose + 1 assign batch
    assert "1 call(s)" in captured.out  # check: 1 batch

    # Writes nothing under the answer store or anywhere else in the tmp
    # tree -- no pipeline artifact, not even a new empty directory.
    after = sorted(str(p) for p in tmp_path.rglob("*"))
    assert after == before


# ---------------------------------------------------------------------------
# `axial brief sweep --arm` (issue #808): the named retrieval arm, and its
# `--map` alias.
# ---------------------------------------------------------------------------


def test_build_parser_brief_sweep_defaults_arm_to_name(tmp_path):
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        ["brief", "sweep", "wl.txt", "--draws", "3", "--sweep-dir", str(tmp_path)]
    )

    assert args.command == "brief"
    assert args.brief_command == "sweep"
    assert args.arm == "name"


def test_build_parser_brief_sweep_recognises_arm_flag(tmp_path):
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "brief",
            "sweep",
            "wl.txt",
            "--draws",
            "3",
            "--sweep-dir",
            str(tmp_path),
            "--arm",
            "map",
        ]
    )

    assert args.arm == "map"


def test_build_parser_brief_sweep_map_flag_is_an_alias_for_arm_map(tmp_path):
    """`--map` (issue #572) stays a working alias for `--arm map` (issue
    #808), so no existing invocation breaks."""
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        ["brief", "sweep", "wl.txt", "--draws", "3", "--sweep-dir", str(tmp_path), "--map"]
    )

    assert args.arm == "map"


def test_build_parser_brief_sweep_accepts_an_arbitrary_arm_name(tmp_path):
    """issue #808: the CLI parser holds no fixed list of valid arm names --
    an arm no lower layer recognizes yet still parses cleanly."""
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "brief",
            "sweep",
            "wl.txt",
            "--draws",
            "3",
            "--sweep-dir",
            str(tmp_path),
            "--arm",
            "map+vocab",
        ]
    )

    assert args.arm == "map+vocab"


def test_main_brief_sweep_forwards_arm_to_run_sweep(tmp_path, monkeypatch):
    import axial.cli as cli_mod
    from axial.brief.sweep import SweepSummary

    captured = {}

    def _fake_run_sweep(worklist_path, *, draws, sweep_dir, workers, arm):
        captured["worklist_path"] = worklist_path
        captured["draws"] = draws
        captured["sweep_dir"] = sweep_dir
        captured["workers"] = workers
        captured["arm"] = arm
        return SweepSummary(
            briefs=[], total_draws=0, ok_count=0, fail_count=0, skip_count=0, arm=arm
        )

    monkeypatch.setattr(cli_mod, "run_sweep", _fake_run_sweep)

    exit_code = cli_mod.main(
        [
            "brief",
            "sweep",
            "wl.txt",
            "--draws",
            "2",
            "--sweep-dir",
            str(tmp_path / "sweep"),
            "--arm",
            "map",
        ]
    )

    assert exit_code == 0
    assert captured["arm"] == "map"


def test_main_brief_sweep_map_flag_forwards_arm_map_to_run_sweep(tmp_path, monkeypatch):
    import axial.cli as cli_mod
    from axial.brief.sweep import SweepSummary

    captured = {}

    def _fake_run_sweep(worklist_path, *, draws, sweep_dir, workers, arm):
        captured["arm"] = arm
        return SweepSummary(
            briefs=[], total_draws=0, ok_count=0, fail_count=0, skip_count=0, arm=arm
        )

    monkeypatch.setattr(cli_mod, "run_sweep", _fake_run_sweep)

    exit_code = cli_mod.main(
        ["brief", "sweep", "wl.txt", "--draws", "1", "--sweep-dir", str(tmp_path / "sweep"), "--map"]
    )

    assert exit_code == 0
    assert captured["arm"] == "map"


def test_main_brief_sweep_prints_error_and_returns_nonzero_on_a_mixed_arm_refusal(
    tmp_path, monkeypatch, capsys
):
    """The mixed-arm refusal (issue #808) reaches the CLI through the same
    `SweepError` catch `axial brief sweep` already has -- naming the arm
    already in `--sweep-dir` in the printed error."""
    import axial.cli as cli_mod
    from axial.brief.sweep import SweepError

    def _refuse(worklist_path, *, draws, sweep_dir, workers, arm):
        raise SweepError(f"{sweep_dir} already holds draws for arm 'map'; refusing arm {arm!r}")

    monkeypatch.setattr(cli_mod, "run_sweep", _refuse)

    exit_code = cli_mod.main(
        [
            "brief",
            "sweep",
            "wl.txt",
            "--draws",
            "1",
            "--sweep-dir",
            str(tmp_path / "sweep"),
            "--arm",
            "name",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "arm 'map'" in captured.err
    assert "'name'" in captured.err


# ---------------------------------------------------------------------------
# `axial sources` and the orphaned-envelope reverse pass (issue #819): an
# ingested source whose raw file is gone is reported and exits non-zero.
# ---------------------------------------------------------------------------


def _stub_sources_scan(monkeypatch, orphans):
    """Point both halves of `axial sources`'s local report at fixtures: the
    forward walk returns a single healthy source, the reverse pass returns
    whatever this test wants. Neither reads the real (gitignored) `data/`."""
    from axial import cli as cli_mod
    from axial.sources import DONE, SourceRecord

    monkeypatch.setattr(cli_mod, "scan_local", lambda *a, **kw: [SourceRecord("alpha.pdf", DONE)])
    monkeypatch.setattr(cli_mod, "scan_orphaned_envelopes", lambda *a, **kw: orphans)


def test_main_sources_check_exits_zero_and_prints_no_orphan_block_when_clean(
    monkeypatch, capsys
):
    from axial.cli import main

    _stub_sources_scan(monkeypatch, [])

    exit_code = main(["sources", "--backend", "local", "--check"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "alpha.pdf" in captured.out
    assert "missing" not in captured.out
    assert captured.err == ""


def test_main_sources_check_names_the_orphaned_source_and_exits_non_zero(monkeypatch, capsys):
    from axial.cli import main
    from axial.sources import MISSING, SourceRecord

    _stub_sources_scan(
        monkeypatch,
        [
            SourceRecord("beshara-2011-8410a9059300", MISSING, "no raw file in data/sources"),
            SourceRecord("zulu-2020-ffffffffffff", MISSING, "no raw file in data/sources"),
        ],
    )

    exit_code = main(["sources", "--backend", "local", "--check"])
    captured = capsys.readouterr()

    # Non-zero, because this is the state that kills a paid run at the corpus
    # pin (issue #816) -- `new` and `changed` are not errors and still exit 0.
    assert exit_code != 0
    # Both named, not just the first.
    assert "beshara-2011-8410a9059300" in captured.out
    assert "zulu-2020-ffffffffffff" in captured.out
    assert MISSING in captured.out
    # The forward report is still printed in full alongside it.
    assert "alpha.pdf" in captured.out


def test_main_sources_orphan_check_runs_without_check_flag_too(monkeypatch, capsys):
    """The reverse pass is not a `--check`-only extra: a plain `axial sources`
    that ingests new files still reports a corpus that cannot run the map arm."""
    from axial.cli import main
    from axial.sources import MISSING, SourceRecord

    _stub_sources_scan(
        monkeypatch, [SourceRecord("beshara-2011-8410a9059300", MISSING, "no raw file")]
    )

    exit_code = main(["sources", "--backend", "local"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "beshara-2011-8410a9059300" in captured.out
    # Nothing was pending, so no client was ever built and no pass ever ran.
    assert "nothing new" in captured.out
