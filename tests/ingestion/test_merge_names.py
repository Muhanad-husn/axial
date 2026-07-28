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


def _answers(names: list[str]) -> dict:
    return {
        "about": ["x"],
        "claim": "x",
        "move": "x",
        "ranges_over": "not-in-passage",
        "stops_holding": "not-in-passage",
        "position_of": "not-in-passage",
        "arguing_against": [],
        "names": [{"name": name, "kind": "concept"} for name in names],
        "citations": [],
        "mechanism": "not-in-passage",
        "evidence": "not-in-passage",
        "comparison": "not-in-passage",
        "defines": [],
        "uses": [],
        "concedes": "not-in-passage",
        "assumes": "not-in-passage",
    }


def _build_fixture_answers(root: Path, name_groups: list[list[str]]) -> None:
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
                        "answers": _answers(names),
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

    summary = _merge(names_dir, root, ConcurrentClient(), workers=3, clusters_per_call=1)

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

    summary = _merge(names_dir, root, CountingClient(), workers=8, limit=1, clusters_per_call=1)

    assert len(calls) == 1, "workers must not outrun --limit"
    assert summary["decided"] == 1
    assert summary["complete"] is False

    # The partial run says so on disk, where the map's own shape cannot.
    manifest = json.loads((names_dir / "merge_manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["batches_total"] == 3


def test_one_call_decides_many_clusters_and_records_each_separately(isolated_vault_root):
    """Issue #440. Three clusters must ride in ONE model call, and the flat
    response must be split back into one decision record per cluster -- that
    split is what keeps every already-bought decision reusable and every
    cluster independently resumable."""
    root = isolated_vault_root
    names_dir = _six_name_fixture(root)

    prompts: list[str] = []

    class PackingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            prompts.append(prompt)
            # Fold each pair; the response is flat across all three groups.
            nodes = [
                {"canonical": _ALL_SIX[i], "aliases": [_ALL_SIX[i + 1]]} for i in (0, 2, 4)
            ]
            return json.dumps({"nodes": nodes})

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    summary = _merge(names_dir, root, PackingClient(), workers=4, clusters_per_call=20)

    assert len(prompts) == 1, "three clusters must share one call"
    assert summary["calls"] == 1
    assert summary["batches"] == 3
    assert summary["decided"] == 3, "one decision record per cluster, not per call"

    # One line per cluster, each with its own key -- so a re-run reuses them.
    lines = (names_dir / "merge_decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    records = [json.loads(line) for line in lines]
    assert len({r["batch_key"] for r in records}) == 3
    for record in records:
        assert len(record["nodes"]) == 1, "each record carries only its own cluster's node"
        node = record["nodes"][0]
        assert {node["canonical"], *node["aliases"]} <= set(record["members"])

    # The map is the same three folds, and nothing was dropped.
    nodes = _nodes_by_canonical(_read_alias_map(root))
    for i in (0, 2, 4):
        assert nodes[_ALL_SIX[i]] == [_ALL_SIX[i + 1]]


def test_a_packed_run_is_reused_by_a_later_unpacked_one(isolated_vault_root):
    """The decision key is per cluster, so packing is purely a request-shaping
    choice: decisions bought at one packing are reused at any other."""
    root = isolated_vault_root
    names_dir = _six_name_fixture(root)

    class OnceClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            self.calls += 1
            members = [name for name in _ALL_SIX if name in prompt]
            return json.dumps({"nodes": [{"canonical": m, "aliases": []} for m in members]})

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "fake"

    _merge(names_dir, root, OnceClient(), workers=4, clusters_per_call=20)

    second = OnceClient()
    summary = _merge(names_dir, root, second, workers=4, clusters_per_call=1)
    assert second.calls == 0, "a re-run at different packing must re-decide nothing"
    assert summary["decided"] == 0
    assert summary["reused"] == 3
