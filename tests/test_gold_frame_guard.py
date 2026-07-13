"""Outer acceptance test for issue #131 (gold sample leaks back-matter &
fragment chunks into the frame -- P0-9 filter false-negatives).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a tagged prose vault that contains, alongside substantive argument
      prose spanning the balancing strata (field x empirical_scope x
      role_in_argument):
        (a) an endnote section titled with a page range
            ("NOTES TO PAGES 85-93") whose body is a bare citation,
        (b) a roman-numeral-prefixed bibliography subsection
            ("V. Articles and Periodicals") whose body is a full reference
            entry,
        (c) a bare-citation prose fragment sitting inside an ordinary,
            non-back-matter chapter section ("Chapter 1"), and
        (d) an OCR-garbage / header-fragment chunk sitting inside an
            ordinary chapter section,
When   the user runs `axial gold sample`
Then   none of (a)-(d) is ever written under data/gold/chunks/
And    every substantive prose chunk IS selected
And    the run still exits 0 and produces a non-empty frame

See specs/PRODUCT.md P0-9 (spec section 8) and section 9 (gold corpus &
labeling): "Non-substantive back-matter (endnotes, references/bibliography,
index, appendix, front-matter) is excluded from the sampling frame; the
sampler draws only from substantive prose." GitHub issue #131 documents two
concrete false-negatives in `axial.gold._is_back_matter` (endnote titles
carrying a page range; roman-numeral bibliography subsections) plus the
absence of any minimum-substance guard (so a bare citation or an OCR-garbage
fragment sitting inside an otherwise-ordinary chapter section -- not
back-matter by title at all -- currently passes straight through). This test
arranges each documented leak with a SYNTHETIC body (an invented citation /
OCR-garble stand-in, never source text -- copyright) that reproduces only the
structural SHAPE the guard keys on (title pattern, short length, non-alpha
ratio), so it fails for the real behavioral gap without carrying any part of
a source into the repo.

Arrange mechanism -- seed the vault directly, no LLM
-----------------------------------------------------------------------
Mirrors tests/test_gold_sample.py (issue #53 slice 01, PR #124's ratified
Appendix-H frontmatter nesting): seed tagged prose note `.md` files directly
into `<root>/data/vault/prose/` with the exact frontmatter shape `axial
vault write` produces, rather than running the tag/vault thread live. No
LLM, no network, no docling. This file is deliberately self-contained (does
not import from test_gold_sample.py) so it carries no dependency on that
other locked contract.

Isolation -- run from an isolated staging root (issue #68)
-----------------------------------------------------------------------
Every `axial` subprocess here runs with `cwd` set to `isolated_vault_root`
(tests/conftest.py's opt-in fixture): a fresh per-test staging directory
outside this repo entirely. The real, large `data/vault/prose/` corpus is
never read or written.

Source identity -- derived from chunk_id
-----------------------------------------------------------------------
The vault frontmatter carries no top-level `source` key; source identity
lives in the `chunk_id` prefix (`<source_id>_<order>_<slug>_<NNN>`, per
src/axial/chunk.py). This test builds every seeded chunk_id in that exact
shape. No `data/gold/sources.yaml` is seeded -- source-type balancing is
irrelevant to this issue's contract (the frame-exclusion guard), and its
absence is a supported, logged-only condition (src/axial/gold.py's
`run_gold_sample`).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _prose_dir(root: Path) -> Path:
    return root / "data" / "vault" / "prose"


def _chunks_dir(root: Path) -> Path:
    return root / "data" / "gold" / "chunks"


def _render_note(frontmatter: dict) -> str:
    """Render a prose note structurally the way src/axial/vault.py's
    `render_note` does: a `---`-delimited YAML frontmatter block then a
    readable body. Only the frontmatter block is ever parsed by
    `axial.gold.parse_note` -- the body below the second `---` is cosmetic,
    matching the real vault-note format."""
    block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    section = frontmatter.get("section", "")
    chunk_text = frontmatter.get("chunk_text", "")
    return f"---\n{block}---\n# {section}\n\n{chunk_text}\n"


def _write_note(
    prose_dir: Path,
    *,
    chunk_id: str,
    section: str,
    chunk_text: str,
    field: str,
    scope: str,
    role: str,
) -> str:
    """Seed one tagged prose note with the Appendix-H frontmatter shape
    (mirrors tests/test_gold_sample.py's `_write_note`) and return its
    chunk_id."""
    frontmatter = {
        "chunk_id": chunk_id,
        "section": section,
        "chunk_text": chunk_text,
        "source_meta": {
            "author": "Seeded Author",
            "title": chunk_id,
            "date": "2020",
            "thesis": "A seeded thesis.",
            "scope": "A seeded scope.",
        },
        "schema_version": "0.1",
        "role_in_argument": role,
        "field": {"primary": field, "secondary": []},
        "claim_type": {"primary": "state-formation", "secondary": None, "subtags": []},
        "theory_school": {"primary": "bellicist", "secondary": None, "status": "candidate"},
        "empirical_scope": {"value": scope},
        "artifact_refs": [],
    }
    prose_dir.mkdir(parents=True, exist_ok=True)
    (prose_dir / f"{chunk_id}.md").write_text(_render_note(frontmatter), encoding="utf-8")
    return chunk_id


# ---------------------------------------------------------------------------
# Junk shapes -- the four false-negatives issue #131 documents. Each body is
# a SYNTHETIC stand-in (invented citation / OCR-garble, never source text --
# copyright) carrying only the structural shape the guard keys on.
# ---------------------------------------------------------------------------

JUNK_ENDNOTE_PAGE_RANGE = dict(
    chunk_id="fabricated-endnote-source-aaaaaaaaaaaa_7_notes-to-pages-85-93_001",
    section="NOTES TO PAGES 85-93",
    chunk_text="12  Roe, A Fictional Study, p. 88.",
    field="state",
    scope="scope:general",
    role="role:setup",
)

JUNK_ROMAN_BIBLIOGRAPHY = dict(
    chunk_id="fabricated-bibliography-source-bbbbbbbbbbbb_8_articles-and-periodicals_001",
    section="V. Articles and Periodicals",
    chunk_text=("Roe, Jane, 'An Invented Article Title', Journal of Nowhere, 12/3 (2001), 1-20."),
    field="ideology",
    scope="scope:comparative",
    role="role:evidence",
)

JUNK_INBODY_BARE_CITATION = dict(
    chunk_id="fabricated-chapter-source-cccccccccccc_1_chapter-one_004",
    section="Chapter 1",
    chunk_text="Roe, Invented Book, pp. 10-14.",
    field="violence",
    scope="scope:country-case",
    role="role:claim",
)

JUNK_OCR_GARBAGE = dict(
    chunk_id="fabricated-ocr-source-dddddddddddd_3_chapter-three_002",
    section="Chapter 3",
    chunk_text="XZQ7t KKtempc;, ZZ QWRTo QQ FALSE",
    field="state",
    scope="scope:regional",
    role="role:synthesis",
)

JUNK_SPECS = [
    JUNK_ENDNOTE_PAGE_RANGE,
    JUNK_ROMAN_BIBLIOGRAPHY,
    JUNK_INBODY_BARE_CITATION,
    JUNK_OCR_GARBAGE,
]

# ---------------------------------------------------------------------------
# Substantive prose -- multi-sentence real argument (~300+ chars each),
# spanning >=2 values of each balancing axis (field x empirical_scope x
# role_in_argument), so the frame is non-empty and the "substantive prose
# stays in" half of the contract is a real, checkable clause.
# ---------------------------------------------------------------------------

SUBSTANTIVE_NOTES = [
    dict(
        chunk_id="state-formation-study-000000000001_1_introduction_001",
        section="Introduction",
        chunk_text=(
            "The colonial administration's approach to direct taxation fundamentally "
            "reshaped local power structures: tribal leaders who had previously "
            "mediated disputes and collected tribute independently increasingly relied "
            "on state-backed enforcement mechanisms to extract revenue from their own "
            "constituents, gradually eroding their autonomous legitimacy in favor of a "
            "bureaucratized, extractive relationship between center and periphery that "
            "would outlast the colonial period itself."
        ),
        field="state",
        scope="scope:general",
        role="role:setup",
    ),
    dict(
        chunk_id="state-formation-study-000000000001_2_chapter-one_001",
        section="Chapter 1",
        chunk_text=(
            "In the province under study, the transition from indirect to direct rule "
            "was neither smooth nor uniformly resisted; some notable families "
            "positioned themselves as intermediaries within the new bureaucratic "
            "apparatus, converting inherited social capital into formal administrative "
            "office, while others who refused this accommodation found themselves "
            "displaced from the networks of patronage that had sustained their "
            "authority for generations."
        ),
        field="violence",
        scope="scope:country-case",
        role="role:claim",
    ),
    dict(
        chunk_id="comparative-ideology-tracts-000000000002_1_chapter-two_001",
        section="Chapter 2",
        chunk_text=(
            "Across the cases surveyed here, the ideological justification for "
            "centralized rule shifted markedly once external military threats receded: "
            "where wartime rhetoric had emphasized unity against a common enemy, "
            "peacetime discourse pivoted toward development and modernization as the "
            "new organizing narrative, a rhetorical move that let ruling elites "
            "preserve the expanded administrative capacity built during the emergency "
            "without having to justify it in security terms any longer."
        ),
        field="ideology",
        scope="scope:comparative",
        role="role:evidence",
    ),
    dict(
        chunk_id="comparative-ideology-tracts-000000000002_2_findings_001",
        section="Findings",
        chunk_text=(
            "A close reading of the party congress proceedings across three regional "
            "affiliates shows that the doctrinal language of self-determination was "
            "invoked most heavily precisely where the center's actual administrative "
            "reach was weakest, suggesting the rhetoric functioned less as a "
            "description of practice than as a substitute for the coercive capacity "
            "the movement had not yet built on the ground."
        ),
        field="ideology",
        scope="scope:regional",
        role="role:synthesis",
    ),
    dict(
        chunk_id="regional-violence-patterns-000000000003_1_analysis_001",
        section="Analysis",
        chunk_text=(
            "The pattern of episodic violence documented in this region correlates "
            "closely with periods of contested succession at the center rather than "
            "with any single grievance specific to the periphery itself, which argues "
            "against purely local explanations and toward an account centered on how "
            "uncertainty about central authority propagates outward and destabilizes "
            "arrangements that otherwise held for decades at a time."
        ),
        field="violence",
        scope="scope:general",
        role="role:evidence",
    ),
]


def _seed_vault(root: Path) -> dict[str, list[str]]:
    """Seed the substantive notes and the four junk notes. Returns the
    expected substantive chunk_ids and the junk chunk_ids (which must NOT
    appear in the selection)."""
    prose_dir = _prose_dir(root)

    substantive_ids = [
        _write_note(
            prose_dir,
            chunk_id=spec["chunk_id"],
            section=spec["section"],
            chunk_text=spec["chunk_text"],
            field=spec["field"],
            scope=spec["scope"],
            role=spec["role"],
        )
        for spec in SUBSTANTIVE_NOTES
    ]

    junk_ids = [
        _write_note(
            prose_dir,
            chunk_id=spec["chunk_id"],
            section=spec["section"],
            chunk_text=spec["chunk_text"],
            field=spec["field"],
            scope=spec["scope"],
            role=spec["role"],
        )
        for spec in JUNK_SPECS
    ]

    return {"substantive": substantive_ids, "junk": junk_ids}


def _run_gold_sample(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"  # any run that reaches an LLM is a bug
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", "gold", "sample", *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `gold sample` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- the subcommand does not exist "
            f"yet or was never reached:\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


def _load_records(root: Path) -> list[dict]:
    chunks_dir = _chunks_dir(root)
    assert chunks_dir.exists(), (
        f"expected `axial gold sample` to create {chunks_dir} and write chunk "
        f"records into it, but it does not exist after a successful run"
    )
    records = []
    for path in sorted(chunks_dir.glob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def test_gold_sample_excludes_back_matter_and_fragment_junk(isolated_vault_root):
    root = isolated_vault_root
    seeded = _seed_vault(root)

    result = _run_gold_sample(root)
    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit code 0 for `axial gold sample` on a seeded vault, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    records = _load_records(root)
    assert records, (
        f"expected `axial gold sample` to write at least one chunk record "
        f"under {_chunks_dir(root)}, got none. stdout: {result.stdout!r}"
    )

    selected_ids = {record["chunk_id"] for record in records}
    selected_sections = {record["chunk_id"]: record["section"] for record in records}
    selected_bodies = {record["chunk_id"]: record["chunk_text"] for record in records}

    # (a) endnote section carrying a page range in its title.
    assert JUNK_ENDNOTE_PAGE_RANGE["chunk_id"] not in selected_ids, (
        f"expected the endnote section {JUNK_ENDNOTE_PAGE_RANGE['section']!r} "
        f"(a page-range-qualified 'notes' title, issue #131 false-negative 1) "
        f"to be excluded from the gold sampling frame, but chunk "
        f"{JUNK_ENDNOTE_PAGE_RANGE['chunk_id']!r} was selected with section "
        f"{selected_sections.get(JUNK_ENDNOTE_PAGE_RANGE['chunk_id'])!r}"
    )

    # (b) roman-numeral-prefixed bibliography subsection.
    assert JUNK_ROMAN_BIBLIOGRAPHY["chunk_id"] not in selected_ids, (
        f"expected the bibliography subsection "
        f"{JUNK_ROMAN_BIBLIOGRAPHY['section']!r} (a roman-numeral-prefixed "
        f"references subsection, issue #131 false-negative 2) to be excluded "
        f"from the gold sampling frame, but chunk "
        f"{JUNK_ROMAN_BIBLIOGRAPHY['chunk_id']!r} was selected with section "
        f"{selected_sections.get(JUNK_ROMAN_BIBLIOGRAPHY['chunk_id'])!r}"
    )

    # (c) bare citation sitting inside an ordinary chapter section -- not
    # back-matter by title at all, must be caught by a minimum-substance
    # guard on the body.
    assert JUNK_INBODY_BARE_CITATION["chunk_id"] not in selected_ids, (
        f"expected the bare-citation fragment "
        f"{JUNK_INBODY_BARE_CITATION['chunk_text']!r} sitting inside the "
        f"ordinary section {JUNK_INBODY_BARE_CITATION['section']!r} to be "
        f"excluded from the gold sampling frame by a minimum-substance guard "
        f"(issue #131), but chunk {JUNK_INBODY_BARE_CITATION['chunk_id']!r} "
        f"was selected with chunk_text "
        f"{selected_bodies.get(JUNK_INBODY_BARE_CITATION['chunk_id'])!r}"
    )

    # (d) OCR-garbage / header fragment sitting inside an ordinary chapter
    # section -- also not back-matter by title, must be caught by the same
    # substance guard.
    assert JUNK_OCR_GARBAGE["chunk_id"] not in selected_ids, (
        f"expected the OCR-garbage fragment "
        f"{JUNK_OCR_GARBAGE['chunk_text']!r} sitting inside the ordinary "
        f"section {JUNK_OCR_GARBAGE['section']!r} to be excluded from the "
        f"gold sampling frame by a minimum-substance guard (issue #131), but "
        f"chunk {JUNK_OCR_GARBAGE['chunk_id']!r} was selected with "
        f"chunk_text {selected_bodies.get(JUNK_OCR_GARBAGE['chunk_id'])!r}"
    )

    # No junk chunk_id leaks through under any circumstance (belt-and-braces
    # set check alongside the individual, more diagnostic assertions above).
    junk_selected = selected_ids & set(seeded["junk"])
    assert not junk_selected, (
        f"expected none of the four #131 junk shapes to be selected, but "
        f"these leaked into the frame: {sorted(junk_selected)}"
    )

    # The substantive half of the contract: every substantive prose chunk
    # IS selected (the frame has only 9 candidate notes total, well under
    # the default 100-120 band, so the band clamps to "all substantive").
    missing_substantive = set(seeded["substantive"]) - selected_ids
    assert not missing_substantive, (
        f"expected every substantive prose chunk to be selected (available "
        f"substantive count is below the default 100-120 band floor, so the "
        f"band clamps to all of them), but these were dropped: "
        f"{sorted(missing_substantive)}"
    )
