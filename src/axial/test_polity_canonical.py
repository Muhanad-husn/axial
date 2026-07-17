"""Inner unit tests for the offline canonical polity-map module (issue #205,
slice 01; plans/polity-normalization/01-canonical-map.md's inner-loop list)."""

from __future__ import annotations

import re

import pytest
import yaml

from axial.polity_canonical import (
    AmbiguousAliasError,
    MalformedPolityCanonicalError,
    MissingPolityCanonicalFileError,
    MissingVersionError,
    PolityCanonicalError,
    canonicalize,
    harvest_vault_polities,
    load_polity_canonical,
    run_polity_build,
    run_polity_report,
)

BASE_TREE = """version: 1
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


def _write_canonical(domain_dir, text):
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / "polity_canonical.yaml").write_text(text, encoding="utf-8")


def _write_note(prose_dir, chunk_id, polity=None, polities_touched=None, section="Body"):
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {"chunk_id": chunk_id, "section": section, "chunk_text": f"{chunk_id} text."}
    if polity is not None:
        frontmatter["empirical_scope"] = {"value": "scope:country-case", "polity": polity}
    if polities_touched is not None:
        frontmatter["polities_touched"] = polities_touched
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


# -- loader --


def test_load_polity_canonical_reads_version_and_node_tree(tmp_path):
    _write_canonical(tmp_path, BASE_TREE)

    cmap = load_polity_canonical(tmp_path)

    assert cmap.version == 1
    canonicals = {node.canonical for node in cmap.nodes}
    assert canonicals == {"United Kingdom", "Soviet Union", "Syria", "Lebanon", "Ottoman Empire"}
    uk = next(node for node in cmap.nodes if node.canonical == "United Kingdom")
    assert {child.canonical for child in uk.children} == {"Scotland", "England"}


def test_missing_canonical_file_raises_typed_error(tmp_path):
    with pytest.raises(
        MissingPolityCanonicalFileError, match=re.escape(str(tmp_path / "polity_canonical.yaml"))
    ):
        load_polity_canonical(tmp_path)


def test_malformed_yaml_raises_typed_error_not_a_traceback(tmp_path):
    _write_canonical(tmp_path, "version: 1\nnodes: [this is not, valid: yaml: mapping")

    with pytest.raises(MalformedPolityCanonicalError):
        load_polity_canonical(tmp_path)


def test_missing_version_key_raises_typed_error(tmp_path):
    _write_canonical(tmp_path, "nodes:\n  - canonical: Syria\n    aliases: []\n")

    with pytest.raises(MissingVersionError):
        load_polity_canonical(tmp_path)


def test_malformed_error_and_missing_version_error_are_polity_canonical_errors(tmp_path):
    _write_canonical(tmp_path, "nodes: not_a_list\nversion: 1\n")
    with pytest.raises(PolityCanonicalError):
        load_polity_canonical(tmp_path)


# -- ambiguity guard --


def test_duplicate_alias_across_two_nodes_raises_ambiguous_alias_error(tmp_path):
    _write_canonical(
        tmp_path,
        """version: 1
nodes:
  - canonical: North Korea
    aliases: [Korea]
  - canonical: South Korea
    aliases: [Korea]
""",
    )

    with pytest.raises(AmbiguousAliasError, match="Korea"):
        load_polity_canonical(tmp_path)


def test_same_alias_repeated_on_the_same_node_is_not_ambiguous(tmp_path):
    _write_canonical(
        tmp_path,
        """version: 1
nodes:
  - canonical: United Kingdom
    aliases: [Britain, Britain]
""",
    )

    cmap = load_polity_canonical(tmp_path)
    assert cmap.index["britain"].canonical == "United Kingdom"


# -- canonicalize: alias fold --


def test_canonicalize_folds_alias_case_and_space_insensitively(tmp_path):
    _write_canonical(tmp_path, BASE_TREE)
    cmap = load_polity_canonical(tmp_path)

    result = canonicalize("  britain  ", cmap)
    assert result.status == "mapped"
    assert result.canonical == "United Kingdom"
    assert result.verbatim == "  britain  "  # original preserved


def test_canonicalize_exact_canonical_name_maps_to_itself(tmp_path):
    _write_canonical(tmp_path, BASE_TREE)
    cmap = load_polity_canonical(tmp_path)

    result = canonicalize("Syria", cmap)
    assert result.status == "mapped"
    assert result.canonical == "Syria"


# -- canonicalize: child not parent, siblings never merge --


def test_canonicalize_child_alias_resolves_to_child_not_parent(tmp_path):
    _write_canonical(tmp_path, BASE_TREE)
    cmap = load_polity_canonical(tmp_path)

    result = canonicalize("Scotland", cmap)
    assert result.status == "mapped"
    assert result.canonical == "Scotland"


def test_canonicalize_sibling_tokens_never_merge(tmp_path):
    _write_canonical(tmp_path, BASE_TREE)
    cmap = load_polity_canonical(tmp_path)

    north = canonicalize("North Korea", cmap)
    south = canonicalize("South Korea", cmap)
    assert north.status == "candidate"
    assert south.status == "candidate"
    assert north.verbatim != south.verbatim


# -- canonicalize: leaks --


def test_canonicalize_multi_polity_string_is_a_leak_with_both_parts(tmp_path):
    _write_canonical(tmp_path, BASE_TREE)
    cmap = load_polity_canonical(tmp_path)

    result = canonicalize("Syria and Lebanon", cmap)
    assert result.status == "leak"
    assert set(result.parts) == {"Syria", "Lebanon"}


def test_canonicalize_bosnia_and_herzegovina_is_not_a_leak(tmp_path):
    _write_canonical(tmp_path, BASE_TREE)
    cmap = load_polity_canonical(tmp_path)

    result = canonicalize("Bosnia and Herzegovina", cmap)
    assert result.status == "candidate"


def test_canonicalize_leak_via_comma_and_slash_separators(tmp_path):
    _write_canonical(tmp_path, BASE_TREE)
    cmap = load_polity_canonical(tmp_path)

    assert canonicalize("Syria, Lebanon", cmap).status == "leak"
    assert canonicalize("Syria/Lebanon", cmap).status == "leak"


# -- canonicalize: candidate passthrough --


def test_canonicalize_unmapped_verbatim_is_a_candidate_unchanged(tmp_path):
    _write_canonical(tmp_path, BASE_TREE)
    cmap = load_polity_canonical(tmp_path)

    result = canonicalize("Freedonia", cmap)
    assert result.status == "candidate"
    assert result.verbatim == "Freedonia"
    assert result.canonical is None


# -- vault harvest --


def test_harvest_vault_polities_counts_and_notes(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_note(prose_dir, "src_001_body_001", polity="Freedonia")
    _write_note(prose_dir, "src_002_body_001", polity="Freedonia")
    _write_note(prose_dir, "src_003_body_001", polity="Syria")

    harvest = harvest_vault_polities(prose_dir)

    assert harvest["Freedonia"]["count"] == 2
    assert set(harvest["Freedonia"]["notes"]) == {"src_001_body_001", "src_002_body_001"}
    assert harvest["Syria"]["count"] == 1


def test_harvest_vault_polities_reads_polities_touched_list(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_note(prose_dir, "src_001_body_001", polities_touched=["Syria", "Lebanon"])

    harvest = harvest_vault_polities(prose_dir)

    assert harvest["Syria"]["count"] == 1
    assert harvest["Lebanon"]["count"] == 1
    assert harvest["Syria"]["notes"] == ["src_001_body_001"]


def test_harvest_vault_polities_same_note_dual_mention_counts_once(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_note(prose_dir, "src_001_body_001", polity="Syria", polities_touched=["Syria"])

    harvest = harvest_vault_polities(prose_dir)

    assert harvest["Syria"]["count"] == 1


# -- axial polity build determinism --


def test_run_polity_build_emits_sorted_seed_nodes(tmp_path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "src_001_body_001", polity="Freedonia")
    _write_note(prose_dir, "src_002_body_001", polity="Britain")

    text = run_polity_build(vault_dir=vault_dir)
    document = yaml.safe_load(text)

    assert document["version"] == 1
    canonicals = [node["canonical"] for node in document["nodes"]]
    assert canonicals == sorted(canonicals)
    assert "Freedonia" in canonicals
    assert "Britain" in canonicals


def test_run_polity_build_is_deterministic_across_runs(tmp_path):
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_note(prose_dir, "src_001_body_001", polity="Freedonia")

    first = run_polity_build(vault_dir=vault_dir)
    second = run_polity_build(vault_dir=vault_dir)
    assert first == second


# -- axial polity report --


def test_run_polity_report_moves_candidate_to_mapped_after_edit(tmp_path):
    domain_dir = tmp_path / "domain"
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_canonical(domain_dir, BASE_TREE)
    _write_note(prose_dir, "src_001_body_001", polity="Freedonia")

    first = run_polity_report(domain_dir=domain_dir, vault_dir=vault_dir)
    assert any(c["verbatim"] == "Freedonia" for c in first["candidates"])
    assert first["candidate_count"] == 1

    _write_canonical(domain_dir, BASE_TREE + "  - canonical: Freedonia\n    aliases: []\n")

    second = run_polity_report(domain_dir=domain_dir, vault_dir=vault_dir)
    assert not any(c["verbatim"] == "Freedonia" for c in second["candidates"])
    assert any(
        m["verbatim"] == "Freedonia" and m["canonical"] == "Freedonia" for m in second["mapped"]
    )
    assert second["candidate_count"] == 0


def test_run_polity_report_candidate_count_matches_list_length(tmp_path):
    domain_dir = tmp_path / "domain"
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    _write_canonical(domain_dir, BASE_TREE)
    _write_note(prose_dir, "src_001_body_001", polity="Freedonia")
    _write_note(prose_dir, "src_002_body_001", polity="North Korea")

    report = run_polity_report(domain_dir=domain_dir, vault_dir=vault_dir)
    assert report["candidate_count"] == len(report["candidates"]) == 2
