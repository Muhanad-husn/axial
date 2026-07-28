"""Phase A v1 slice 05 (issue #416): Reconcile -- the model merges names
into a reversible alias map (`specs/PRODUCT.md` §7.16 artifact 3, §7.9's
`reconcile` pass, P0-12's last four bullets).

D10: "the model makes the merge calls with clusters as hints. Start loose,
tighten by inspection. The output is an alias map, which is data, so every
merge is reversible and re-runnable."

This is NOT `src/axial/reconcile.py`, which shares only the English word:
that module is #291's deterministic, model-free garbage collection of
derived artifacts whose source file is gone. Nothing here imports it, and
`axial names merge` never collides with `axial reconcile gc`. The merge
lives on the `names` surface because all four §7.16 artifacts -- inventory,
similarity view, alias map, index -- are one family under `data/names/`.

How it works:

  1. **The clusters are hints, chosen by a dial.** The persisted name
     vectors (`data/names/embeddings.lance`, slice 04) are re-clustered at
     the tightness `config/pipeline.yaml`'s `names.merge_min_cluster_size` /
     `names.merge_min_samples` name -- the same two HDBSCAN settings `axial
     names examine` sweeps and reports, so the founder moves this dial by
     reading that report (D10's "start loose, tighten by inspection"). It is
     re-clustered rather than read off the build's persisted labels so
     changing the dial costs one HDBSCAN fit, never a re-embed.
  2. **One call per cluster, batched only to bound the request.** A cluster
     whose rendered surface forms exceed `DEFAULT_MEMBER_CHAR_BUDGET`
     characters is split across a small number of calls. That budget is a
     construction limit on prompt size, in the same spirit as P0-13's
     Gather budget -- not a quality knob and not tuned.
  3. **The prompt states the judgment and stops.** No rules, no criteria
     list, no worked examples, and deliberately no "think step by step":
     the pass runs at `temperature: 1` with `reasoning: high` (founder
     directive, §7.9's `reconcile` entry), because the project's own
     measurement says an underdetermined generative task is won by sampling
     and by letting the model think, not by prompt engineering
     (`docs/tag-reliability-best-of-n.md` §2.11, lesson 4).
  4. **Every decision is persisted before it is used.** Each batch's answer
     lands in `data/names/merge_decisions.jsonl`, keyed by a content hash of
     the batch's own member list. That is what makes the pass re-runnable in
     the acceptance sense: a temperature-1 sampler does not repeat itself,
     so re-running reproduces the same merges by reusing the same recorded
     decisions, and moving the tightness dial re-decides exactly the batches
     whose membership actually changed. It is also the resume point for a
     pass that costs real money per call.
  4b. **Calls run concurrently, bounded by `--workers`.** A serial pass over
     ~19k clusters is a ~12-hour job at this call's own expected latency, for
     calls that cost a fraction of a cent each -- the work is I/O-bound
     (network, not CPU), so a `ThreadPoolExecutor` over the pending batches
     is the fix. One client is shared by the pool, because the client IS the
     connection pool. Checkpoint writes stay on ONE thread (the
     result-collection loop, never inside a worker), so resumability is
     unchanged: a mid-run kill still leaves every already-decided batch
     durably on disk. The fold (`build_alias_map_nodes`, via `_Union`) was
     already order-independent by construction -- a union's winner is always
     the lexicographically smaller root, never "whichever arrived first" --
     so completions racing in is not a new hazard; it is pinned by a direct
     test rather than left to that argument alone.
  5. **`polity_canonical.yaml` seeds the map and never gates it** (D9,
     §7.1). Its foldings are unioned in alongside the model's, and a
     surface it does not mention passes through untouched. Where a seed
     node's canonical spelling is itself in the corpus, it wins the group's
     canonical; where it is not, the canonical is still elected from the
     group's own surface forms, so no name page is ever minted for a string
     the corpus never said.
  6. **Nothing is dropped.** Seed foldings and model merges are unioned
     over the whole inventory, so a surface no cluster reached, no model
     call placed, and no seed mentioned survives as its own canonical node
     with no aliases (§7.16's closing sentence).

Outputs, under `data/names/` (§6): `alias_map.json` in §7.16's exact
`{version, generated_at, nodes: [{canonical, kind, aliases[]}]}` shape --
never a field more, so a partial run's map is not distinguished by its own
shape -- and `index.json`, the surviving canonical set slice 06 writes one
page per entry for. Both are rewritten whole on every run, and nothing else
on disk depends on the map having been applied -- deleting a node from
`alias_map.json` undoes exactly that merge the next time slice 06 runs.

A THIRD file, `merge_manifest.json`, carries what the other two cannot say
about themselves: whether this run actually decided every cluster
(`complete`) and the batch counts behind that. `alias_map.json`/`index.json`
are rewritten whole from whatever decisions exist so far, on purpose (that is
what makes the pass resumable) -- which also means a map built from 30 of
19,434 clusters looks, by its own shape, identical to a finished one. The
manifest is the one place that distinction is on disk rather than only in a
run's own stdout.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from axial.checkpoint import append_checkpoint_record, load_checkpoint_records
from axial.interrogate import _default_domain_dir
from axial.llm import RECONCILE_PASS_NAME, LLMClient, get_client
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.names import (
    ClusterFn,
    DEFAULT_EMBEDDINGS_DIR,
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_MIN_SAMPLES,
    DEFAULT_NAMES_DATA_DIR,
    DEFAULT_PCA_COMPONENTS,
    NOISE_LABEL,
    _cluster_reduced,
    _load_name_rows,
    _reduce_vectors,
)
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH
from axial.polity_canonical import PolityCanonicalError, _normalize, load_polity_canonical

# §6's `data/names/` family: the inventory and the similarity view are slice
# 04's; these two are Reconcile's own output, plus the decision log that makes
# a sampled pass reproducible.
DEFAULT_ALIAS_MAP_PATH = DEFAULT_NAMES_DATA_DIR / "alias_map.json"
DEFAULT_INDEX_PATH = DEFAULT_NAMES_DATA_DIR / "index.json"
DEFAULT_DECISIONS_PATH = DEFAULT_NAMES_DATA_DIR / "merge_decisions.jsonl"
DEFAULT_MERGE_MANIFEST_PATH = DEFAULT_NAMES_DATA_DIR / "merge_manifest.json"

# Bounded concurrent cluster-decision workers (issue #416). The work is
# I/O-bound: ~19k independent calls that each wait on the network, so a
# serial pass takes cluster_count x per-call latency end to end (at 2s a
# call that is ~11 hours; at 10s -- plausible with reasoning at `high` --
# it is over two days) while the pool divides that by `workers`.
#
# 12 is a STARTING value, not a measured one: per-call latency for this pass
# has never been observed, so no number here can be. It is the same order as
# this project's existing concurrent-worker precedent
# (`axial.brief.sweep.DEFAULT_WORKERS` = 3, over calls far heavier than one
# cluster's), raised because these calls are small and independent. It is a
# CLI flag (`--workers`), so the founder moves it after watching one real
# run rather than editing this line.
DEFAULT_WORKERS = 12

# How many clusters ride in one model call (issue #440). One-per-call sent a
# median 825-character prompt against a 20,000-character budget -- 4.1% of it
# -- because 84% of real clusters hold only two or three surface forms, and it
# paid the per-call reasoning ramp-up once per cluster: 19,434 times for a
# corpus of 78,115 names.
#
# 20 is the founder's dial, exposed as `--clusters-per-call`, not a tuned
# constant. It trades the model's bookkeeping span (every surface must be
# placed exactly once, which gets harder the more are in front of it) against
# the call count, and it is deliberately well under what the character budget
# alone would allow (~160) so the first packed run is not also the most
# aggressive one. `DEFAULT_MEMBER_CHAR_BUDGET` still caps the request.
DEFAULT_CLUSTERS_PER_CALL = 20

# §7.16's own map shape carries a `version`; `polity_canonical.yaml`, which
# seeds it, uses the same field for the same job.
ALIAS_MAP_VERSION = 1

# The largest rendered member block one merge call may carry, in characters.
# A construction limit on request size -- the same rule P0-13 states for
# Gather ("a hard character limit enforced in code, not an instruction in the
# prompt") -- not a quality knob: a cluster under it is one call, exactly as
# §7.16 says, and only an outsized one is split across a few. 20k characters
# of surface forms is a few thousand names, comfortably inside any model's
# context alongside the short prompt around it.
DEFAULT_MEMBER_CHAR_BUDGET = 20_000

_PROMPT_TEMPLATE = """\
Below are name surface forms collected from academic passages -- people, \
places, concepts, works, groups, arguments. They were grouped together by a \
clustering algorithm because their wordings are similar. That grouping is a \
hint, and it is often wrong.

Decide which of them name the same thing. Where several do, pick the clearest \
one as the canonical name and list the rest as its aliases. A surface form \
that names something of its own stands on its own, with no aliases.

SURFACE FORMS
{members}

RESPONSE. Reply with ONLY a JSON object, no prose and no markdown fences:
{{"nodes": [{{"canonical": "<surface form>", "aliases": ["<surface form>", ...]}}, ...]}}
Write every surface form exactly as it appears above, and use each one exactly \
once across all nodes.
"""

# The packed form of the same prompt, for a call carrying several clusters
# (issue #440). Identical wording, with ONE structural sentence added -- that
# the groups are independent -- because that is the fact the single-cluster
# prompt got for free from there being only one group. Nothing about how to
# judge changes: still no criteria, no examples, no instruction to think.
_PACKED_PROMPT_TEMPLATE = """\
Below are groups of name surface forms collected from academic passages -- \
people, places, concepts, works, groups, arguments. Each group was put \
together by a clustering algorithm because the wordings are similar. That \
grouping is a hint, and it is often wrong.

Decide which of them name the same thing. Where several do, pick the clearest \
one as the canonical name and list the rest as its aliases. A surface form \
that names something of its own stands on its own, with no aliases.

The groups are independent of each other. Decide each one on its own.

{groups}

RESPONSE. Reply with ONLY a JSON object covering every group, no prose and no \
markdown fences:
{{"nodes": [{{"canonical": "<surface form>", "aliases": ["<surface form>", ...]}}, ...]}}
Write every surface form exactly as it appears above, and use each one exactly \
once across all nodes.
"""


class MergeNamesError(Exception):
    """Base class for all name-merge errors."""


class MergeResponseError(MergeNamesError):
    """Raised when a merge response is not usable as a set of merge
    decisions over the batch it was asked about -- a shape failure, so it is
    re-askable within `complete_json`'s own bounded budget."""


class MergeDecisionsCorruptError(MergeNamesError):
    def __init__(self, path: Path, line_no: int, cause: json.JSONDecodeError):
        super().__init__(f"merge decision log {path} is corrupt at line {line_no}: {cause}")


# ---------------------------------------------------------------------------
# The tightness dial (D10: chosen by looking at slice 04's report)
# ---------------------------------------------------------------------------


def _resolve_merge_tightness(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> tuple[int, int]:
    """`(min_cluster_size, min_samples)` from `config/pipeline.yaml`'s
    `names` block, falling back to `axial.names`' own loosest defaults when
    the file, the block or either key is absent -- the same
    config-then-code-default resolution every other tunable in that file
    uses."""
    if not config_path.is_file():
        return DEFAULT_MIN_CLUSTER_SIZE, DEFAULT_MIN_SAMPLES
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    block = document.get("names") or {}
    return (
        int(block.get("merge_min_cluster_size", DEFAULT_MIN_CLUSTER_SIZE)),
        int(block.get("merge_min_samples", DEFAULT_MIN_SAMPLES)),
    )


# ---------------------------------------------------------------------------
# Batching (one call per cluster; a few only when the request would be huge)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeBatch:
    """One model call's worth of a cluster's members."""

    cluster_label: int
    members: tuple[str, ...]

    @property
    def key(self) -> str:
        """Content hash of this batch's member list -- the decision log's
        key. Content-addressed on purpose: moving the tightness dial changes
        which surfaces sit together, so a batch whose membership is unchanged
        reuses its recorded decision and one that changed is re-decided,
        without anyone tracking which setting produced what."""
        payload = json.dumps(list(self.members), ensure_ascii=False, sort_keys=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_batches(
    labels: Iterable[int],
    surface_forms: list[str],
    member_char_budget: int = DEFAULT_MEMBER_CHAR_BUDGET,
) -> list[MergeBatch]:
    """One batch per cluster -- §7.16's "one call per cluster" -- splitting
    only a cluster whose rendered members would exceed `member_char_budget`.
    Noise (`NOISE_LABEL`) and single-member clusters produce no batch at all:
    there is no merge to decide, and those surfaces survive as their own
    canonical nodes. Deterministic: clusters in label order, members in
    inventory (sorted surface form) order."""
    clusters: dict[int, list[str]] = {}
    for label, surface_form in zip(labels, surface_forms):
        if label == NOISE_LABEL:
            continue
        clusters.setdefault(label, []).append(surface_form)

    batches: list[MergeBatch] = []
    for label in sorted(clusters):
        members = clusters[label]
        if len(members) < 2:
            continue
        current: list[str] = []
        size = 0
        for surface_form in members:
            cost = len(surface_form) + 1
            if current and size + cost > member_char_budget:
                batches.append(MergeBatch(label, tuple(current)))
                current, size = [], 0
            current.append(surface_form)
            size += cost
        if len(current) > 1:
            batches.append(MergeBatch(label, tuple(current)))
    return batches


def pack_batches(
    batches: list[MergeBatch],
    clusters_per_call: int = DEFAULT_CLUSTERS_PER_CALL,
    member_char_budget: int = DEFAULT_MEMBER_CHAR_BUDGET,
) -> list[tuple[MergeBatch, ...]]:
    """Group per-cluster batches into CALLS (issue #440).

    84% of real clusters hold two or three surface forms, so one call per
    cluster sent a median 825-character prompt against a 20,000-character
    budget -- 4% of it -- and paid the model's per-call reasoning ramp-up
    19,434 times over for ~2 strings a time. Packing amortises that ramp-up
    across `clusters_per_call` decisions instead of paying it per decision.

    Each batch keeps its own identity and its own decision-log key, so this
    changes only how many decisions share one request. A pass that already
    decided a cluster one-per-call reuses that decision unchanged.

    Two bounds, and the tighter one wins: `clusters_per_call` (the model's
    bookkeeping span -- it must place every surface exactly once, and that
    gets harder with more of them) and `member_char_budget` (the same request
    size guard `build_batches` already enforces). A single batch that is
    itself at the size guard becomes a call of one, exactly as before."""
    calls: list[tuple[MergeBatch, ...]] = []
    current: list[MergeBatch] = []
    size = 0
    for batch in batches:
        cost = sum(len(surface_form) + 1 for surface_form in batch.members)
        too_many = len(current) >= max(clusters_per_call, 1)
        too_big = current and size + cost > member_char_budget
        if too_many or too_big:
            calls.append(tuple(current))
            current, size = [], 0
        current.append(batch)
        size += cost
    if current:
        calls.append(tuple(current))
    return calls


# ---------------------------------------------------------------------------
# The call: a loose prompt, and a parse that never invents a name
# ---------------------------------------------------------------------------


def compose_merge_prompt(members: Iterable[str], kinds: dict[str, str | None]) -> str:
    """One batch's prompt: the surface forms with the kind the corpus gave
    each, and the judgment being asked for. Nothing else -- no criteria, no
    examples, no instruction to think (see the module docstring)."""
    rendered = "\n".join(
        f"- {surface_form!r} ({kinds.get(surface_form)})"
        if kinds.get(surface_form)
        else f"- {surface_form!r}"
        for surface_form in members
    )
    return _PROMPT_TEMPLATE.format(members=rendered)


def _render_members(members: Iterable[str], kinds: dict[str, str | None]) -> str:
    return "\n".join(
        f"- {surface_form!r} ({kinds.get(surface_form)})"
        if kinds.get(surface_form)
        else f"- {surface_form!r}"
        for surface_form in members
    )


def compose_call_prompt(groups: list[tuple[str, ...]], kinds: dict[str, str | None]) -> str:
    """One CALL's prompt (issue #440). A call carrying a single group renders
    exactly the single-cluster prompt it always did, byte for byte, so packing
    changes nothing for a call that was not packed."""
    if len(groups) == 1:
        return compose_merge_prompt(groups[0], kinds)
    rendered = "\n\n".join(
        f"GROUP {index}\n{_render_members(members, kinds)}"
        for index, members in enumerate(groups, start=1)
    )
    return _PACKED_PROMPT_TEMPLATE.format(groups=rendered)


def parse_merge_response(raw: str, members: Iterable[str]) -> list[dict[str, Any]]:
    """Parse one merge response into `[{canonical, aliases[]}]` restricted to
    `members`.

    A surface form the batch did not contain is dropped rather than minted:
    the inventory is the lossless record of what the corpus said (§7.16), and
    a merge pass may fold names, never invent them. A member the response
    placed twice keeps its first placement, so the result is always a
    partition. A member the response never placed is simply absent here and
    survives downstream as its own node.

    Raises `MergeResponseError` on a shape failure -- no `nodes` list, or a
    response that placed none of this batch's members -- which is response
    noise rather than a judgment, and so is re-asked by `complete_json`.
    """
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise MergeResponseError(f"merge response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise MergeResponseError("merge response must be a JSON object with a 'nodes' list")

    known = {_normalize(surface_form): surface_form for surface_form in members}
    claimed: set[str] = set()
    nodes: list[dict[str, Any]] = []

    def resolve(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        surface_form = known.get(_normalize(value))
        if surface_form is None or surface_form in claimed:
            return None
        claimed.add(surface_form)
        return surface_form

    for raw_node in data["nodes"]:
        if not isinstance(raw_node, dict):
            continue
        canonical = resolve(raw_node.get("canonical"))
        raw_aliases = raw_node.get("aliases")
        aliases = [
            resolved
            for resolved in (
                resolve(alias) for alias in (raw_aliases if isinstance(raw_aliases, list) else [])
            )
            if resolved is not None
        ]
        if canonical is None:
            # The model's canonical was not one of this batch's surface
            # forms (or was already used): the merge it described is still
            # real, so promote its first surviving alias rather than
            # discarding the node.
            if not aliases:
                continue
            canonical = aliases.pop(0)
        nodes.append({"canonical": canonical, "aliases": sorted(aliases)})

    if not nodes:
        raise MergeResponseError(
            "merge response placed none of the batch's surface forms; expected each "
            "one to appear exactly once across 'nodes'"
        )
    return nodes


def _decide_call(
    call: tuple[MergeBatch, ...],
    kinds: dict[str, str | None],
    client: LLMClient,
) -> tuple[tuple[MergeBatch, ...], list[dict[str, Any]] | None, str | None]:
    """Decide one CALL's worth of clusters. Runs on a worker thread (#416/#440).

    Returns `(call, records, failure_reason)`: one decision record PER BATCH,
    or `None` on a content-shaped failure (`failure_reason` then carries the
    message). A failure loses the whole call's clusters for this run, but none
    is recorded, so a later run retries them.

    `ModelJsonError`/`MergeResponseError` are caught here exactly as they were
    when a call carried one cluster, and NOTHING else is: a transport-level
    failure (`LLMError`/`httpx.HTTPError`) propagates out, surfaces from
    `future.result()`, and stays fatal.

    The response is a FLAT node list, so it is parsed once against every
    surface the call carried and then split back per batch by which batch owns
    each node's canonical. Batches are disjoint, so every node lands in
    exactly one record. A node the model built ACROSS two groups -- against
    the prompt's own instruction -- keeps its cross-group aliases and is
    recorded under its canonical's batch: clusters are hints (D10), so a real
    merge the model saw through the grouping is kept, not discarded.
    `build_alias_map_nodes` reads every record's nodes as one flat list and
    folds them order-independently, so which record carries a node never
    changes the map.

    This function NEVER writes to disk. Every worker returns its records and
    the single result-collecting thread does the checkpoint append, which is
    what keeps resumability intact under concurrency (`run_merge_names`).

    ONE client is shared by every worker rather than built per call: it is the
    connection pool, and re-establishing one per call would throw away
    keep-alive on the very workload concurrency is here to speed up.
    `httpx.Client` is thread-safe, and every request-shaping decision this
    pass makes (temperature, reasoning, model) is per-CALL via `pass_name`,
    never per-client state.
    """
    groups = [batch.members for batch in call]
    everything = tuple(surface for members in groups for surface in members)
    prompt = compose_call_prompt(groups, kinds)
    started = time.monotonic()
    try:
        raw = complete_json(
            client,
            prompt,
            pass_name=RECONCILE_PASS_NAME,
            validate=lambda response: parse_merge_response(response, everything),
        )
        nodes = parse_merge_response(raw, everything)
    except (ModelJsonError, MergeResponseError) as exc:
        return call, None, str(exc)

    model = client.model_for_pass(RECONCILE_PASS_NAME)
    decided_at = _utc_now()
    owner = {surface: index for index, batch in enumerate(call) for surface in batch.members}
    per_batch: list[list[dict[str, Any]]] = [[] for _ in call]
    for node in nodes:
        per_batch[owner[node["canonical"]]].append(node)

    records = [
        {
            "batch_key": batch.key,
            "cluster_label": batch.cluster_label,
            "members": list(batch.members),
            "nodes": per_batch[index],
            "model": model,
            "decided_at": decided_at,
        }
        for index, batch in enumerate(call)
    ]
    print(
        f"reconcile: {len(call)} cluster(s), {len(everything)} surface(s) "
        f"answered in {time.monotonic() - started:.1f}s",
        file=sys.stderr,
    )
    return call, records, None


# ---------------------------------------------------------------------------
# Folding decisions + the seed into one alias map (order-independent)
# ---------------------------------------------------------------------------


class _Union:
    """Plain union-find over surface forms. The model's merges arrive per
    batch and the seed's arrive per node, and the two can chain (the model
    folds A into B in one cluster, the seed folds B into C); union-find makes
    the fold order-independent and idempotent, which is what "re-running
    reproduces the same merges" needs."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self._parent.setdefault(item, item)

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            # Lexicographic root, so the grouping never depends on the order
            # the unions arrived in.
            winner, loser = sorted((left_root, right_root))
            self._parent[loser] = winner

    def groups(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for item in self._parent:
            grouped.setdefault(self.find(item), []).append(item)
        return {root: sorted(members) for root, members in grouped.items()}


def _seed_groups(
    surface_forms: Iterable[str], domain_dir: Path
) -> tuple[dict[str, list[str]], str]:
    """`polity_canonical.yaml`'s foldings, restricted to surfaces the corpus
    actually produced: `{seed canonical: [surface forms]}` (D9, §7.1 -- a
    cleanup aid, never a gate). A missing or malformed seed file yields no
    foldings and a reason, never an error: an unmapped name always passes
    through on its merits."""
    try:
        cmap = load_polity_canonical(domain_dir)
    except PolityCanonicalError as exc:
        return {}, f"seed not applied ({exc})"

    grouped: dict[str, list[str]] = {}
    for surface_form in surface_forms:
        node = cmap.index.get(_normalize(surface_form))
        if node is not None:
            grouped.setdefault(node.canonical, []).append(surface_form)
    return grouped, f"seeded from {Path(domain_dir) / 'polity_canonical.yaml'}"


def build_alias_map_nodes(
    entries: list[tuple[str, str | None, int]],
    decision_nodes: list[dict[str, Any]],
    seed_groups: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Fold every model decision and every seed folding over the WHOLE
    inventory and elect one canonical per resulting group.

    `entries` is `(surface_form, kind, count)` for every inventory entry, so
    a surface no decision and no seed touched still comes out as its own node
    with no aliases (§7.16). The canonical is elected in this order: the
    seed's own spelling when the corpus contains it (it is the curated one),
    then the canonical the model chose, then the most-mentioned surface form
    -- ties broken lexicographically throughout, so the map is a pure
    function of its inputs.
    """
    counts = {surface_form: count for surface_form, _kind, count in entries}
    kinds = {surface_form: kind for surface_form, kind, _count in entries}

    union = _Union()
    for surface_form, _kind, _count in entries:
        union.add(surface_form)

    model_canonical: dict[str, int] = {}
    for node in decision_nodes:
        canonical = node["canonical"]
        if canonical not in counts:
            continue
        model_canonical[canonical] = max(model_canonical.get(canonical, 0), len(node["aliases"]))
        for alias in node["aliases"]:
            if alias in counts:
                union.union(canonical, alias)

    seed_canonical: set[str] = set()
    for canonical, members in seed_groups.items():
        normalized_canonical = _normalize(canonical)
        for member in members:
            union.union(members[0], member)
            if _normalize(member) == normalized_canonical:
                seed_canonical.add(member)

    nodes: list[dict[str, Any]] = []
    for members in union.groups().values():
        canonical = _elect_canonical(members, seed_canonical, model_canonical, counts)
        aliases = sorted(member for member in members if member != canonical)
        nodes.append(
            {
                "canonical": canonical,
                "kind": _elect_kind(canonical, members, kinds, counts),
                "aliases": aliases,
            }
        )
    nodes.sort(key=lambda node: node["canonical"])
    return nodes


def _elect_canonical(
    members: list[str],
    seed_canonical: set[str],
    model_canonical: dict[str, int],
    counts: dict[str, int],
) -> str:
    seeded = sorted(member for member in members if member in seed_canonical)
    if seeded:
        return seeded[0]
    chosen = [member for member in members if member in model_canonical]
    if chosen:
        return min(chosen, key=lambda member: (-model_canonical[member], -counts[member], member))
    return min(members, key=lambda member: (-counts[member], member))


def _elect_kind(
    canonical: str,
    members: list[str],
    kinds: dict[str, str | None],
    counts: dict[str, int],
) -> str | None:
    """The canonical's own kind, falling back to the group's most-mentioned
    kind when the canonical never carried one (a citation-only surface form,
    §7.16). `None` when no member carried one at all."""
    if kinds.get(canonical):
        return kinds[canonical]
    weighted: dict[str, int] = {}
    for member in members:
        kind = kinds.get(member)
        if kind:
            weighted[kind] = weighted.get(kind, 0) + counts[member]
    if not weighted:
        return None
    return min(weighted, key=lambda kind: (-weighted[kind], kind))


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_alias_map(nodes: list[dict[str, Any]], path: Path) -> None:
    """§7.16's exact shape: `{version, generated_at, nodes: [{canonical,
    kind, aliases[]}]}`. Rewritten whole every run -- it is the only thing
    that carries a merge, so editing or deleting a node undoes exactly that
    merge and nothing else."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"version": ALIAS_MAP_VERSION, "generated_at": _utc_now(), "nodes": nodes},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def write_index(nodes: list[dict[str, Any]], path: Path) -> None:
    """The surviving canonical set (§7.16: "the surviving `canonical` set is
    the index") -- what slice 06 writes one name page per entry for."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": ALIAS_MAP_VERSION,
                "generated_at": _utc_now(),
                "names": [node["canonical"] for node in nodes],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def write_merge_manifest(
    path: Path,
    *,
    complete: bool,
    batches_total: int,
    batches_decided: int,
    batches_reused: int,
    batches_failed: int,
) -> None:
    """The one place a partial run says so on disk (issue #416, founder
    correction). `alias_map.json`/`index.json` are rewritten whole from
    whatever decisions exist so far, on purpose -- that is what makes the
    pass resumable -- but it also means a map built from 30 of 19,434
    clusters is, by its own `{version, generated_at, nodes}` shape,
    indistinguishable from a finished one. Mirrors slice 04's own sibling
    `similarity_manifest.json` convention under `data/names/`: a reader must
    check `complete` here before treating the map as the whole corpus's
    answer, not just count its own nodes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": _utc_now(),
                "complete": complete,
                "batches_total": batches_total,
                "batches_decided": batches_decided,
                "batches_reused": batches_reused,
                "batches_failed": batches_failed,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def load_decisions(path: Path) -> dict[str, dict[str, Any]]:
    """Every recorded batch decision, keyed by `batch_key` -- the inverse of
    the append below, `{}` before the first run."""
    records = load_checkpoint_records(path, MergeDecisionsCorruptError)
    return {record["batch_key"]: record for record in records}


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def run_merge_names(
    embeddings_dir: Path | None = None,
    alias_map_path: Path | None = None,
    index_path: Path | None = None,
    decisions_path: Path | None = None,
    manifest_path: Path | None = None,
    domain_dir: str | Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    client: LLMClient | None = None,
    min_cluster_size: int | None = None,
    min_samples: int | None = None,
    pca_components: int = DEFAULT_PCA_COMPONENTS,
    member_char_budget: int = DEFAULT_MEMBER_CHAR_BUDGET,
    limit: int | None = None,
    workers: int = DEFAULT_WORKERS,
    clusters_per_call: int = DEFAULT_CLUSTERS_PER_CALL,
    cluster_fn: ClusterFn | None = None,
) -> dict[str, Any]:
    """Merge the name inventory into a reversible alias map and return the
    run summary.

    Reads slice 04's persisted similarity view, re-clusters it at the
    configured tightness, and asks the model about pending clusters
    concurrently -- up to `workers` at once (default `DEFAULT_WORKERS`; issue
    #416, founder correction: this pass is I/O-bound and a serial ~19k-call
    pass costs ~12 hours of wall clock for a few cents of spend). Writes
    `alias_map.json`, `index.json`, and `merge_manifest.json` (whether this
    run answered every cluster). Every batch's answer is appended to the
    decision log AS IT IS PRODUCED, on the single result-collecting thread,
    never inside a worker -- so an interrupted run (any worker count) resumes
    from exactly what is already on disk, a re-run reproduces the same
    merges regardless of which worker happened to finish first (the fold is
    order-independent by construction, see `_Union`), and moving the
    tightness dial only re-decides the batches whose membership changed.

    `limit`, when given, caps how many clusters this run SUBMITS, so it is
    still "stop after that many model calls this run" with workers in play:
    exactly `limit` batches are handed to the pool, never 19k futures that
    are then abandoned. The map is still written from every decision recorded
    so far, which is what makes a bounded first look on the real corpus cheap.

    `client`, when given, is used by every worker; otherwise one real client
    is built here and shared the same way (see `_decide_batch` for why one
    client, not one per batch).

    `cluster_fn`, when given, replaces the HDBSCAN clustering with a caller-
    supplied labelling -- the same injection seam `axial.names.run_names`
    already exposes, and the one a test uses to put a known set of surface
    forms in front of the model without depending on what HDBSCAN does to
    four vectors.

    Raises `axial.names.NoNamesToClusterError` when the similarity view does
    not exist -- running this before `axial names build` is a misconfigured
    invocation, not an empty map.
    """
    embeddings_dir = Path(embeddings_dir or DEFAULT_EMBEDDINGS_DIR)
    alias_map_path = Path(alias_map_path or DEFAULT_ALIAS_MAP_PATH)
    index_path = Path(index_path or DEFAULT_INDEX_PATH)
    decisions_path = Path(decisions_path or DEFAULT_DECISIONS_PATH)
    manifest_path = Path(manifest_path or DEFAULT_MERGE_MANIFEST_PATH)
    if domain_dir is None:
        domain_dir = _default_domain_dir(config_path)

    configured_min_cluster_size, configured_min_samples = _resolve_merge_tightness(config_path)
    if min_cluster_size is None:
        min_cluster_size = configured_min_cluster_size
    if min_samples is None:
        min_samples = configured_min_samples

    rows = _load_name_rows(embeddings_dir)
    entries = [(row["surface_form"], row["kind"] or None, int(row["count"])) for row in rows]
    surface_forms = [surface_form for surface_form, _kind, _count in entries]
    kinds = {surface_form: kind for surface_form, kind, _count in entries}

    vectors = [row["vector"] for row in rows]
    if cluster_fn is None:
        labels = _cluster_reduced(
            _reduce_vectors(vectors, pca_components), min_cluster_size, min_samples
        )
    else:
        labels = cluster_fn(vectors)

    batches = build_batches(labels, surface_forms, member_char_budget)
    decisions = load_decisions(decisions_path)
    pending = [batch for batch in batches if batch.key not in decisions]
    reused = len(batches) - len(pending)
    to_attempt = pending if limit is None else pending[:limit]
    calls = pack_batches(to_attempt, clusters_per_call, member_char_budget)
    print(
        f"reconcile: {len(surface_forms)} surface form(s), {len(batches)} cluster batch(es) "
        f"at min_cluster_size={min_cluster_size} min_samples={min_samples}; "
        f"{reused} already decided, {len(to_attempt)} to decide now in {len(calls)} call(s) "
        f"({len(pending) - len(to_attempt)} more pending) across {max(workers, 1)} worker(s)",
        file=sys.stderr,
    )

    called = 0
    failed = 0
    settled_calls = 0
    model: str | None = None
    if calls:
        # Built once, here, and shared by every worker -- never inside the
        # pool, so a misconfigured provider fails before any thread starts.
        if client is None:
            client = get_client(config_path=config_path)
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as executor:
            futures = {executor.submit(_decide_call, call, kinds, client): call for call in calls}
            # Results are collected -- and every checkpoint write happens --
            # on THIS one thread only, in whatever order calls actually
            # finish. That is exactly what makes resumability survive
            # concurrency: a mid-run kill still leaves every already-decided
            # batch durably on disk, one line at a time, never two workers
            # racing to append to the same file.
            for future in as_completed(futures):
                call = futures[future]
                _call, records, failure_reason = future.result()
                settled_calls += 1
                if records is None:
                    print(
                        f"reconcile: call of {len(call)} cluster(s) failed: {failure_reason}",
                        file=sys.stderr,
                    )
                    failed += len(call)
                    continue

                for record in records:
                    append_checkpoint_record(decisions_path, record)
                    decisions[record["batch_key"]] = record
                    called += 1
                model = records[0]["model"]
                print(
                    f"reconcile: {len(records)} cluster(s) recorded "
                    f"({settled_calls}/{len(calls)} calls, "
                    f"{called + failed}/{len(to_attempt)} clusters settled)",
                    file=sys.stderr,
                )

    seed_groups, seed_note = _seed_groups(surface_forms, Path(domain_dir))
    decision_nodes = [node for record in decisions.values() for node in record["nodes"]]
    nodes = build_alias_map_nodes(entries, decision_nodes, seed_groups)

    write_alias_map(nodes, alias_map_path)
    write_index(nodes, index_path)
    complete = all(batch.key in decisions for batch in batches)
    write_merge_manifest(
        manifest_path,
        complete=complete,
        batches_total=len(batches),
        batches_decided=called,
        batches_reused=reused,
        batches_failed=failed,
    )

    merged = sum(len(node["aliases"]) for node in nodes)
    return {
        "pass": RECONCILE_PASS_NAME,
        "model": model,
        "alias_map_path": str(alias_map_path),
        "index_path": str(index_path),
        "decisions_path": str(decisions_path),
        "manifest_path": str(manifest_path),
        "surface_forms": len(surface_forms),
        "clusters": len({label for label in labels if label != NOISE_LABEL}),
        "batches": len(batches),
        "decided": called,
        "reused": reused,
        "failed": failed,
        "workers": max(workers, 1),
        "calls": len(calls),
        "clusters_per_call": max(clusters_per_call, 1),
        "canonical_names": len(nodes),
        "merged_surface_forms": merged,
        "seed": seed_note,
        "seeded_surface_forms": sum(len(members) for members in seed_groups.values()),
        "min_cluster_size": min_cluster_size,
        "min_samples": min_samples,
        "limit": limit,
        # A cluster is complete when its decision is on disk; a failed or
        # unreached one is not, and a later run picks it up.
        "complete": complete,
    }
