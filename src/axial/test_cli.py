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


def test_build_parser_recognises_tag_subcommand_with_default_domain():
    """`--domain` omitted defaults to `None` (an unresolved sentinel), not a
    hardcoded path -- `run_tag` resolves it from `config/pipeline.yaml`'s
    `paths.domain_dir` (falling back to `DEFAULT_DOMAIN_DIR`) when omitted
    (issue #38)."""
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["tag", "some/source.pdf"])

    assert args.command == "tag"
    assert args.source_path == "some/source.pdf"
    assert args.domain_dir is None


def test_build_parser_recognises_tag_subcommand_domain_override():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["tag", "some/source.pdf", "--domain", "custom/domain"])

    assert args.domain_dir == "custom/domain"


def test_main_tag_against_a_tag_error_is_nonzero_and_prints_error(monkeypatch, capsys):
    import axial.cli as cli_mod
    from axial.tag import TagError

    def _boom(source_path, domain_dir):
        raise TagError("simulated tag failure")

    monkeypatch.setattr(
        cli_mod, "run_tag", lambda source_path, domain_dir: _boom(source_path, domain_dir)
    )

    exit_code = cli_mod.main(["tag", "some/source.pdf"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "simulated tag failure" in captured.err


def test_build_parser_recognises_artifacts_subcommand_with_default_domain():
    from axial.artifacts import DEFAULT_DOMAIN_DIR
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["artifacts", "some-source.pdf"])

    assert args.command == "artifacts"
    assert args.source_path == "some-source.pdf"
    assert args.domain == str(DEFAULT_DOMAIN_DIR)


def test_build_parser_recognises_artifacts_domain_override():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["artifacts", "some-source.pdf", "--domain", "some/other/domain"])

    assert args.domain == "some/other/domain"


def test_main_artifacts_prints_error_and_returns_nonzero_on_artifacts_error(monkeypatch, capsys):
    import axial.cli as cli_mod
    from axial.artifacts import ArtifactsError

    def _boom(source_path, domain_dir=None):
        raise ArtifactsError("simulated artifacts failure")

    monkeypatch.setattr(cli_mod, "run_artifacts", _boom)

    exit_code = cli_mod.main(["artifacts", "some-source.pdf"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "simulated artifacts failure" in captured.err


def test_main_eval_prints_error_and_returns_nonzero_on_malformed_polity_canonical_map(
    monkeypatch, capsys
):
    """`run_eval` can raise a `PolityCanonicalError` subclass (#215's alias
    fold reads `polity_canonical.yaml`, #205) when the map is malformed --
    `_eval()` must catch it via the repo's `error: ...` / exit-1 convention,
    not let it surface as a raw traceback (mirrors `_polity_report`'s own
    `except PolityCanonicalError`, #215 stage-2 review)."""
    import axial.cli as cli_mod
    from axial.polity_canonical import MalformedPolityCanonicalError

    def _boom():
        raise MalformedPolityCanonicalError(
            Path("some/polity_canonical.yaml"), "simulated malformed map"
        )

    monkeypatch.setattr(cli_mod, "run_eval", _boom)

    exit_code = cli_mod.main(["eval"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "simulated malformed map" in captured.err
    assert "Traceback" not in captured.err
