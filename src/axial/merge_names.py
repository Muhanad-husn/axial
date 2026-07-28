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

**Issue #446: HDBSCAN clustering's own loose tightness has a recall cost.**
Slice 04's clustering (D10, kept loose so it never fuses distinct entities --
#442 measured why tightening it globally is the wrong lever) means a name and
its variant routinely land in different clusters, so no merge call ever sees
them together and both survive as separate canonical names. `_candidate_
batches` (via `axial.name_candidates.generate_candidate_clusters`) is a
second, deterministic, LLM-free step that proposes the missing pairs as
additional cluster-shaped batches, fed to the exact same, unchanged merge
call below -- it decides nothing and merges nothing itself.

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
from axial.name_candidates import generate_candidate_clusters
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
    parse_scoped_source,
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
# 36 is MEASURED; it is the only value with a full-corpus run behind it
# (19,381 clusters, 1.76 clusters/s, near-zero non-200s). The old 12 was a
# guess.
#
# Do not raise it further without re-measuring. 96 was tried and the provider
# saturates: ~2.2 clusters/s against 36's 1.76, so 2.7x the workers bought
# ~25% -- and the deadline/error rate went from near-zero to ~1% of calls.
# The bottleneck is not the pool, it is generation. Per-call latency is a
# median 8s against a 16s MEAN, because ~5% of clusters send the model into a
# long generation that holds a worker slot for 5-10x the median; adding
# workers does not shorten those.
#
# Concurrency is still the only lever that costs no accuracy. The two that
# looked cleverer were measured against 200 already-decided real clusters and
# both lost: packing 20 clusters per call ran 1.9x SLOWER (output tokens
# dominate, and packing does not reduce them), and turning reasoning off ran
# 5.1x faster at 68% agreement with a lopsided over-merge bias -- 55 clusters
# merged MORE against 7 less. Against an 88.9% self-agreement noise floor,
# that 68% is a real degradation; over-merging destroys information and D10
# forbids it.
#
# `--workers` still goes higher for anyone who wants to re-measure.
DEFAULT_WORKERS = 36

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

# Issue #446: candidate clusters (`axial.name_candidates`) get their own
# `cluster_label` namespace, disjoint from HDBSCAN's (`NOISE_LABEL`=-1, real
# clusters numbered from 0) -- so a candidate batch is never mistaken for a
# real cluster in the decision log or a run's own printouts.
_CANDIDATE_LABEL_BASE = -1_000_000

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


def _split_into_batches(
    label: int, members: list[str], member_char_budget: int
) -> list[MergeBatch]:
    """One cluster's members, split into as few batches as fit under
    `member_char_budget` -- shared by `build_batches` (real HDBSCAN clusters)
    and `_candidate_batches` (issue #446's proposed clusters), so both go
    through the exact same construction limit on request size."""
    batches: list[MergeBatch] = []
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
        batches.extend(_split_into_batches(label, members, member_char_budget))
    return batches


def _candidate_batches(
    entries: list[tuple[str, str | None, int]],
    existing_keys: set[str],
    member_char_budget: int,
) -> list[MergeBatch]:
    """Issue #446: propose the pairs slice 04's own clustering never put in
    front of the merge model, as additional cluster-shaped batches.

    `existing_keys` is every batch key `build_batches` already produced from
    the real HDBSCAN clusters this run -- content-hashed on the member list
    (`MergeBatch.key`), so a candidate whose exact member set a real cluster
    ALREADY covers this run is skipped rather than asked twice, and (via
    `merge_decisions.jsonl`, keyed the same way) a candidate already decided
    on a previous run is reused untouched rather than re-decided."""
    batches: list[MergeBatch] = []
    for offset, members in enumerate(generate_candidate_clusters(entries)):
        label = _CANDIDATE_LABEL_BASE - offset
        for batch in _split_into_batches(label, list(members), member_char_budget):
            if batch.key in existing_keys:
                continue
            existing_keys.add(batch.key)
            batches.append(batch)
    return batches


# ---------------------------------------------------------------------------
# The call: a loose prompt, and a parse that never invents a name
# ---------------------------------------------------------------------------


def render_member(surface_form: str, kinds: dict[str, str | None]) -> str:
    """How ONE surface form appears in the prompt.

    Shared with `parse_merge_response` so the two can never drift. The prompt
    tells the model to write each surface "exactly as it appears above", and
    this function is what "above" means -- so the parse has to accept this
    form back (issue #416, the 2.89% failure below).
    """
    kind = kinds.get(surface_form)
    return f"{surface_form!r} ({kind})" if kind else f"{surface_form!r}"


def compose_merge_prompt(members: Iterable[str], kinds: dict[str, str | None]) -> str:
    """One batch's prompt: the surface forms with the kind the corpus gave
    each, and the judgment being asked for. Nothing else -- no criteria, no
    examples, no instruction to think (see the module docstring)."""
    rendered = "\n".join(f"- {render_member(m, kinds)}" for m in members)
    return _PROMPT_TEMPLATE.format(members=rendered)


def parse_merge_response(
    raw: str,
    members: Iterable[str],
    kinds: dict[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """Parse one merge response into `[{canonical, aliases[]}]` restricted to
    `members`.

    `kinds`, when given, also accepts each surface back in the exact form the
    PROMPT showed it (`render_member`) -- i.e. `'Sociology' (institution/group)`
    as well as `Sociology`. This is not fuzzy matching: it is the one other
    string this code itself put in front of the model. It exists because the
    prompt says "write every surface form exactly as it appears above", and
    2.89% of the first full corpus pass (561 of 19,434 clusters) was discarded
    for taking that literally -- the model answered correctly, echoed the
    rendered form, and the whole cluster was thrown away on formatting. Only
    the exact rendered string is accepted, never a stripped-parenthetical
    heuristic, because real surfaces end in parentheses too
    (`Phelps-Brown and Hopkins (1956)`).

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

    members = list(members)

    # EXACT match first. `_normalize` casefolds, so two members differing only
    # by case (`Slavery`/`slavery`) collapse to one key -- and then the model's
    # correct merge is silently dropped, because both strings resolve to the
    # same surface and the second is refused as already-claimed. The first
    # corpus map carried 1,514 such pairs as separate canonical names, which
    # would have become 1,514 duplicate wiki pages.
    exact: dict[str, str] = {surface_form: surface_form for surface_form in members}
    if kinds:
        # Plus the form the PROMPT showed, accepted back verbatim.
        for surface_form in members:
            exact.setdefault(render_member(surface_form, kinds), surface_form)

    # Normalized match stays, for whitespace and stray case the model
    # introduced -- but ONLY where it is unambiguous. A normalized key two
    # different members share resolves nothing; those must be written exactly,
    # which is what the model does anyway, since it is copying from the prompt.
    buckets: dict[str, set[str]] = {}
    for surface_form in members:
        buckets.setdefault(_normalize(surface_form), set()).add(surface_form)
        if kinds:
            rendered = _normalize(render_member(surface_form, kinds))
            buckets.setdefault(rendered, set()).add(surface_form)
    known = {key: next(iter(group)) for key, group in buckets.items() if len(group) == 1}
    claimed: set[str] = set()
    nodes: list[dict[str, Any]] = []

    def resolve(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        surface_form = exact.get(value) or known.get(_normalize(value))
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


def _decide_batch(
    batch: MergeBatch,
    kinds: dict[str, str | None],
    client: LLMClient,
) -> tuple[MergeBatch, dict[str, Any] | None, str | None]:
    """Decide one cluster batch. Runs on a worker thread (issue #416).

    Returns `(batch, record, failure_reason)`: `record` is the decision
    record to persist, or `None` on a content-shaped failure (`failure_reason`
    then carries the message). `ModelJsonError`/`MergeResponseError` are
    caught here exactly as they were in the pre-concurrency serial loop -- a
    bad cluster simply goes unmerged this run, not recorded as a decision, so
    a later run retries it -- and NOTHING else is caught: a transport-level
    failure (`LLMError`/`httpx.HTTPError`) propagates out of this function,
    surfaces from `future.result()` in the caller, and is fatal exactly as it
    was before this pass ran concurrently.

    This function NEVER writes to disk. Every worker returns its record and
    the single result-collecting thread does the checkpoint append, which is
    what keeps resumability intact under concurrency (`run_merge_names`).

    ONE client is shared by every worker rather than built per batch: it is
    the connection pool, and 19k calls through 19k fresh pools would throw
    away keep-alive on the very workload concurrency is here to speed up.
    `httpx.Client` is thread-safe, and every request-shaping decision this
    pass makes (temperature, reasoning, model) is per-CALL via `pass_name`,
    never per-client state.
    """
    prompt = compose_merge_prompt(batch.members, kinds)
    started = time.monotonic()
    try:
        raw = complete_json(
            client,
            prompt,
            pass_name=RECONCILE_PASS_NAME,
            validate=lambda response: parse_merge_response(response, batch.members, kinds),
        )
        nodes = parse_merge_response(raw, batch.members, kinds)
    except (ModelJsonError, MergeResponseError) as exc:
        return batch, None, str(exc)

    record = {
        "batch_key": batch.key,
        "cluster_label": batch.cluster_label,
        "members": list(batch.members),
        "nodes": nodes,
        "model": client.model_for_pass(RECONCILE_PASS_NAME),
        "decided_at": _utc_now(),
    }
    print(
        f"reconcile: cluster {batch.cluster_label} answered "
        f"({len(batch.members)} member(s)) in {time.monotonic() - started:.1f}s",
        file=sys.stderr,
    )
    return batch, record, None


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


def _locator_source_conflict(surface_a: str, surface_b: str) -> bool:
    """Issue #445: whether `surface_a`/`surface_b` are `axial.names.
    scoped_surface_form`'s own source-scoped instances of a locator-shaped
    surface, from two DIFFERENT sources -- the one pair this fold must
    refuse, however a cluster or the model proposes it. Both members must
    carry the "(source_id)" suffix (`parse_scoped_source`) for this to fire
    at all: a bare, single-source locator (by `build_inventory`'s own
    construction) never conflicts with anything, and two scoped instances
    from the SAME source are a legitimate same-book spelling merge."""
    source_a, source_b = parse_scoped_source(surface_a), parse_scoped_source(surface_b)
    return source_a is not None and source_b is not None and source_a != source_b


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

    Issue #445: two source-scoped instances of the same locator-shaped
    surface (`axial.names.build_inventory`'s own "Table 4.1 (source_id)"
    convention) are never folded together here, however a cluster or the
    model proposes it (`_locator_source_conflict`) -- the whole point of
    scoping their identity by source is undone if this fold re-fuses them.
    A bare (single-source) locator, or two scoped instances from the SAME
    source, are untouched by this check and may still be folded normally.
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
            if alias in counts and not _locator_source_conflict(canonical, alias):
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
    # Issue #446: the same corpus's variants routinely land in different
    # HDBSCAN clusters, so no merge call ever sees them together. This is a
    # second, deterministic candidate-generation step over the SAME
    # inventory, proposing the missing pairs as additional cluster-shaped
    # batches for the exact same, unchanged merge call -- it decides nothing.
    candidate_batches = _candidate_batches(
        entries, {batch.key for batch in batches}, member_char_budget
    )
    batches = batches + candidate_batches
    decisions = load_decisions(decisions_path)
    pending = [batch for batch in batches if batch.key not in decisions]
    reused = len(batches) - len(pending)
    to_attempt = pending if limit is None else pending[:limit]
    print(
        f"reconcile: {len(surface_forms)} surface form(s), {len(batches)} cluster batch(es) "
        f"({len(candidate_batches)} from candidate generation, issue #446) "
        f"at min_cluster_size={min_cluster_size} min_samples={min_samples}; "
        f"{reused} already decided, {len(to_attempt)} to decide now "
        f"({len(pending) - len(to_attempt)} more pending) across {max(workers, 1)} worker(s)",
        file=sys.stderr,
    )

    called = 0
    failed = 0
    model: str | None = None
    if to_attempt:
        # Built once, here, and shared by every worker -- never inside the
        # pool, so a misconfigured provider fails before any thread starts.
        if client is None:
            client = get_client(config_path=config_path)
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as executor:
            futures = {
                executor.submit(_decide_batch, batch, kinds, client): batch for batch in to_attempt
            }
            # Results are collected -- and every checkpoint write happens --
            # on THIS one thread only, in whatever order calls actually
            # finish. That is exactly what makes resumability survive
            # concurrency: a mid-run kill still leaves every already-decided
            # batch durably on disk, one line at a time, never two workers
            # racing to append to the same file.
            for future in as_completed(futures):
                batch = futures[future]
                _batch, record, failure_reason = future.result()
                if record is None:
                    print(
                        f"reconcile: cluster {batch.cluster_label} failed: {failure_reason}",
                        file=sys.stderr,
                    )
                    failed += 1
                    continue

                append_checkpoint_record(decisions_path, record)
                decisions[batch.key] = record
                model = record["model"]
                called += 1
                print(
                    f"reconcile: cluster {batch.cluster_label} recorded "
                    f"({called + failed}/{len(to_attempt)} settled)",
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
        "candidate_batches": len(candidate_batches),
        "decided": called,
        "reused": reused,
        "failed": failed,
        "workers": max(workers, 1),
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
