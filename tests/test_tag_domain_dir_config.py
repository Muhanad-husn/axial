"""Outer acceptance test for issue #38 (config-driven domain directory
default for `axial tag`, a follow-up to #27).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given config/pipeline.yaml declares paths.domain_dir pointing at a domain
      directory
When  the user runs `axial tag <source>` with no --domain flag
Then  the tagger loads the schema/codebook from that configured directory
And   with no paths.domain_dir declared it falls back to config/domains/syria
And   an explicit --domain still overrides both

See GitHub issue #38. The pattern this mirrors is already locked and green
for the structural-envelope pass: `axial.envelope._default_envelopes_dir`
reads `paths.envelopes_dir` from `config/pipeline.yaml`, falling back to a
hardcoded default when the file/key is absent (see `run_envelope`'s own
`envelopes_dir: Path | None = None` parameter, resolved lazily). This test
locks the same shape for `axial tag`'s `domain_dir`: today
`src/axial/tag.py`'s `run_tag(..., domain_dir: str | Path = DEFAULT_DOMAIN_DIR)`
and `src/axial/cli.py`'s `tag` subparser (`--domain`, default
`str(DEFAULT_DOMAIN_DIR)`) both hardcode `config/domains/syria` and never
consult `config/pipeline.yaml` at all -- this test is red until that
indirection exists.

Seam decision 1 -- driving the config-resolution arms through `run_tag`
directly, not a CLI subprocess, because no `--config` flag exists
-----------------------------------------------------------------------
`tests/test_tag.py`'s existing outer acceptance test drives `axial tag`
via a `uv run axial tag ...` subprocess with `cwd=REPO_ROOT`, which always
reads the ONE real, git-tracked `config/pipeline.yaml` at the repo root --
there is no `--config` flag on the CLI to point it at an isolated fixture
config in a `tmp_path` sandbox. Two options were considered: (a) temporarily
overwrite the real, tracked `config/pipeline.yaml` for the duration of each
test and restore it afterward, or (b) drive the shared resolution logic
through `run_tag` itself, which already accepts `config_path` as a
parameter (mirroring `run_envelope`'s own `config_path` parameter) and is
the exact function `cli.py`'s `_tag()` calls with `args.domain_dir` forwarded
verbatim and no additional logic in between (confirmed by reading
`src/axial/cli.py`'s `_tag()`: `return run_tag(source_path,
domain_dir=domain_dir)` -- nothing else happens to that value). Option (a)
risks corrupting every developer's shared config file if a test crashes
between overwrite and restore; option (b) is fully hermetic and exercises
the same resolution logic the CLI delegates to unchanged. This test picks
(b) for the config-resolution arms (arms 1 and 3 below), and separately
locks the CLI's own `--domain` argparse wiring (test
`test_tag_cli_domain_flag_defaults_to_unresolved_when_omitted` below) so a
future implementer cannot satisfy `run_tag`'s contract while leaving the CLI
layer's `--domain` default hardcoded to a concrete path (which would
silently defeat the whole feature at the actual `axial tag` command line).
The fallback arm (arm 2) is additionally driven end-to-end through the real
CLI subprocess against the real, UNMODIFIED `config/pipeline.yaml` (which
today already declares no `paths.domain_dir` key), since that arm needs no
fixture config at all and so carries none of option (a)'s risk.

Seam decision 2 -- a minimal, version-distinct fixture domain proves the
configured directory was genuinely loaded, not merely tolerated
-----------------------------------------------------------------------
`tests/fixtures/domain/tag38_alt_domain/` is a fixture domain directory
(schema.yaml + codebook.yaml) that is deliberately NOT a copy of Syria's:
its `version` ("9.9-tag38-alt-fixture") is unambiguously different from
Syria's ("0.1"), so a tagged record's `schema_version` can only equal it if
this directory was actually loaded -- loading Syria instead (today's
behavior, since `paths.domain_dir` is never consulted) produces Syria's
`schema_version` and fails this test's assertion. This fixture only declares
`role_in_argument` (whose vocabulary includes `role:claim`, the value
`StubLLMClient`'s canned tag-pass response always returns), so the stub-
driven happy path tags cleanly against it without needing to replicate
Syria's full multi-axis vocabulary (`run_tag` only tags axes the loaded
schema actually declares). Neither this fixture's version string nor its
tag ids are hardcoded as correctness assertions anywhere below except as
the deliberately-chosen, self-evidently-fixture-only literals they are;
the schema is loaded at test time via `load_schema` for every comparison,
exactly as `tests/test_tag.py`'s own seam decisions 2/6/10 require.

Seam decision 3 -- "no --domain flag" modeled as omitting the `domain_dir`
keyword entirely, not passing `None` explicitly
-----------------------------------------------------------------------
`run_tag`'s `domain_dir` parameter's default value is exactly what "no
override was given" means, both today (hardcoded to
`config/domains/syria`) and after this issue is implemented (expected to
become an unresolved sentinel that triggers config-based resolution,
mirroring `run_envelope`'s `envelopes_dir: Path | None = None`). Tests for
"no --domain flag" below therefore never pass `domain_dir` explicitly --
they call `run_tag` with that keyword omitted, so whichever default the
implementer wires in is the one actually exercised. This is also what makes
today's red genuine: omitting `domain_dir` currently resolves to Syria
regardless of `config_path`'s content, so arm 1 fails on a real
`schema_version` mismatch, not a `TypeError` from prematurely assuming the
future sentinel shape.

Seam decision 4 -- fully in-process, hermetic arrangement (no subprocess,
no shared data/ directories) for the `run_tag`-driven arms
-----------------------------------------------------------------------
Unlike `tests/test_tag.py`'s subprocess-based harness, the `run_tag`-driven
tests below call `axial.envelope.run_envelope` and `axial.tag.run_tag`
in-process with an explicit `client=StubLLMClient()` and an explicit
`envelopes_dir` under `tmp_path`, so no `AXIAL_LLM_PROVIDER` environment
variable and no real `data/envelopes/` writes are needed. The one exception
is `data/trees/<source_id>.json`: `axial.extract.extract` (called internally
by `run_envelope`) always persists there regardless of `envelopes_dir`, so
this test pre-places the same committed real tree fixture
(`tests/fixtures/envelope/thesis_paper_tree.json`) that `tests/test_tag.py`
already uses, and relies on `tests/conftest.py`'s autouse
`_isolate_persisted_tree_and_envelope_state` fixture to restore that shared
directory afterward -- exactly as every other acceptance test touching this
fixture already does.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from axial.chunk import HashingEmbedder, run_chunk_embedding
from axial.cli import build_parser
from axial.envelope import compute_source_id, run_envelope
from axial.llm import StubLLMClient
from axial.schema import load_schema
from axial.tag import run_tag

REPO_ROOT = Path(__file__).resolve().parent.parent
ENVELOPE_FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"
TREES_DIR = REPO_ROOT / "data" / "trees"

THESIS_PAPER_PDF = ENVELOPE_FIXTURES_DIR / "thesis_paper.pdf"
THESIS_PAPER_TREE_FIXTURE = ENVELOPE_FIXTURES_DIR / "thesis_paper_tree.json"

SYRIA_DOMAIN_DIR = REPO_ROOT / "config" / "domains" / "syria"
ALT_DOMAIN_DIR = REPO_ROOT / "tests" / "fixtures" / "domain" / "tag38_alt_domain"

REAL_PIPELINE_CONFIG_PATH = REPO_ROOT / "config" / "pipeline.yaml"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# argparse's fallback error for an as-yet-nonexistent subcommand/argument.
# Any of these substrings in combined output means the real `tag` behavior
# was never actually reached -- mirrors tests/test_tag.py's own constant.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _place_tree_fixture(source_pdf: Path, tree_fixture_path: Path) -> Path:
    """Pre-place the committed REAL tree fixture at
    data/trees/<source_id>.json so `axial.extract.extract` reuses it
    verbatim instead of running docling (mirrors tests/test_tag.py)."""
    source_id = compute_source_id(source_pdf)
    tree_path = TREES_DIR / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture_path.read_bytes())
    return tree_path


def _arrange_stored_envelope(envelopes_dir: Path, client: StubLLMClient, config_path: Path) -> dict:
    """Pre-place the real tree fixture, then run `run_envelope` in-process
    with the stub client so a stored envelope exists at
    `envelopes_dir/<source_id>.json` before tagging. Returns the parsed
    envelope dict."""
    _place_tree_fixture(THESIS_PAPER_PDF, THESIS_PAPER_TREE_FIXTURE)
    envelope = run_envelope(
        THESIS_PAPER_PDF,
        client=client,
        envelopes_dir=envelopes_dir,
        config_path=config_path,
    )
    assert envelope.get("source_id"), (
        f"arrange step failed: expected run_envelope to return an envelope "
        f"dict carrying a non-empty 'source_id', got: {envelope!r}"
    )
    return envelope


def _arrange_chunk_artifact(chunks_dir: Path, config_path: Path) -> None:
    """Write the real, on-disk chunk artifact for the fixture IN-PROCESS
    (`axial.chunk.run_chunk_embedding`, the stub/offline `HashingEmbedder`)
    at `chunks_dir` (issue #154 slice 04: `axial tag` no longer computes
    chunks itself -- it reads `<chunks_dir>/<source_id>.jsonl` via
    `axial.chunk.read_chunks`, and no longer accepts an `envelopes_dir`
    parameter at all). Requires `_place_tree_fixture`/`_arrange_stored_
    envelope` to have already placed the persisted tree this reads."""
    run_chunk_embedding(
        THESIS_PAPER_PDF,
        embedder=HashingEmbedder(),
        chunks_dir=chunks_dir,
        config_path=config_path,
    )


def _write_pipeline_config(config_path: Path, paths: dict[str, str]) -> None:
    """Write a minimal `config/pipeline.yaml`-shaped file at `config_path`
    with the given `paths:` block (no `llm:` block needed -- every call
    below passes an explicit `client`, so provider resolution is never
    exercised)."""
    config_path.write_text(
        yaml.safe_dump({"paths": paths}, sort_keys=True),
        encoding="utf-8",
    )


def _existing_envelope_files() -> set[Path]:
    envelopes_dir = REPO_ROOT / "data" / "envelopes"
    if not envelopes_dir.exists():
        return set()
    return set(envelopes_dir.glob("*.json"))


@pytest.fixture
def clean_envelopes():
    """Snapshot data/envelopes/*.json before the test and delete any file
    the test caused to appear (mirrors tests/test_tag.py's own fixture of
    the same name) -- only needed by the real-CLI-subprocess test below,
    which -- unlike the in-process tests above -- necessarily writes into
    the shared, real data/envelopes/ directory."""
    before = _existing_envelope_files()
    yield
    after = _existing_envelope_files()
    for created in after - before:
        created.unlink()


def test_tag_resolves_domain_dir_from_pipeline_config_when_no_override(tmp_path):
    """Arm 1 (issue #38 Gherkin): config/pipeline.yaml's paths.domain_dir,
    when declared, is what `axial tag` loads its schema/codebook from when
    no --domain override is given -- proven by a tagged record's
    schema_version matching the FIXTURE domain's own version, not Syria's
    (seam decision 2). This is the arm expected to fail today: `run_tag`
    currently ignores config_path for domain resolution entirely and always
    resolves to Syria regardless of what config declares."""
    alt_schema = load_schema(str(ALT_DOMAIN_DIR))
    syria_schema = load_schema(str(SYRIA_DOMAIN_DIR))
    assert alt_schema.version != syria_schema.version, (
        "test setup invariant broken: the fixture domain's version must "
        "differ from Syria's, or this test cannot actually distinguish "
        "which directory was loaded"
    )

    envelopes_dir = tmp_path / "envelopes"
    chunks_dir = tmp_path / "chunks"
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path, {"domain_dir": str(ALT_DOMAIN_DIR)})

    client = StubLLMClient()
    _arrange_stored_envelope(envelopes_dir, client, config_path)
    _arrange_chunk_artifact(chunks_dir, config_path)

    # --- the acceptance criterion itself: no `domain_dir` override given,
    # so resolution must come from config_path's paths.domain_dir (seam
    # decision 3: omitted, never passed as an explicit None) ---
    records = run_tag(
        THESIS_PAPER_PDF,
        client=client,
        chunks_dir=chunks_dir,
        config_path=config_path,
    )

    assert records, (
        f"expected at least one tagged record, got none. config_path "
        f"declared paths.domain_dir={str(ALT_DOMAIN_DIR)!r}"
    )
    for record in records:
        assert record.get("schema_version") == alt_schema.version, (
            f"expected `axial tag` (no --domain override) to load its "
            f"schema/codebook from config/pipeline.yaml's declared "
            f"paths.domain_dir ({str(ALT_DOMAIN_DIR)!r}, version "
            f"{alt_schema.version!r}) -- issue #38 Gherkin: 'the tagger "
            f"loads the schema/codebook from that configured directory' -- "
            f"got schema_version {record.get('schema_version')!r} instead "
            f"(Syria's own version is {syria_schema.version!r}; getting "
            f"that here would mean paths.domain_dir was silently ignored "
            f"and Syria was loaded regardless). Full record: {record!r}"
        )
        role = record.get("role_in_argument")
        assert role in alt_schema.axes["role_in_argument"].tag_ids, (
            f"expected tagged record's role_in_argument to be a member of "
            f"the CONFIGURED fixture domain's own vocabulary "
            f"{sorted(alt_schema.axes['role_in_argument'].tag_ids)}, got "
            f"{role!r} (full record: {record!r})"
        )


def test_tag_falls_back_to_syria_domain_when_pipeline_config_declares_no_domain_dir(tmp_path):
    """Arm 2 (issue #38 Gherkin): 'with no paths.domain_dir declared it
    falls back to config/domains/syria' -- driven through `run_tag`
    in-process with a config file whose paths: block declares OTHER keys
    but not domain_dir, mirroring how the real config/pipeline.yaml looks
    today (envelopes_dir/vault_dir declared, domain_dir absent)."""
    syria_schema = load_schema(str(SYRIA_DOMAIN_DIR))

    envelopes_dir = tmp_path / "envelopes"
    chunks_dir = tmp_path / "chunks"
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(
        config_path,
        {"envelopes_dir": str(envelopes_dir), "vault_dir": str(tmp_path / "vault")},
    )

    client = StubLLMClient()
    _arrange_stored_envelope(envelopes_dir, client, config_path)
    _arrange_chunk_artifact(chunks_dir, config_path)

    records = run_tag(
        THESIS_PAPER_PDF,
        client=client,
        chunks_dir=chunks_dir,
        config_path=config_path,
    )

    assert records, "expected at least one tagged record, got none"
    for record in records:
        assert record.get("schema_version") == syria_schema.version, (
            f"expected `axial tag` to fall back to config/domains/syria "
            f"(version {syria_schema.version!r}) when config/pipeline.yaml "
            f"declares no paths.domain_dir key (issue #38 Gherkin), got "
            f"schema_version {record.get('schema_version')!r} (full "
            f"record: {record!r})"
        )


def test_tag_cli_end_to_end_falls_back_to_syria_with_real_pipeline_config(clean_envelopes):
    """Arm 2, driven end-to-end through the REAL `axial tag` CLI subprocess
    against the real, unmodified config/pipeline.yaml (which today already
    declares no paths.domain_dir key -- see config/pipeline.yaml at the repo
    root). No fixture config is written or mutated by this test (seam
    decision 1): this is a genuine, zero-risk full-stack confirmation of the
    fallback arm through the actual command line, complementing the
    in-process test above."""
    assert REAL_PIPELINE_CONFIG_PATH.is_file(), (
        f"test setup invariant broken: expected the real {REAL_PIPELINE_CONFIG_PATH} to exist"
    )
    real_config_text = REAL_PIPELINE_CONFIG_PATH.read_text(encoding="utf-8")
    real_config = yaml.safe_load(real_config_text) or {}
    assert "domain_dir" not in (real_config.get("paths") or {}), (
        "test setup invariant broken: the real config/pipeline.yaml must "
        "declare no paths.domain_dir key for this arm to actually exercise "
        "the fallback path -- if this now fails, the repo's real pipeline "
        "config gained a paths.domain_dir key and this test's premise no "
        "longer holds"
    )

    syria_schema = load_schema(str(SYRIA_DOMAIN_DIR))

    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "stub"

    # --- arrange: a stored envelope must exist before `axial tag` can run
    # (mirrors tests/test_tag.py's own `_arrange_stored_envelope`); this
    # necessarily writes into the shared, real data/envelopes/ directory
    # since this test drives the real CLI against the real config, with no
    # envelopes_dir override available from the command line ---
    _place_tree_fixture(THESIS_PAPER_PDF, THESIS_PAPER_TREE_FIXTURE)
    envelope_result = subprocess.run(
        ["uv", "run", "axial", "envelope", str(THESIS_PAPER_PDF)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert envelope_result.returncode == 0, (
        f"arrange step failed: expected exit code 0 for `axial envelope` "
        f"on the fixture with the stub LLM provider, got "
        f"{envelope_result.returncode}\nstdout: {envelope_result.stdout!r}\n"
        f"stderr: {envelope_result.stderr!r}"
    )

    # issue #154 slice 04: `axial tag` no longer computes chunks itself --
    # it reads `data/chunks/<source_id>.jsonl` (via `axial.chunk.
    # read_chunks`) and fails clearly if absent. Write it here, in-process,
    # into the SAME cwd-relative `data/chunks/` the `axial tag` subprocess
    # below (cwd=REPO_ROOT) reads from.
    run_chunk_embedding(THESIS_PAPER_PDF, embedder=HashingEmbedder())

    result = subprocess.run(
        ["uv", "run", "axial", "tag", str(THESIS_PAPER_PDF)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )

    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `tag` behavior path, not an argparse "
            f"fallback (found {marker!r})\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial tag <fixture>` (no --domain) "
        f"against the real, unmodified config/pipeline.yaml, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    records = json.loads(result.stdout.strip())
    assert isinstance(records, list) and records, (
        f"expected a non-empty JSON array of tagged records on stdout, got: {result.stdout!r}"
    )
    for record in records:
        assert record.get("schema_version") == syria_schema.version, (
            f"expected `axial tag <fixture>` (no --domain flag, real "
            f"config/pipeline.yaml with no paths.domain_dir declared) to "
            f"fall back to config/domains/syria (version "
            f"{syria_schema.version!r}), got schema_version "
            f"{record.get('schema_version')!r} (full record: {record!r})"
        )


def test_tag_explicit_domain_override_wins_over_configured_domain_dir(tmp_path):
    """Arm 3 (issue #38 Gherkin): 'an explicit --domain still overrides
    both' -- config/pipeline.yaml's paths.domain_dir names the FIXTURE
    domain, but an explicit domain_dir override (mirroring the CLI's
    --domain flag, which cli.py's _tag() forwards to run_tag's domain_dir
    parameter completely unchanged) names Syria; Syria must win."""
    syria_schema = load_schema(str(SYRIA_DOMAIN_DIR))
    alt_schema = load_schema(str(ALT_DOMAIN_DIR))
    assert syria_schema.version != alt_schema.version, (
        "test setup invariant broken: the two domains' versions must differ"
    )

    envelopes_dir = tmp_path / "envelopes"
    chunks_dir = tmp_path / "chunks"
    config_path = tmp_path / "pipeline.yaml"
    # config points at the FIXTURE domain -- the override below must still
    # win over this.
    _write_pipeline_config(config_path, {"domain_dir": str(ALT_DOMAIN_DIR)})

    client = StubLLMClient()
    _arrange_stored_envelope(envelopes_dir, client, config_path)
    _arrange_chunk_artifact(chunks_dir, config_path)

    records = run_tag(
        THESIS_PAPER_PDF,
        client=client,
        chunks_dir=chunks_dir,
        config_path=config_path,
        domain_dir=str(SYRIA_DOMAIN_DIR),
    )

    assert records, "expected at least one tagged record, got none"
    for record in records:
        assert record.get("schema_version") == syria_schema.version, (
            f"expected an explicit domain_dir override "
            f"({str(SYRIA_DOMAIN_DIR)!r}, version {syria_schema.version!r}) "
            f"to win over config/pipeline.yaml's configured "
            f"paths.domain_dir ({str(ALT_DOMAIN_DIR)!r}, version "
            f"{alt_schema.version!r}) -- issue #38 Gherkin: 'an explicit "
            f"--domain still overrides both' -- got schema_version "
            f"{record.get('schema_version')!r} (full record: {record!r})"
        )


def test_tag_cli_domain_flag_defaults_to_unresolved_when_omitted():
    """CLI-wiring guard (issue #38): `axial tag`'s `--domain` argparse
    default must NOT be a hardcoded concrete path -- if it were, the CLI
    layer would silently ignore config/pipeline.yaml's paths.domain_dir even
    if the resolution logic elsewhere (run_tag / a future
    _default_domain_dir) is correctly wired, since cli.py's _tag() forwards
    args.domain_dir to run_tag(domain_dir=...) verbatim with no further
    logic (confirmed by reading src/axial/cli.py). This test only inspects
    argparse's own parsed defaults -- no source file, no subprocess, no
    network -- so it is a cheap, sharp guard against exactly that failure
    mode, complementing the run_tag-level tests above which cannot see
    cli.py's own argument wiring at all.

    Also locks that an explicit --domain value still parses through
    unchanged (the CLI half of arm 3)."""
    parser = build_parser()

    omitted_args = parser.parse_args(["tag", "irrelevant-source.pdf"])
    assert omitted_args.domain_dir is None, (
        f"expected `axial tag`'s --domain flag to default to None (an "
        f"unresolved sentinel) so the tag pass can resolve its default "
        f"from config/pipeline.yaml's paths.domain_dir when no --domain "
        f"flag is given (issue #38 Gherkin: 'the user runs `axial tag "
        f"<source>` with no --domain flag'), got a hardcoded default of "
        f"{omitted_args.domain_dir!r} instead"
    )

    explicit_args = parser.parse_args(
        ["tag", "irrelevant-source.pdf", "--domain", "some/explicit/domain"]
    )
    assert explicit_args.domain_dir == "some/explicit/domain", (
        f"expected an explicit --domain value to still parse through "
        f"unchanged, got {explicit_args.domain_dir!r}"
    )
