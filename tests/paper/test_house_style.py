"""Issue #787 slice 05: the prose conventions a paper is written to live in
`config/domains/<domain>/house_style.yaml`, load at runtime, and reach both
prose-writing prompts as context.

The acceptance criterion (plan `05-house-style-is-domain-data.md`):

    Given a domain frame at config/domains/<domain>/ that declares house
          style conventions
    When  an operator runs `uv run axial paper draft <a brief in that domain>`
    Then  the drafting prompt for every section carries those conventions as
          context
    And   a domain frame declaring no house style produces a prompt unchanged
          from slice 02's
    And   no house-style value appears anywhere in src/ as a literal or a
          branch

The prompt-level half of that -- and the byte-identity pin against 5a34d45 --
is in `test_draft_house_style.py`. This file covers the loader, the shipped
domain file, and the whole pipeline through `run_paper`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.llm import StubLLMClient
from axial.paper.brief import PaperBrief, PaperBriefContent, compute_paper_brief_id
from axial.paper.house_style import (
    HOUSE_STYLE_FILENAME,
    HouseStyle,
    HouseStyleError,
    MalformedHouseStyleError,
    load_house_style,
)
from axial.paper.record import run_paper
from axial.paths import DEFAULT_DOMAIN_DIR

SRC_DIR = Path(__file__).resolve().parents[2] / "src"

CONVENTIONS = [
    "Hold one register from the first sentence to the last.",
    "Open with the point, not with an announcement of what is about to be argued.",
]


def _domain_dir(tmp_path: Path, conventions: list[str] | None, name: str = "atlantis") -> Path:
    directory = tmp_path / "domains" / name
    directory.mkdir(parents=True)
    if conventions is not None:
        (directory / HOUSE_STYLE_FILENAME).write_text(
            json.dumps({"conventions": conventions}), encoding="utf-8"
        )
    return directory


# ---------------------------------------------------------------------------
# The loader: a domain DIRECTORY in, a block or nothing out, and no
# country-specific handling anywhere in it.
# ---------------------------------------------------------------------------


def test_the_loader_reads_a_house_style_from_any_domain_directory(tmp_path: Path):
    style = load_house_style(_domain_dir(tmp_path, CONVENTIONS))
    assert isinstance(style, HouseStyle)
    assert list(style.conventions) == CONVENTIONS


@pytest.mark.parametrize("domain_name", ["syria", "atlantis", "a-domain-nobody-has-written-yet"])
def test_the_loader_treats_every_domain_the_same_way(tmp_path: Path, domain_name: str):
    """Nothing in the loader branches on which domain it is (CLAUDE.md: the
    domain frame is data). Three differently-named directories with identical
    contents load identically."""
    style = load_house_style(_domain_dir(tmp_path, CONVENTIONS, name=domain_name))
    assert style is not None
    assert list(style.conventions) == CONVENTIONS


def test_a_domain_with_no_house_style_file_loads_as_nothing(tmp_path: Path):
    assert load_house_style(_domain_dir(tmp_path, None)) is None


def test_a_domain_directory_that_does_not_exist_loads_as_nothing(tmp_path: Path):
    assert load_house_style(tmp_path / "no-such-domain") is None


def test_malformed_yaml_fails_loudly_rather_than_reaching_a_prompt(tmp_path: Path):
    directory = _domain_dir(tmp_path, None)
    (directory / HOUSE_STYLE_FILENAME).write_text("conventions: [unclosed\n", encoding="utf-8")
    with pytest.raises(MalformedHouseStyleError) as excinfo:
        load_house_style(directory)
    assert HOUSE_STYLE_FILENAME in str(excinfo.value)


@pytest.mark.parametrize(
    "document",
    [
        "a bare string",
        {},
        {"conventions": None},
        {"conventions": "one convention, unlisted"},
        {"conventions": []},
        {"conventions": ["fine", ""]},
        {"conventions": ["fine", "   "]},
        {"conventions": ["fine", 7]},
    ],
    ids=[
        "not-a-mapping",
        "no-conventions-key",
        "null-conventions",
        "conventions-not-a-list",
        "empty-list",
        "empty-entry",
        "blank-entry",
        "non-string-entry",
    ],
)
def test_a_malformed_block_is_a_typed_error_not_a_silent_drop(tmp_path: Path, document):
    directory = _domain_dir(tmp_path, None)
    (directory / HOUSE_STYLE_FILENAME).write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(HouseStyleError):
        load_house_style(directory)


def test_conventions_are_stripped_and_kept_in_declared_order(tmp_path: Path):
    directory = _domain_dir(tmp_path, ["  second thought  ", "first thought"])
    style = load_house_style(directory)
    assert style is not None
    assert list(style.conventions) == ["second thought", "first thought"]


# ---------------------------------------------------------------------------
# The shipped domain frame, and the rule it exists to satisfy.
# ---------------------------------------------------------------------------


def test_the_syria_domain_frame_declares_a_house_style():
    style = load_house_style(DEFAULT_DOMAIN_DIR)
    assert style is not None
    assert style.conventions
    assert all(convention.strip() for convention in style.conventions)


def test_no_house_style_value_appears_anywhere_in_src():
    """The conventions are domain data. Not one of them may exist in `src/`
    as a literal -- if it did, editing the domain frame would stop being how
    house style changes."""
    style = load_house_style(DEFAULT_DOMAIN_DIR)
    assert style is not None
    sources = {path: path.read_text(encoding="utf-8") for path in SRC_DIR.rglob("*.py")}
    for convention in style.conventions:
        for path, text in sources.items():
            assert convention not in text, f"{path} carries a house-style convention verbatim"


def test_removing_the_domain_file_removes_the_house_style(tmp_path: Path):
    """The domain file is the only place the conventions live: take it away
    and there is no fallback block hidden in the package."""
    directory = _domain_dir(tmp_path, None)
    (directory / HOUSE_STYLE_FILENAME).write_text(
        (DEFAULT_DOMAIN_DIR / HOUSE_STYLE_FILENAME).read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert load_house_style(directory) == load_house_style(DEFAULT_DOMAIN_DIR)

    (directory / HOUSE_STYLE_FILENAME).unlink()
    assert load_house_style(directory) is None


# ---------------------------------------------------------------------------
# End to end through `run_paper`, against a scripted stub client.
# ---------------------------------------------------------------------------


def _claim(claim_id, text, chunk_id, names):
    return {
        "claim_id": claim_id,
        "kind": "a",
        "text": text,
        "confidence": "high",
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        "names_touched": names,
    }


@pytest.fixture
def analyses_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "analyses"
    directory.mkdir()
    record = {
        "brief_id": "brief-a",
        "corpus_pin": "sim-2026-08-18",
        "lens": "political-economy",
        "interrogation": {"disposition": "proceed"},
        "claims": [
            _claim("a1", "The mechanism runs through extraction.", "src-1_1_a_001", ["A Author"]),
            _claim("a2", "The opposing account holds otherwise.", "src-1_2_b_001", ["A Author"]),
        ],
        "coverage_map": {
            "A Author": {
                "corpus_note_count": 154,
                "evidence_note_count": 8,
                "coverage_band": "dense",
            }
        },
        "counter_position": {
            "present": True,
            "stance": "the opposing account",
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "confidence": {"overall_band": "high", "rationale": "..."},
    }
    (directory / "brief-a.json").write_text(json.dumps(record), encoding="utf-8")
    return directory


@pytest.fixture
def lenses_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "lenses"
    directory.mkdir()
    (directory / "political-economy.yaml").write_text(
        "name: political-economy\ndescription: Reads for who pays and who decides.\n",
        encoding="utf-8",
    )
    return directory


PLAN = {
    "thesis_statement": "The mechanism explains the outcome better than the alternative.",
    "sections": [
        {
            "section_id": "s1",
            "heading": "The mechanism",
            "role": "claim",
            "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a1"}],
        },
        {
            "section_id": "s2",
            "heading": "The case against",
            "role": "counter-position",
            "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a2"}],
        },
    ],
}

# Prose that breaks the shipped conventions on purpose: it opens with a
# formula about itself, and it is what the "never a gate" test below expects
# to survive into the record untouched.
UNSTYLED_PROSE = [
    {
        "prose": "This paper argues that the mechanism ran through extraction [pc-001].",
        "new_claims": [],
    },
    {
        "prose": "This paper argues that the opposing account still has force [pc-002].",
        "new_claims": [],
    },
]


class StubClient(StubLLMClient):
    model_by_pass = {
        "paper_plan": "stub/plan",
        "paper_draft": "stub/draft",
        "paper_shape": "stub/shape",
        "paper_abstract": "stub/abstract",
    }

    def __init__(self, drafts):
        super().__init__()
        self._drafts = list(drafts)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, prompt, pass_name=None, **_):
        self.prompts.append((pass_name, prompt))
        if pass_name == "paper_plan":
            return json.dumps(PLAN)
        if pass_name == "paper_shape":
            return json.dumps({"band": "strong", "defects": []})
        if pass_name == "paper_abstract":
            return json.dumps({"abstract": "The argument and where it commits itself."})
        return json.dumps(self._drafts.pop(0))

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)

    def prompts_for(self, pass_name: str) -> list[str]:
        return [prompt for name, prompt in self.prompts if name == pass_name]


def _run(tmp_path, analyses_dir, lenses_dir, *, domain_dir):
    client = StubClient(UNSTYLED_PROSE)
    content = PaperBriefContent(
        thesis="Which account explains the outcome?",
        analysis_ids=("brief-a",),
        lens="political-economy",
    )
    brief = PaperBrief(
        paper_brief_id=compute_paper_brief_id(content),
        thesis=content.thesis,
        analysis_ids=content.analysis_ids,
        lens=content.lens,
        title=content.title,
    )
    record = run_paper(
        client,
        brief,
        analyses_dir=analyses_dir,
        lenses_dir=lenses_dir,
        domain_dir=domain_dir,
        source_meta_dir=tmp_path / "source_meta",
        papers_dir=tmp_path / "papers",
    )
    return record, client


def test_every_drafting_prompt_carries_the_domains_conventions(tmp_path, analyses_dir, lenses_dir):
    domain_dir = _domain_dir(tmp_path, CONVENTIONS)
    _, client = _run(tmp_path, analyses_dir, lenses_dir, domain_dir=domain_dir)

    draft_prompts = client.prompts_for("paper_draft")
    assert len(draft_prompts) == 2
    for prompt in draft_prompts:
        for convention in CONVENTIONS:
            assert convention in prompt


def test_the_abstract_prompt_carries_them_too(tmp_path, analyses_dir, lenses_dir):
    domain_dir = _domain_dir(tmp_path, CONVENTIONS)
    _, client = _run(tmp_path, analyses_dir, lenses_dir, domain_dir=domain_dir)

    abstract_prompts = client.prompts_for("paper_abstract")
    assert len(abstract_prompts) == 1
    for convention in CONVENTIONS:
        assert convention in abstract_prompts[0]


def test_a_domain_declaring_no_house_style_leaves_both_prompts_alone(
    tmp_path, analyses_dir, lenses_dir
):
    domain_dir = _domain_dir(tmp_path, None)
    _, client = _run(tmp_path, analyses_dir, lenses_dir, domain_dir=domain_dir)

    styled = load_house_style(DEFAULT_DOMAIN_DIR)
    assert styled is not None
    for prompt in client.prompts_for("paper_draft") + client.prompts_for("paper_abstract"):
        assert "House style" not in prompt
        for convention in CONVENTIONS + list(styled.conventions):
            assert convention not in prompt


def test_the_block_is_context_and_never_a_gate(tmp_path, analyses_dir, lenses_dir):
    """Prose that breaks the conventions still drafts, still persists, and is
    still what the record carries. Nothing validates, scores or rejects prose
    against the block -- a style gate is the mechanism CLAUDE.md forbids."""
    domain_dir = _domain_dir(tmp_path, CONVENTIONS)
    record, _ = _run(tmp_path, analyses_dir, lenses_dir, domain_dir=domain_dir)

    assert [draft["prose"] for draft in record["drafts"]] == [
        draft["prose"] for draft in UNSTYLED_PROSE
    ]
    assert record["shape"]["band"] == "strong"
    assert (tmp_path / "papers" / f"{record['paper_brief_id']}.json").is_file()
