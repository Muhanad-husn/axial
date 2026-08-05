"""Outer acceptance test for issue #412 (Phase A v1 slice 07 -- Gather: the
disagreement pass, spec §7.18, P0-13).

Locked behavioural contract, read off `specs/PRODUCT.md` §7.18 and D12/D13
(`docs/DECISIONS.md`, `plans/phase-a-v1/README.md`):

Given slice 06's name pages on disk (`data/vault/names/`), slice 05's alias
      map, slice 04's inventory and slice 02's per-note answer records
When  the operator runs `axial names gather`
Then  a name whose assembled packet fits under the budget takes exactly ONE
      model call, and its name page gains a section saying what the authors
      gathered there disagree about, plus name-to-name links to the other
      names the index already carries
And   a name whose packet exceeds the budget is split into batches, Gather
      runs once per batch, and one short final call merges the batch
      findings into a single write on the page
And   the budget is a code constant that is never spelled out, named, or
      hinted at inside any prompt the model sees (D12's named regression
      risk: "a hard character budget in code, not in the prompt")
And   no assembled model input ever carries a note's full `chunk_text` --
      only the packet fields (author, year, one-sentence claim, whose
      position it is, what that position is where the note carries one, who
      it argues against) (D13: "Gather itself never reads full notes")
And   a member note interrogated before frame 0.2 -- which carries no
      `position` key at all -- renders byte-for-byte what it rendered before
      the field existed, so `GatherJob.key` is unchanged and the recorded
      findings in `data/names/disagreements.jsonl` stay addressable
      (issue #496)
And   every disagreement written onto a page has a corresponding record on
      disk (`data/names/disagreements.jsonl`, the convention slice 02's
      `data/answers/` set) carrying the name, the member-note ids that fed
      it, which batch produced each finding, and whether the page's text
      survived a merge call -- scope added mid-flight so issue #447's
      undecided quality measure does not force a re-run of the corpus pass
      to recover provenance

Seam decisions
-----------------------------------------------------------------------
1. **Fixtures are written directly in slice 02/04/05/06's own documented
   on-disk shapes**, not produced by running those passes -- each already
   has its own acceptance test; this one's subject is what Gather does with
   them. The name pages themselves are produced by the REAL
   `axial.materialize.run_materialize`, because "written onto slice 06's
   name page" is exactly what is under test.
2. **A recording fake client**, injected through the existing
   `client: LLMClient | None` seam (`axial.tag.run_tag`,
   `axial.vault.run_vault_write`, `axial.merge_names.run_merge_names`), so
   every prompt the model would see is captured verbatim and asserted
   against. One CLI smoke test at the bottom exercises the real `axial
   names gather` subprocess.
3. **`workers=1` everywhere**, so the recorded prompt order is the call
   order. Concurrency is exercised by the real pass's default, not pinned
   here.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from axial.gather import (
    DEFAULT_MIN_GATHER_MEMBERS,
    DISAGREEMENT_HEADING,
    GATHER_PACKET_CHAR_BUDGET,
    MEMBER_PACKET_CHARS,
    GatherJob,
    GatherResponseError,
    MemberPacket,
    _resolve_min_gather_members,
    _select_by_canonical,
    build_packets,
    parse_gather_response,
    render_packet,
    run_gather,
    split_into_batches,
    upsert_disagreement_section,
)
from axial.llm import PROVIDER_ENV_VAR
from axial.materialize import run_materialize

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# A sentinel long enough, and odd enough, that finding it inside any prompt
# proves a note's full text leaked into the model input (D13).
CHUNK_TEXT_SENTINEL = "ZZQX-full-note-body-that-gather-must-never-read-ZZQX"


class FakeClient:
    """Records every prompt and replies with a scripted response.

    Batch calls and the merge call are told apart by what the prompt
    carries, not by its wording: a batch prompt carries the fixture's own
    member packets (and so its authors), the merge call carries only the
    batch findings. `batch` is consumed in batch order with the last entry
    repeating, so a test that only cares about "one call" scripts one.
    `merge` works the same way and also accepts a single string for the
    common one-response case; a list lets a test script a merge call that
    keeps failing across `complete_json`'s own bounded re-ask budget."""

    _FIXTURE_AUTHORS = ("Charles Tilly", "Miguel Centeno")

    def __init__(self, batch: list[str], merge: str | list[str] | None = None):
        self._batch = list(batch)
        if merge is None:
            self._merge: list[str] | None = None
        elif isinstance(merge, str):
            self._merge = [merge]
        else:
            self._merge = list(merge)
        self.prompts: list[str] = []
        self.batch_prompts: list[str] = []
        self.merge_prompts: list[str] = []
        self.pass_names: list[str | None] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.prompts.append(prompt)
        self.pass_names.append(pass_name)
        if any(author in prompt for author in self._FIXTURE_AUTHORS):
            self.batch_prompts.append(prompt)
            return self._batch[min(len(self.batch_prompts) - 1, len(self._batch) - 1)]
        self.merge_prompts.append(prompt)
        assert self._merge is not None, "an unexpected merge call was made"
        return self._merge[min(len(self.merge_prompts) - 1, len(self._merge) - 1)]

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake"


def _response(disagreement: str, names: list[str] | None = None) -> str:
    return json.dumps({"disagreement": disagreement, "names": names or []})


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _answer_record(
    chunk_id: str,
    source_id: str,
    *,
    claim: str,
    position_of: str,
    arguing_against: list[str],
    names: list[dict],
    position: str | None = None,
) -> dict:
    """One answer record in slice 02's own on-disk shape. `position` omitted
    is the **frame 0.1** shape -- the key is absent entirely, which is what
    every one of the corpus's 6,148 existing records looks like (issue
    #496); passing one writes the frame 0.2 shape."""
    answers = {
        "about": ["state formation"],
        "claim": claim,
        "move": "x",
        "ranges_over": "not-in-passage",
        "stops_holding": "not-in-passage",
        "position_of": position_of,
        "arguing_against": arguing_against,
        "names": names,
        "citations": [],
        "mechanism": "not-in-passage",
        "evidence": "not-in-passage",
        "comparison": "not-in-passage",
        "defines": [],
        "uses": [],
        "concedes": "not-in-passage",
        "assumes": "not-in-passage",
    }
    if position is not None:
        answers["position"] = position
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "section": "Introduction",
        "pass": "note_interrogate",
        "model": "stub",
        "frame_version": "0.2" if position is not None else "0.1",
        "answered_at": "2026-01-01T00:00:00Z",
        "answers": answers,
    }


def _write_source(root: Path, source_id: str, author: str, year: int, chunk_ids: list[str]) -> None:
    _write_jsonl(
        root / "data" / "chunks" / f"{source_id}.jsonl",
        [
            {
                "chunk_id": chunk_id,
                "section": "Introduction",
                "section_order": str(index),
                "text": f"{CHUNK_TEXT_SENTINEL} {chunk_id} " + ("body text. " * 40),
            }
            for index, chunk_id in enumerate(chunk_ids)
        ],
    )
    _write_json(
        root / "data" / "envelopes" / f"{source_id}.json",
        {
            "source_id": source_id,
            "thesis": "Thesis.",
            "toc": [{"title": "Chapter 1", "children": ["Introduction"]}],
            "scope": "Scope.",
            "stated_argument": "Argument.",
        },
    )
    _write_json(
        root / "data" / "source_meta" / f"{source_id}.json",
        {
            "author": {"value": author, "provenance": "title page"},
            "title": {"value": f"Book {source_id}", "provenance": "embedded metadata"},
            "date": {"value": year, "provenance": "embedded metadata"},
        },
    )


def _build_small_fixture(root: Path) -> None:
    """Two books whose notes both name "war making", plus a second name
    ("Michael Mann") the index carries so a name-to-name link has somewhere
    to point, and one name the model will invent that the index does NOT
    carry."""
    _write_source(root, "tilly-1990", "Charles Tilly", 1990, ["tilly-1990_000_intro_001"])
    _write_source(root, "centeno-2002", "Miguel Centeno", 2002, ["centeno-2002_000_intro_001"])

    _write_jsonl(
        root / "data" / "answers" / "tilly-1990.jsonl",
        [
            _answer_record(
                "tilly-1990_000_intro_001",
                "tilly-1990",
                claim="War made the state and the state made war.",
                position_of="bellicist historical sociology",
                arguing_against=["modernization theory"],
                names=[
                    {"name": "war making", "kind": "concept"},
                    {"name": "Michael Mann", "kind": "person"},
                ],
            )
        ],
    )
    _write_jsonl(
        root / "data" / "answers" / "centeno-2002.jsonl",
        [
            _answer_record(
                "centeno-2002_000_intro_001",
                "centeno-2002",
                claim="Limited war produced limited states in Latin America.",
                position_of="comparative historical sociology",
                arguing_against=["Charles Tilly"],
                names=[{"name": "war making", "kind": "concept"}],
            )
        ],
    )

    _write_jsonl(
        root / "data" / "names" / "inventory.jsonl",
        [
            {
                "surface": "war making",
                "kind": "concept",
                "count": 2,
                "chunk_ids": ["tilly-1990_000_intro_001", "centeno-2002_000_intro_001"],
            },
            {
                "surface": "Michael Mann",
                "kind": "person",
                "count": 1,
                "chunk_ids": ["tilly-1990_000_intro_001"],
            },
        ],
    )
    _write_json(
        root / "data" / "names" / "alias_map.json",
        {
            "version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "nodes": [
                {"canonical": "Michael Mann", "kind": "person", "aliases": []},
                {"canonical": "war making", "kind": "concept", "aliases": []},
            ],
        },
    )


def _build_large_fixture(root: Path, members: int = 60) -> None:
    """One name ("war making") named by `members` notes across two books,
    each carrying a realistically long claim -- enough assembled packet to
    exceed the budget and force at least two batches."""
    long_claim = (
        "War making concentrated coercion and capital in the hands of rulers who "
        "had to bargain with their populations for the means of war, and that "
        "bargaining is what produced the representative institutions later read "
        "back as the natural form of the state. "
    )
    chunk_ids: dict[str, list[str]] = {"tilly-1990": [], "centeno-2002": []}
    for index in range(members):
        source_id = "tilly-1990" if index % 2 == 0 else "centeno-2002"
        chunk_ids[source_id].append(f"{source_id}_{index:03d}_intro_001")

    _write_source(root, "tilly-1990", "Charles Tilly", 1990, chunk_ids["tilly-1990"])
    _write_source(root, "centeno-2002", "Miguel Centeno", 2002, chunk_ids["centeno-2002"])
    for source_id, ids in chunk_ids.items():
        _write_jsonl(
            root / "data" / "answers" / f"{source_id}.jsonl",
            [
                _answer_record(
                    chunk_id,
                    source_id,
                    claim=long_claim,
                    position_of="bellicist historical sociology",
                    arguing_against=["modernization theory"],
                    names=[{"name": "war making", "kind": "concept"}],
                )
                for chunk_id in ids
            ],
        )

    all_ids = sorted(chunk_ids["tilly-1990"] + chunk_ids["centeno-2002"])
    _write_jsonl(
        root / "data" / "names" / "inventory.jsonl",
        [{"surface": "war making", "kind": "concept", "count": members, "chunk_ids": all_ids}],
    )
    _write_json(
        root / "data" / "names" / "alias_map.json",
        {
            "version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "nodes": [{"canonical": "war making", "kind": "concept", "aliases": []}],
        },
    )


def _dirs(root: Path) -> dict:
    return {
        "alias_map_path": root / "data" / "names" / "alias_map.json",
        "inventory_path": root / "data" / "names" / "inventory.jsonl",
        "answers_dir": root / "data" / "answers",
        "source_meta_dir": root / "data" / "source_meta",
        "vault_dir": root / "data" / "vault",
    }


def _materialize(root: Path) -> None:
    run_materialize(
        chunks_dir=root / "data" / "chunks",
        envelopes_dir=root / "data" / "envelopes",
        artifacts_dir=root / "data" / "artifacts",
        **_dirs(root),
    )


def _disagreements_path(root: Path) -> Path:
    return root / "data" / "names" / "disagreements.jsonl"


def _low_threshold_config_path(root: Path) -> Path:
    """Every fixture in this file predates the founder's member-count scope
    cut (2026-07-29) and exercises the pass at its `_MIN_MEMBERS` floor of 2
    -- the "configured member threshold" tests below cover the real default
    (`DEFAULT_MIN_GATHER_MEMBERS`, 10) explicitly, by name, with their own
    `config_path` override; this keeps every other test's fixture asking
    about its 2-member name the way it always did, unaffected by that
    default's own value."""
    path = root / "gather-test-config.yaml"
    if not path.exists():
        path.write_text(yaml.safe_dump({"gather": {"min_members": 2}}), encoding="utf-8")
    return path


def _gather(root: Path, client, **overrides):
    kwargs = {
        **_dirs(root),
        "disagreements_path": _disagreements_path(root),
        "client": client,
        "workers": 1,
        "config_path": _low_threshold_config_path(root),
    }
    kwargs.update(overrides)
    return run_gather(**kwargs)


def _records(root: Path) -> list[dict]:
    path = _disagreements_path(root)
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _page(root: Path, canonical: str) -> str:
    return (root / "data" / "vault" / "names" / f"{canonical}.md").read_text(encoding="utf-8")


# -- inner unit tests: the two pure pieces the budget rests on ----------------


def test_a_rendered_packet_carries_the_five_fields_and_nothing_else():
    packet = MemberPacket(
        chunk_id="src1_000_intro_001",
        author="Charles Tilly",
        year=1990,
        claim="War made the state.",
        position_of="bellicist historical sociology",
        arguing_against="modernization theory",
    )
    rendered = render_packet(packet)

    assert "Charles Tilly" in rendered
    assert "1990" in rendered
    assert "War made the state." in rendered
    assert "bellicist historical sociology" in rendered
    assert "modernization theory" in rendered
    assert len(rendered) <= MEMBER_PACKET_CHARS


# -- issue #496: the old packet format is frozen, byte for byte -- ONLY when
# it fits under the cap untouched ---------------------------------------------
#
# THIS LITERAL IS A PIN, NOT A FIXTURE. It is what `main` rendered for a
# member note whose answer record carries no `position` key, short enough
# that neither `main`'s tail truncation nor #500/D1's claim-remainder
# truncation ever engages. That untruncated case is still frozen after D1:
# nothing was truncated either way, so there is nothing for the render order
# to change. A packet old OR new format that DOES hit the cap is a different
# story -- see
# `test_a_packet_over_the_cap_no_longer_renders_byte_for_byte_this_is_the_500_re_key`
# below, which pins that #500 deliberately breaks the byte-for-byte guarantee
# once truncation is in play. Do not "update" this literal to match new
# behaviour: a diff in an UNTRUNCATED case means the change is wrong.
#
# There used to be a second pinned literal here, `OLD_FORMAT_JOB_KEY`:
# `GatherJob.key` was a sha256 over the rendered packets above, so the old
# render pinned the key too. Issue #678 retired that -- the key is now a
# hash of the name's SOURCE SET, not its render -- so pinning a render no
# longer says anything about the key. See the `GatherJob.key` tests below
# (issue #678) for what the key contract is now.
OLD_FORMAT_MEMBER_RENDER = (
    "Charles Tilly (1990): War made the state and the state made war. "
    "[position of: bellicist historical sociology; arguing against: modernization theory]"
)


def _old_format_packets() -> list[MemberPacket]:
    """Two members carrying no `position` -- packets as they were built
    before frame 0.2 existed."""
    return [
        MemberPacket(
            chunk_id="tilly-1990_000_intro_001",
            author="Charles Tilly",
            year=1990,
            claim="War made the state and the state made war.",
            position_of="bellicist historical sociology",
            arguing_against="modernization theory",
        ),
        MemberPacket(
            chunk_id="centeno-2002_000_intro_001",
            author="Miguel Centeno",
            year=2002,
            claim="Limited war produced limited states in Latin America.",
            position_of="comparative historical sociology",
            arguing_against="Charles Tilly",
        ),
    ]


def test_an_old_format_member_renders_exactly_as_it_did_before_position_existed():
    """The one thing #496 must not break: an old-format render is a frozen
    wire format. (What used to be this test's second half -- that the same
    render also pinned `GatherJob.key` -- is retired by #678, which keys on
    the source set, not the render; see the `GatherJob.key` tests below.)"""
    packets = _old_format_packets()

    assert packets[0].position is None
    assert render_packet(packets[0]) == OLD_FORMAT_MEMBER_RENDER


def test_an_answer_record_with_no_position_key_builds_a_packet_with_no_position():
    """The absence has to survive the read, not just the render: `position`
    is taken on KEY PRESENCE, so a record written under frame 0.1 produces
    `None` -- structurally distinct from an abstention, which is a string."""
    record = _answer_record(
        "tilly-1990_000_intro_001",
        "tilly-1990",
        claim="War made the state and the state made war.",
        position_of="bellicist historical sociology",
        arguing_against=["modernization theory"],
        names=[],
    )
    assert "position" not in record["answers"]

    (packet,) = build_packets(
        ["tilly-1990_000_intro_001"],
        {"tilly-1990_000_intro_001": record},
        {"tilly-1990": ("Charles Tilly", 1990)},
    )

    assert packet.position is None
    assert render_packet(packet) == OLD_FORMAT_MEMBER_RENDER


# -- issue #678: `GatherJob.key` is the name's SOURCE SET, not its rendered
# packets -----------------------------------------------------------------


def test_gather_job_key_is_unchanged_by_a_content_only_edit_to_an_existing_member():
    """The core #678 contract at the `GatherJob.key` level: revising an
    already-represented member's answers -- a re-interrogation, a re-render
    -- must not move the key, because the disagreement's evidence is which
    books are in the room, not how one member's claim happened to render
    this run."""
    packets = _old_format_packets()
    revised = [
        replace(packets[0], claim="A totally different sentence about the same book."),
        replace(packets[1], author="M. Centeno", claim="Also revised, same book."),
    ]

    key_before = GatherJob(canonical="war making", batches=(tuple(packets),)).key
    key_after = GatherJob(canonical="war making", batches=(tuple(revised),)).key

    assert key_before == key_after


def test_gather_job_key_changes_when_a_member_from_a_new_source_joins():
    """The other half: a member whose `chunk_id` resolves to a `source_id`
    neither existing member came from DOES move the key -- a genuinely new
    book might change who is arguing with whom."""
    packets = _old_format_packets()
    new_book_member = MemberPacket(
        chunk_id="hobsbawm-1990_000_intro_001",
        author="Eric Hobsbawm",
        year=1990,
        claim="Nations and nationalism, not war alone, forged the modern state.",
        position_of="the author's own",
        arguing_against="Charles Tilly",
    )

    key_before = GatherJob(canonical="war making", batches=(tuple(packets),)).key
    key_after = GatherJob(canonical="war making", batches=(tuple([*packets, new_book_member]),)).key

    assert key_before != key_after


def test_gather_job_key_differs_across_canonicals_sharing_the_same_source_set():
    """Two names named by exactly the same two books are not the same job --
    the canonical has to be part of the key, or they would collide."""
    packets = _old_format_packets()

    key_a = GatherJob(canonical="war making", batches=(tuple(packets),)).key
    key_b = GatherJob(canonical="state formation", batches=(tuple(packets),)).key

    assert key_a != key_b


def test_a_name_mixing_both_frames_renders_the_new_field_only_on_the_members_that_have_it():
    """The corpus is a permanent mix: one name's members can come from a
    book interrogated last month and a book interrogated after the split."""
    old = _answer_record(
        "tilly-1990_000_intro_001",
        "tilly-1990",
        claim="War made the state and the state made war.",
        position_of="bellicist historical sociology",
        arguing_against=["modernization theory"],
        names=[],
    )
    new = _answer_record(
        "centeno-2002_000_intro_001",
        "centeno-2002",
        claim="Limited war produced limited states in Latin America.",
        position_of="the author's own",
        position="war in Latin America was too limited to build strong states",
        arguing_against=["Charles Tilly"],
        names=[],
    )

    old_packet, new_packet = build_packets(
        [old["chunk_id"], new["chunk_id"]],
        {old["chunk_id"]: old, new["chunk_id"]: new},
        {"tilly-1990": ("Charles Tilly", 1990), "centeno-2002": ("Miguel Centeno", 2002)},
    )

    assert render_packet(old_packet) == OLD_FORMAT_MEMBER_RENDER
    assert render_packet(new_packet) == (
        "Miguel Centeno (2002): Limited war produced limited states in Latin America. "
        "[position of: the author's own; "
        "arguing against: Charles Tilly; "
        "position: war in Latin America was too limited to build strong states]"
    )


def test_the_bracket_survives_the_cap_and_claim_is_truncated_into_the_remainder():
    """Issue #500, D1, the accepted fix. Before: the whole line was rendered
    then the TAIL truncated, so whichever field sat last (`position`, or
    `arguing_against` in the old field order) was what a long packet lost --
    measured live, 22.4% of all rendered packets lost `arguing_against`
    entirely. After: the bracket (`position_of`, `arguing_against`,
    `position`) is reserved whole and `claim` -- the field that actually
    runs long -- is truncated into whatever is left of `MEMBER_PACKET_CHARS`.
    This is the acceptance case: a `claim` long enough to blow the cap on its
    own must not cost the bracket anything.
    """
    # Padded to `MEMBER_PACKET_CHARS` itself -- guaranteed longer than any
    # possible remainder left after the bracket, whatever the cap is set to,
    # so this test does not silently stop exercising truncation if the cap
    # moves again (#500's own cap correction, 400 -> 800, is exactly why
    # this is derived rather than a hard-coded literal).
    packet = MemberPacket(
        chunk_id="centeno-2002_000_intro_001",
        author="Miguel Centeno",
        year=2002,
        claim="W" * MEMBER_PACKET_CHARS,
        position_of="the author's own",
        position="war in Latin America was too limited to build strong states",
        arguing_against="Charles Tilly",
    )
    rendered = render_packet(packet)

    assert len(rendered) <= MEMBER_PACKET_CHARS
    # Every bracket field survives in full -- this is the whole fix.
    assert "position of: the author's own" in rendered
    assert "arguing against: Charles Tilly" in rendered
    assert "position: war in Latin America was too limited to build strong states" in rendered
    # `claim` is the field that gave way, truncated with the same ellipsis
    # marker the old tail truncation used.
    assert rendered.count("W") < MEMBER_PACKET_CHARS
    assert (
        rendered.rstrip("]").endswith("…") is False
    )  # ellipsis sits before the bracket, not at EOL
    assert "…" in rendered


def test_a_packet_that_fits_the_cap_untouched_renders_every_field_verbatim():
    """Boundary: nothing to truncate. All three bracket fields and the whole
    `claim` appear, and the render is well under `MEMBER_PACKET_CHARS`."""
    packet = MemberPacket(
        chunk_id="centeno-2002_000_intro_001",
        author="Miguel Centeno",
        year=2002,
        claim="Limited war produced limited states in Latin America.",
        position_of="the author's own",
        position="war in Latin America was too limited to build strong states",
        arguing_against="Charles Tilly",
    )
    rendered = render_packet(packet)

    assert rendered == (
        "Miguel Centeno (2002): Limited war produced limited states in Latin America. "
        "[position of: the author's own; "
        "arguing against: Charles Tilly; "
        "position: war in Latin America was too limited to build strong states]"
    )
    assert "…" not in rendered
    assert len(rendered) < MEMBER_PACKET_CHARS


def test_a_packet_over_the_cap_no_longer_renders_byte_for_byte_this_is_the_500_re_key():
    """The pre-0.2 byte-for-byte render contract (#496) is DELIBERATELY
    broken by #500/D1 for any packet that hits the cap, old format or new.
    `main`'s tail truncation used to cut into the bracket -- `arguing
    against` here loses its own value entirely, down to "modernization" with
    no closing bracket. D1 truncates `claim` instead and the bracket comes
    through whole. That means `GatherJob.key` changes for this exact
    old-format packet the moment it crosses the cap, which is the corpus
    re-key issue #500 pays for (see `plans/name-layer-rekey/README.md`,
    slice 03) -- not an accidental drift.
    """
    # Padded to `MEMBER_PACKET_CHARS` itself, same reasoning as the sibling
    # test above -- guaranteed to force truncation whatever the cap is set
    # to.
    packet = MemberPacket(
        chunk_id="tilly-1990_000_intro_001",
        author="Charles Tilly",
        year=1990,
        claim="W" * MEMBER_PACKET_CHARS,
        position_of="bellicist historical sociology",
        arguing_against="modernization theory",
        # No `position` -- this is the pre-0.2 record shape (#496).
    )
    assert packet.position is None

    rendered = render_packet(packet)

    assert len(rendered) <= MEMBER_PACKET_CHARS
    # The bracket survives whole under D1 -- unlike `main`'s tail truncation,
    # which would have cut "arguing against: modernization theory]" down to
    # an unterminated "arguing against: modernization".
    assert "arguing against: modernization theory]" in rendered
    assert "position of: bellicist historical sociology" in rendered
    # `claim` is what gave way instead.
    assert rendered.count("W") < MEMBER_PACKET_CHARS


def test_a_position_key_holding_an_abstention_is_rendered_not_dropped():
    """An abstention is an answer the note gave (D7). Only an ABSENT key --
    a question the note was never asked -- renders nothing."""
    record = _answer_record(
        "centeno-2002_000_intro_001",
        "centeno-2002",
        claim="Limited war produced limited states.",
        position_of="the author's own",
        position="not-in-passage",
        arguing_against=["Charles Tilly"],
        names=[],
    )

    (packet,) = build_packets(
        [record["chunk_id"]],
        {record["chunk_id"]: record},
        {"centeno-2002": ("Miguel Centeno", 2002)},
    )

    # Rendered as the same marker every other abstaining field gets, not
    # dropped the way an absent key is. `position` is the bracket's last
    # clause, so it closes the bracket rather than carrying a separator.
    assert packet.position is not None
    assert f"position: {packet.position}]" in render_packet(packet)


def test_a_rendered_packet_is_capped_so_the_budget_is_a_guarantee():
    """Everything oversized at once -- author, claim, and the whole
    bracket. However pathological the inputs, the cap holds; this is the
    arithmetic guarantee `GATHER_PACKET_CHAR_BUDGET //
    MEMBER_PACKET_CHARS` rests on."""
    packet = MemberPacket(
        chunk_id="src1_000_intro_001",
        author="A" * 500,
        year=1990,
        claim="B" * 5000,
        position_of="C" * 500,
        arguing_against="D" * 500,
    )
    assert len(render_packet(packet)) <= MEMBER_PACKET_CHARS
    # A frame 0.2 member carries one field more, so it meets the cap more
    # often. The cap still holds, which is what makes the block budget
    # arithmetic rather than an average.
    assert len(render_packet(replace(packet, position="E" * 500))) <= MEMBER_PACKET_CHARS


def test_the_one_degenerate_case_a_bracket_alone_over_the_cap_falls_back_to_tail_truncation():
    """Issue #500, D1's named degenerate case: `position_of` and
    `arguing_against` together already exceed `MEMBER_PACKET_CHARS` before
    `claim` gets a single character of remainder. There is no split to make
    -- `render_packet` falls back to `main`'s pre-D1 whole-line-then-tail
    truncation, which is not new behaviour and needs no new constant. The
    cap still holds; that is the one thing this path is not allowed to give
    up."""
    # Each bracket field alone is padded to `MEMBER_PACKET_CHARS`, so the two
    # together always exceed the cap regardless of its value -- the
    # degenerate condition by construction, not by a literal tuned to 400.
    packet = MemberPacket(
        chunk_id="src1_000_intro_001",
        author="Charles Tilly",
        year=1990,
        claim="short claim",
        position_of="C" * MEMBER_PACKET_CHARS,
        arguing_against="D" * MEMBER_PACKET_CHARS,
    )
    rendered = render_packet(packet)

    assert len(rendered) <= MEMBER_PACKET_CHARS
    assert rendered.endswith("…")


def test_split_into_batches_keeps_every_batch_under_the_budget():
    packets = [
        MemberPacket(
            chunk_id=f"src1_{index:03d}_intro_001",
            author="Charles Tilly",
            year=1990,
            claim="W" * 300,
            position_of="bellicist historical sociology",
            arguing_against="modernization theory",
        )
        for index in range(200)
    ]
    batches = split_into_batches(packets)

    assert len(batches) > 1
    assert [packet for batch in batches for packet in batch] == packets
    for batch in batches:
        assert sum(len(render_packet(packet)) + 1 for packet in batch) <= GATHER_PACKET_CHAR_BUDGET


def test_upsert_replaces_an_existing_section_instead_of_stacking_them():
    page = "---\nname: X\n---\n# X\n\n**Member notes:**\n- [[a]]\n"
    once = upsert_disagreement_section(page, "First reading.", [])
    twice = upsert_disagreement_section(once, "Second reading.", [])

    assert twice.count(DISAGREEMENT_HEADING) == 1
    assert "Second reading." in twice
    assert "First reading." not in twice
    assert "**Member notes:**" in twice


def test_upsert_with_a_null_disagreement_removes_an_existing_section():
    page = "---\nname: X\n---\n# X\n\n**Member notes:**\n- [[a]]\n"
    with_section = upsert_disagreement_section(page, "A reading.", [])
    removed = upsert_disagreement_section(with_section, None, [])

    assert DISAGREEMENT_HEADING not in removed
    assert "A reading." not in removed
    assert "**Member notes:**" in removed


# -- per-canonical selection: the union of a name's whole record history -----
# (#495 -- `disagreements.jsonl` is append-only, so one canonical can carry
# more than one record when an upstream re-render changes its packet hash
# without changing the canonical. The write loop selects across ALL of a
# canonical's records, never just the one under its current key. Records are
# written in both orders below so nothing here could pass on file order
# alone.)


def _disagreement_record(name_key: str, canonical: str, disagreement: str | None) -> dict:
    return {"name_key": name_key, "canonical": canonical, "disagreement": disagreement}


def test_select_by_canonical_keeps_an_older_finding_over_a_later_null():
    older = _disagreement_record("key-a", "war making", "They used to disagree about scope.")
    newer_null = _disagreement_record("key-b", "war making", None)

    assert _select_by_canonical([older, newer_null])["war making"] is older


def test_select_by_canonical_picks_whichever_non_null_record_is_physically_last():
    first = _disagreement_record("key-a", "war making", "First reading.")
    second = _disagreement_record("key-b", "war making", "Second reading.")

    # The choice tracks file order (chronology), not some fixed content-based
    # tie-break -- flipping which record comes last flips the winner.
    assert _select_by_canonical([first, second])["war making"] is second
    assert _select_by_canonical([second, first])["war making"] is first


def test_select_by_canonical_falls_back_to_the_newest_record_when_every_one_is_null():
    older_null = _disagreement_record("key-a", "war making", None)
    newer_null = _disagreement_record("key-b", "war making", None)

    selected = _select_by_canonical([older_null, newer_null])
    assert selected["war making"] is newer_null

    reversed_selected = _select_by_canonical([newer_null, older_null])
    assert reversed_selected["war making"] is older_null


def test_parse_gather_response_reads_a_structured_null():
    disagreement, names = parse_gather_response(_response(None, ["Some Name"]))
    assert disagreement is None
    # A null finding still carries whatever names came with it -- the
    # caller (`_gather_one`) is what decides names are only kept for a
    # non-null finding, not the parser.
    assert names == ["Some Name"]


def test_parse_gather_response_rejects_a_missing_disagreement_key():
    with pytest.raises(GatherResponseError):
        parse_gather_response(json.dumps({"names": []}))


def test_parse_gather_response_rejects_an_empty_disagreement_string():
    with pytest.raises(GatherResponseError):
        parse_gather_response(_response("", []))


# -- literal "null" as a JSON *string*, not the JSON literal (regression) ----
# (fix, 2026-07-29: measured live on the seeded 100-name sample after the
# null-is-a-last-resort fix -- `Russia` (429 members), `Adrienne
# Windhoff-Héritier` and `Müller and Weede (1990)` all carried the literal
# 4-character string "null" as their finding, which used to pass validation
# as a genuine disagreement and would have been written onto the page.)


@pytest.mark.parametrize(
    "raw_value",
    ["null", "NULL", "  null  ", '"null"', "none", "None", "'none'"],
)
def test_a_bare_null_or_none_string_is_treated_as_a_structured_null(raw_value):
    disagreement, _names = parse_gather_response(_response(raw_value, []))
    assert disagreement is None


def test_a_finding_that_merely_contains_the_word_null_is_left_alone():
    text = "The authors disagree about whether the null hypothesis of no state effect holds."
    disagreement, _names = parse_gather_response(_response(text, []))
    assert disagreement == text


# -- acceptance 1: under budget, one call, disagreement + name-to-name links --


def test_a_name_under_the_budget_takes_one_call_and_gains_disagreement_and_links(tmp_path):
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    client = FakeClient(
        batch=[
            _response(
                "Tilly reads war making as the engine of state capacity; Centeno "
                "reads Latin America's limited wars as producing limited states.",
                ["Michael Mann", "A Name The Index Does Not Carry"],
            )
        ]
    )
    result = _gather(tmp_path, client)

    assert len(client.prompts) == 1, "a name under the budget is exactly one call"
    assert result["names_gathered"] == 1
    assert result["merge_calls"] == 0

    page = _page(tmp_path, "war making")
    assert DISAGREEMENT_HEADING in page
    assert "Centeno reads Latin America's limited wars" in page
    # Name-to-name link, but only to a name the index actually carries -- a
    # link to a page that does not exist is not a link.
    assert "[[Michael Mann]]" in page
    assert "A Name The Index Does Not Carry" not in page
    # The slice 06 body survives underneath.
    assert "**Member notes:**" in page
    assert "[[tilly-1990_000_intro_001]]" in page


def test_re_running_gather_reuses_the_recorded_decision_and_calls_nothing(tmp_path):
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    first = FakeClient(batch=[_response("They disagree about scope.", [])])
    _gather(tmp_path, first)

    second = FakeClient(batch=[_response("A different answer nobody should see.", [])])
    result = _gather(tmp_path, second)

    assert second.prompts == []
    assert result["reused"] == 1
    assert "They disagree about scope." in _page(tmp_path, "war making")


def test_a_record_written_under_an_earlier_key_format_is_still_reused_no_migration_needed(
    tmp_path,
):
    """The #678 rollout-safety guarantee: `load_disagreements` recomputes a
    record's key from its own `canonical`/`chunk_ids` rather than trusting
    whatever format its persisted `name_key` happens to be in -- the same
    fields §7.18 already guarantees every record carries. A record written
    under the retired content-hash-of-rendered-packets key (or any other
    string) is still found, with no migration pass and no rewrite of
    `disagreements.jsonl`."""
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    _write_jsonl(
        _disagreements_path(tmp_path),
        [
            {
                "name_key": "not-a-real-source-set-key-this-is-the-old-pre-678-format",
                "canonical": "war making",
                "chunk_ids": ["tilly-1990_000_intro_001", "centeno-2002_000_intro_001"],
                "batches": [],
                "merged": False,
                "disagreement": "A finding recorded before issue #678.",
                "names": [],
                "pass": "gather",
                "model": "stub",
                "gathered_at": "2026-01-01T00:00:00Z",
            }
        ],
    )

    client = FakeClient(batch=[_response("Nobody should ever see this.", [])])
    result = _gather(tmp_path, client)

    assert client.prompts == [], "an old-format record must still resolve as a reuse"
    assert result["reused"] == 1
    assert "A finding recorded before issue #678." in _page(tmp_path, "war making")


# -- acceptance 2: over budget, one call per batch, then one merge call -------


def test_an_over_budget_name_runs_per_batch_then_one_merge_call(tmp_path):
    _build_large_fixture(tmp_path)
    _materialize(tmp_path)

    client = FakeClient(
        batch=[_response("Batch finding one.", []), _response("Batch finding two.", [])],
        merge=_response("The merged statement of the disagreement.", []),
    )
    result = _gather(tmp_path, client)

    assert result["batch_calls"] >= 2, "the fixture must actually exceed the budget"
    assert result["merge_calls"] == 1
    assert len(client.prompts) == result["batch_calls"] + 1

    # The final call is a merge over the batch FINDINGS, not over the packets.
    merge_prompt = client.prompts[-1]
    assert "Batch finding one." in merge_prompt
    assert "Charles Tilly" not in merge_prompt

    # One page, one section, the merged text -- not a truncated one and not
    # six stacked ones.
    page = _page(tmp_path, "war making")
    assert page.count(DISAGREEMENT_HEADING) == 1
    assert "The merged statement of the disagreement." in page
    assert "Batch finding one." not in page


# -- structured null: a batch that found nothing says so without prose -------
# (root cause behind both the ~15,000 empty-section pages a full pass would
# write and the merge prompt mistaking several "no disagreement" findings
# for readings that disagree with EACH OTHER, data/logs/
# 2026-07-29-gather-stratified-sample/summary.md)


def test_a_null_finding_writes_no_section(tmp_path):
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response(None, [])])
    result = _gather(tmp_path, client)

    assert result["pages_written"] == 0
    page = _page(tmp_path, "war making")
    assert DISAGREEMENT_HEADING not in page

    # The null is still persisted -- a re-run must not re-ask it.
    (record,) = _records(tmp_path)
    assert record["disagreement"] is None


def test_re_running_gather_reuses_a_recorded_null_and_calls_nothing(tmp_path):
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    first = FakeClient(batch=[_response(None, [])])
    _gather(tmp_path, first)

    second = FakeClient(batch=[_response("A disagreement nobody should see.", [])])
    result = _gather(tmp_path, second)

    assert second.prompts == []
    assert result["reused"] == 1
    assert DISAGREEMENT_HEADING not in _page(tmp_path, "war making")


def _revise_centeno_claim(root: Path, claim: str) -> None:
    """Re-renders `centeno-2002`'s one packet field -- under issue #678's
    source-set key this does NOT change the "war making" job's key, since
    `centeno-2002` was already on the page: see
    `test_revising_an_existing_members_claim_reuses_the_recorded_decision`
    below, which is the direct fix for the behaviour PR #474 documented
    (520 real names re-asked for exactly this reason, back when the key was
    a hash of the rendered packets)."""
    _write_jsonl(
        root / "data" / "answers" / "centeno-2002.jsonl",
        [
            _answer_record(
                "centeno-2002_000_intro_001",
                "centeno-2002",
                claim=claim,
                position_of="comparative historical sociology",
                arguing_against=["Charles Tilly"],
                names=[{"name": "war making", "kind": "concept"}],
            )
        ],
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _add_member_note(
    root: Path,
    *,
    chunk_id: str,
    source_id: str,
    claim: str,
    name: str = "war making",
    author: str = "New Author",
    year: int = 2010,
    new_source: bool,
) -> None:
    """Add one more member note naming `name` on top of `_build_small_
    fixture`'s corpus -- either from a source already represented on the
    page (`new_source=False`: `source_id` must be one of the fixture's own,
    e.g. `tilly-1990`) or from a genuinely new book (`new_source=True`,
    which also writes the chunk/envelope/source-metadata `_write_source`
    needs). Appends to that source's own answers file and to the name's
    `chunk_ids` in `inventory.jsonl`, the same shape a real re-
    interrogation or a re-run of `axial names build` produces -- the
    fixture-level lever issue #678's acceptance bar is written against."""
    if new_source:
        _write_source(root, source_id, author, year, [chunk_id])

    answers_path = root / "data" / "answers" / f"{source_id}.jsonl"
    existing = _read_jsonl(answers_path) if answers_path.is_file() else []
    existing.append(
        _answer_record(
            chunk_id,
            source_id,
            claim=claim,
            position_of="a later position",
            arguing_against=["someone else"],
            names=[{"name": name, "kind": "concept"}],
        )
    )
    _write_jsonl(answers_path, existing)

    inventory_path = root / "data" / "names" / "inventory.jsonl"
    rows = _read_jsonl(inventory_path)
    for row in rows:
        if row["surface"] == name:
            row["chunk_ids"] = sorted(set(row["chunk_ids"]) | {chunk_id})
            row["count"] = len(row["chunk_ids"])
    _write_jsonl(inventory_path, rows)


def _add_new_book_member(root: Path) -> None:
    """A brand-new book's note joining "war making" -- the one lever that
    still changes `GatherJob.key` under issue #678 (a source neither
    `tilly-1990` nor `centeno-2002` was on the page for before)."""
    _add_member_note(
        root,
        chunk_id="hobsbawm-1990_000_intro_001",
        source_id="hobsbawm-1990",
        claim="Nations and nationalism, not war alone, forged the modern state.",
        new_source=True,
    )


def test_a_name_whose_section_existed_survives_a_later_null_re_ask(tmp_path):
    """#495: the write loop unions a canonical's whole record history rather
    than reading only the record under its CURRENT key, so an older
    non-null record outlives a later null one at the same name."""
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    first = FakeClient(batch=[_response("They used to disagree about scope.", [])])
    _gather(tmp_path, first)
    assert DISAGREEMENT_HEADING in _page(tmp_path, "war making")

    _add_new_book_member(tmp_path)

    second = FakeClient(batch=[_response(None, [])])
    result = _gather(tmp_path, second)

    # A genuinely new source joined the page, so the job's key changed and
    # the name is asked -- exactly as before this fix, only the trigger
    # moved from "any content changed" to "the source set changed" (#678).
    assert result["asked"] == 1
    assert len(_records(tmp_path)) == 2, "both records stay on disk -- history is untouched"

    page = _page(tmp_path, "war making")
    assert DISAGREEMENT_HEADING in page
    assert "They used to disagree about scope." in page


def test_two_non_null_records_write_the_newer_finding(tmp_path):
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    first = FakeClient(batch=[_response("The original reading.", [])])
    _gather(tmp_path, first)
    assert "The original reading." in _page(tmp_path, "war making")

    _add_new_book_member(tmp_path)

    second = FakeClient(batch=[_response("The revised reading.", [])])
    result = _gather(tmp_path, second)

    assert result["asked"] == 1
    assert len(_records(tmp_path)) == 2

    page = _page(tmp_path, "war making")
    assert "The revised reading." in page
    assert "The original reading." not in page


def test_two_null_records_still_write_no_section(tmp_path):
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    first = FakeClient(batch=[_response(None, [])])
    _gather(tmp_path, first)
    assert DISAGREEMENT_HEADING not in _page(tmp_path, "war making")

    _add_new_book_member(tmp_path)

    second = FakeClient(batch=[_response(None, [])])
    result = _gather(tmp_path, second)

    assert result["asked"] == 1
    records = _records(tmp_path)
    assert len(records) == 2
    assert all(record["disagreement"] is None for record in records)
    assert DISAGREEMENT_HEADING not in _page(tmp_path, "war making")


# -- issue #678 acceptance: re-ask on a new SOURCE, not a new note ------------


def test_a_page_gaining_a_note_from_an_existing_source_is_not_re_asked(tmp_path):
    """The acceptance bar's first half: a note joining from a book already
    on the page (a second `tilly-1990` passage) must reuse the recorded
    disagreement, with no model call."""
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    first = FakeClient(batch=[_response("They disagree about scope.", [])])
    _gather(tmp_path, first)

    _add_member_note(
        tmp_path,
        chunk_id="tilly-1990_001_intro_002",
        source_id="tilly-1990",
        claim="A second passage, same book, also naming war making.",
        new_source=False,
    )

    second = FakeClient(batch=[_response("A different answer nobody should see.", [])])
    result = _gather(tmp_path, second)

    assert second.prompts == [], "a note from an already-represented book must not trigger a call"
    assert result["reused"] == 1
    assert result["asked"] == 0
    assert "They disagree about scope." in _page(tmp_path, "war making")


def test_a_page_gaining_a_note_from_a_new_book_is_re_asked(tmp_path):
    """The acceptance bar's second half: a note joining from a book NOT
    already on the page changes the source set, so the name is re-asked."""
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    first = FakeClient(batch=[_response("They disagree about scope.", [])])
    _gather(tmp_path, first)

    _add_new_book_member(tmp_path)

    second = FakeClient(batch=[_response("A newly expanded disagreement.", [])])
    result = _gather(tmp_path, second)

    assert len(second.prompts) == 1
    assert result["asked"] == 1
    assert "A newly expanded disagreement." in _page(tmp_path, "war making")


def test_revising_an_existing_members_claim_reuses_the_recorded_decision(tmp_path):
    """A re-interrogation or a re-render that changes an already-represented
    member's answer text -- same book, same source -- must not re-key the
    name either: the key no longer looks at content at all (issue #678)."""
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    first = FakeClient(batch=[_response("They disagree about scope.", [])])
    _gather(tmp_path, first)

    _revise_centeno_claim(tmp_path, "Limited war produced limited states -- revised.")

    second = FakeClient(batch=[_response("A different answer nobody should see.", [])])
    result = _gather(tmp_path, second)

    assert second.prompts == []
    assert result["reused"] == 1
    assert "They disagree about scope." in _page(tmp_path, "war making")


def test_limit_zero_makes_no_model_calls(tmp_path):
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response("Should never be seen.", [])])
    result = _gather(tmp_path, client, limit=0)

    assert client.prompts == []
    assert result["asked"] == 0
    assert DISAGREEMENT_HEADING not in _page(tmp_path, "war making")


def test_an_all_null_batched_name_makes_no_merge_call(tmp_path):
    _build_large_fixture(tmp_path, members=60)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response(None, []), _response(None, [])])
    result = _gather(tmp_path, client)

    assert result["batch_calls"] >= 2, "the fixture must actually exceed the budget"
    assert result["merge_calls"] == 0, "an all-null name spends no merge call"
    assert len(client.prompts) == result["batch_calls"], "no merge prompt was sent at all"

    (record,) = _records(tmp_path)
    assert record["merged"] is False
    assert record["disagreement"] is None
    assert DISAGREEMENT_HEADING not in _page(tmp_path, "war making")


def test_a_single_surviving_finding_among_batches_skips_the_merge_call(tmp_path):
    _build_large_fixture(tmp_path, members=60)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response(None, []), _response("The only real finding.", [])])
    result = _gather(tmp_path, client)

    assert result["merge_calls"] == 0, "one surviving finding needs no merge call"
    assert len(client.prompts) == result["batch_calls"]

    (record,) = _records(tmp_path)
    assert record["merged"] is False
    assert record["disagreement"] == "The only real finding."
    assert "The only real finding." in _page(tmp_path, "war making")


def test_a_null_batch_never_reaches_the_merge_call(tmp_path):
    _build_large_fixture(tmp_path, members=125)
    _materialize(tmp_path)

    client = FakeClient(
        batch=[
            _response(None, []),
            _response("Finding A.", []),
            _response("Finding B.", []),
        ],
        merge=_response("Merged from A and B only.", []),
    )
    result = _gather(tmp_path, client)

    assert result["batch_calls"] == 3, "the fixture must actually produce three batches"
    assert result["merge_calls"] == 1, "two real findings still merge"

    merge_prompt = client.prompts[-1]
    assert "Finding A." in merge_prompt
    assert "Finding B." in merge_prompt
    # The null batch was dropped, not merged: exactly two numbered readings
    # reach the merge call, not three.
    findings_block = merge_prompt.split("FINDINGS")[1].split("Write one account")[0]
    assert [line for line in findings_block.splitlines() if line.strip()] == [
        "1. Finding A.",
        "2. Finding B.",
    ]

    page = _page(tmp_path, "war making")
    assert page.count(DISAGREEMENT_HEADING) == 1
    assert "Merged from A and B only." in page


# -- invariant: a merge handed real evidence must not yield a null record ----
# (fix, 2026-07-29: `data/logs/2026-07-29-gather-rerun-after-472/summary.md`
# measured `Syria` -- 2 real batch findings out of 18 -- and `Michael Mann`
# -- 4 of 8 -- both merging to null/"no disagreement". There is no honest
# reading under which two genuine disagreements combine to nothing, so this
# is enforced in code, not asked for in the prompt.)


def test_a_merge_that_keeps_returning_null_falls_back_to_the_survivors_it_was_handed(
    tmp_path,
):
    _build_large_fixture(tmp_path, members=60)
    _materialize(tmp_path)

    client = FakeClient(
        batch=[_response("Finding A.", []), _response("Finding B.", [])],
        # Every merge attempt -- including every re-ask -- insists on null
        # despite two real surviving findings.
        merge=[_response(None, [])],
    )
    result = _gather(tmp_path, client)

    assert result["merge_calls"] == 1
    assert len(client.merge_prompts) == 3, (
        "the invariant is enforced through complete_json's own bounded "
        "re-ask budget, not a new retry loop"
    )

    (record,) = _records(tmp_path)
    assert record["disagreement"] is not None, (
        "a merge handed non-null findings must never persist a null record"
    )
    assert "Finding A." in record["disagreement"]
    assert "Finding B." in record["disagreement"]

    page = _page(tmp_path, "war making")
    assert DISAGREEMENT_HEADING in page
    assert "Finding A." in page
    assert "Finding B." in page


def test_a_merge_that_finds_a_real_disagreement_on_a_later_attempt_is_not_overridden(
    tmp_path,
):
    """The invariant only fires once complete_json's own re-ask budget is
    exhausted -- a merge call that eventually returns a real finding is used
    as-is, not replaced by the survivors' raw text."""
    _build_large_fixture(tmp_path, members=60)
    _materialize(tmp_path)

    client = FakeClient(
        batch=[_response("Finding A.", []), _response("Finding B.", [])],
        merge=[_response(None, []), _response("The real merged account.", [])],
    )
    result = _gather(tmp_path, client)

    assert result["merge_calls"] == 1
    assert len(client.merge_prompts) == 2

    (record,) = _records(tmp_path)
    assert record["disagreement"] == "The real merged account."


# -- acceptance 3: the budget never appears in a prompt (D12's risk) ----------


def test_the_budget_is_never_spelled_out_or_referenced_in_any_prompt(tmp_path):
    _build_large_fixture(tmp_path)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response("Finding.", [])], merge=_response("Merged.", []))
    _gather(tmp_path, client)

    assert len(client.prompts) > 2, "need both batch prompts and the merge prompt"
    forbidden = [
        str(GATHER_PACKET_CHAR_BUDGET),
        f"{GATHER_PACKET_CHAR_BUDGET:,}",
        str(MEMBER_PACKET_CHARS),
        "budget",
        "character limit",
        "characters",
    ]
    for prompt in client.prompts:
        lowered = prompt.lower()
        for token in forbidden:
            assert token.lower() not in lowered, (
                f"the budget leaked into the prompt as {token!r} -- D12 requires it "
                "to be a code constant, never an instruction the model reads"
            )


# -- acceptance 4: no full chunk_text ever reaches the model (D13) ------------


def test_gather_never_puts_a_notes_full_text_in_front_of_the_model(tmp_path):
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response("They disagree about the mechanism.", [])])
    _gather(tmp_path, client)

    assert client.prompts
    for prompt in client.prompts:
        assert CHUNK_TEXT_SENTINEL not in prompt, (
            "a note's full chunk_text reached the model input -- D13: Gather "
            "itself never reads full notes"
        )
    # The five packet fields DID reach it, so the absence above is not
    # vacuous.
    prompt = client.prompts[0]
    assert "Charles Tilly" in prompt
    assert "1990" in prompt
    assert "War made the state and the state made war." in prompt
    assert "bellicist historical sociology" in prompt
    assert "modernization theory" in prompt


def test_gather_skips_a_name_with_only_one_member_note(tmp_path):
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response("Finding.", [])])
    result = _gather(tmp_path, client)

    # "Michael Mann" is named by exactly one note: there is no second author
    # to disagree with, so no call is spent on it.
    assert result["names_skipped_single_member"] == 1
    assert len(client.prompts) == 1
    assert DISAGREEMENT_HEADING not in _page(tmp_path, "Michael Mann")


# Issue #508: the numeral-only and apparatus-pointer gates Gather used to
# apply here are gone. Both predicates now cut at inventory time
# (`axial.names.iter_name_occurrences`), so no such node can reach the alias
# map Gather reads -- which is also what removes its wiki page, the thing
# the old call-time gate never did. Pinned in
# `tests/ingestion/test_merge_names.py` and `tests/ingestion/test_names.py`.


# -- the configured member threshold: a founder scope decision, not a
# heuristic (2026-07-29) ------------------------------------------------------


def test_gather_skips_a_name_below_the_configured_member_threshold(tmp_path):
    """A name below `DEFAULT_MIN_GATHER_MEMBERS` (10) is skipped before a
    packet is assembled or a model call made -- distinct from, and on top
    of, the `_MIN_MEMBERS` (2) definitional gate: 9 members clears that gate
    but not the configured scope threshold."""
    _build_large_fixture(tmp_path, members=9)
    _materialize(tmp_path)

    # No config file at all -- exercises the real default, not this file's
    # shared low-threshold fixture config (`_low_threshold_config_path`).
    client = FakeClient(batch=[_response("Finding.", [])])
    result = _gather(tmp_path, client, config_path=tmp_path / "no-such-config.yaml")

    assert result["names_skipped_below_min_members"] == 1
    assert result["names_skipped_single_member"] == 0
    assert result["min_gather_members"] == DEFAULT_MIN_GATHER_MEMBERS
    assert client.prompts == [], "a below-threshold name must never reach a model call"
    assert DISAGREEMENT_HEADING not in _page(tmp_path, "war making")


def test_gather_asks_a_name_at_exactly_the_member_threshold(tmp_path):
    """A name at exactly the configured floor is asked -- the cut is
    inclusive of the threshold itself."""
    _build_large_fixture(tmp_path, members=DEFAULT_MIN_GATHER_MEMBERS)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response("They disagree about war making.", [])])
    result = _gather(tmp_path, client, config_path=tmp_path / "no-such-config.yaml")

    assert result["names_skipped_below_min_members"] == 0
    assert len(client.prompts) == 1
    assert DISAGREEMENT_HEADING in _page(tmp_path, "war making")


def test_gather_member_threshold_is_read_from_config(tmp_path):
    """An explicit `gather.min_members` in `config/pipeline.yaml` overrides
    the default -- lowering it to 5 lets a 5-member name through that the
    default (10) would have skipped."""
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(yaml.safe_dump({"gather": {"min_members": 5}}), encoding="utf-8")
    _build_large_fixture(tmp_path, members=5)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response("They disagree about war making.", [])])
    result = _gather(tmp_path, client, config_path=config_path)

    assert result["min_gather_members"] == 5
    assert result["names_skipped_below_min_members"] == 0
    assert len(client.prompts) == 1


def test_gather_member_threshold_override_still_skips_below_it(tmp_path):
    """The overridden threshold is still enforced, not just raised: a name
    below the *configured* 5 is skipped even though it clears the
    definitional 2-member gate."""
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(yaml.safe_dump({"gather": {"min_members": 5}}), encoding="utf-8")
    _build_large_fixture(tmp_path, members=4)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response("Finding.", [])])
    result = _gather(tmp_path, client, config_path=config_path)

    assert result["names_skipped_below_min_members"] == 1
    assert client.prompts == []


def test_resolve_min_gather_members_falls_back_to_default_when_config_absent(tmp_path):
    missing_path = tmp_path / "does-not-exist.yaml"
    assert _resolve_min_gather_members(missing_path) == DEFAULT_MIN_GATHER_MEMBERS


def test_resolve_min_gather_members_falls_back_to_default_when_gather_block_absent(tmp_path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(yaml.safe_dump({"llm": {"provider": "openrouter"}}), encoding="utf-8")
    assert _resolve_min_gather_members(config_path) == DEFAULT_MIN_GATHER_MEMBERS


def test_gather_never_hands_the_model_a_sentinel_author(tmp_path):
    """Fix (2026-07-29): `axial.vault.bibliographic_value` renders the
    `unavailable`/`not_attempted` sentinels as themselves for a note's own
    frontmatter -- correct there, so a metadata gap stays visible. A Gather
    packet is not frontmatter: 2 of 100 sampled entries named an author as
    "the 'unavailable (2000)' author" because the sentinel reached the model
    as if it were a person. This reproduces the real corpus's exact defect
    shape (`data/source_meta/heydemann-2000-66701ffbb36c.json`: `author` is
    the literal string `"unavailable"`, not `{value, provenance}`) and
    asserts the prompt carries a real fallback derived from `source_id`
    instead."""
    _write_source(
        tmp_path,
        "smith-2010-abc123def456",
        "Jane Smith",
        2010,
        ["smith-2010-abc123def456_000_intro_001"],
    )
    _write_source(
        tmp_path,
        "heydemann-2000-66701ffbb36c",
        "Placeholder",
        2000,
        ["heydemann-2000-66701ffbb36c_000_intro_001"],
    )
    # Overwrite with the real defect's exact on-disk shape.
    _write_json(
        tmp_path / "data" / "source_meta" / "heydemann-2000-66701ffbb36c.json",
        {
            "author": "unavailable",
            "title": "unavailable",
            "date": {"value": 2000, "provenance": "title page"},
        },
    )
    _write_jsonl(
        tmp_path / "data" / "answers" / "smith-2010-abc123def456.jsonl",
        [
            _answer_record(
                "smith-2010-abc123def456_000_intro_001",
                "smith-2010-abc123def456",
                claim="Upgrading is a response to genuine reform pressure.",
                position_of="reform-from-above",
                arguing_against=["authoritarian resilience theory"],
                names=[{"name": "authoritarian upgrading", "kind": "concept"}],
            )
        ],
    )
    _write_jsonl(
        tmp_path / "data" / "answers" / "heydemann-2000-66701ffbb36c.jsonl",
        [
            _answer_record(
                "heydemann-2000-66701ffbb36c_000_intro_001",
                "heydemann-2000-66701ffbb36c",
                claim="Upgrading absorbs pressure without ceding real power.",
                position_of="authoritarian resilience theory",
                arguing_against=["reform-from-above"],
                names=[{"name": "authoritarian upgrading", "kind": "concept"}],
            )
        ],
    )
    _write_jsonl(
        tmp_path / "data" / "names" / "inventory.jsonl",
        [
            {
                "surface": "authoritarian upgrading",
                "kind": "concept",
                "count": 2,
                "chunk_ids": [
                    "smith-2010-abc123def456_000_intro_001",
                    "heydemann-2000-66701ffbb36c_000_intro_001",
                ],
            }
        ],
    )
    _write_json(
        tmp_path / "data" / "names" / "alias_map.json",
        {
            "version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "nodes": [{"canonical": "authoritarian upgrading", "kind": "concept", "aliases": []}],
        },
    )

    _materialize(tmp_path)

    class RecordingClient:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            self.prompts.append(prompt)
            return _response("They disagree about the mechanism.", [])

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    client = RecordingClient()
    _gather(tmp_path, client)

    assert len(client.prompts) == 1
    prompt = client.prompts[0]
    assert "unavailable" not in prompt.lower()
    assert "Heydemann" in prompt
    assert "Jane Smith" in prompt


# -- the disagreement record: provenance for issue #447's undecided measure --


def test_every_disagreement_on_a_page_has_a_record_with_its_member_notes(tmp_path):
    _build_small_fixture(tmp_path)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response("They disagree about the mechanism.", ["Michael Mann"])])
    _gather(tmp_path, client)

    records = _records(tmp_path)
    assert len(records) == 1
    record = records[0]

    assert record["canonical"] == "war making"
    assert record["disagreement"] == "They disagree about the mechanism."
    assert record["disagreement"] in _page(tmp_path, "war making")
    # The member notes that fed it, traceable back to the passages.
    assert sorted(record["chunk_ids"]) == [
        "centeno-2002_000_intro_001",
        "tilly-1990_000_intro_001",
    ]
    # One under-budget call: one batch, no merge.
    assert record["merged"] is False
    assert [batch["batch"] for batch in record["batches"]] == [1]
    assert sorted(record["batches"][0]["chunk_ids"]) == sorted(record["chunk_ids"])
    assert record["batches"][0]["finding"] == record["disagreement"]


def test_the_batched_path_records_which_batch_each_finding_came_from(tmp_path):
    _build_large_fixture(tmp_path)
    _materialize(tmp_path)

    client = FakeClient(
        batch=[_response("Batch finding one.", []), _response("Batch finding two.", [])],
        merge=_response("The merged statement.", []),
    )
    result = _gather(tmp_path, client)

    (record,) = _records(tmp_path)
    assert record["merged"] is True
    assert record["disagreement"] == "The merged statement."
    assert len(record["batches"]) == result["batch_calls"] >= 2
    # Numbered in order, and every batch's own member notes are recorded --
    # the merge call is exactly where provenance is easiest to lose.
    assert [batch["batch"] for batch in record["batches"]] == list(
        range(1, len(record["batches"]) + 1)
    )
    per_batch = [chunk_id for batch in record["batches"] for chunk_id in batch["chunk_ids"]]
    assert per_batch == record["chunk_ids"]
    assert len(set(per_batch)) == len(per_batch)
    assert all(batch["finding"] for batch in record["batches"])


# ---------------------------------------------------------------------------
# Issue #677: the four `units_*` counters -- reused/asked/touching_new,
# derived from `disagreements.jsonl` itself (issue #678: a record already
# carries the `chunk_ids` it was written from), with no new manifest file.
# ---------------------------------------------------------------------------


class _NameKeyedGatherClient:
    """One scripted disagreement per name, keyed by whichever canonical
    name appears in the prompt. Every name in these fixtures has exactly two
    member notes -- always one call, never a merge -- so this sidesteps the
    shared `FakeClient`'s author-based batch/merge routing entirely."""

    def __init__(self, replies: dict[str, str]):
        self._replies = replies
        self.prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.prompts.append(prompt)
        for name, reply in self._replies.items():
            if name in prompt:
                return reply
        raise AssertionError(f"unexpected prompt, no scripted name matched: {prompt!r}")

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake"


def _write_units_fixture_name(
    root: Path, name: str, source_a: str, source_b: str
) -> tuple[str, str]:
    """One two-member name, its members drawn from two dedicated,
    never-reused source ids -- so a later test can add a genuinely new pair
    of sources without disturbing an earlier name's own provenance."""
    chunk_a = f"{source_a}_000_intro_001"
    chunk_b = f"{source_b}_000_intro_001"
    _write_source(root, source_a, "Author A", 2001, [chunk_a])
    _write_source(root, source_b, "Author B", 2002, [chunk_b])
    _write_jsonl(
        root / "data" / "answers" / f"{source_a}.jsonl",
        [
            _answer_record(
                chunk_a,
                source_a,
                claim=f"{name}: claim A.",
                position_of="position A",
                arguing_against=["x"],
                names=[{"name": name, "kind": "concept"}],
            )
        ],
    )
    _write_jsonl(
        root / "data" / "answers" / f"{source_b}.jsonl",
        [
            _answer_record(
                chunk_b,
                source_b,
                claim=f"{name}: claim B.",
                position_of="position B",
                arguing_against=["y"],
                names=[{"name": name, "kind": "concept"}],
            )
        ],
    )
    return chunk_a, chunk_b


def _write_units_fixture_index(root: Path, names: dict[str, tuple[str, str]]) -> None:
    """`inventory.jsonl`/`alias_map.json` covering exactly `names` (issue
    #677's tests rewrite the whole index each time a name is added, the same
    way a real `axial names build`/`merge` re-run would)."""
    _write_jsonl(
        root / "data" / "names" / "inventory.jsonl",
        [
            {"surface": name, "kind": "concept", "count": 2, "chunk_ids": list(chunk_ids)}
            for name, chunk_ids in names.items()
        ],
    )
    _write_json(
        root / "data" / "names" / "alias_map.json",
        {
            "version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "nodes": [{"canonical": name, "kind": "concept", "aliases": []} for name in names],
        },
    )


def test_unit_counters_reuse_the_second_run_and_flag_a_genuinely_new_source(tmp_path):
    """Issue #677's own acceptance bar, end to end:
    - a first-ever run (nothing in `disagreements.jsonl` yet) reports
      `units_asked == units_total` and does not crash
    - the same corpus run twice reports `units_asked: 0` and `units_reused
      == units_total`
    - adding a name whose members are genuinely new sources reports a
      non-zero `units_asked_touching_new`, a subset of `units_asked`
    - `units_asked + units_reused == units_total` throughout
    """
    root = tmp_path
    alpha = _write_units_fixture_name(root, "Alpha Claim", "units-src-1", "units-src-2")
    _write_units_fixture_index(root, {"Alpha Claim": alpha})

    # First-ever run: `disagreements.jsonl` does not exist yet.
    assert not _disagreements_path(root).is_file()
    first_client = _NameKeyedGatherClient({"Alpha Claim": _response("Alpha disagreement.")})
    first = _gather(root, first_client)
    assert len(first_client.prompts) == 1
    assert first["units_total"] == 1
    assert first["units_reused"] == 0
    assert first["units_asked"] == 1
    assert first["units_asked_touching_new"] == 1
    assert first["units_asked"] + first["units_reused"] == first["units_total"]

    # Second run, same corpus: "Alpha Claim" is already recorded.
    second_client = _NameKeyedGatherClient(
        {"Alpha Claim": _response("A different answer nobody should see.")}
    )
    second = _gather(root, second_client)
    assert second_client.prompts == []
    assert second["units_total"] == 1
    assert second["units_reused"] == 1
    assert second["units_asked"] == 0
    assert second["units_asked_touching_new"] == 0
    assert second["units_asked"] + second["units_reused"] == second["units_total"]

    # A genuinely new name, whose two members are BOTH brand-new sources
    # (never part of any recorded disagreement). "Alpha Claim" stays reused.
    beta = _write_units_fixture_name(root, "Beta Claim", "units-src-3", "units-src-4")
    _write_units_fixture_index(root, {"Alpha Claim": alpha, "Beta Claim": beta})

    third_client = _NameKeyedGatherClient({"Beta Claim": _response("Beta disagreement.")})
    third = _gather(root, third_client)
    assert len(third_client.prompts) == 1, "only the new name is asked about"
    assert third["units_total"] == 2
    assert third["units_reused"] == 1
    assert third["units_asked"] == 1
    assert third["units_asked_touching_new"] == 1
    assert third["units_asked_touching_new"] <= third["units_asked"]
    assert third["units_asked"] + third["units_reused"] == third["units_total"]


def test_unit_counters_a_note_from_an_existing_source_is_reused_not_touching_new(tmp_path):
    """Issue #678's own bar on top of #677's counters: a page gaining a note
    from a source it already had must count as reused, and
    `units_asked_touching_new` must stay at zero for it -- the second bucket
    the founder's validation comment (2026-08-05) asks be reported and be
    zero."""
    root = tmp_path
    alpha = _write_units_fixture_name(root, "Alpha Claim", "units-src-1", "units-src-2")
    _write_units_fixture_index(root, {"Alpha Claim": alpha})

    first_client = _NameKeyedGatherClient({"Alpha Claim": _response("Alpha disagreement.")})
    first = _gather(root, first_client)
    assert first["units_asked"] == 1

    # A second note from `units-src-1`, a source already on the page.
    chunk_a2 = "units-src-1_001_intro_002"
    answers_path = root / "data" / "answers" / "units-src-1.jsonl"
    _write_jsonl(
        answers_path,
        _read_jsonl(answers_path)
        + [
            _answer_record(
                chunk_a2,
                "units-src-1",
                claim="Alpha Claim: a second passage, same book.",
                position_of="position A2",
                arguing_against=["z"],
                names=[{"name": "Alpha Claim", "kind": "concept"}],
            )
        ],
    )
    inventory_path = root / "data" / "names" / "inventory.jsonl"
    rows = _read_jsonl(inventory_path)
    for row in rows:
        if row["surface"] == "Alpha Claim":
            row["chunk_ids"].append(chunk_a2)
    _write_jsonl(inventory_path, rows)

    second_client = _NameKeyedGatherClient({"Alpha Claim": _response("Nobody should see this.")})
    second = _gather(root, second_client)

    assert second_client.prompts == [], "an existing-source note must not trigger a call"
    assert second["units_total"] == 1
    assert second["units_reused"] == 1
    assert second["units_asked"] == 0
    assert second["units_asked_touching_new"] == 0


# -- CLI wiring smoke test -----------------------------------------------------


def test_names_gather_cli_subcommand_is_wired(isolated_vault_root):
    root = isolated_vault_root
    _build_small_fixture(root)
    _materialize(root)
    # The fixture's "war making" name has 2 member notes; the real default
    # member-count floor is 10 (`DEFAULT_MIN_GATHER_MEMBERS`), so this smoke
    # test -- which is about the CLI wiring, not the threshold -- overrides
    # it the same way an operator would.
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "pipeline.yaml").write_text(
        yaml.safe_dump({"gather": {"min_members": 2}}), encoding="utf-8"
    )

    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "stub"
    env["AXIAL_STUB_GATHER_RESPONSE"] = _response(
        "Scripted disagreement from the stub client.", ["Michael Mann"]
    )
    result = subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", "names", "gather"],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )

    combined = result.stdout + result.stderr
    assert "invalid choice" not in combined and "unrecognized arguments" not in combined, (
        "expected a real 'axial names gather' run, not an argparse fallback:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "names_gathered: 1" in result.stdout
    page = _page(root, "war making")
    assert "Scripted disagreement from the stub client." in page
    assert "[[Michael Mann]]" in page


@pytest.mark.parametrize("members", [2, 60])
def test_no_assembled_prompt_ever_exceeds_the_budget(tmp_path, members):
    """P0-13's own observable, stated as a property over both paths: the
    single-call path and the batched one."""
    if members == 2:
        _build_small_fixture(tmp_path)
    else:
        _build_large_fixture(tmp_path, members=members)
    _materialize(tmp_path)

    client = FakeClient(batch=[_response("Finding.", [])], merge=_response("Merged.", []))
    result = _gather(tmp_path, client)

    assert result["names_gathered"] >= 1
    for prompt in client.prompts:
        members_block_chars = sum(
            len(line) + 1 for line in prompt.splitlines() if line.startswith("- ")
        )
        assert members_block_chars <= GATHER_PACKET_CHAR_BUDGET
