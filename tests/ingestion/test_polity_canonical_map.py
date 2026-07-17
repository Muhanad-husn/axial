"""Outer acceptance test for issue #205, slice 01 ("Offline canonical polity
normalization map") of the polity-normalization feature.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fixture domain with a `polity_canonical.yaml` canonical tree (United
      Kingdom{aliases: Britain, UK; children: Scotland, England}; Soviet
      Union{aliases: USSR}; Syria; Lebanon; Ottoman Empire[historical])
And   a staged vault of prose notes carrying polity verbatims: "Britain",
      "UK", "Scotland", "North Korea", "South Korea", "USSR", "Syria and
      Lebanon", "Freedonia" (unmapped)
When  the user runs `axial polity report`
Then  "Britain" and "UK" canonicalize to United Kingdom, "Scotland" to the
      Scotland child (NOT to United Kingdom), "USSR" to Soviet Union
And   "North Korea" and "South Korea" are NOT collapsed (distinct -- both
      unmapped candidates here, never merged into each other or any node)
And   "Syria and Lebanon" is surfaced as a multi-polity leak flag, never
      folded
And   "Freedonia" passes through unchanged and is reported as a candidate
      with its occurrence count and source note ids (exit 0 -- non-fatal)
And   the notification prints the candidate count + list (and a clean
      "nothing to resolve" confirmation when the set is empty)
When  the operator edits `polity_canonical.yaml` to add "Freedonia" as a new
      canonical node and re-runs `axial polity report`
Then  "Freedonia" is now mapped and no longer a candidate -- the edit+rerun
      changes output deterministically
And   `axial polity build` over the staged vault emits a deterministic seed
      tree (same vault -> identical observable output)

See plans/polity-normalization/01-canonical-map.md (this slice's plan) and
specs/PRODUCT.md Appendix C (the `polity` free-text + downstream-
normalization rule: "faithful naming preserved upstream ... this map is a
downstream reconciliation layer, never a tag-time gate") and Sec 11 step 7.
This pass is deterministic, offline, and model-free (no LLM/stub needed):
`axial polity report` and `axial polity build` are pure, cwd-scoped CLI
commands over a fixture canonical-map file and a staged vault of prose
notes -- never the real gitignored `data/vault` or the real
`config/domains/syria/polity_canonical.yaml`.

Fixture/isolation mechanism: mirrors tests/ingestion/test_tag_polity_capture.py
exactly -- `_run_axial` shells `uv run --project <repo> axial ...` with `cwd`
pinned to a fresh, isolated per-test staging root (`isolated_vault_root` from
tests/conftest.py, or an equivalent hand-built root via `tmp_path_factory`
for the two-root build-determinism test below); `_assert_not_argparse_fallback`
guards every invocation against a not-yet-registered `polity` subcommand
tree, so an unmet `axial polity report`/`build` fails this test as "unmet
behavior", never silently as "unknown command"; `isolated_vault_root` already
stages a read-only copy of the real domain's `schema.yaml`/`codebook.yaml`
under `<root>/config/domains/syria/` (the default, cwd-relative domain dir
every `axial` subcommand resolves) -- this test additionally writes a FIXTURE
`polity_canonical.yaml` into that same directory, and writes its own staged
vault prose notes directly under `<root>/data/vault/prose/` (the default,
cwd-relative vault dir), bypassing `axial tag`/`axial vault write` entirely
since this pass needs no LLM and no real tag-pass run to exercise.

Seam decision -- `axial polity report`'s structured-output contract
-----------------------------------------------------------------------
Neither the spec nor the slice plan pins an exact print format for
`report`'s "notification" (only that it prints "the candidate count + list"
and the leak flags, and a clean confirmation when there is nothing to
resolve). Left fully open, the Gherkin's most important semantic claims --
"Scotland resolves to the Scotland child, NOT to United Kingdom", "North
Korea and South Korea are never collapsed into each other" -- would be
unobservable from the CLI surface if `report` only ever printed the
*unmapped* candidates and leaks (a "clean" verbatim's specific resolved
node would never appear anywhere in the output at all). This test locks a
structured contract, deliberately consistent with this codebase's existing
convention for programmatically-relevant `axial` subcommands (`axial tag`
emits JSON records on stdout and reserves stderr for non-fatal candidate/
diagnostic notifications -- see tests/ingestion/test_tag_polity_capture.py):

  - stdout is a single, bare JSON object with (at least) three top-level
    keys: `mapped` (list of `{verbatim, canonical}` entries -- every
    verbatim that folded to a canonical node, naming which node), `candidates`
    (list of `{verbatim, count, notes}` entries -- every unmapped verbatim,
    its occurrence count, and the source note/chunk ids it came from), and
    `leaks` (list of `{verbatim, parts}` entries -- every multi-polity leak
    flag, never folded to a single node); plus a top-level `candidate_count`
    integer.
  - stderr carries the human-readable notification: the candidate/leak
    verbatims named in plain text (mirrors `axial tag`'s stderr diagnostic
    for an out-of-examples `polity` value), and a "nothing to resolve"-style
    confirmation phrase when there are no candidates/leaks at all.

If the real implementation lands on a different split, that is spec drift
against this locked test, not a reason to weaken it quietly.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DOMAIN_DIR_PARTS = ("config", "domains", "syria")
DOMAIN_FILES = ("schema.yaml", "codebook.yaml")

COUNTRY_CASE_SCOPE_VALUE = "scope:country-case"

# argparse's fallback error for an as-yet-nonexistent subcommand/flag. Any of
# these substrings in the combined output means the target subcommand's
# logic was never actually exercised -- mirrors every other test in this
# family (tests/ingestion/test_tag_polity_capture.py and siblings).
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)

# The fixture canonical tree from this slice's own Gherkin: United Kingdom
# (aliases Britain/UK; children Scotland/England), Soviet Union (alias
# USSR), and three standalone nodes (Syria, Lebanon, Ottoman Empire).
BASE_CANONICAL_YAML = """version: 1
nodes:
  - canonical: United Kingdom
    kind: modern
    aliases: [Britain, UK]
    children:
      - canonical: Scotland
        kind: modern
        aliases: []
      - canonical: England
        kind: modern
        aliases: []
  - canonical: Soviet Union
    kind: historical
    aliases: [USSR]
  - canonical: Syria
    kind: modern
    aliases: []
  - canonical: Lebanon
    kind: modern
    aliases: []
  - canonical: Ottoman Empire
    kind: historical
    aliases: []
"""

# The same tree, hand-edited to add "Freedonia" as a brand-new root canonical
# node -- the resolution-loop scenario's post-edit fixture.
CANONICAL_YAML_WITH_FREEDONIA = (
    BASE_CANONICAL_YAML
    + """  - canonical: Freedonia
    kind: modern
    aliases: []
"""
)

# The main scenario's staged vault: one prose note per (chunk_id, polity
# verbatim) pair. Two distinct Freedonia notes so its candidate entry's
# occurrence-count aggregation is genuinely exercised, not merely count==1.
MIXED_VAULT_POLITIES = [
    ("fixture-src_001_body_001", "Britain"),
    ("fixture-src_002_body_001", "UK"),
    ("fixture-src_003_body_001", "Scotland"),
    ("fixture-src_004_body_001", "North Korea"),
    ("fixture-src_005_body_001", "South Korea"),
    ("fixture-src_006_body_001", "USSR"),
    ("fixture-src_007_body_001", "Syria and Lebanon"),
    ("fixture-src_008_body_001", "Freedonia"),
    ("fixture-src_009_body_001", "Freedonia"),
]

FREEDONIA_NOTE_IDS = {"fixture-src_008_body_001", "fixture-src_009_body_001"}

# The clean-vault scenario: every verbatim maps cleanly (Britain -> United
# Kingdom via alias, Syria -> Syria verbatim), so `report` should confirm
# there is nothing to resolve.
CLEAN_VAULT_POLITIES = [
    ("clean-src_001_body_001", "Britain"),
    ("clean-src_002_body_001", "Syria"),
]

# The build-determinism scenario's staged vault (independent of any
# canonical-map fixture -- `axial polity build` is a raw harvest of distinct
# verbatims from vault prose, per the plan).
BUILD_VAULT_POLITIES = [
    ("build-src_001_body_001", "Britain"),
    ("build-src_002_body_001", "UK"),
    ("build-src_003_body_001", "Freedonia"),
]

NOTHING_TO_RESOLVE_PHRASES = (
    "nothing to resolve",
    "no candidates",
    "all polities resolved",
    "fully resolved",
    "nothing left to resolve",
)


def _stage_domain_files(root: Path) -> Path:
    """Copy the real domain's schema.yaml/codebook.yaml into <root>'s
    default, cwd-relative domain dir (mirrors tests/conftest.py's
    `isolated_vault_root`) -- used for the build-determinism scenario, which
    hand-builds its own isolated roots via `tmp_path_factory` rather than
    requesting the `isolated_vault_root` fixture twice in one test."""
    domain_dir = root.joinpath(*DOMAIN_DIR_PARTS)
    domain_dir.mkdir(parents=True, exist_ok=True)
    for filename in DOMAIN_FILES:
        shutil.copyfile(
            REPO_ROOT.joinpath(*DOMAIN_DIR_PARTS, filename), domain_dir / filename
        )
    return domain_dir


def _write_canonical_map(root: Path, yaml_text: str) -> Path:
    """Write the fixture `polity_canonical.yaml` into <root>'s default,
    cwd-relative domain dir (sibling to schema.yaml/codebook.yaml, per the
    plan's artifact-location decision)."""
    domain_dir = root.joinpath(*DOMAIN_DIR_PARTS)
    domain_dir.mkdir(parents=True, exist_ok=True)
    path = domain_dir / "polity_canonical.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


def _prose_dir(root: Path) -> Path:
    return root / "data" / "vault" / "prose"


def _write_prose_note(root: Path, chunk_id: str, polity: str) -> Path:
    """Write one staged prose note directly under <root>'s default,
    cwd-relative vault prose dir, carrying the nested
    `empirical_scope: {value: scope:country-case, polity: <verbatim>}`
    frontmatter shape (mirrors tests/ingestion/test_tag_polity_capture.py's
    real `axial vault write` output shape -- this test bypasses `axial tag`/
    `axial vault write` entirely since the canonical-map pass is model-free
    and needs no LLM/stub tag-pass run)."""
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "Body",
        "chunk_text": f"Prose discussing {polity} at some length.",
        "empirical_scope": {"value": COUNTRY_CASE_SCOPE_VALUE, "polity": polity},
        "artifact_refs": [],
    }
    body = f"# Body\n\nProse discussing {polity} at some length.\n"
    frontmatter_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    note_text = f"---\n{frontmatter_yaml}---\n{body}"

    prose_dir = _prose_dir(root)
    prose_dir.mkdir(parents=True, exist_ok=True)
    path = prose_dir / f"{chunk_id}.md"
    path.write_text(note_text, encoding="utf-8")
    return path


def _stage_vault(root: Path, polities: list[tuple[str, str]]) -> None:
    for chunk_id, polity in polities:
        _write_prose_note(root, chunk_id, polity)


def _run_axial(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess, command: str) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `{command}` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `{command}` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _parse_report_json(result: subprocess.CompletedProcess) -> dict:
    """Parse `axial polity report`'s stdout as a single, bare JSON object
    (this test's locked structured-output contract -- see the module
    docstring's seam decision)."""
    stripped = result.stdout.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"expected `axial polity report`'s stdout to be a single "
            f"parseable JSON object carrying (at least) 'mapped', "
            f"'candidates', and 'leaks' lists plus a 'candidate_count' "
            f"integer -- this test's locked structured-output contract, "
            f"consistent with `axial tag`'s own JSON-records-on-stdout "
            f"convention -- got a JSONDecodeError ({exc}) on stdout: "
            f"{result.stdout!r}\nstderr: {result.stderr!r}"
        ) from None
    assert isinstance(data, dict), (
        f"expected `axial polity report`'s stdout to parse to a JSON "
        f"object (mapping), got {type(data).__name__}: {data!r}"
    )
    for key in ("mapped", "candidates", "leaks"):
        assert isinstance(data.get(key), list), (
            f"expected `axial polity report`'s JSON output to carry a "
            f"top-level {key!r} list, got {data.get(key)!r} (full "
            f"output: {data!r})"
        )
    assert isinstance(data.get("candidate_count"), int), (
        f"expected `axial polity report`'s JSON output to carry a "
        f"top-level integer 'candidate_count', got "
        f"{data.get('candidate_count')!r} (full output: {data!r})"
    )
    assert data["candidate_count"] == len(data["candidates"]), (
        f"expected 'candidate_count' to equal the length of the "
        f"'candidates' list, got candidate_count={data['candidate_count']!r} "
        f"but len(candidates)={len(data['candidates'])} (full output: {data!r})"
    )
    return data


def _mapped_canonical(report: dict, verbatim: str) -> str | None:
    for entry in report["mapped"]:
        if entry.get("verbatim") == verbatim:
            return entry.get("canonical")
    return None


def _candidate_entry(report: dict, verbatim: str) -> dict | None:
    for entry in report["candidates"]:
        if entry.get("verbatim") == verbatim:
            return entry
    return None


def _leak_entry(report: dict, verbatim: str) -> dict | None:
    for entry in report["leaks"]:
        if entry.get("verbatim") == verbatim:
            return entry
    return None


def test_polity_report_resolves_aliases_flags_leaks_and_surfaces_candidates(isolated_vault_root):
    """The main Gherkin scenario: aliases fold to their canonical node
    (Britain/UK -> United Kingdom, USSR -> Soviet Union), a child alias
    resolves to the child not the parent (Scotland -> Scotland, never United
    Kingdom), siblings never collapse into each other (North Korea/South
    Korea stay distinct unmapped candidates), a multi-polity string is
    flagged as a leak and never folded (Syria and Lebanon), and an unmapped
    verbatim passes through as a non-fatal candidate with its occurrence
    count and source note ids (Freedonia)."""
    root = isolated_vault_root
    _write_canonical_map(root, BASE_CANONICAL_YAML)
    _stage_vault(root, MIXED_VAULT_POLITIES)

    result = _run_axial(["polity", "report"], root)
    _assert_not_argparse_fallback(result, "polity report")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial polity report` -- unmapped "
        f"candidates and leaks are non-fatal by design (a living "
        f"reconciliation layer, never a closed gate), got exit code "
        f"{result.returncode}\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    report = _parse_report_json(result)

    # -- Britain and UK fold to United Kingdom via explicit alias --
    for alias in ("Britain", "UK"):
        assert _mapped_canonical(report, alias) == "United Kingdom", (
            f"expected {alias!r} to canonicalize to 'United Kingdom' (an "
            f"explicit alias of that node), got "
            f"{_mapped_canonical(report, alias)!r} (full report: {report!r})"
        )

    # -- Scotland resolves to the Scotland CHILD, never blanket-merged up
    # into its parent United Kingdom --
    scotland_canonical = _mapped_canonical(report, "Scotland")
    assert scotland_canonical == "Scotland", (
        f"expected 'Scotland' to canonicalize to the 'Scotland' child node "
        f"itself, NOT to be blanket-merged into its parent 'United "
        f"Kingdom' (distinguish, don't blanket-merge -- sub-polities must "
        f"never collapse under a naive parent/child rule), got "
        f"{scotland_canonical!r} (full report: {report!r})"
    )

    # -- USSR folds to Soviet Union via explicit alias --
    assert _mapped_canonical(report, "USSR") == "Soviet Union", (
        f"expected 'USSR' to canonicalize to 'Soviet Union', got "
        f"{_mapped_canonical(report, 'USSR')!r} (full report: {report!r})"
    )

    # -- North Korea and South Korea: neither has a canonical node or alias
    # in this fixture tree, so both must surface as DISTINCT unmapped
    # candidates -- never collapsed into each other, and never silently
    # mapped anywhere --
    north_korea_candidate = _candidate_entry(report, "North Korea")
    south_korea_candidate = _candidate_entry(report, "South Korea")
    assert north_korea_candidate is not None, (
        f"expected 'North Korea' to surface as an unmapped candidate, got "
        f"none among candidates: {report['candidates']!r}"
    )
    assert south_korea_candidate is not None, (
        f"expected 'South Korea' to surface as an unmapped candidate, got "
        f"none among candidates: {report['candidates']!r}"
    )
    assert north_korea_candidate is not south_korea_candidate, (
        "expected 'North Korea' and 'South Korea' to be reported as two "
        "distinct candidate entries, never merged into a single shared entry"
    )
    assert _mapped_canonical(report, "North Korea") is None, (
        "expected 'North Korea' to never appear in the 'mapped' list "
        "(it has no canonical node in this fixture tree)"
    )
    assert _mapped_canonical(report, "South Korea") is None, (
        "expected 'South Korea' to never appear in the 'mapped' list "
        "(it has no canonical node in this fixture tree)"
    )

    # -- "Syria and Lebanon" is a multi-polity LEAK: both "Syria" and
    # "Lebanon" independently canonicalize to their own standalone nodes, so
    # the combined string must be flagged, never folded to either one --
    leak = _leak_entry(report, "Syria and Lebanon")
    assert leak is not None, (
        f"expected 'Syria and Lebanon' to surface as a leak flag (both "
        f"'Syria' and 'Lebanon' independently canonicalize to standalone "
        f"nodes), got none among leaks: {report['leaks']!r}"
    )
    assert set(leak.get("parts", [])) == {"Syria", "Lebanon"}, (
        f"expected the leak entry for 'Syria and Lebanon' to name its two "
        f"split parts {{'Syria', 'Lebanon'}}, got {leak.get('parts')!r}"
    )
    assert _candidate_entry(report, "Syria and Lebanon") is None, (
        "expected 'Syria and Lebanon' to never ALSO appear as a plain "
        "unmapped candidate -- it is a leak, a distinct status"
    )
    assert _mapped_canonical(report, "Syria and Lebanon") is None, (
        "expected 'Syria and Lebanon' to never be folded to a single "
        "canonical node (leak, not mapped)"
    )

    # -- "Freedonia" passes through unchanged: a candidate with its
    # occurrence count (two staged notes) and both source note ids --
    freedonia = _candidate_entry(report, "Freedonia")
    assert freedonia is not None, (
        f"expected 'Freedonia' to surface as an unmapped candidate, got "
        f"none among candidates: {report['candidates']!r}"
    )
    assert freedonia.get("count") == 2, (
        f"expected 'Freedonia's candidate entry to carry its occurrence "
        f"count (2 staged notes), got {freedonia.get('count')!r} (entry: "
        f"{freedonia!r})"
    )
    assert set(freedonia.get("notes", [])) == FREEDONIA_NOTE_IDS, (
        f"expected 'Freedonia's candidate entry to name both source note "
        f"ids {FREEDONIA_NOTE_IDS!r}, got {freedonia.get('notes')!r} "
        f"(entry: {freedonia!r})"
    )

    # -- the notification prints the candidate count + list on stderr,
    # naming each surfaced candidate/leak verbatim --
    assert report["candidate_count"] == 3, (
        f"expected exactly 3 distinct unmapped candidates (North Korea, "
        f"South Korea, Freedonia), got candidate_count="
        f"{report['candidate_count']!r} (candidates: {report['candidates']!r})"
    )
    for verbatim in ("North Korea", "South Korea", "Freedonia"):
        assert verbatim in result.stderr, (
            f"expected `axial polity report`'s stderr notification to name "
            f"the unmapped candidate {verbatim!r}, got stderr: "
            f"{result.stderr!r}"
        )
    assert "Syria and Lebanon" in result.stderr, (
        f"expected `axial polity report`'s stderr notification to name the "
        f"'Syria and Lebanon' leak flag, got stderr: {result.stderr!r}"
    )


def test_polity_report_clean_vault_confirms_nothing_to_resolve(isolated_vault_root):
    """The clean-path scenario: when every staged verbatim maps cleanly (no
    candidates, no leaks), `axial polity report` must exit 0 and print a
    clean "nothing to resolve"-style confirmation rather than an empty or
    ambiguous notification."""
    root = isolated_vault_root
    _write_canonical_map(root, BASE_CANONICAL_YAML)
    _stage_vault(root, CLEAN_VAULT_POLITIES)

    result = _run_axial(["polity", "report"], root)
    _assert_not_argparse_fallback(result, "polity report")
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial polity report` over a fully "
        f"clean vault, got {result.returncode}\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )

    report = _parse_report_json(result)
    assert report["candidates"] == [], (
        f"expected zero candidates over a vault whose every polity "
        f"verbatim maps cleanly, got {report['candidates']!r}"
    )
    assert report["leaks"] == [], (
        f"expected zero leaks over a vault whose every polity verbatim "
        f"maps cleanly, got {report['leaks']!r}"
    )
    assert report["candidate_count"] == 0, (
        f"expected candidate_count == 0 over a fully clean vault, got "
        f"{report['candidate_count']!r}"
    )

    lowered_stderr = result.stderr.lower()
    assert any(phrase in lowered_stderr for phrase in NOTHING_TO_RESOLVE_PHRASES), (
        f"expected `axial polity report`'s stderr to print a clean "
        f"'nothing to resolve'-style confirmation when every verbatim maps "
        f"cleanly (one of {NOTHING_TO_RESOLVE_PHRASES!r}), got stderr: "
        f"{result.stderr!r}"
    )


def test_polity_report_edit_and_rerun_moves_candidate_to_mapped(isolated_vault_root):
    """The resolution-loop scenario: hand-editing `polity_canonical.yaml` to
    add a new canonical node for a former candidate, then re-running `axial
    polity report`, must move that verbatim from candidates to mapped --
    proving the edit+rerun loop changes output deterministically with no
    interactive tooling needed (the YAML file is the whole surface)."""
    root = isolated_vault_root
    canonical_path = _write_canonical_map(root, BASE_CANONICAL_YAML)
    _stage_vault(root, MIXED_VAULT_POLITIES)

    first = _run_axial(["polity", "report"], root)
    _assert_not_argparse_fallback(first, "polity report")
    assert first.returncode == 0, (
        f"arrange step failed: expected exit code 0 for the first `axial "
        f"polity report` run, got {first.returncode}\nstdout: "
        f"{first.stdout!r}\nstderr: {first.stderr!r}"
    )
    first_report = _parse_report_json(first)

    assert _candidate_entry(first_report, "Freedonia") is not None, (
        "arrange-step invariant broken: 'Freedonia' must start out as an "
        "unmapped candidate (no canonical node yet exists for it) or this "
        "test is not actually exercising the resolution loop -- first "
        f"report: {first_report!r}"
    )
    assert _mapped_canonical(first_report, "Freedonia") is None, (
        "arrange-step invariant broken: 'Freedonia' must not already be "
        f"mapped before the edit -- first report: {first_report!r}"
    )

    # -- the operator hand-edits the canonical map to add a new node --
    canonical_path.write_text(CANONICAL_YAML_WITH_FREEDONIA, encoding="utf-8")

    second = _run_axial(["polity", "report"], root)
    _assert_not_argparse_fallback(second, "polity report")
    assert second.returncode == 0, (
        f"expected exit code 0 for `axial polity report` after adding "
        f"'Freedonia' as a canonical node, got {second.returncode}\n"
        f"stdout: {second.stdout!r}\nstderr: {second.stderr!r}"
    )
    second_report = _parse_report_json(second)

    assert _candidate_entry(second_report, "Freedonia") is None, (
        f"expected 'Freedonia' to no longer appear as a candidate after "
        f"the edit+rerun, got it still present among candidates: "
        f"{second_report['candidates']!r}"
    )
    assert _mapped_canonical(second_report, "Freedonia") == "Freedonia", (
        f"expected 'Freedonia' to now canonicalize to its own new "
        f"canonical node after the edit+rerun, got "
        f"{_mapped_canonical(second_report, 'Freedonia')!r} (full report: "
        f"{second_report!r})"
    )
    assert second_report["candidate_count"] == first_report["candidate_count"] - 1, (
        f"expected the edit+rerun to deterministically shrink the "
        f"candidate count by exactly one (Freedonia moving from candidate "
        f"to mapped), got first candidate_count="
        f"{first_report['candidate_count']!r}, second candidate_count="
        f"{second_report['candidate_count']!r}"
    )


def _snapshot_all_files(root: Path) -> dict[str, bytes]:
    """Map every file under `root` (relative path -> bytes), recursively --
    used to detect ANY new/changed file `axial polity build` writes,
    regardless of the exact path/filename it picks (this test does not
    presuppose a specific seed-tree output location)."""
    snapshot: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if path.is_file():
            snapshot[str(path.relative_to(root))] = path.read_bytes()
    return snapshot


def _stage_build_root(tmp_path_factory, label: str) -> Path:
    root = tmp_path_factory.mktemp(label)
    _stage_domain_files(root)
    _stage_vault(root, BUILD_VAULT_POLITIES)
    return root


def test_polity_build_emits_a_deterministic_seed_tree(tmp_path_factory):
    """`axial polity build` over the staged vault must emit a deterministic
    seed tree: run over two independently-staged, byte-identical vaults, the
    TOTAL observable output (stdout plus any newly created/changed file
    anywhere under the run's cwd -- this test does not assume whether the
    seed tree lands on stdout, a new file, or both) must be byte-for-byte
    identical, and must be non-trivial (it must actually mention a distinct
    polity verbatim the vault carries)."""
    root_a = _stage_build_root(tmp_path_factory, "polity-build-a")
    root_b = _stage_build_root(tmp_path_factory, "polity-build-b")

    before_a = _snapshot_all_files(root_a)
    before_b = _snapshot_all_files(root_b)

    result_a = _run_axial(["polity", "build"], root_a)
    _assert_not_argparse_fallback(result_a, "polity build")
    assert result_a.returncode == 0, (
        f"expected exit code 0 for `axial polity build`, got "
        f"{result_a.returncode}\nstdout: {result_a.stdout!r}\n"
        f"stderr: {result_a.stderr!r}"
    )

    result_b = _run_axial(["polity", "build"], root_b)
    _assert_not_argparse_fallback(result_b, "polity build")
    assert result_b.returncode == 0, (
        f"expected exit code 0 for `axial polity build`, got "
        f"{result_b.returncode}\nstdout: {result_b.stdout!r}\n"
        f"stderr: {result_b.stderr!r}"
    )

    after_a = _snapshot_all_files(root_a)
    after_b = _snapshot_all_files(root_b)

    new_or_changed_a = {
        path: content for path, content in after_a.items() if before_a.get(path) != content
    }
    new_or_changed_b = {
        path: content for path, content in after_b.items() if before_b.get(path) != content
    }

    observed_a = result_a.stdout + "".join(
        f"{path}:{content!r}\n" for path, content in sorted(new_or_changed_a.items())
    )
    observed_b = result_b.stdout + "".join(
        f"{path}:{content!r}\n" for path, content in sorted(new_or_changed_b.items())
    )

    assert observed_a.strip(), (
        f"expected `axial polity build` to produce SOME observable output "
        f"(stdout content and/or a new/changed file) over a non-empty "
        f"staged vault, got neither; stdout={result_a.stdout!r}, "
        f"new/changed files={sorted(new_or_changed_a)!r}"
    )
    assert "Freedonia" in observed_a, (
        f"expected the deterministic seed tree to include a node for the "
        f"distinct 'Freedonia' polity verbatim this vault carries, found "
        f"none in the observed output: {observed_a!r}"
    )
    assert observed_a == observed_b, (
        f"expected `axial polity build` over two byte-identical staged "
        f"vaults to produce byte-identical observable output (stdout plus "
        f"any newly written/changed files) -- got divergent output:\n"
        f"root_a observed={observed_a!r}\nroot_b observed={observed_b!r}"
    )
