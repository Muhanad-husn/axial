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
# `axial vocabulary build` (issue #806, derived-vocabulary slice 02):
# assigning a whole column against the frozen scheme, and persisting it
# ---------------------------------------------------------------------------


_BUILD_SCHEME_YAML = """
columns:
  mechanism:
    version: "test-v1"
    categories:
      - id: war-and-state-formation
        name: "war and state formation"
        gloss: "warfare drives state-building, extraction and institutional change"
      - id: identity-construction-and-boundary-making
        name: "identity construction and boundary-making"
        gloss: "ethnic, national or religious categories are made and politicised"
"""


class _FakeVocabBuildClient:
    """A minimal `LLMClient` that assigns by reading the numbered values
    back out of the assign prompt, via a value -> category-name lookup; a
    value it has no entry for comes back as a real "none" refusal. Records
    every value it was ever asked about, which is what the second and third
    runs of the acceptance criterion turn on. Mirrors `axial.
    test_vocabulary_build._ScriptedAssignClient`, duplicated here (small,
    self-contained) rather than imported across test modules."""

    def __init__(self, assign_by_value):
        self._assign_by_value = dict(assign_by_value)
        self.asked_values = []
        self._calls = {}
        self._cost = {}

    def complete(self, prompt, pass_name=None):
        import json as _json
        import re as _re

        self._calls[pass_name] = self._calls.get(pass_name, 0) + 1
        self._cost[pass_name] = self._cost.get(pass_name, 0.0) + 0.001
        assignments = []
        for line in prompt.splitlines():
            match = _re.match(r"^(\d+)\.\s(.*)$", line)
            if match is None:
                continue
            number, value = int(match.group(1)), match.group(2)
            self.asked_values.append(value)
            assignments.append({"n": number, "category": self._assign_by_value.get(value, "none")})
        return _json.dumps({"assignments": assignments})

    def model_for_pass(self, pass_name=None):
        return "z-ai/glm-5.2"

    def calls_for_pass(self, pass_name=None):
        return self._calls.get(pass_name, 0)

    def cost_for_pass(self, pass_name=None):
        return self._cost.get(pass_name) if self._calls.get(pass_name, 0) else None


def test_build_parser_recognises_vocabulary_build_subcommand(tmp_path):
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "vocabulary",
            "build",
            "--columns",
            "mechanism",
            "--answers-dir",
            str(tmp_path / "answers"),
            "--scheme-path",
            str(tmp_path / "vocabulary.yaml"),
            "--vocabulary-dir",
            str(tmp_path / "vocabulary"),
            "--workers",
            "4",
            "--force",
        ]
    )

    assert args.command == "vocabulary"
    assert args.vocabulary_command == "build"
    assert args.columns == "mechanism"
    assert args.answers_dir == str(tmp_path / "answers")
    assert args.scheme_path == str(tmp_path / "vocabulary.yaml")
    assert args.vocabulary_dir == str(tmp_path / "vocabulary")
    assert args.workers == 4
    assert args.force is True


def test_main_vocabulary_build_exits_non_zero_when_a_value_is_left_unanswered(
    tmp_path, capsys, monkeypatch
):
    """`specs/PHASE-B.md` §7.18: an unanswered value is a failed run, not a
    result, and the command "reports it and exits non-zero". That exit code
    is the whole contract for anything wrapping this command, and nothing
    asserted it -- the report is prose, the code is the machine-readable
    half. Drives `main` so the return value, not just `stats.complete`, is
    what is checked."""
    import json

    import axial.vocabulary as vocabulary_mod
    from axial.cli import main

    answers_dir = tmp_path / "answers"
    repeated, _unrelated = _write_vocabulary_answers(answers_dir)
    scheme_path = tmp_path / "vocabulary.yaml"
    scheme_path.write_text(_BUILD_SCHEME_YAML, encoding="utf-8")
    vocabulary_dir = tmp_path / "vocabulary"

    real_assign_all = vocabulary_mod._assign_all

    def _lossy(client, pass_name, scheme_text, sample, workers=1):
        assignments = real_assign_all(client, pass_name, scheme_text, sample, workers)
        assignments.pop(1, None)
        return assignments

    monkeypatch.setattr(vocabulary_mod, "_assign_all", _lossy)
    monkeypatch.setattr(
        vocabulary_mod,
        "get_client",
        lambda *a, **kw: _FakeVocabBuildClient(
            {value: "war and state formation" for value in repeated}
        ),
    )

    assert main(
        [
            "vocabulary",
            "build",
            "--columns",
            "mechanism",
            "--answers-dir",
            str(answers_dir),
            "--scheme-path",
            str(scheme_path),
            "--vocabulary-dir",
            str(vocabulary_dir),
        ]
    ) == 1
    captured = capsys.readouterr()

    assert "1 unanswered" in captured.out
    assert "INCOMPLETE" in captured.out
    manifest = json.loads(
        (vocabulary_dir / "mechanism" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["complete"] is False
    assert manifest["unanswered_count"] == 1


def test_main_vocabulary_build_force_re_assigns_after_a_scheme_edit(tmp_path, capsys, monkeypatch):
    """Refusing a scheme-version mismatch by default is right and stays.
    Without a flag, though, the operator's only remedy is moving a
    directory by hand -- and `axial map build` already refuses by default
    and re-spends behind exactly this flag."""
    import json

    import axial.vocabulary as vocabulary_mod
    from axial.cli import main

    answers_dir = tmp_path / "answers"
    repeated, _unrelated = _write_vocabulary_answers(answers_dir)
    scheme_path = tmp_path / "vocabulary.yaml"
    scheme_path.write_text(_BUILD_SCHEME_YAML, encoding="utf-8")
    vocabulary_dir = tmp_path / "vocabulary"
    lookup = {value: "war and state formation" for value in repeated}

    argv = [
        "vocabulary",
        "build",
        "--columns",
        "mechanism",
        "--answers-dir",
        str(answers_dir),
        "--scheme-path",
        str(scheme_path),
        "--vocabulary-dir",
        str(vocabulary_dir),
    ]

    monkeypatch.setattr(vocabulary_mod, "get_client", lambda *a, **kw: _FakeVocabBuildClient(lookup))
    assert main(argv) == 0
    capsys.readouterr()

    scheme_path.write_text(
        _BUILD_SCHEME_YAML.replace("test-v1", "test-v2"), encoding="utf-8"
    )

    # Without the flag: refuse, name both versions, spend nothing.
    refusing = _FakeVocabBuildClient(lookup)
    monkeypatch.setattr(vocabulary_mod, "get_client", lambda *a, **kw: refusing)
    assert main(argv) == 1
    captured = capsys.readouterr()
    assert "test-v1" in captured.err and "test-v2" in captured.err
    assert "--force" in captured.err
    assert refusing.asked_values == []

    # With it: the whole column re-assigns under the new version, and the
    # artifact that was paid for is still on disk beside it.
    forcing = _FakeVocabBuildClient(lookup)
    monkeypatch.setattr(vocabulary_mod, "get_client", lambda *a, **kw: forcing)
    assert main(argv + ["--force"]) == 0
    captured = capsys.readouterr()

    assert len(forcing.asked_values) == 8
    manifest = json.loads(
        (vocabulary_dir / "mechanism" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["scheme_version"] == "test-v2"
    aside = [path for path in vocabulary_dir.iterdir() if path.name != "mechanism"]
    assert len(aside) == 1
    assert json.loads((aside[0] / "manifest.json").read_text(encoding="utf-8"))[
        "scheme_version"
    ] == "test-v1"
    assert "set aside" in captured.out


def test_main_vocabulary_build_writes_then_reuses_then_extends_the_assignment(
    tmp_path, capsys, monkeypatch
):
    """The acceptance criterion (#806's gherkin), all three clauses in one
    test because the second and third are about what the first left on
    disk: build, then rebuild unchanged, then rebuild after a further
    source's answers land.

    No test makes a model call -- the client is injected by monkeypatching
    the same seam `axial.vocabulary.build_vocabulary`'s own `client=None`
    default resolves through (`axial.vocabulary.get_client`)."""
    import json

    import axial.vocabulary as vocabulary_mod
    from axial.cli import main

    answers_dir = tmp_path / "answers"
    repeated, unrelated = _write_vocabulary_answers(answers_dir)
    scheme_path = tmp_path / "vocabulary.yaml"
    scheme_path.write_text(_BUILD_SCHEME_YAML, encoding="utf-8")
    vocabulary_dir = tmp_path / "vocabulary"

    argv = [
        "vocabulary",
        "build",
        "--columns",
        "mechanism",
        "--answers-dir",
        str(answers_dir),
        "--scheme-path",
        str(scheme_path),
        "--vocabulary-dir",
        str(vocabulary_dir),
    ]

    # --- first run: every answered value lands, with a category or a refusal
    first = _FakeVocabBuildClient({value: "war and state formation" for value in repeated})
    monkeypatch.setattr(vocabulary_mod, "get_client", lambda *a, **kw: first)

    assert main(argv) == 0
    captured = capsys.readouterr()

    assignments_path = vocabulary_dir / "mechanism" / "assignments.jsonl"
    manifest_path = vocabulary_dir / "mechanism" / "manifest.json"
    records = [
        json.loads(line) for line in assignments_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 8
    assert sum(1 for r in records if r["category_id"] == "war-and-state-formation") == 5
    assert sum(1 for r in records if r["refused"]) == 3
    assert {r["value"] for r in records if r["refused"]} == set(unrelated)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["scheme_version"] == "test-v1"
    assert manifest["answers_pin"]
    assert manifest["unanswered_count"] == 0
    war = next(c for c in manifest["categories"] if c["category_id"] == "war-and-state-formation")
    assert war["member_count"] == 5
    assert war["source_count"] == 3

    assert "mechanism: 8 answered value(s)" in captured.out
    assert "scheme test-v1" in captured.out
    assert "5 assigned" in captured.out
    assert "3 refused" in captured.out

    # --- second run: unchanged answers, unchanged scheme -> reuse, zero calls
    second = _FakeVocabBuildClient({value: "war and state formation" for value in repeated})
    monkeypatch.setattr(vocabulary_mod, "get_client", lambda *a, **kw: second)
    before_assignments = assignments_path.read_bytes()
    before_manifest = manifest_path.read_bytes()

    assert main(argv) == 0
    captured = capsys.readouterr()

    assert second.asked_values == []
    assert second.calls_for_pass(vocabulary_mod.BUILD_PASS_NAME) == 0
    assert "reused" in captured.out.lower()
    assert assignments_path.read_bytes() == before_assignments
    assert manifest_path.read_bytes() == before_manifest

    # --- third run: one further source's answers land -> only those assign
    new_values = [
        "Conscription for a long war built the tax bureaucracy that outlived it.",
        "A census taken to raise troops became the register the state governed by.",
    ]
    _write_jsonl(
        answers_dir / "delta-2023.jsonl",
        [
            {
                "chunk_id": "delta-2023_1",
                "source_id": "delta-2023",
                "answers": {"mechanism": new_values[0]},
            },
            {
                "chunk_id": "delta-2023_2",
                "source_id": "delta-2023",
                "answers": {"mechanism": new_values[1]},
            },
        ],
    )
    lookup = {value: "war and state formation" for value in repeated}
    lookup.update({value: "war and state formation" for value in new_values})
    third = _FakeVocabBuildClient(lookup)
    monkeypatch.setattr(vocabulary_mod, "get_client", lambda *a, **kw: third)
    before_lines = assignments_path.read_text(encoding="utf-8").splitlines()

    assert main(argv) == 0
    captured = capsys.readouterr()

    assert third.asked_values == new_values
    after_lines = assignments_path.read_text(encoding="utf-8").splitlines()
    assert len(after_lines) == 10
    for line in before_lines:
        assert line in after_lines
    assert "2 newly assigned" in captured.out


def test_main_vocabulary_build_without_a_scheme_for_the_column_fails_naming_it(
    tmp_path, capsys, monkeypatch
):
    """A column the frozen scheme file says nothing about is an operator
    error with a name, not a stack trace and not an empty success."""
    import axial.vocabulary as vocabulary_mod
    from axial.cli import main

    answers_dir = tmp_path / "answers"
    _write_vocabulary_answers(answers_dir)
    scheme_path = tmp_path / "vocabulary.yaml"
    scheme_path.write_text(_BUILD_SCHEME_YAML, encoding="utf-8")

    client = _FakeVocabBuildClient({})
    monkeypatch.setattr(vocabulary_mod, "get_client", lambda *a, **kw: client)

    exit_code = main(
        [
            "vocabulary",
            "build",
            "--columns",
            "comparison",
            "--answers-dir",
            str(answers_dir),
            "--scheme-path",
            str(scheme_path),
            "--vocabulary-dir",
            str(tmp_path / "vocabulary"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "comparison" in captured.err
    assert client.asked_values == []
    assert not (tmp_path / "vocabulary").exists()


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

    def _fake_run_sweep(worklist_path, *, draws, sweep_dir, workers, arm, **_kwargs):
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

    def _fake_run_sweep(worklist_path, *, draws, sweep_dir, workers, arm, **_kwargs):
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

    def _refuse(worklist_path, *, draws, sweep_dir, workers, arm, **_kwargs):
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
# `axial brief run --arm` (issue #807): the named retrieval arm the CLI
# forwards to `run_brief` verbatim, and the `--map` alias it supersedes.
# `run_brief` itself is monkeypatched throughout -- this proves the CLI's
# own wiring, not the engine (that lives in `src/axial/answer/test_record.py`
# and `src/axial/argmap/test_ask.py`).
# ---------------------------------------------------------------------------


def test_build_parser_brief_run_defaults_arm_to_none():
    """`None`, not `'name'` -- so `run_brief`'s own `use_map`/`arm`
    precedence (issue #807) can tell "nothing given" from "name explicitly
    asked for", the same distinction `--map`'s legacy boolean needs."""
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["brief", "run", "brief.yaml"])

    assert args.arm is None
    assert args.use_map is False


def test_build_parser_brief_run_recognises_arm_map_vocab():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["brief", "run", "brief.yaml", "--arm", "map+vocab"])

    assert args.arm == "map+vocab"


def test_build_parser_brief_run_refuses_an_unknown_arm(capsys):
    """Unlike `brief sweep --arm` (issue #808, deliberately no whitelist),
    `brief run --arm` is a fixed, small set (issue #807) -- an unknown value
    is refused by argparse itself, naming the arms that exist."""
    from axial.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["brief", "run", "brief.yaml", "--arm", "bogus"])

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "name" in captured.err
    assert "map+vocab" in captured.err


def _stub_brief_run(monkeypatch, captured: dict):
    import axial.cli as cli_mod
    from axial.answer.record import BriefRunResult

    def _fake_run_brief(brief, *, use_map=False, arm=None, **_kwargs):
        captured["use_map"] = use_map
        captured["arm"] = arm
        return BriefRunResult(
            record={
                "brief_id": brief.brief_id,
                "interrogation": {"disposition": "proceed"},
            },
            path=Path("data/analyses/x.json"),
            markdown_path=Path("data/analyses/x.md"),
            report={},
            report_path=Path("data/runs/x.json"),
        )

    monkeypatch.setattr(cli_mod, "run_brief", _fake_run_brief)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())


def test_main_brief_run_forwards_arm_map_vocab_to_run_brief(tmp_path, monkeypatch):
    import axial.cli as cli_mod

    brief_path = tmp_path / "brief.yaml"
    brief_path.write_text('case: "A case."\nrequest: "A question?"\n', encoding="utf-8")

    captured: dict = {}
    _stub_brief_run(monkeypatch, captured)

    exit_code = cli_mod.main(["brief", "run", str(brief_path), "--arm", "map+vocab"])

    assert exit_code == 0
    assert captured["arm"] == "map+vocab"


def test_main_brief_run_map_flag_still_works_with_no_arm_given(tmp_path, monkeypatch):
    import axial.cli as cli_mod

    brief_path = tmp_path / "brief.yaml"
    brief_path.write_text('case: "A case."\nrequest: "A question?"\n', encoding="utf-8")

    captured: dict = {}
    _stub_brief_run(monkeypatch, captured)

    exit_code = cli_mod.main(["brief", "run", str(brief_path), "--map"])

    assert exit_code == 0
    assert captured["use_map"] is True
    assert captured["arm"] is None


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
    # Both named, not just the first, and on STDERR -- stdout stays a single
    # tab-separated table with one header row that a parser can still read.
    assert "beshara-2011-8410a9059300" in captured.err
    assert "zulu-2020-ffffffffffff" in captured.err
    assert MISSING in captured.err
    assert "beshara-2011-8410a9059300" not in captured.out
    # The forward report is still printed in full on stdout alongside it.
    assert "alpha.pdf" in captured.out
    assert captured.out.count("	status	") == 1


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
    assert "beshara-2011-8410a9059300" in captured.err
    # Nothing was pending, so no client was ever built and no pass ever ran.
    assert "nothing new" in captured.out


def test_main_sources_orphan_check_runs_on_the_drive_backend_too(monkeypatch, capsys):
    """The reverse pass is wired into `_sources`, after whichever backend
    reported, not into either backend -- both ingest against the same
    `data/sources/`, and an unresolvable envelope kills the corpus pin
    whichever one put it there."""
    from axial import cli as cli_mod
    from axial.cli import main
    from axial.sources import MISSING, SourceRecord

    def _fake_drive(check):
        print("name\tstatus\treason")
        print("alpha.pdf\tdone\t")
        return 0

    monkeypatch.setattr(cli_mod, "_sources_drive", _fake_drive)
    monkeypatch.setattr(
        cli_mod,
        "scan_orphaned_envelopes",
        lambda *a, **kw: [SourceRecord("beshara-2011-8410a9059300", MISSING, "no raw source file")],
    )

    exit_code = main(["sources", "--backend", "drive", "--check"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "beshara-2011-8410a9059300" in captured.err
    assert "alpha.pdf" in captured.out


def test_main_sources_keeps_the_backends_own_non_zero_exit_when_nothing_is_orphaned(
    monkeypatch, capsys
):
    """`missing` is not the only thing that can fail this command -- the
    Drive backend returns its own exit code, and a clean reverse pass must
    not swallow it."""
    from axial import cli as cli_mod
    from axial.cli import main

    monkeypatch.setattr(cli_mod, "_sources_drive", lambda check: 3)
    monkeypatch.setattr(cli_mod, "scan_orphaned_envelopes", lambda *a, **kw: [])

    assert main(["sources", "--backend", "drive", "--check"]) == 3


# ---------------------------------------------------------------------------
# The four vocabulary knobs on the command line (issue #822, item 2). #809
# measures the `map+vocab` arm next and the per-category cap binds on every
# category, so a knob nobody can set from the command line would force a code
# change mid-measurement.
# ---------------------------------------------------------------------------


def test_build_parser_brief_run_defaults_the_vocabulary_knobs_to_the_join_declaration():
    from axial.argmap.vocabulary_join import DEFAULT_VOCABULARY_COLUMN, PER_CATEGORY_CAP
    from axial.cli import build_parser

    args = build_parser().parse_args(["brief", "run", "b.yaml"])

    assert args.vocabulary_column == DEFAULT_VOCABULARY_COLUMN
    assert args.vocabulary_level is None
    assert args.vocabulary_dir is None
    assert args.vocabulary_cap == PER_CATEGORY_CAP


def test_build_parser_brief_run_recognises_the_four_vocabulary_flags(tmp_path):
    from axial.cli import build_parser

    args = build_parser().parse_args(
        [
            "brief",
            "run",
            "b.yaml",
            "--arm",
            "map+vocab",
            "--vocabulary-column",
            "stops_holding",
            "--vocabulary-level",
            "2",
            "--vocabulary-dir",
            str(tmp_path / "vocab"),
            "--vocabulary-cap",
            "7",
        ]
    )

    assert args.vocabulary_column == "stops_holding"
    assert args.vocabulary_level == 2
    assert args.vocabulary_dir == str(tmp_path / "vocab")
    assert args.vocabulary_cap == 7


def test_build_parser_brief_sweep_recognises_the_four_vocabulary_flags(tmp_path):
    from axial.cli import build_parser

    args = build_parser().parse_args(
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
            "--vocabulary-column",
            "stops_holding",
            "--vocabulary-level",
            "2",
            "--vocabulary-dir",
            str(tmp_path / "vocab"),
            "--vocabulary-cap",
            "7",
        ]
    )

    assert args.vocabulary_column == "stops_holding"
    assert args.vocabulary_level == 2
    assert args.vocabulary_dir == str(tmp_path / "vocab")
    assert args.vocabulary_cap == 7


def test_main_brief_run_forwards_the_vocabulary_knobs_to_run_brief(tmp_path, monkeypatch):
    import axial.cli as cli_mod

    captured = {}

    def _fake_run_brief(_brief, **kwargs):
        captured.update(kwargs)
        raise cli_mod.AnswerError("stop after the call is captured")

    monkeypatch.setattr(cli_mod, "load_brief", lambda _path: object())
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())
    monkeypatch.setattr(cli_mod, "run_brief", _fake_run_brief)

    exit_code = cli_mod.main(
        [
            "brief",
            "run",
            "b.yaml",
            "--arm",
            "map+vocab",
            "--vocabulary-column",
            "stops_holding",
            "--vocabulary-level",
            "2",
            "--vocabulary-dir",
            str(tmp_path / "vocab"),
            "--vocabulary-cap",
            "7",
        ]
    )

    assert exit_code == 1  # the fake raises once it has captured the call
    assert captured["arm"] == "map+vocab"
    assert captured["vocabulary_column"] == "stops_holding"
    assert captured["vocabulary_level"] == 2
    assert captured["vocabulary_dir"] == Path(tmp_path / "vocab")
    assert captured["vocabulary_cap"] == 7


def test_main_brief_sweep_forwards_the_vocabulary_knobs_to_run_sweep(tmp_path, monkeypatch):
    import axial.cli as cli_mod
    from axial.brief.sweep import SweepSummary

    captured = {}

    def _fake_run_sweep(worklist_path, **kwargs):
        captured.update(kwargs)
        return SweepSummary(
            briefs=[], total_draws=0, ok_count=0, fail_count=0, skip_count=0, arm=kwargs["arm"]
        )

    monkeypatch.setattr(cli_mod, "run_sweep", _fake_run_sweep)

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
            "map+vocab",
            "--vocabulary-column",
            "stops_holding",
            "--vocabulary-level",
            "2",
            "--vocabulary-dir",
            str(tmp_path / "vocab"),
            "--vocabulary-cap",
            "7",
        ]
    )

    assert exit_code == 0
    assert captured["vocabulary_column"] == "stops_holding"
    assert captured["vocabulary_level"] == 2
    assert captured["vocabulary_dir"] == Path(tmp_path / "vocab")
    assert captured["vocabulary_cap"] == 7


# ---------------------------------------------------------------------------
# `axial brief smoke --arm` (issue #822, item 4): the last place an arm name
# could not travel.
# ---------------------------------------------------------------------------


def test_build_parser_brief_smoke_defaults_arm_to_none_so_map_still_decides():
    """`--arm` must default to `None`, not `"name"`: a `"name"` default
    would override `--map` and silently run the name layer."""
    from axial.cli import build_parser

    args = build_parser().parse_args(["brief", "smoke"])

    assert args.arm is None
    assert args.use_map is False


def test_build_parser_brief_smoke_recognises_the_arm_flag():
    from axial.cli import build_parser

    args = build_parser().parse_args(["brief", "smoke", "--arm", "map+vocab"])

    assert args.arm == "map+vocab"


def test_main_brief_smoke_forwards_the_arm_to_run_smoke(tmp_path, monkeypatch):
    import axial.cli as cli_mod
    from axial.brief.smoke import Budgets, SmokeSummary

    captured = {}

    def _fake_run_smoke(**kwargs):
        captured.update(kwargs)
        return SmokeSummary(briefs=[], budgets=Budgets(None, None))

    monkeypatch.setattr(cli_mod, "run_smoke", _fake_run_smoke)

    exit_code = cli_mod.main(
        ["brief", "smoke", "--sweep-dir", str(tmp_path / "smoke"), "--arm", "map+vocab"]
    )

    assert exit_code == 0
    assert captured["arm"] == "map+vocab"


# ---------------------------------------------------------------------------
# `axial eval layers` (issue #809): the per-arm comparison's own CLI surface.
# The report's own behaviour is tested in `axial/eval/test_layers.py`.
# ---------------------------------------------------------------------------


def test_build_parser_eval_layers_collects_every_arm_dir_in_order():
    from axial.cli import build_parser

    args = build_parser().parse_args(
        [
            "eval",
            "layers",
            "--arm-dir",
            "sweeps/name",
            "--arm-dir",
            "sweeps/map",
            "--arm-dir",
            "sweeps/map-vocab",
        ]
    )

    assert args.command == "eval"
    assert args.eval_command == "layers"
    assert args.arm_dirs == ["sweeps/name", "sweeps/map", "sweeps/map-vocab"]


def test_build_parser_eval_layers_requires_at_least_one_arm_dir():
    from axial.cli import build_parser

    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["eval", "layers"])

    assert excinfo.value.code == 2


def test_main_eval_layers_forwards_every_arm_dir_to_compare_arms(monkeypatch, capsys):
    import axial.cli as cli_mod

    captured = {}

    def _fake_compare_arms(sweep_dirs):
        captured["sweep_dirs"] = list(sweep_dirs)
        return "comparison"

    monkeypatch.setattr(cli_mod, "compare_arms", _fake_compare_arms)
    monkeypatch.setattr(cli_mod, "format_layer_comparison", lambda comparison: comparison)

    exit_code = cli_mod.main(
        ["eval", "layers", "--arm-dir", "sweeps/name", "--arm-dir", "sweeps/map"]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert captured["sweep_dirs"] == [Path("sweeps/name"), Path("sweeps/map")]
    assert "comparison" in out


def test_main_eval_layers_reports_a_refusal_on_stderr_and_exits_nonzero(monkeypatch, capsys):
    import axial.cli as cli_mod
    from axial.eval.layers import LayerComparisonError

    def _refuse(sweep_dirs):
        raise LayerComparisonError("arm 'name' ran 3 draws, arm 'map' ran 2")

    monkeypatch.setattr(cli_mod, "compare_arms", _refuse)

    exit_code = cli_mod.main(
        ["eval", "layers", "--arm-dir", "sweeps/name", "--arm-dir", "sweeps/map"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "arm 'name' ran 3 draws, arm 'map' ran 2" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# `axial map purity` (issue #827): the pure-function bag/vocabulary
# cross-tab, CLI-level acceptance coverage. Fixture dirs only -- no `data/`
# dependence, no model call.
# ---------------------------------------------------------------------------


def _purity_write_bag_state(outdir, assignments):
    import json as _json

    outdir.mkdir(parents=True, exist_ok=True)
    state = {
        "config": {"encoder": "test-encoder", "bag_distance_threshold": 0.2},
        "assignments": assignments,
        "centroids": {},
    }
    (outdir / "bag_state.json").write_text(_json.dumps(state), encoding="utf-8")


def _purity_write_map_json(outdir):
    import json as _json

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "map.json").write_text(_json.dumps({"corpus_pin": outdir.name}), encoding="utf-8")


def _purity_write_vocabulary(root, column, assignments, categories):
    import json as _json

    column_dir = root / column
    column_dir.mkdir(parents=True, exist_ok=True)
    (column_dir / "assignments.jsonl").write_text(
        "\n".join(_json.dumps(record) for record in assignments), encoding="utf-8"
    )
    manifest = {
        "column": column,
        "scheme_version": "v1",
        "max_level": 1,
        "categories": categories,
    }
    (column_dir / "manifest.json").write_text(_json.dumps(manifest), encoding="utf-8")


def _purity_assignment(chunk_id, category_id, **overrides):
    record = {
        "chunk_id": chunk_id,
        "source_id": f"{chunk_id}-source",
        "column": "claim",
        "element_index": 0,
        "level": 1,
        "value": f"value for {chunk_id}",
        "category_id": category_id,
        "refused": category_id is None,
    }
    record.update(overrides)
    return record


def _purity_category(category_id):
    return {"category_id": category_id, "name": category_id, "member_count": 0, "source_count": 0}


def test_build_parser_recognises_map_purity_subcommand(tmp_path):
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "map",
            "purity",
            "--column",
            "claim",
            "--pin",
            "abc123",
            "--map-dir",
            str(tmp_path / "map"),
            "--vocabulary-dir",
            str(tmp_path / "vocab"),
            "--level",
            "1",
        ]
    )

    assert args.command == "map"
    assert args.map_command == "purity"
    assert args.column == "claim"
    assert args.pin == "abc123"
    assert args.map_dir == str(tmp_path / "map")
    assert args.vocabulary_dir == str(tmp_path / "vocab")
    assert args.level == 1


def test_main_map_purity_prints_purity_scatter_pairs_and_coverage_for_bags_with_2plus_members(
    tmp_path, capsys
):
    """The acceptance criterion (issue #827, plan §"Acceptance criterion"),
    plus the issue's own added clause: the category-pair confusion table,
    with the two #826 pairs reported by name whether or not they rank."""
    from axial.cli import main

    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _purity_write_map_json(outdir)
    # bag 0: 3 categorised (2x cat-a, 1x cat-b) -- eligible, impure.
    # bag 1: 1 categorised member -- excluded from purity, still counted.
    # "bag-only"/"vocab-only" chunks exercise the coverage gap both ways.
    _purity_write_bag_state(
        outdir,
        {"n1": 0, "n2": 0, "n3": 0, "n4": 1, "bag-only": 0},
    )
    vocabulary_dir = tmp_path / "vocab"
    id_a, id_b = (
        "causal-argument-state-formation-or-power",
        "causal-argument-violence-war-or-conflict",
    )
    _purity_write_vocabulary(
        vocabulary_dir,
        "claim",
        [
            _purity_assignment("n1", "cat-a"),
            _purity_assignment("n2", "cat-a"),
            _purity_assignment("n3", "cat-b"),
            _purity_assignment("n4", "cat-a"),
            _purity_assignment("vocab-only", "cat-a"),
        ],
        categories=[
            _purity_category("cat-a"),
            _purity_category("cat-b"),
            _purity_category(id_a),
            _purity_category(id_b),
        ],
    )

    exit_code = main(
        [
            "map",
            "purity",
            "--column",
            "claim",
            "--pin",
            "pin-1",
            "--map-dir",
            str(map_dir),
            "--vocabulary-dir",
            str(vocabulary_dir),
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "pin: pin-1" in out
    assert "eligible bags: 1" in out
    assert "excluded (fewer than 2 categorised members): 1" in out
    assert "median purity: 0.67" in out
    assert "CATEGORY SCATTER" in out
    assert "cat-a" in out and "cat-b" in out
    assert "CATEGORY PAIR CO-OCCURRENCE" in out
    assert "bag-only (no vocabulary record for this column): 1" in out
    assert "vocabulary-only (no bag): 1" in out
    assert "overlap assigned 2+ categories: 0" in out
    # Issue #827 fix round (reviewer F2): the scatter table's own base is
    # named, and it is NOT the same number as "eligible bags: 1" three lines
    # above -- bag 1 (one categorised member) is scattered but not eligible.
    assert "CATEGORY SCATTER (over 2 bag(s) holding at least one categorised member)" in out
    assert "NAMED PAIRS" in out
    assert f"{id_a} x {id_b}" in out
    assert "absent from the raw ranking (0 bags)" in out


def test_main_map_purity_with_no_pin_uses_the_newest_map_directory(tmp_path, capsys):
    import time

    from axial.cli import main

    map_dir = tmp_path / "map"
    older = map_dir / "pin-older"
    newer = map_dir / "pin-newer"
    _purity_write_map_json(older)
    time.sleep(0.01)
    _purity_write_map_json(newer)
    _purity_write_bag_state(newer, {"n1": 0})
    vocabulary_dir = tmp_path / "vocab"
    _purity_write_vocabulary(
        vocabulary_dir, "claim", [_purity_assignment("n1", "cat-a")], [_purity_category("cat-a")]
    )

    exit_code = main(
        [
            "map",
            "purity",
            "--column",
            "claim",
            "--map-dir",
            str(map_dir),
            "--vocabulary-dir",
            str(vocabulary_dir),
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "pin: pin-newer" in out


def test_main_map_purity_reports_a_missing_bag_state_by_name_not_a_traceback(tmp_path, capsys):
    from axial.cli import main

    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _purity_write_map_json(outdir)  # no bag_state.json written

    exit_code = main(
        [
            "map",
            "purity",
            "--column",
            "claim",
            "--pin",
            "pin-1",
            "--map-dir",
            str(map_dir),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "bag_state.json" in captured.err
    assert "pin-1" in captured.err


def test_main_map_purity_reports_an_unbuilt_vocabulary_column_by_name(tmp_path, capsys):
    from axial.cli import main

    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _purity_write_map_json(outdir)
    _purity_write_bag_state(outdir, {"n1": 0})

    exit_code = main(
        [
            "map",
            "purity",
            "--column",
            "claim",
            "--pin",
            "pin-1",
            "--map-dir",
            str(map_dir),
            "--vocabulary-dir",
            str(tmp_path / "vocab"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "claim" in captured.err
    assert "axial vocabulary build" in captured.err


# ---------------------------------------------------------------------------
# `--named-pair` (issue #827 fix round, reviewer F6): the two #826 claim-
# scheme ids are the CLI's default, never a hardwired gate.
# ---------------------------------------------------------------------------


def test_build_parser_recognises_repeated_named_pair_flag(tmp_path):
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "map",
            "purity",
            "--column",
            "mechanism",
            "--named-pair",
            "cat-a,cat-b",
            "--named-pair",
            "cat-c,cat-d",
        ]
    )

    assert args.named_pairs == ["cat-a,cat-b", "cat-c,cat-d"]


def test_build_parser_map_purity_defaults_named_pair_to_none_so_the_827_default_applies(tmp_path):
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["map", "purity", "--column", "claim"])

    assert args.named_pairs is None


def test_main_map_purity_forwards_named_pair_overrides_to_the_report(tmp_path, capsys):
    from axial.cli import main

    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _purity_write_map_json(outdir)
    _purity_write_bag_state(outdir, {"n1": 0, "n2": 0})
    vocabulary_dir = tmp_path / "vocab"
    _purity_write_vocabulary(
        vocabulary_dir,
        "mechanism",
        [
            _purity_assignment("n1", "war-and-state"),
            _purity_assignment("n2", "elite-competition"),
        ],
        categories=[_purity_category("war-and-state"), _purity_category("elite-competition")],
    )

    exit_code = main(
        [
            "map",
            "purity",
            "--column",
            "mechanism",
            "--pin",
            "pin-1",
            "--map-dir",
            str(map_dir),
            "--vocabulary-dir",
            str(vocabulary_dir),
            "--named-pair",
            "war-and-state,elite-competition",
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    # `_named_pair` sorts the pair alphabetically, the same key shape the
    # ranked table itself uses.
    assert "elite-competition x war-and-state: 1 bag(s)" in out
    # The module's own #826 claim-scheme default was NOT consulted.
    assert "causal-argument-state-formation-or-power" not in out


def test_main_map_purity_reports_a_malformed_named_pair_by_name_not_a_traceback(tmp_path, capsys):
    from axial.cli import main

    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _purity_write_map_json(outdir)
    _purity_write_bag_state(outdir, {"n1": 0})
    vocabulary_dir = tmp_path / "vocab"
    _purity_write_vocabulary(
        vocabulary_dir, "claim", [_purity_assignment("n1", "cat-a")], [_purity_category("cat-a")]
    )

    exit_code = main(
        [
            "map",
            "purity",
            "--column",
            "claim",
            "--pin",
            "pin-1",
            "--map-dir",
            str(map_dir),
            "--vocabulary-dir",
            str(vocabulary_dir),
            "--named-pair",
            "only-one-id",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "only-one-id" in captured.err


# ---------------------------------------------------------------------------
# `axial map grouping-report` (issue #828): both candidate inner splits from
# the approach doc's own §6 -- claim x mechanism intersection, and per-claim-
# category embedding sub-clustering -- computed offline and printed side by
# side. Fixture dirs only; the local encoder/cluster seam
# (`axial.argmap.grouping._default_encoder` / `_agglomerative_cluster`) is
# monkeypatched away so the fast tier never imports sentence-transformers or
# scikit-learn for a report this cheap (issue #828's own "zero model calls").
# ---------------------------------------------------------------------------


def _grouping_write_bag_state(outdir, chunk_ids):
    import json as _json

    outdir.mkdir(parents=True, exist_ok=True)
    state = {
        "config": {"encoder": "test-encoder", "bag_distance_threshold": 0.2},
        "assignments": {chunk_id: 0 for chunk_id in chunk_ids},
        "centroids": {},
    }
    (outdir / "bag_state.json").write_text(_json.dumps(state), encoding="utf-8")


def _grouping_write_map_json(outdir):
    import json as _json

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "map.json").write_text(_json.dumps({"corpus_pin": outdir.name}), encoding="utf-8")


def _grouping_assignment(chunk_id, category_id, value, **overrides):
    record = {
        "chunk_id": chunk_id,
        "source_id": f"{chunk_id}-source",
        "column": "claim",
        "element_index": 0,
        "level": 1,
        "value": value,
        "category_id": category_id,
        "refused": category_id is None,
    }
    record.update(overrides)
    return record


def _grouping_write_vocabulary(root, column, assignments, categories):
    import json as _json

    column_dir = root / column
    column_dir.mkdir(parents=True, exist_ok=True)
    (column_dir / "assignments.jsonl").write_text(
        "\n".join(_json.dumps(record) for record in assignments), encoding="utf-8"
    )
    manifest = {"column": column, "scheme_version": "v1", "max_level": 1, "categories": categories}
    (column_dir / "manifest.json").write_text(_json.dumps(manifest), encoding="utf-8")


def _grouping_category(category_id):
    return {"category_id": category_id, "name": category_id, "member_count": 0, "source_count": 0}


def test_build_parser_recognises_map_grouping_report_subcommand(tmp_path):
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "map",
            "grouping-report",
            "--pin",
            "abc123",
            "--map-dir",
            str(tmp_path / "map"),
            "--vocabulary-dir",
            str(tmp_path / "vocab"),
            "--level",
            "1",
        ]
    )

    assert args.command == "map"
    assert args.map_command == "grouping-report"
    assert args.pin == "abc123"
    assert args.map_dir == str(tmp_path / "map")
    assert args.vocabulary_dir == str(tmp_path / "vocab")
    assert args.level == 1


def test_main_map_grouping_report_prints_both_candidates_side_by_side(
    tmp_path, capsys, monkeypatch
):
    """Acceptance criterion (issue #828): group count, group-size min/median/
    max, passages left ungrouped, and projected extraction slices, for BOTH
    candidates, side by side in one table.

    Fixture: n1-n4 share claim category cat-a, split mech-x (n1, n2) / mech-y
    (n3, n4) on the mechanism axis, so the intersection candidate makes two
    cells of 2. n5 is claim category cat-b with no mechanism record at all --
    ungrouped on the intersection candidate (refused on the mechanism axis),
    its own singleton group on the sub-cluster candidate. n6 has no claim
    category at all -- ungrouped on BOTH candidates. The fake encoder maps a
    value's own text to `len(text) % 2`, and the fake cluster_fn passes that
    straight through as the label, splitting cat-a's four members 3-1
    (n1/n2/n4 land on 0, n3 lands on 1)."""
    from axial.argmap import grouping as grouping_mod
    from axial.cli import main

    def fake_encode(texts):
        import numpy as np

        return np.array([[float(len(text) % 2)] for text in texts])

    def fake_cluster(vectors, _threshold):
        return [int(row[0]) for row in vectors]

    monkeypatch.setattr(grouping_mod, "_default_encoder", lambda: fake_encode)
    monkeypatch.setattr(grouping_mod, "_agglomerative_cluster", fake_cluster)

    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _grouping_write_map_json(outdir)
    chunk_ids = ["n1", "n2", "n3", "n4", "n5", "n6"]
    _grouping_write_bag_state(outdir, chunk_ids)

    vocabulary_dir = tmp_path / "vocab"
    _grouping_write_vocabulary(
        vocabulary_dir,
        "claim",
        [
            _grouping_assignment("n1", "cat-a", "aa"),  # len 2 -> 0
            _grouping_assignment("n2", "cat-a", "bb"),  # len 2 -> 0
            _grouping_assignment("n3", "cat-a", "aaa"),  # len 3 -> 1
            _grouping_assignment("n4", "cat-a", "bbbb"),  # len 4 -> 0
            _grouping_assignment("n5", "cat-b", "c"),
            _grouping_assignment("n6", None, "unassigned", refused=True),
        ],
        categories=[_grouping_category("cat-a"), _grouping_category("cat-b")],
    )
    _grouping_write_vocabulary(
        vocabulary_dir,
        "mechanism",
        [
            _grouping_assignment("n1", "mech-x", "mx1"),
            _grouping_assignment("n2", "mech-x", "mx2"),
            _grouping_assignment("n3", "mech-y", "my1"),
            _grouping_assignment("n4", "mech-y", "my2"),
            # n5, n6: never answered for this column at all.
        ],
        categories=[_grouping_category("mech-x"), _grouping_category("mech-y")],
    )

    exit_code = main(
        [
            "map",
            "grouping-report",
            "--pin",
            "pin-1",
            "--map-dir",
            str(map_dir),
            "--vocabulary-dir",
            str(vocabulary_dir),
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "pin: pin-1" in out
    lines = out.splitlines()

    def row(label):
        return next(line for line in lines if line.strip().startswith(label))

    header = row("claim x mechanism")
    assert "claim + subcluster" in header

    groups_row = row("groups")
    assert groups_row.split()[-2:] == ["2", "3"]

    size_row = row("group size min/median/max")
    assert "2 / 2.00 / 2" in size_row
    assert "1 / 1.00 / 3" in size_row

    ungrouped_row = row("ungrouped")
    assert ungrouped_row.split()[-2:] == ["2", "1"]

    slices_row = row("projected extraction slices")
    assert slices_row.split()[-2:] == ["2", "3"]
    assert "projected extraction slices (EXTRACT_SLICE=" in slices_row

    from axial.argmap.build import BAG_DISTANCE_THRESHOLD

    assert f"subcluster inner distance threshold: {BAG_DISTANCE_THRESHOLD}" in out

    # n5: claim cat-b, no mechanism record at all -- mechanism missing only.
    # n6: no claim category, no mechanism record -- missing both.
    assert (
        "claim x mechanism ungrouped breakdown: "
        "claim missing only 0, mechanism missing only 1, missing both 1" in out
    )


def test_main_map_grouping_report_reports_a_missing_bag_state_by_name_not_a_traceback(
    tmp_path, capsys
):
    from axial.cli import main

    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _grouping_write_map_json(outdir)  # no bag_state.json written

    exit_code = main(
        [
            "map",
            "grouping-report",
            "--pin",
            "pin-1",
            "--map-dir",
            str(map_dir),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "bag_state.json" in captured.err
    assert "pin-1" in captured.err
