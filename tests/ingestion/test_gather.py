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
      only the five packet fields (author, year, one-sentence claim, whose
      position it is, who it argues against) (D13: "Gather itself never
      reads full notes")
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
from pathlib import Path

import pytest

from axial.gather import (
    DISAGREEMENT_HEADING,
    GATHER_PACKET_CHAR_BUDGET,
    MEMBER_PACKET_CHARS,
    MemberPacket,
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
    repeating, so a test that only cares about "one call" scripts one."""

    _FIXTURE_AUTHORS = ("Charles Tilly", "Miguel Centeno")

    def __init__(self, batch: list[str], merge: str | None = None):
        self._batch = list(batch)
        self._merge = merge
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
        return self._merge

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
) -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "section": "Introduction",
        "pass": "note_interrogate",
        "model": "stub",
        "frame_version": "0.1",
        "answered_at": "2026-01-01T00:00:00Z",
        "answers": {
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
        },
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


def _gather(root: Path, client, **overrides):
    kwargs = {
        **_dirs(root),
        "disagreements_path": _disagreements_path(root),
        "client": client,
        "workers": 1,
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


def test_a_rendered_packet_is_capped_so_the_budget_is_a_guarantee():
    packet = MemberPacket(
        chunk_id="src1_000_intro_001",
        author="A" * 500,
        year=1990,
        claim="B" * 5000,
        position_of="C" * 500,
        arguing_against="D" * 500,
    )
    assert len(render_packet(packet)) <= MEMBER_PACKET_CHARS


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


def test_gather_gates_a_numeral_only_surface_before_any_model_call(tmp_path):
    """Fix (2026-07-29): a bare page number is locator residue, not a name --
    it must never draw a Gather call, even with two member notes across two
    books (exactly the shape that used to draw one: #452 scoped a locator by
    source so it never merges across books, but never stopped it from being
    asked about)."""
    _build_small_fixture(tmp_path)

    inventory_path = tmp_path / "data" / "names" / "inventory.jsonl"
    inventory = [
        json.loads(line) for line in inventory_path.read_text(encoding="utf-8").splitlines()
    ]
    inventory.append(
        {
            "surface": "13",
            "kind": None,
            "count": 2,
            "chunk_ids": ["tilly-1990_000_intro_001", "centeno-2002_000_intro_001"],
        }
    )
    _write_jsonl(inventory_path, inventory)

    alias_map_path = tmp_path / "data" / "names" / "alias_map.json"
    alias_map = json.loads(alias_map_path.read_text(encoding="utf-8"))
    alias_map["nodes"].append({"canonical": "13", "kind": None, "aliases": []})
    _write_json(alias_map_path, alias_map)

    _materialize(tmp_path)

    client = FakeClient(batch=[_response("Tilly and Centeno disagree about war making.", [])])
    result = _gather(tmp_path, client)

    # "13" has two member notes across two books -- enough to clear
    # `_MIN_MEMBERS` -- and is gated before ever reaching `build_packets`.
    assert result["names_skipped_numeral_only"] == 1
    assert len(client.prompts) == 1, "only 'war making' should have drawn a call"
    assert DISAGREEMENT_HEADING not in _page(tmp_path, "13")


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


# -- CLI wiring smoke test -----------------------------------------------------


def test_names_gather_cli_subcommand_is_wired(isolated_vault_root):
    root = isolated_vault_root
    _build_small_fixture(root)
    _materialize(root)

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
