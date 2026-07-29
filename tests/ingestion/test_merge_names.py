"""Outer acceptance test for issue #416 (Phase A v1 slice 05 -- Reconcile:
the model merges names into a reversible alias map, spec §7.16 artifact 3,
P0-12's last four bullets).

Locked behavioural contract, read off `specs/PRODUCT.md` §7.16/§7.9 and D10
(`docs/DECISIONS.md`, `plans/phase-a-v1/README.md`):

Given slice 04's name inventory and similarity view on disk
      (`data/names/inventory.jsonl`, `data/names/embeddings.lance`)
When  the operator runs `axial names merge`
Then  the model is asked, one cluster at a time, which surface forms name the
      same thing -- the clusters are hints it may ignore
And   the output is data: `data/names/alias_map.json` in exactly the shape
      `{version, generated_at, nodes: [{canonical, kind, aliases[]}]}`, plus
      `data/names/index.json`, the surviving canonical set slice 06 writes
      one page per entry for
And   no surface form is ever dropped: one the model never folded survives as
      its own canonical node with no aliases
And   the merges are reversible and re-runnable -- re-running reproduces the
      same map, and nothing else on disk depends on the map having been
      applied
And   "state formation through war" and "bellicist state building" merge,
      while two genuinely distinct claims that share surface similarity do
      not (the worked example D10 and the review both name)
And   the merge call carries `temperature: 1` and reasoning at `high`, and no
      other pass's sampling moves
And   the existing `axial reconcile gc` (issue #291's model-free orphan GC,
      same English word, different feature) is untouched

Seam decisions
-----------------------------------------------------------------------
1. **Real embeddings, scripted model answers.** The inventory and vectors are
   produced by the real `axial names build` (a local sentence-transformer,
   no API), and only the merge judgment itself is faked -- via
   `AXIAL_STUB_RECONCILE_RESPONSE` for the CLI path, and a fake client for
   the worked example. That keeps the artifact under test real and the
   judgment under the test's control.
2. **The worked example injects the clustering** (`cluster_fn`, the seam
   `axial.names.run_names` already exposes) rather than depending on what
   HDBSCAN does to four vectors. The behaviour under test there is the merge
   decision and the fold, not the hint.

Requires the `distill` dependency group (`uv sync --group distill`), like
`tests/ingestion/test_names.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("lancedb")
pytest.importorskip("sentence_transformers")
pytest.importorskip("hdbscan")
pytest.importorskip("sklearn")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECONCILE_RESPONSE_ENV_VAR = "AXIAL_STUB_RECONCILE_RESPONSE"

BELLICIST = "state formation through war"
BELLICIST_ALIAS = "bellicist state building"
DISTINCT_A = "the state is a protection racket"
DISTINCT_B = "the state is a bureaucratic cage"

# Six unrelated surfaces for the concurrency tests below: what they say does
# not matter there, only that they cluster into three independent calls.
_ALL_SIX = [f"concept number {index}" for index in range(6)]


def _run_axial(root: Path, *args: str, env_extra: dict[str, str] | None = None):
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "stub"
    env.update(env_extra or {})
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _answers(names: list[str], kind: str = "concept") -> dict:
    return {
        "about": ["x"],
        "claim": "x",
        "move": "x",
        "ranges_over": "not-in-passage",
        "stops_holding": "not-in-passage",
        "position_of": "not-in-passage",
        "arguing_against": [],
        "names": [{"name": name, "kind": kind} for name in names],
        "citations": [],
        "mechanism": "not-in-passage",
        "evidence": "not-in-passage",
        "comparison": "not-in-passage",
        "defines": [],
        "uses": [],
        "concedes": "not-in-passage",
        "assumes": "not-in-passage",
    }


def _build_fixture_answers(root: Path, name_groups: list[list[str]], kind: str = "concept") -> None:
    answers_dir = root / "data" / "answers"
    answers_dir.mkdir(parents=True, exist_ok=True)
    with (answers_dir / "src1.jsonl").open("w", encoding="utf-8") as handle:
        for index, names in enumerate(name_groups):
            handle.write(
                json.dumps(
                    {
                        "chunk_id": f"src1_{index:03d}_intro_001",
                        "source_id": "src1",
                        "section": "Introduction",
                        "pass": "note_interrogate",
                        "model": "stub",
                        "frame_version": "0.1",
                        "answered_at": "2026-01-01T00:00:00Z",
                        "answers": _answers(names, kind),
                    }
                )
                + "\n"
            )


def _read_alias_map(root: Path) -> dict:
    return json.loads((root / "data" / "names" / "alias_map.json").read_text(encoding="utf-8"))


def _nodes_by_canonical(alias_map: dict) -> dict[str, list[str]]:
    return {node["canonical"]: node["aliases"] for node in alias_map["nodes"]}


def test_merge_writes_a_reversible_alias_map_and_the_index(isolated_vault_root):
    root = isolated_vault_root
    _build_fixture_answers(root, [[BELLICIST, DISTINCT_A], [BELLICIST_ALIAS, DISTINCT_B]])

    build = _run_axial(root, "names", "build")
    assert build.returncode == 0, f"stdout: {build.stdout!r}\nstderr: {build.stderr!r}"

    scripted = json.dumps(
        {
            "nodes": [
                {"canonical": BELLICIST, "aliases": [BELLICIST_ALIAS]},
                {"canonical": DISTINCT_A, "aliases": []},
                {"canonical": DISTINCT_B, "aliases": []},
            ]
        }
    )
    merge = _run_axial(root, "names", "merge", env_extra={RECONCILE_RESPONSE_ENV_VAR: scripted})
    combined = merge.stdout + merge.stderr
    assert "invalid choice" not in combined and "unrecognized arguments" not in combined, (
        "expected a real `axial names merge` run, not an argparse fallback:\n"
        f"stdout: {merge.stdout!r}\nstderr: {merge.stderr!r}"
    )
    assert merge.returncode == 0, f"stdout: {merge.stdout!r}\nstderr: {merge.stderr!r}"

    alias_map = _read_alias_map(root)
    assert set(alias_map) == {"version", "generated_at", "nodes"}
    for node in alias_map["nodes"]:
        assert set(node) == {"canonical", "kind", "aliases"}

    # Nothing is dropped (§7.16): every surface the corpus said is either a
    # canonical name or an alias of one, exactly once.
    placed = [
        surface for node in alias_map["nodes"] for surface in [node["canonical"], *node["aliases"]]
    ]
    assert sorted(placed) == sorted([BELLICIST, BELLICIST_ALIAS, DISTINCT_A, DISTINCT_B])

    # The index is the surviving canonical set.
    index = json.loads((root / "data" / "names" / "index.json").read_text(encoding="utf-8"))
    assert index["names"] == [node["canonical"] for node in alias_map["nodes"]]

    # Re-runnable: the same input reproduces the same merges, and the second
    # run makes no fresh decision (the pass resumes off its decision log,
    # which is what makes a temperature-1 sampler reproducible).
    rerun = _run_axial(
        root,
        "names",
        "merge",
        env_extra={RECONCILE_RESPONSE_ENV_VAR: json.dumps({"nodes": []})},
    )
    assert rerun.returncode == 0, f"stdout: {rerun.stdout!r}\nstderr: {rerun.stderr!r}"
    assert "decided: 0" in rerun.stdout
    assert _nodes_by_canonical(_read_alias_map(root)) == _nodes_by_canonical(alias_map)


def test_merge_before_build_fails_loudly(isolated_vault_root):
    result = _run_axial(isolated_vault_root, "names", "merge")

    assert result.returncode == 1
    assert "error:" in result.stderr


def test_reconcile_gc_is_a_different_untouched_feature(isolated_vault_root):
    """Issue #291's model-free orphan GC shares only the English word with
    this slice; `axial names merge` must not have displaced it."""
    result = _run_axial(isolated_vault_root, "reconcile", "gc")

    combined = result.stdout + result.stderr
    assert "invalid choice" not in combined and "unrecognized arguments" not in combined


def test_worked_example_merges_the_same_idea_and_keeps_distinct_claims_apart(isolated_vault_root):
    """D10's own worked example: "'State formation through war' and
    'bellicist state building' must meet; two genuinely different ideas must
    not." The four surface forms are handed to the model as ONE cluster hint,
    and the model's answer -- not the cluster -- decides."""
    from axial.merge_names import run_merge_names
    from axial.names import run_names

    root = isolated_vault_root
    _build_fixture_answers(root, [[BELLICIST, DISTINCT_A], [BELLICIST_ALIAS, DISTINCT_B]])
    names_dir = root / "data" / "names"
    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
    )

    prompts: list[str] = []

    class FakeClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            prompts.append(prompt)
            return json.dumps(
                {
                    "nodes": [
                        {"canonical": BELLICIST, "aliases": [BELLICIST_ALIAS]},
                        {"canonical": DISTINCT_A, "aliases": []},
                        {"canonical": DISTINCT_B, "aliases": []},
                    ]
                }
            )

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=names_dir / "merge_decisions.jsonl",
        domain_dir=root / "no-such-domain",
        client=FakeClient(),
        cluster_fn=lambda vectors: [0] * len(vectors),
    )

    assert len(prompts) == 1, "one call per cluster (§7.16)"
    for surface in (BELLICIST, BELLICIST_ALIAS, DISTINCT_A, DISTINCT_B):
        assert surface in prompts[0]

    nodes = _nodes_by_canonical(_read_alias_map(root))
    assert nodes[BELLICIST] == [BELLICIST_ALIAS]
    assert nodes[DISTINCT_A] == []
    assert nodes[DISTINCT_B] == []


# ---------------------------------------------------------------------------
# Issue #450: a third outcome -- the model says it cannot tell
# ---------------------------------------------------------------------------


def test_an_escalated_surface_stands_alone_and_is_recorded_and_counted(isolated_vault_root):
    """The model folds one pair, escalates one surface (says it cannot tell),
    and places the last one as its own node. `alias_map.json` treats the
    escalated surface exactly like an unplaced one -- it stands alone, and
    the map's own §7.16 shape does not change -- but the decision log and
    the manifest both make the escalation legible."""
    from axial.merge_names import run_merge_names
    from axial.names import run_names

    root = isolated_vault_root
    _build_fixture_answers(root, [[BELLICIST, DISTINCT_A], [BELLICIST_ALIAS, DISTINCT_B]])
    names_dir = root / "data" / "names"
    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
    )

    class FakeClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            return json.dumps(
                {
                    "nodes": [
                        {"canonical": BELLICIST, "aliases": [BELLICIST_ALIAS]},
                        {"canonical": DISTINCT_B, "aliases": []},
                    ],
                    "undecided": [DISTINCT_A],
                }
            )

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    manifest_path = names_dir / "merge_manifest.json"
    summary = run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=names_dir / "merge_decisions.jsonl",
        manifest_path=manifest_path,
        domain_dir=root / "no-such-domain",
        client=FakeClient(),
        cluster_fn=lambda vectors: [0] * len(vectors),
    )

    # §7.16's shape is untouched: an escalated surface stands alone, exactly
    # like an unplaced one, and the map carries no new field.
    alias_map = _read_alias_map(root)
    assert set(alias_map) == {"version", "generated_at", "nodes"}
    for node in alias_map["nodes"]:
        assert set(node) == {"canonical", "kind", "aliases"}
    nodes = _nodes_by_canonical(alias_map)
    assert nodes[BELLICIST] == [BELLICIST_ALIAS]
    assert nodes[DISTINCT_A] == []
    assert nodes[DISTINCT_B] == []

    # The escalation is legible in the decision log, addressable by name.
    (decision_line,) = (
        (names_dir / "merge_decisions.jsonl").read_text(encoding="utf-8").splitlines()
    )
    record = json.loads(decision_line)
    assert record["escalated"] == [DISTINCT_A]

    # And counted, off the manifest, without re-parsing the decision log.
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["escalated_surfaces"] == 1
    assert summary["escalated_surfaces"] == 1


# ---------------------------------------------------------------------------
# Issue #469: a client-side parse failure is not a real "undecided"
# ---------------------------------------------------------------------------


def test_a_client_side_parse_failure_never_lands_in_the_escalation_pile(isolated_vault_root):
    """A batch whose response never once places any of its own surface forms
    -- across `complete_json`'s WHOLE re-ask budget -- is response noise
    (issue #469's dominant merge-parse failure shape:
    "merge response placed none of the batch's surface forms"), not a model
    judgment. It must stay indistinguishable from noise everywhere #460
    would look: absent from `merge_decisions.jsonl` (so a later run retries
    it), contributing nothing to `escalated_surfaces` or `axial names
    escalations`'s listing -- unlike a genuine escalation from a SIBLING
    batch in the same run, which must still show up exactly as before. What
    changes with this issue is durability: the failed batch's own surface
    forms and reason are no longer lost to the run's stderr once it ends."""
    from axial.merge_names import list_escalations, run_merge_names
    from axial.names import run_names

    root = isolated_vault_root
    ok_pair = ["aaa name one", "aaa name two"]
    noise_pair = ["zzz name three", "zzz name four"]
    _build_fixture_answers(root, [ok_pair, noise_pair])
    names_dir = root / "data" / "names"
    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
    )

    class NoiseClient:
        """One cluster gets a genuine, whole-batch escalation; the other
        NEVER places either of its own members, no matter how many times it
        is asked -- exactly the "well-formed JSON, wrong batch" noise shape
        a client-side response mixup or a garbled model answer would both
        produce."""

        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            if ok_pair[0] in prompt:
                return json.dumps({"nodes": [], "undecided": ok_pair})
            return json.dumps({"nodes": [{"canonical": "unrelated thing", "aliases": []}]})

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    decisions_path = names_dir / "merge_decisions.jsonl"
    failures_path = names_dir / "merge_failures.jsonl"
    manifest_path = names_dir / "merge_manifest.json"
    inventory_path = names_dir / "inventory.jsonl"
    summary = run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=decisions_path,
        manifest_path=manifest_path,
        failures_path=failures_path,
        domain_dir=root / "no-such-domain",
        client=NoiseClient(),
        cluster_fn=lambda vectors: [0, 0, 1, 1],
    )

    assert summary["decided"] == 1
    assert summary["failed"] == 1
    assert summary["failures_path"] == str(failures_path)

    # The failed batch never became a decision -- it stays retryable.
    decision_lines = decisions_path.read_text(encoding="utf-8").splitlines()
    assert len(decision_lines) == 1
    decided_members = json.loads(decision_lines[0])["members"]
    assert sorted(decided_members) == sorted(ok_pair)

    # The escalation pile carries only the genuine escalation -- the noise
    # batch's surface forms never appear in it.
    escalated_surfaces = {
        entry.surface_form
        for entry in list_escalations(decisions_path=decisions_path, inventory_path=inventory_path)
    }
    assert escalated_surfaces == set(ok_pair)
    assert summary["escalated_surfaces"] == len(ok_pair)
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["escalated_surfaces"] == len(
        ok_pair
    )

    # But it is not lost either: durably recorded, shape-distinct from a
    # real decision (no "nodes"/"escalated" keys -- nothing here could ever
    # be mistaken for a judgment by a reader that only checks for those).
    failure_lines = failures_path.read_text(encoding="utf-8").splitlines()
    assert len(failure_lines) == 1
    failure_record = json.loads(failure_lines[0])
    assert sorted(failure_record["members"]) == sorted(noise_pair)
    assert "placed none of the batch's surface forms" in failure_record["reason"]
    assert "nodes" not in failure_record
    assert "escalated" not in failure_record


def test_the_merge_pass_samples_at_temperature_1_with_high_reasoning():
    """Founder directive (issue #416, §7.9): both resolved from
    `config/pipeline.yaml`'s own per-pass blocks, and no other pass's request
    body moves."""
    import httpx

    from axial.llm import (
        NOTE_INTERROGATE_PASS_NAME,
        RECONCILE_PASS_NAME,
        OpenRouterClient,
        _load_pipeline_llm_config,
        _resolve_reasoning_by_pass,
        _resolve_temperature_by_pass,
    )

    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    llm_config = _load_pipeline_llm_config(REPO_ROOT / "config" / "pipeline.yaml")
    client = OpenRouterClient(
        api_key="test-key",
        model="test-model",
        transport=httpx.MockTransport(handler),
        reasoning_by_pass=_resolve_reasoning_by_pass(llm_config),
        temperature_by_pass=_resolve_temperature_by_pass(llm_config),
    )

    client.complete("merge these", pass_name=RECONCILE_PASS_NAME)
    client.complete("interrogate this", pass_name=NOTE_INTERROGATE_PASS_NAME)

    assert bodies[0]["temperature"] == 1
    assert bodies[0]["reasoning"] == {"enabled": True, "effort": "high"}
    assert "temperature" not in bodies[1]


def _cluster_pairs(vectors) -> list[int]:
    """Two names per cluster, in inventory order -- so a fixture with six
    names yields three clusters and therefore three independent calls."""
    return [index // 2 for index in range(len(vectors))]


def _six_name_fixture(root: Path) -> Path:
    _build_fixture_answers(root, [_ALL_SIX[:3], _ALL_SIX[3:]])
    names_dir = root / "data" / "names"
    from axial.names import run_names

    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
    )
    return names_dir


def _merge(names_dir: Path, root: Path, client, **kwargs):
    from axial.merge_names import run_merge_names

    return run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=names_dir / "merge_decisions.jsonl",
        manifest_path=names_dir / "merge_manifest.json",
        domain_dir=root / "no-such-domain",
        client=client,
        cluster_fn=_cluster_pairs,
        **kwargs,
    )


def test_clusters_are_decided_concurrently_and_the_decision_log_stays_intact(isolated_vault_root):
    """Issue #416: a serial pass over the real corpus's ~19k clusters is a
    ~12-hour job, so the calls run concurrently. The barrier makes that a
    fact rather than a claim -- three clusters must be in flight at once or
    it times out. The decision log is appended from ONE thread only, so
    resumability survives concurrency; a per-line JSON parse is what would
    catch two workers racing to append."""
    import threading

    root = isolated_vault_root
    names_dir = _six_name_fixture(root)

    barrier = threading.Barrier(3, timeout=30)

    class ConcurrentClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            # Fails loudly (BrokenBarrierError) unless three calls overlap.
            barrier.wait()
            members = [name for name in _ALL_SIX if name in prompt]
            return json.dumps({"nodes": [{"canonical": m, "aliases": []} for m in members]})

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    summary = _merge(names_dir, root, ConcurrentClient(), workers=3)

    assert summary["batches"] == 3
    assert summary["decided"] == 3
    assert summary["failed"] == 0
    assert summary["workers"] == 3
    assert summary["complete"] is True

    # One well-formed record per batch: no torn or interleaved append.
    lines = (names_dir / "merge_decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert sorted(json.loads(line)["cluster_label"] for line in lines) == [0, 1, 2]

    # Nothing dropped, whatever order the workers finished in.
    placed = [
        surface
        for node in _read_alias_map(root)["nodes"]
        for surface in [node["canonical"], *node["aliases"]]
    ]
    assert sorted(placed) == sorted(_ALL_SIX)


def test_limit_caps_the_calls_actually_submitted(isolated_vault_root):
    """`--limit` is "stop after that many model calls THIS run" -- with a
    worker pool that must mean only that many batches are handed to it, never
    19k futures submitted and then abandoned."""
    import threading

    root = isolated_vault_root
    names_dir = _six_name_fixture(root)

    calls: list[str] = []
    lock = threading.Lock()

    class CountingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            with lock:
                calls.append(prompt)
            members = [name for name in _ALL_SIX if name in prompt]
            return json.dumps({"nodes": [{"canonical": m, "aliases": []} for m in members]})

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    summary = _merge(names_dir, root, CountingClient(), workers=8, limit=1)

    assert len(calls) == 1, "workers must not outrun --limit"
    assert summary["decided"] == 1
    assert summary["complete"] is False

    # The partial run says so on disk, where the map's own shape cannot.
    manifest = json.loads((names_dir / "merge_manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["batches_total"] == 3


# ---------------------------------------------------------------------------
# Issue #446: candidate generation recovers the pairs clustering never sees
# ---------------------------------------------------------------------------

C_TILLY = "C. Tilly"
CHARLES_TILLY = "Charles Tilly"
ABERCROMBIE = "Abercrombie"
NIKOLAS_ABERCROMBIE = "Nikolas Abercrombie"
R_COHEN = "R. Cohen"
ROBIN_COHEN = "Robin Cohen"
ROGER_COHEN = "Roger Cohen"


def _singleton_clusters(vectors) -> list[int]:
    """Every surface form its OWN cluster -- the worst case for slice 04's
    recall, and exactly the shape issue #446 describes: a name and its
    variant that never land in the same HDBSCAN cluster, so no real cluster
    batch would ever contain both."""
    return list(range(len(vectors)))


def test_candidate_generation_recovers_pairs_hdbscan_never_co_clusters(isolated_vault_root):
    """Issue #446. With every surface form in its own singleton cluster
    (simulating clustering's recall gap), `build_batches` alone would submit
    ZERO calls -- yet `C. Tilly`/`Charles Tilly` and `Abercrombie`/`Nikolas
    Abercrombie` still resolve to one canonical each, because candidate
    generation proposes them as additional clusters for the SAME merge call.
    `R. Cohen` (ambiguous against two candidates) is never even sent to the
    model, so it and a genuinely distinct name stay apart."""
    root = isolated_vault_root
    _build_fixture_answers(
        root,
        [
            [C_TILLY],
            [CHARLES_TILLY],
            [ABERCROMBIE],
            [NIKOLAS_ABERCROMBIE],
            [R_COHEN],
            [ROBIN_COHEN],
            [ROGER_COHEN],
            [DISTINCT_A],
        ],
        kind="person",
    )
    names_dir = root / "data" / "names"
    from axial.merge_names import run_merge_names
    from axial.names import run_names

    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
        cluster_fn=_singleton_clusters,
    )

    prompts: list[str] = []

    class MergeEverythingClient:
        """Merges whatever a batch hands it. Safe here only because the
        fixture is built so the ambiguous group (R. Cohen / Robin Cohen /
        Roger Cohen) is never proposed as one batch in the first place --
        this asserts that directly, rather than trusting the client to
        refuse."""

        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            prompts.append(prompt)
            assert not (R_COHEN in prompt and ROBIN_COHEN in prompt), (
                "R. Cohen is ambiguous against Robin Cohen and Roger Cohen -- "
                "must never be proposed as a merge candidate"
            )
            assert not (R_COHEN in prompt and ROGER_COHEN in prompt)
            members = [
                name
                for name in (
                    C_TILLY,
                    CHARLES_TILLY,
                    ABERCROMBIE,
                    NIKOLAS_ABERCROMBIE,
                    R_COHEN,
                    ROBIN_COHEN,
                    ROGER_COHEN,
                    DISTINCT_A,
                )
                if name in prompt
            ]
            canonical, *aliases = sorted(members)
            return json.dumps({"nodes": [{"canonical": canonical, "aliases": aliases}]})

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    summary = run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=names_dir / "merge_decisions.jsonl",
        manifest_path=names_dir / "merge_manifest.json",
        domain_dir=root / "no-such-domain",
        client=MergeEverythingClient(),
        cluster_fn=_singleton_clusters,
    )

    # No real HDBSCAN cluster produced a batch (every cluster is a
    # singleton); every call made was a proposed candidate.
    assert summary["clusters"] == 8
    assert summary["candidate_batches"] == 2
    assert summary["batches"] == 2
    assert len(prompts) == 2

    nodes = _nodes_by_canonical(_read_alias_map(root))
    # The two pairs slice 04's clustering never co-located resolve to one
    # canonical each.
    tilly_group = sorted([C_TILLY, *nodes.get(C_TILLY, [])] + nodes.get(CHARLES_TILLY, []))
    abercrombie_group = sorted(
        [ABERCROMBIE, *nodes.get(ABERCROMBIE, [])] + nodes.get(NIKOLAS_ABERCROMBIE, [])
    )
    assert (C_TILLY in nodes and nodes[C_TILLY] == [CHARLES_TILLY]) or (
        CHARLES_TILLY in nodes and nodes[CHARLES_TILLY] == [C_TILLY]
    )
    assert (ABERCROMBIE in nodes and nodes[ABERCROMBIE] == [NIKOLAS_ABERCROMBIE]) or (
        NIKOLAS_ABERCROMBIE in nodes and nodes[NIKOLAS_ABERCROMBIE] == [ABERCROMBIE]
    )
    del tilly_group, abercrombie_group  # readable-by-construction above

    # The ambiguous pair, and the never-related distinct name, stay apart:
    # each survives as its own canonical with no aliases.
    for surface in (R_COHEN, ROBIN_COHEN, ROGER_COHEN, DISTINCT_A):
        assert nodes[surface] == []


def test_existing_decisions_are_reused_when_candidates_are_added(isolated_vault_root):
    """Issue #446: re-running after candidate generation is wired in must not
    re-decide a cluster the model already settled -- only genuinely new
    clusters (real or candidate) get a fresh call."""
    root = isolated_vault_root
    _build_fixture_answers(
        root,
        [[C_TILLY], [CHARLES_TILLY], [DISTINCT_A, DISTINCT_B]],
        kind="person",
    )
    names_dir = root / "data" / "names"
    from axial.merge_names import run_merge_names
    from axial.names import run_names

    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
        cluster_fn=lambda vectors: [0, 1, 2, 2],
    )

    class MergeClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            if DISTINCT_A in prompt and DISTINCT_B in prompt:
                return json.dumps({"nodes": [{"canonical": DISTINCT_A, "aliases": [DISTINCT_B]}]})
            return json.dumps(
                {"nodes": [{"canonical": C_TILLY, "aliases": [CHARLES_TILLY]}]}
                if C_TILLY in prompt
                else {"nodes": []}
            )

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    first = run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=names_dir / "merge_decisions.jsonl",
        manifest_path=names_dir / "merge_manifest.json",
        domain_dir=root / "no-such-domain",
        client=MergeClient(),
        cluster_fn=lambda vectors: [0, 1, 2, 2],
    )
    assert first["decided"] == 2  # the real cluster + the one candidate pair
    decisions_before = (names_dir / "merge_decisions.jsonl").read_text(encoding="utf-8")

    class ExplodingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            raise AssertionError("no cluster should be re-decided on an unchanged re-run")

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    second = run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=names_dir / "merge_decisions.jsonl",
        manifest_path=names_dir / "merge_manifest.json",
        domain_dir=root / "no-such-domain",
        client=ExplodingClient(),
        cluster_fn=lambda vectors: [0, 1, 2, 2],
    )
    assert second["decided"] == 0
    assert second["reused"] == first["batches"]
    assert (names_dir / "merge_decisions.jsonl").read_text(encoding="utf-8") == decisions_before


# ---------------------------------------------------------------------------
# Issue #463: case, whitespace and punctuation fold upstream of every
# candidate source and the HDBSCAN blocker -- so an identical-under-fold
# group is one entity by construction and never reaches a merge call at all.
# ---------------------------------------------------------------------------

COLD_WAR = "Cold War"
COLD_WAR_LOWER_W = "Cold war"
COLD_WAR_LOWER = "cold war"
ABBAS_APOSTROPHE = "'Abbas"
ABBAS = "Abbas"
PROTESTANT_QUOTED = '"Protestant constitution"'
PROTESTANT_BARE = "Protestant constitution"


def test_fold_collapses_case_whitespace_and_punctuation_with_no_model_call(isolated_vault_root):
    """Issue #463's own worked examples: a pure case group, a pure
    punctuation (apostrophe/quotes) group, and a distinct, untouched
    surface -- all with every surface form in its own singleton HDBSCAN
    cluster, so the ONLY way any of these could reach the model is through
    a candidate family. Before this fix, family 3 (issue #446) proposed
    exactly the case group as a batch; this asserts no batch is ever built
    for a fold-only group at all -- the model is never even asked."""
    root = isolated_vault_root
    _build_fixture_answers(
        root,
        [
            [COLD_WAR],
            [COLD_WAR_LOWER_W],
            [COLD_WAR_LOWER],
            [ABBAS_APOSTROPHE],
            [ABBAS],
            [DISTINCT_A],
        ],
        kind="concept",
    )
    names_dir = root / "data" / "names"
    from axial.merge_names import run_merge_names
    from axial.names import run_names

    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
        cluster_fn=_singleton_clusters,
    )

    class ExplodingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            raise AssertionError(
                "a case/whitespace/punctuation-only group must never reach a merge call"
            )

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    summary = run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=names_dir / "merge_decisions.jsonl",
        manifest_path=names_dir / "merge_manifest.json",
        domain_dir=root / "no-such-domain",
        client=ExplodingClient(),
        cluster_fn=_singleton_clusters,
    )

    # No model call was made at all -- not one batch was ever submitted.
    assert summary["decided"] == 0
    assert summary["batches"] == 0
    assert summary["candidate_batches"] == 0
    assert summary["fold_groups"] == 2

    canonical_of = {
        surface: node["canonical"]
        for node in _read_alias_map(root)["nodes"]
        for surface in [node["canonical"], *node["aliases"]]
    }
    assert canonical_of[COLD_WAR] == canonical_of[COLD_WAR_LOWER_W] == canonical_of[COLD_WAR_LOWER]
    assert canonical_of[ABBAS_APOSTROPHE] == canonical_of[ABBAS]
    # A genuinely distinct surface is never touched by the fold.
    assert canonical_of[DISTINCT_A] == DISTINCT_A


def test_fold_collapses_quoted_punctuation_with_no_model_call(isolated_vault_root):
    """The quote-mark row of the issue's own table, at the phase level.

    A whitespace-ONLY pair is not exercisable at this level: `axial.names.
    _clean` already collapses internal whitespace before a name ever
    reaches the inventory, so two answer records naming `Nation  State` and
    `Nation State` become ONE inventory entry before `axial.name_candidates`
    ever sees either -- whitespace was already fully handled upstream of
    this issue. `fold_groups`'s own whitespace-only unit coverage
    (`src/axial/test_name_candidates.py`) pins the fold function directly."""
    root = isolated_vault_root
    _build_fixture_answers(
        root,
        [
            [PROTESTANT_QUOTED],
            [PROTESTANT_BARE],
        ],
        kind="concept",
    )
    names_dir = root / "data" / "names"
    from axial.merge_names import run_merge_names
    from axial.names import run_names

    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
        cluster_fn=_singleton_clusters,
    )

    class ExplodingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            raise AssertionError("a fold-only group must never reach a merge call")

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    summary = run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=names_dir / "merge_decisions.jsonl",
        manifest_path=names_dir / "merge_manifest.json",
        domain_dir=root / "no-such-domain",
        client=ExplodingClient(),
        cluster_fn=_singleton_clusters,
    )

    assert summary["decided"] == 0
    assert summary["batches"] == 0
    assert summary["fold_groups"] == 1

    canonical_of = {
        surface: node["canonical"]
        for node in _read_alias_map(root)["nodes"]
        for surface in [node["canonical"], *node["aliases"]]
    }
    assert canonical_of[PROTESTANT_QUOTED] == canonical_of[PROTESTANT_BARE]


# ---------------------------------------------------------------------------
# Fix (2026-07-29): `is_numeral_only_surface` gates a bare page number or a
# plain century out of every merge call -- locator residue, not a name.
# ---------------------------------------------------------------------------

BARE_PAGE_NUMBER = "13"
CENTURY = "10th century"
WAR_FOOTING = "war footing"
WARTIME_FOOTING = "wartime footing"


def test_a_numeral_only_surface_never_reaches_a_merge_call(isolated_vault_root):
    """A cluster whose only two members are locator residue -- a bare page
    number and a plain century -- must never be submitted: after both are
    gated, nothing remains to decide."""
    root = isolated_vault_root
    _build_fixture_answers(root, [[BARE_PAGE_NUMBER], [CENTURY]], kind="concept")
    names_dir = root / "data" / "names"
    from axial.merge_names import run_merge_names
    from axial.names import run_names

    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
        cluster_fn=lambda vectors: [0] * len(vectors),
    )

    class ExplodingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            raise AssertionError("a numeral-only surface must never reach a merge call")

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    summary = run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=names_dir / "merge_decisions.jsonl",
        manifest_path=names_dir / "merge_manifest.json",
        domain_dir=root / "no-such-domain",
        client=ExplodingClient(),
        cluster_fn=lambda vectors: [0] * len(vectors),
    )

    assert summary["decided"] == 0
    assert summary["batches"] == 0
    assert summary["numeral_gated_surfaces"] == 2

    # Neither is dropped from the map (§7.16 is lossless) -- both survive as
    # their own unmerged canonical, just never asked about.
    canonical_of = {
        surface: node["canonical"]
        for node in _read_alias_map(root)["nodes"]
        for surface in [node["canonical"], *node["aliases"]]
    }
    assert canonical_of[BARE_PAGE_NUMBER] == BARE_PAGE_NUMBER
    assert canonical_of[CENTURY] == CENTURY


def test_a_mixed_cluster_still_asks_about_its_real_members(isolated_vault_root):
    """A cluster HDBSCAN put a bare page number alongside two genuinely
    similar real names must still ask about the real pair -- gating the
    numeral must not silently cancel a real name's chance to merge, and the
    numeral itself must never appear in what the model is shown."""
    root = isolated_vault_root
    _build_fixture_answers(
        root, [[BARE_PAGE_NUMBER], [WAR_FOOTING], [WARTIME_FOOTING]], kind="concept"
    )
    names_dir = root / "data" / "names"
    from axial.merge_names import run_merge_names
    from axial.names import run_names

    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
        cluster_fn=lambda vectors: [0] * len(vectors),
    )

    class RecordingClient:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            self.prompts.append(prompt)
            return json.dumps({"nodes": [{"canonical": WAR_FOOTING, "aliases": [WARTIME_FOOTING]}]})

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    client = RecordingClient()
    summary = run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=names_dir / "merge_decisions.jsonl",
        manifest_path=names_dir / "merge_manifest.json",
        domain_dir=root / "no-such-domain",
        client=client,
        cluster_fn=lambda vectors: [0] * len(vectors),
    )

    assert summary["decided"] == 1
    assert summary["numeral_gated_surfaces"] == 1
    assert len(client.prompts) == 1
    assert BARE_PAGE_NUMBER not in client.prompts[0]

    canonical_of = {
        surface: node["canonical"]
        for node in _read_alias_map(root)["nodes"]
        for surface in [node["canonical"], *node["aliases"]]
    }
    assert canonical_of[WAR_FOOTING] == canonical_of[WARTIME_FOOTING] == WAR_FOOTING
    assert canonical_of[BARE_PAGE_NUMBER] == BARE_PAGE_NUMBER


# ---------------------------------------------------------------------------
# Issue #449's rollout hazard: `MergeBatch.key` folds in evidence, so a
# corpus already decided under a bare-name pass must not be silently
# re-asked in full just because evidence attachment turned on.
# ---------------------------------------------------------------------------


def test_an_evidence_tier_change_refuses_to_reask_without_confirmation(isolated_vault_root):
    """A cluster already decided (no `evidence_tier` on its record -- every
    real pre-#449 decision) must not be silently re-asked once evidence is
    turned on: the run refuses BEFORE making any call, naming the count."""
    from axial.merge_names import MergeReaskConfirmationRequiredError, run_merge_names
    from axial.names import run_names

    root = isolated_vault_root
    _build_fixture_answers(root, [[BELLICIST, DISTINCT_A], [BELLICIST_ALIAS, DISTINCT_B]])
    names_dir = root / "data" / "names"
    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
    )

    decisions_path = names_dir / "merge_decisions.jsonl"
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    bare_members = sorted([BELLICIST, BELLICIST_ALIAS, DISTINCT_A, DISTINCT_B])
    decisions_path.write_text(
        json.dumps(
            {
                "batch_key": "pre-449-bare-decision",
                "cluster_label": 0,
                "members": bare_members,
                "nodes": [{"canonical": BELLICIST, "aliases": [BELLICIST_ALIAS]}],
                "model": "stub",
                "decided_at": "2026-01-01T00:00:00Z",
                # No "evidence_tier": exactly every real decision recorded
                # before this issue.
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class ExplodingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            raise AssertionError("must not call the model before the reask is confirmed")

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    with pytest.raises(MergeReaskConfirmationRequiredError) as excinfo:
        run_merge_names(
            embeddings_dir=names_dir / "embeddings.lance",
            alias_map_path=names_dir / "alias_map.json",
            index_path=names_dir / "index.json",
            decisions_path=decisions_path,
            manifest_path=names_dir / "merge_manifest.json",
            domain_dir=root / "no-such-domain",
            client=ExplodingClient(),
            cluster_fn=lambda vectors: [0] * len(vectors),
        )
    assert "1 cluster batch" in str(excinfo.value)

    # The decision log is untouched: refusing to reask must not purge
    # anything either.
    assert decisions_path.read_text(encoding="utf-8").count("pre-449-bare-decision") == 1


def test_confirming_the_reask_purges_the_stale_decision_and_redecides_it(isolated_vault_root):
    """`confirm_reask=True` purges exactly the superseded record and lets
    the model decide the cluster again, this time stamped with the tier
    that made the re-ask necessary."""
    from axial.merge_names import run_merge_names
    from axial.names import run_names

    root = isolated_vault_root
    _build_fixture_answers(root, [[BELLICIST, DISTINCT_A], [BELLICIST_ALIAS, DISTINCT_B]])
    names_dir = root / "data" / "names"
    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
    )

    decisions_path = names_dir / "merge_decisions.jsonl"
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    bare_members = sorted([BELLICIST, BELLICIST_ALIAS, DISTINCT_A, DISTINCT_B])
    decisions_path.write_text(
        json.dumps(
            {
                "batch_key": "pre-449-bare-decision",
                "cluster_label": 0,
                "members": bare_members,
                "nodes": [{"canonical": BELLICIST, "aliases": [BELLICIST_ALIAS]}],
                "model": "stub",
                "decided_at": "2026-01-01T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    prompts: list[str] = []

    class FakeClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            prompts.append(prompt)
            return json.dumps(
                {
                    "nodes": [
                        {"canonical": BELLICIST, "aliases": [BELLICIST_ALIAS]},
                        {"canonical": DISTINCT_A, "aliases": []},
                        {"canonical": DISTINCT_B, "aliases": []},
                    ]
                }
            )

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    summary = run_merge_names(
        embeddings_dir=names_dir / "embeddings.lance",
        alias_map_path=names_dir / "alias_map.json",
        index_path=names_dir / "index.json",
        decisions_path=decisions_path,
        manifest_path=names_dir / "merge_manifest.json",
        domain_dir=root / "no-such-domain",
        client=FakeClient(),
        cluster_fn=lambda vectors: [0] * len(vectors),
        confirm_reask=True,
    )

    assert len(prompts) == 1, "the purged cluster is decided again, exactly once"
    assert summary["stale_evidence_tier_reasked"] == 1
    assert summary["decided"] == 1

    manifest = json.loads((names_dir / "merge_manifest.json").read_text(encoding="utf-8"))
    assert manifest["stale_evidence_tier_reasked"] == 1

    remaining = [
        json.loads(line) for line in decisions_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(remaining) == 1, "the stale record is purged, not left alongside the new one"
    assert remaining[0]["batch_key"] != "pre-449-bare-decision"
    assert remaining[0]["evidence_tier"] == 1


def test_a_limited_reask_purges_only_the_batches_it_actually_attempts(isolated_vault_root):
    """Coordinator-caught defect: purging the WHOLE stale population
    regardless of `--limit` would delete every decision behind clusters this
    run never touches -- the log is the only copy, and `--evidence-tier 2
    --confirm-reask --limit 200` would have wiped all ~21,050 real decisions
    while re-asking only 200. A `--limit`-bounded run must purge (and
    report) only the stale decisions it is actually about to re-ask, leaving
    every other stale record -- including the acceptance measurement's own
    bare-name baseline -- untouched on disk."""
    root = isolated_vault_root
    names_dir = _six_name_fixture(root)

    decisions_path = names_dir / "merge_decisions.jsonl"
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    # Three independent bare (pre-#449) decisions, one per pair `_cluster_pairs`
    # produces from the six-name fixture -- all stale once evidence is
    # attached.
    pairs = [_ALL_SIX[0:2], _ALL_SIX[2:4], _ALL_SIX[4:6]]
    with decisions_path.open("w", encoding="utf-8") as handle:
        for index, members in enumerate(pairs):
            handle.write(
                json.dumps(
                    {
                        "batch_key": f"pre-449-bare-decision-{index}",
                        "cluster_label": index,
                        "members": sorted(members),
                        "nodes": [{"canonical": members[0], "aliases": [members[1]]}],
                        "model": "stub",
                        "decided_at": "2026-01-01T00:00:00Z",
                    }
                )
                + "\n"
            )

    calls: list[str] = []

    class CountingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            calls.append(prompt)
            members = [name for name in _ALL_SIX if name in prompt]
            canonical, *aliases = sorted(members)
            return json.dumps({"nodes": [{"canonical": canonical, "aliases": aliases}]})

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    summary = _merge(
        names_dir,
        root,
        CountingClient(),
        confirm_reask=True,
        limit=1,
    )

    # Only the ONE batch this run actually submitted was re-asked and
    # reported -- not the whole stale population of 3.
    assert len(calls) == 1
    assert summary["decided"] == 1
    assert summary["stale_evidence_tier_reasked"] == 1

    remaining_by_key = {
        record["batch_key"]: record
        for record in (
            json.loads(line) for line in decisions_path.read_text(encoding="utf-8").splitlines()
        )
    }
    # Exactly one old bare record was purged (superseded by a fresh,
    # evidence-stamped one); the other TWO, never attempted this run, are
    # untouched -- still on disk, still bare, still there for a later run
    # (or the acceptance measurement's baseline) to read.
    assert len(remaining_by_key) == 3
    untouched = [key for key in remaining_by_key if key.startswith("pre-449-bare-decision")]
    assert len(untouched) == 2
    for key in untouched:
        assert "evidence_tier" not in remaining_by_key[key]
    fresh = [key for key in remaining_by_key if not key.startswith("pre-449-bare-decision")]
    assert len(fresh) == 1
    assert remaining_by_key[fresh[0]]["evidence_tier"] == 1


# ---------------------------------------------------------------------------
# Issue #458: reuse `axial names build`'s own persisted clustering rather
# than re-fitting HDBSCAN over the whole corpus at the start of every merge,
# and print progress while a fit does run instead of nothing at all.
# ---------------------------------------------------------------------------


def _empty_client():
    class _NoOpClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            return json.dumps({"nodes": []})

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    return _NoOpClient()


def test_matching_settings_reuse_the_persisted_cluster_labels(isolated_vault_root, monkeypatch):
    """A merge invocation whose requested tightness matches what `axial
    names build` already fit must not re-run HDBSCAN at all -- it reads the
    `cluster_label` column `run_names` already persisted."""
    import axial.merge_names as merge_names_module
    from axial.names import DEFAULT_MIN_CLUSTER_SIZE, DEFAULT_MIN_SAMPLES, DEFAULT_PCA_COMPONENTS
    from axial.names import run_names

    root = isolated_vault_root
    _build_fixture_answers(root, [[BELLICIST, DISTINCT_A], [BELLICIST_ALIAS, DISTINCT_B]])
    names_dir = root / "data" / "names"
    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
    )

    def _explode(*_args, **_kwargs):
        raise AssertionError("a matching-settings merge must not re-fit HDBSCAN")

    monkeypatch.setattr(merge_names_module, "_cluster_reduced", _explode)

    import io
    import contextlib

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        summary = merge_names_module.run_merge_names(
            embeddings_dir=names_dir / "embeddings.lance",
            alias_map_path=names_dir / "alias_map.json",
            index_path=names_dir / "index.json",
            decisions_path=names_dir / "merge_decisions.jsonl",
            manifest_path=names_dir / "merge_manifest.json",
            similarity_manifest_path=names_dir / "similarity_manifest.json",
            domain_dir=root / "no-such-domain",
            client=_empty_client(),
            min_cluster_size=DEFAULT_MIN_CLUSTER_SIZE,
            min_samples=DEFAULT_MIN_SAMPLES,
            pca_components=DEFAULT_PCA_COMPONENTS,
        )

    manifest = json.loads((names_dir / "similarity_manifest.json").read_text(encoding="utf-8"))
    assert summary["clusters"] == manifest["cluster_count"]
    assert "reusing persisted cluster labels" in stderr.getvalue()


def test_mismatched_settings_still_trigger_a_fresh_fit(isolated_vault_root, monkeypatch):
    """A moved tightness dial must not silently reuse a labeling fit at a
    different setting -- it costs exactly one fresh HDBSCAN fit."""
    import contextlib
    import io

    import axial.merge_names as merge_names_module
    from axial.names import DEFAULT_MIN_SAMPLES, DEFAULT_PCA_COMPONENTS, run_names

    root = isolated_vault_root
    _build_fixture_answers(root, [[BELLICIST, DISTINCT_A], [BELLICIST_ALIAS, DISTINCT_B]])
    names_dir = root / "data" / "names"
    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
    )

    real_cluster_reduced = merge_names_module._cluster_reduced
    calls = []

    def _spy(reduced, min_cluster_size, min_samples):
        calls.append((min_cluster_size, min_samples))
        return real_cluster_reduced(reduced, min_cluster_size, min_samples)

    monkeypatch.setattr(merge_names_module, "_cluster_reduced", _spy)

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        merge_names_module.run_merge_names(
            embeddings_dir=names_dir / "embeddings.lance",
            alias_map_path=names_dir / "alias_map.json",
            index_path=names_dir / "index.json",
            decisions_path=names_dir / "merge_decisions.jsonl",
            manifest_path=names_dir / "merge_manifest.json",
            similarity_manifest_path=names_dir / "similarity_manifest.json",
            domain_dir=root / "no-such-domain",
            client=_empty_client(),
            min_cluster_size=99,  # deliberately not what `run_names` fit at
            min_samples=DEFAULT_MIN_SAMPLES,
            pca_components=DEFAULT_PCA_COMPONENTS,
        )

    assert len(calls) == 1, "a mismatched dial must re-fit exactly once, not skip or repeat"
    assert calls[0] == (99, DEFAULT_MIN_SAMPLES)
    combined = stderr.getvalue()
    assert "clustering" in combined and "HDBSCAN" in combined
    assert "clustering finished" in combined


def test_recluster_flag_forces_a_refit_even_when_settings_match(isolated_vault_root, monkeypatch):
    """`--recluster` (`recluster=True`) must re-fit even when this run's own
    settings match the persisted manifest -- the escape hatch for "I don't
    trust the persisted labels", not just a settings-diff."""
    import contextlib
    import io

    import axial.merge_names as merge_names_module
    from axial.names import DEFAULT_MIN_CLUSTER_SIZE, DEFAULT_MIN_SAMPLES, DEFAULT_PCA_COMPONENTS
    from axial.names import run_names

    root = isolated_vault_root
    _build_fixture_answers(root, [[BELLICIST, DISTINCT_A], [BELLICIST_ALIAS, DISTINCT_B]])
    names_dir = root / "data" / "names"
    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
    )

    real_cluster_reduced = merge_names_module._cluster_reduced
    calls = []

    def _spy(reduced, min_cluster_size, min_samples):
        calls.append((min_cluster_size, min_samples))
        return real_cluster_reduced(reduced, min_cluster_size, min_samples)

    monkeypatch.setattr(merge_names_module, "_cluster_reduced", _spy)

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        merge_names_module.run_merge_names(
            embeddings_dir=names_dir / "embeddings.lance",
            alias_map_path=names_dir / "alias_map.json",
            index_path=names_dir / "index.json",
            decisions_path=names_dir / "merge_decisions.jsonl",
            manifest_path=names_dir / "merge_manifest.json",
            similarity_manifest_path=names_dir / "similarity_manifest.json",
            domain_dir=root / "no-such-domain",
            client=_empty_client(),
            min_cluster_size=DEFAULT_MIN_CLUSTER_SIZE,
            min_samples=DEFAULT_MIN_SAMPLES,
            pca_components=DEFAULT_PCA_COMPONENTS,
            recluster=True,
        )

    assert len(calls) == 1, "--recluster must force exactly one fresh fit"
    assert "--recluster was passed" in stderr.getvalue()


def test_clustering_prints_a_startup_line_and_a_running_heartbeat(isolated_vault_root, monkeypatch):
    """The silence itself was the bug (#458): a re-fit must print that it is
    running before the fit starts, and again while it is still running, not
    only once it returns. `_cluster_reduced` is stubbed to sleep, standing
    in for HDBSCAN's own real multi-minute fit -- long enough, against a
    short `cluster_heartbeat_seconds`, to force more than one heartbeat."""
    import contextlib
    import io
    import time

    import axial.merge_names as merge_names_module
    from axial.names import DEFAULT_MIN_SAMPLES, DEFAULT_PCA_COMPONENTS, run_names

    root = isolated_vault_root
    _build_fixture_answers(root, [[BELLICIST, DISTINCT_A], [BELLICIST_ALIAS, DISTINCT_B]])
    names_dir = root / "data" / "names"
    run_names(
        answers_dir=root / "data" / "answers",
        inventory_path=names_dir / "inventory.jsonl",
        embeddings_dir=names_dir / "embeddings.lance",
        manifest_path=names_dir / "similarity_manifest.json",
    )

    def _slow_cluster(reduced, min_cluster_size, min_samples):
        time.sleep(0.2)
        return [0 for _ in range(len(reduced))]

    monkeypatch.setattr(merge_names_module, "_cluster_reduced", _slow_cluster)

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        merge_names_module.run_merge_names(
            embeddings_dir=names_dir / "embeddings.lance",
            alias_map_path=names_dir / "alias_map.json",
            index_path=names_dir / "index.json",
            decisions_path=names_dir / "merge_decisions.jsonl",
            manifest_path=names_dir / "merge_manifest.json",
            similarity_manifest_path=names_dir / "similarity_manifest.json",
            domain_dir=root / "no-such-domain",
            client=_empty_client(),
            min_cluster_size=99,  # forces the fit (mismatched), not the reuse path
            min_samples=DEFAULT_MIN_SAMPLES,
            pca_components=DEFAULT_PCA_COMPONENTS,
            cluster_heartbeat_seconds=0.04,
        )

    lines = stderr.getvalue().splitlines()
    started_lines = [line for line in lines if "clustering" in line and "HDBSCAN" in line]
    heartbeat_lines = [line for line in lines if "clustering still running" in line]
    finished_lines = [line for line in lines if "clustering finished" in line]

    assert len(started_lines) == 1, "the clustering phase must announce itself before it runs"
    assert len(heartbeat_lines) >= 2, (
        "a 0.2s fit against a 0.04s heartbeat must print more than one "
        f"heartbeat line while it is still running -- got {heartbeat_lines!r}"
    )
    assert len(finished_lines) == 1
