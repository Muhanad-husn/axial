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
     vectors (`data/names/embeddings.lance`, slice 04) are clustered at the
     tightness `config/pipeline.yaml`'s `names.merge_min_cluster_size` /
     `names.merge_min_samples` name -- the same two HDBSCAN settings `axial
     names examine` sweeps and reports, so the founder moves this dial by
     reading that report (D10's "start loose, tighten by inspection").
     **Issue #458:** when this run's own tightness (and `pca_components`)
     matches what `data/names/similarity_manifest.json` says `axial names
     build` already fit, the persisted `cluster_label` column is reused
     rather than re-fit -- a full-corpus HDBSCAN fit is 10+ minutes, paid
     once by `build`, and paying it again on every `merge` invocation at the
     SAME dial bought nothing. Moving the dial (or passing `--recluster`)
     still costs exactly one fresh fit, and that fit now prints an
     elapsed-time heartbeat to stderr while it runs rather than nothing at
     all -- the silence was the actual bug #458 was filed over.
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

**Issue #463: case, whitespace and punctuation are folded upstream of every
candidate source and of the HDBSCAN blocker, before step 1 above ever runs.**
`fold_groups` (`axial.name_candidates`) groups the whole inventory's surface
forms by a fold that casefolds, collapses whitespace and strips punctuation
(hyphens to a space, everything else to nothing); a group of >= 2 is unioned
straight into the alias map by `build_alias_map_nodes`, exactly like the
`polity_canonical.yaml` seed, and is never proposed to the model -- widening
the candidate net was tried first (issue #446's own family 3, since retired)
and measured a 295-of-~305 refusal rate on exactly these pairs, so the fold
replaces the ask rather than repeating it. Only ONE representative per fold
group reaches clustering and the candidate families (`_candidate_batches`;
issue #498 added a third, the parenthesized-acronym pair, alongside #446's
original two), so a fold-only pair is never split across an HDBSCAN batch, or
proposed by family 1/2/3, alongside a genuinely different name -- the full,
unfiltered inventory is what `build_alias_map_nodes` still runs canonical
election over, so filtering here never drops a surface and never decides
which spelling
wins.

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

A FOURTH file, `merge_failures.jsonl` (issue #469), is the durable trace of
every batch that exhausted `complete_json`'s own re-ask budget without ever
producing a parseable/well-shaped answer -- a CLIENT-side failure, never a
model judgment. It is append-only and never read back by `run_merge_names`
itself: a failed batch stays absent from `merge_decisions.jsonl`, so it is
retried by the next run exactly as before this file existed, and its members
never count toward `escalated_surfaces` or appear in `axial names
escalations` -- that separation already followed from `parse_merge_response`
only ever populating `escalated` on a response it could actually parse and
place (see that function's own docstring); this file just keeps the record
past the run's own stderr.

**Issue #449: the merge call was deciding from a bare surface form and a
kind, which does not contain the answer for `Adam Smith` vs `Anthony D.
Smith`.** `build_evidence_index` joins each surface form to the passages the
inventory already has a `chunk_id` for (no new extraction) and attaches
which source book(s) it appears in -- zero file I/O, because `source_id`
lives inside `chunk_id` itself. Two other cumulative tiers (+ section
titles, + a short passage window) were built alongside this one so the
founder's own measurement run could compare all three against the bare-name
pass; the measurement is in and source provenance is the only one that
survives (issue #453, `data/logs/2026-07-28-merge-evidence-tiers/summary.md`,
DEC-51) -- the other two are deleted, not kept as a permanent dial.
`render_member` is still the ONE place that renders a member, reused by the
parse (see its docstring) -- evidence is folded into that same rendered
form, never a separate echo the model has to get right on its own.

CIP DEC-206, "withhold the scores": whatever similarity numbers a candidate
stage computes are for calibration logs, never for this prompt -- it carries
no numbers today and must not gain any, because showing them anchors the
model to the rule's own answer instead of an independent read.

**Issue #450: the merge call had exactly two outcomes -- folded, or
unplaced -- with no way to say "I cannot tell".** An unplaced member has
always looked identical to a confident refusal, so nothing downstream could
tell a genuine "these are distinct" judgment apart from the model being
forced to guess. The response vocabulary now carries a third outcome,
`"undecided"`, alongside `"nodes"` (`parse_merge_response` returns
`(nodes, escalated)`); every decision record persists its own `escalated`
list, so the rate is measurable and the surfaces are addressable by name off
`merge_decisions.jsonl` without re-asking anything. `build_alias_map_nodes`
needs no change at all: an escalated member never appears in any decision's
`nodes`, so it falls through exactly like a member the response never
mentioned -- D10's asymmetry holds, splitting loses less than fusing, and
`alias_map.json`'s §7.16 shape is untouched. `write_merge_manifest` gained
one summary count (`escalated_surfaces`, corpus-wide, not just this run's)
so the rate reads off the manifest alone.

**Issue #461: the escalated count had no listing.** #456's real corpus run
escalated 5,629 surfaces and nothing downstream read them -- an operator
could see the rate off the manifest but not the shape of what it was a rate
of. `list_escalations` is a read-only join of the decision log to the
inventory: for every escalated surface it returns the co-members it was
proposed with (that decision's own `members`, the rest of the batch) and the
source book(s) it appears in (the inventory's `chunk_ids`, resolved to
`source_id`s). Deliberately no queue, no resolution state, no write path --
just enough to see whether the 5,629 are one problem or five, which is also
the evidence issue #460 needs.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
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
from axial.name_candidates import fold_groups, generate_candidate_clusters
from axial.names import (
    ClusterFn,
    DEFAULT_EMBEDDINGS_DIR,
    DEFAULT_INVENTORY_PATH,
    DEFAULT_MANIFEST_PATH as DEFAULT_SIMILARITY_MANIFEST_PATH,
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_MIN_SAMPLES,
    DEFAULT_NAMES_DATA_DIR,
    DEFAULT_PCA_COMPONENTS,
    NOISE_LABEL,
    _cluster_reduced,
    _load_name_rows,
    _reduce_vectors,
    is_apparatus_pointer_shaped,
    is_numeral_only_surface,
    parse_scoped_source,
)
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH
from axial.polity_canonical import PolityCanonicalError, _normalize, load_polity_canonical
from axial.query.reader import MalformedChunkIdError, source_id_from_chunk_id

# §6's `data/names/` family: the inventory and the similarity view are slice
# 04's; these two are Reconcile's own output, plus the decision log that makes
# a sampled pass reproducible.
DEFAULT_ALIAS_MAP_PATH = DEFAULT_NAMES_DATA_DIR / "alias_map.json"
DEFAULT_INDEX_PATH = DEFAULT_NAMES_DATA_DIR / "index.json"
DEFAULT_DECISIONS_PATH = DEFAULT_NAMES_DATA_DIR / "merge_decisions.jsonl"
DEFAULT_MERGE_MANIFEST_PATH = DEFAULT_NAMES_DATA_DIR / "merge_manifest.json"
# Issue #469: a batch `complete_json` never got a parseable/well-shaped
# answer for, across its whole re-ask budget, is a CLIENT-side failure, not
# a model judgment -- it is never written to `DEFAULT_DECISIONS_PATH` (so it
# stays "pending" and is retried by the next run, exactly as before this
# file existed) and its members never count toward `escalated_surfaces` or
# appear in `list_escalations` (that guarantee already followed from
# `parse_merge_response` only ever populating `escalated` on a SUCCESSFUL
# parse -- see its own docstring). What was missing was durability: the only
# trace of a failed batch used to be one stderr line, gone once the run
# ends, so nobody could tell WHICH surface forms a corpus-wide run silently
# gave up on. This is that record -- append-only, never read back by
# `run_merge_names` itself, so it can never affect resume/completeness.
DEFAULT_FAILURES_PATH = DEFAULT_NAMES_DATA_DIR / "merge_failures.jsonl"

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

# Issue #449 stamped every decision record with the evidence tier it was
# rendered at, while three tiers were under measurement (issue #453,
# DEC-51). Source provenance is the only one that survived the measurement,
# so this is now a fixed value rather than a selectable dial -- kept as a
# named constant, not a bare literal, because `_stale_evidence_tier_reasks`
# still has to tell a stamped record apart from a pre-#449 one that has no
# `evidence_tier` field at all.
EVIDENCE_TIER = 1

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
that names something of its own stands on its own, with no aliases. Where \
what is shown does not let you tell, say so instead of guessing.

SURFACE FORMS
{members}

RESPONSE. Reply with ONLY a JSON object, no prose and no markdown fences:
{{"nodes": [{{"canonical": "<surface form>", "aliases": ["<surface form>", ...]}}, ...], \
"undecided": ["<surface form>", ...]}}
Write every surface form exactly as it appears above, and use each one exactly \
once across "nodes" and "undecided" together: a form you cannot judge goes in \
"undecided" rather than into a node of its own.
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


class MergeReaskConfirmationRequiredError(MergeNamesError):
    """Raised BEFORE any model call this run would make, when re-deciding
    would silently re-ask clusters this exact corpus already has an answer
    for -- just recorded before evidence was attached at all, under a
    DIFFERENT `evidence_tier` (issue #449's rollout: `MergeBatch.key` folds
    in evidence on purpose, trap 3, so those old decisions look like
    brand-new clusters to a plain key lookup). A real spend, so it needs an
    explicit `--confirm-reask` (`confirm_reask=True`), not a default."""

    def __init__(self, batch_count: int, decision_count: int):
        self.batch_count = batch_count
        self.decision_count = decision_count
        super().__init__(
            f"{batch_count} cluster batch(es) were already decided under a different "
            f"evidence_tier ({decision_count} recorded decision(s) would be superseded and "
            "purged) -- re-run with --confirm-reask (confirm_reask=True) to purge them and "
            "let the model decide them again with evidence attached; this is a real spend, "
            "not a free format change"
        )


# ---------------------------------------------------------------------------
# The tightness dial (D10: chosen by looking at slice 04's report)
# ---------------------------------------------------------------------------

# Issue #458: HDBSCAN's own `fit_predict` has no progress callback, and a
# full-corpus fit is 10+ minutes. Printing nothing until it returns is what
# actually cost an abandoned experiment -- a timing probe killed at a 600s
# tool ceiling with zero bytes of output, having never reached its first
# call. Elapsed time is the only "how far along" signal available without
# hacking hdbscan's internals, so the fit runs on a worker thread while this
# one prints a heartbeat, mirroring `axial.llm.OpenRouterClient.complete`'s
# own watchdog-thread pattern (a call already this codebase's way of getting
# liveness out of a blocking operation).
DEFAULT_CLUSTER_HEARTBEAT_SECONDS = 30.0


def _read_similarity_manifest(path: Path) -> dict[str, Any] | None:
    """`data/names/similarity_manifest.json`'s own JSON (issue #458), or
    `None` when it does not exist or is not valid JSON -- either way this
    run cannot tell whether its own settings match a persisted fit, so it
    always re-clusters rather than trusting a labeling it cannot verify."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _manifest_matches_request(
    manifest: dict[str, Any] | None,
    min_cluster_size: int,
    min_samples: int,
    pca_components: int,
) -> bool:
    """Whether `axial names build`'s own persisted clustering (`manifest`'s
    `config` block, `axial.names.run_names`) was fit at exactly this run's
    tightness -- the only case where its `cluster_label` column is the same
    answer a fresh HDBSCAN fit at these settings would give."""
    if not manifest:
        return False
    config = manifest.get("config")
    if not isinstance(config, dict):
        return False
    return (
        config.get("min_cluster_size") == min_cluster_size
        and config.get("min_samples") == min_samples
        and config.get("pca_components") == pca_components
    )


def _cluster_with_heartbeat(
    reduced: Any,
    min_cluster_size: int,
    min_samples: int,
    heartbeat_seconds: float,
) -> list[int]:
    """Run `_cluster_reduced` on a worker thread, printing an elapsed-time
    heartbeat to stderr every `heartbeat_seconds` while it runs (issue
    #458). `_cluster_reduced` itself is untouched -- this only wraps the
    call so the fit's own thread can block while this one reports liveness,
    then re-raises any exception on the caller's thread exactly as a direct
    call would."""
    outcome: dict[str, Any] = {}
    done = threading.Event()

    def _run() -> None:
        try:
            outcome["labels"] = _cluster_reduced(reduced, min_cluster_size, min_samples)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread below
            outcome["error"] = exc
        finally:
            done.set()

    started = time.monotonic()
    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    while not done.wait(timeout=heartbeat_seconds):
        print(
            f"reconcile: clustering still running ({time.monotonic() - started:.0f}s elapsed)...",
            file=sys.stderr,
        )
    worker.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["labels"]


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
# Evidence (issue #449): what the join over chunk_ids already has, joined to
# each surface form ONCE, before any batch is built or any worker starts.
# ---------------------------------------------------------------------------


def build_evidence_index(
    chunk_ids_by_surface: dict[str, tuple[str, ...]],
) -> dict[str, str]:
    """One rendered evidence suffix per surface form: which source book(s)
    it appears in, built ONCE here -- before `run_merge_names` builds a
    single batch or starts the worker pool.

    Zero file I/O: `source_id` lives inside `chunk_id` itself
    (`source_id_from_chunk_id`). Issue #453 deleted the two costlier,
    cumulative tiers (+ section titles, + a passage window) that #449 built
    for measurement -- the founder's own comparison run against the
    bare-name pass showed source provenance was the only one that helped
    (`data/logs/2026-07-28-merge-evidence-tiers/summary.md`, DEC-51).

    A surface form with no chunk_ids, or none that resolve to a real
    `chunk_id`, gets no entry here -- `render_member` treats a missing key
    exactly as "no evidence", the pre-#449 behaviour.
    """
    index: dict[str, str] = {}
    for surface_form, chunk_ids in chunk_ids_by_surface.items():
        sources: list[str] = []
        for chunk_id in chunk_ids:
            try:
                source_id = source_id_from_chunk_id(chunk_id)
            except MalformedChunkIdError:
                continue
            if source_id not in sources:
                sources.append(source_id)
        if not sources:
            continue
        index[surface_form] = f"(in {', '.join(sorted(sources))})"
    return index


# ---------------------------------------------------------------------------
# The call: a loose prompt, and a parse that never invents a name
# ---------------------------------------------------------------------------


def render_member(
    surface_form: str,
    kinds: dict[str, str | None],
    evidence: dict[str, str] | None = None,
) -> str:
    """How ONE surface form appears in the prompt.

    Shared with `parse_merge_response` so the two can never drift. The prompt
    tells the model to write each surface "exactly as it appears above", and
    this function is what "above" means -- so the parse has to accept this
    form back (issue #416, the 2.89% failure below).

    `evidence` (issue #449), when given, appends that surface form's
    evidence suffix (`build_evidence_index`) to the SAME rendered line, so
    the round-trip stays a one-renderer contract: whatever this function
    puts in front of the model is also what the parse must accept back.
    """
    kind = kinds.get(surface_form)
    rendered = f"{surface_form!r} ({kind})" if kind else f"{surface_form!r}"
    suffix = evidence.get(surface_form) if evidence else None
    return f"{rendered} {suffix}" if suffix else rendered


def compose_merge_prompt(
    members: Iterable[str],
    kinds: dict[str, str | None],
    evidence: dict[str, str] | None = None,
) -> str:
    """One batch's prompt: the surface forms with the kind the corpus gave
    each and, where available, the evidence #449 joins in (which source
    book(s), section(s), and/or a short passage window it was seen in) --
    and the judgment being asked for. Nothing else -- no criteria, no
    examples, no instruction to think (see the module docstring)."""
    rendered = "\n".join(f"- {render_member(m, kinds, evidence)}" for m in members)
    return _PROMPT_TEMPLATE.format(members=rendered)


# ---------------------------------------------------------------------------
# Batching (one call per cluster; a few only when the request would be huge)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeBatch:
    """One model call's worth of a cluster's members."""

    cluster_label: int
    members: tuple[str, ...]
    # What `render_member` produced for each member at batch-build time --
    # this, not the bare member list, is what the key and the char budget
    # are computed from (issue #449): a kind or evidence change is a
    # different prompt, so it must be a different decision.
    rendered: tuple[str, ...]

    @property
    def key(self) -> str:
        """Content hash of this batch's RENDERED member list -- the decision
        log's key. Content-addressed on purpose: moving the tightness dial
        changes which surfaces sit together, so a batch whose rendered
        members are unchanged reuses its recorded decision, and one whose
        membership OR whose kind/evidence changed is re-decided, without
        anyone tracking which setting produced what."""
        payload = json.dumps(list(self.rendered), ensure_ascii=False, sort_keys=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _split_into_batches(
    label: int,
    members: list[str],
    kinds: dict[str, str | None],
    evidence: dict[str, str] | None,
    member_char_budget: int,
) -> list[MergeBatch]:
    """One cluster's members, split into as few batches as fit under
    `member_char_budget` -- shared by `build_batches` (real HDBSCAN clusters)
    and `_candidate_batches` (issue #446's proposed clusters), so both go
    through the exact same construction limit on request size.

    The budget counts each member's RENDERED length (issue #449), not the
    bare surface form: with evidence attached the rendered line can run
    ~10x longer than the surface form alone, and counting the bare form
    would silently stop bounding the actual request."""
    batches: list[MergeBatch] = []
    current: list[str] = []
    current_rendered: list[str] = []
    size = 0
    for surface_form in members:
        rendered = render_member(surface_form, kinds, evidence)
        cost = len(rendered) + 1
        if current and size + cost > member_char_budget:
            batches.append(MergeBatch(label, tuple(current), tuple(current_rendered)))
            current, current_rendered, size = [], [], 0
        current.append(surface_form)
        current_rendered.append(rendered)
        size += cost
    if len(current) > 1:
        batches.append(MergeBatch(label, tuple(current), tuple(current_rendered)))
    return batches


def build_batches(
    labels: Iterable[int],
    surface_forms: list[str],
    kinds: dict[str, str | None] | None = None,
    evidence: dict[str, str] | None = None,
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

    kinds = kinds or {}
    batches: list[MergeBatch] = []
    for label in sorted(clusters):
        members = clusters[label]
        if len(members) < 2:
            continue
        batches.extend(_split_into_batches(label, members, kinds, evidence, member_char_budget))
    return batches


def _candidate_batches(
    entries: list[tuple[str, str | None, int]],
    kinds: dict[str, str | None],
    evidence: dict[str, str] | None,
    existing_keys: set[str],
    member_char_budget: int,
) -> list[MergeBatch]:
    """Issue #446: propose the pairs slice 04's own clustering never put in
    front of the merge model, as additional cluster-shaped batches.

    `existing_keys` is every batch key `build_batches` already produced from
    the real HDBSCAN clusters this run -- content-hashed on the RENDERED
    member list (`MergeBatch.key`), so a candidate whose exact rendered
    member set a real cluster ALREADY covers this run is skipped rather than
    asked twice, and (via `merge_decisions.jsonl`, keyed the same way) a
    candidate already decided on a previous run is reused untouched rather
    than re-decided."""
    batches: list[MergeBatch] = []
    for offset, members in enumerate(generate_candidate_clusters(entries)):
        label = _CANDIDATE_LABEL_BASE - offset
        for batch in _split_into_batches(label, list(members), kinds, evidence, member_char_budget):
            if batch.key in existing_keys:
                continue
            existing_keys.add(batch.key)
            batches.append(batch)
    return batches


def parse_merge_response(
    raw: str,
    members: Iterable[str],
    kinds: dict[str, str | None] | None = None,
    evidence: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse one merge response into `(nodes, escalated)`, both restricted to
    `members`: `nodes` is `[{canonical, aliases[]}]`, exactly as before, and
    `escalated` (issue #450) is the batch's own surface forms the response
    could not judge -- a third outcome, distinct from "unplaced".

    `kinds`/`evidence`, when given, also accept each surface back in the
    exact form the PROMPT showed it (`render_member`) -- i.e. `'Sociology'
    (institution/group)`, or with issue #449's evidence suffix attached, as
    well as bare `Sociology`. This is not fuzzy matching: it is the one other
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
    placed twice keeps its first placement, so `nodes` is always a partition
    and a member already placed in `nodes` wins over the same surface form
    also appearing in `undecided` -- the response's own node placement is a
    real judgment and takes priority over its abstention. A member the
    response never placed anywhere -- not in a node, not in `undecided` -- is
    simply absent from both lists and survives downstream exactly as it
    always has: unplaced, standing on its own (issue #450's constraint: a
    member the response never mentions must behave exactly as it does today,
    since escalation is a thing the model says, not a default).

    Raises `MergeResponseError` on a shape failure -- no `nodes` list, or a
    response that placed none of this batch's members in EITHER `nodes` or
    `undecided` -- which is response noise rather than a judgment, and so is
    re-asked by `complete_json`. A response that escalates every member of
    the batch, placing nothing in `nodes`, is a real judgment, not noise, and
    does not raise.
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
    if kinds or evidence:
        # Plus the form the PROMPT showed, accepted back verbatim.
        for surface_form in members:
            exact.setdefault(render_member(surface_form, kinds or {}, evidence), surface_form)

    # Normalized match stays, for whitespace and stray case the model
    # introduced -- but ONLY where it is unambiguous. A normalized key two
    # different members share resolves nothing; those must be written exactly,
    # which is what the model does anyway, since it is copying from the prompt.
    buckets: dict[str, set[str]] = {}
    for surface_form in members:
        buckets.setdefault(_normalize(surface_form), set()).add(surface_form)
        if kinds or evidence:
            rendered = _normalize(render_member(surface_form, kinds or {}, evidence))
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

    raw_undecided = data.get("undecided")
    escalated = sorted(
        {
            resolved
            for resolved in (
                resolve(value)
                for value in (raw_undecided if isinstance(raw_undecided, list) else [])
            )
            if resolved is not None
        }
    )

    if not nodes and not escalated:
        raise MergeResponseError(
            "merge response placed none of the batch's surface forms; expected each "
            "one to appear exactly once across 'nodes' and 'undecided' together; "
            f"{_response_diagnostic(raw)}"
        )
    return nodes, escalated


# Issue #469: the number of leading/trailing characters kept when a merge
# response fails validation -- enough to tell "truncated mid-token" (a
# ragged cutoff, no closing brace) apart from "well-formed JSON that just
# names the wrong batch" (a clean tail) without carrying the whole body, in
# the same spirit as `model_json._snippet`'s own bound. Named here rather
# than reused from `model_json` because that module's own `_snippet` is a
# PREFIX only (issue #72's original diagnosability need); this is deliberately
# both ends, per issue #469's own ask ("length and first/last 200 chars").
_DIAGNOSTIC_EDGE_CHARS = 200


def _response_diagnostic(raw: str) -> str:
    """`length=<n> head=<repr> tail=<repr>` for a response that parsed as
    valid JSON but matched none of the batch (issue #469) -- the cheapest
    discriminator between a client-side truncation (a ragged, incomplete
    tail) and a well-formed answer to the wrong prompt (a clean tail that
    simply names different surface forms), without a real corpus run's raw
    traffic to compare against."""
    if len(raw) <= 2 * _DIAGNOSTIC_EDGE_CHARS:
        return f"length={len(raw)} raw={raw!r}"
    return f"length={len(raw)} head={raw[:_DIAGNOSTIC_EDGE_CHARS]!r} tail={raw[-_DIAGNOSTIC_EDGE_CHARS:]!r}"


def _decide_batch(
    batch: MergeBatch,
    kinds: dict[str, str | None],
    client: LLMClient,
    evidence: dict[str, str] | None = None,
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
    prompt = compose_merge_prompt(batch.members, kinds, evidence)
    started = time.monotonic()
    try:
        raw = complete_json(
            client,
            prompt,
            pass_name=RECONCILE_PASS_NAME,
            validate=lambda response: parse_merge_response(
                response, batch.members, kinds, evidence
            ),
        )
        nodes, escalated = parse_merge_response(raw, batch.members, kinds, evidence)
    except (ModelJsonError, MergeResponseError) as exc:
        return batch, None, str(exc)

    record = {
        "batch_key": batch.key,
        "cluster_label": batch.cluster_label,
        "members": list(batch.members),
        "nodes": nodes,
        # Issue #450: the third outcome -- members the response could not
        # judge, distinct from a member it never mentioned at all. Kept as
        # its own field so the escalation rate is measurable and the
        # escalated surfaces are addressable by name straight off the
        # decision log, without re-deriving them from `nodes`' own absence.
        "escalated": escalated,
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
    folded_groups: Iterable[tuple[str, ...]] = (),
) -> list[dict[str, Any]]:
    """Fold every model decision, every seed folding and every fold group
    over the WHOLE inventory and elect one canonical per resulting group.

    `entries` is `(surface_form, kind, count)` for every inventory entry, so
    a surface no decision, no seed and no fold touched still comes out as
    its own node with no aliases (§7.16). The canonical is elected in this
    order: the seed's own spelling when the corpus contains it (it is the
    curated one), then the canonical the model chose, then the most-mentioned
    surface form -- ties broken lexicographically throughout, so the map is a
    pure function of its inputs. `folded_groups` never enters that election:
    it only says which surfaces are the same entity, never which spelling
    wins (issue #463 -- the fold is for candidate generation, not identity).

    Issue #445: two source-scoped instances of the same locator-shaped
    surface (`axial.names.build_inventory`'s own "Table 4.1 (source_id)"
    convention) are never folded together here, however a cluster, the model
    or a fold group proposes it (`_locator_source_conflict`) -- the whole
    point of scoping their identity by source is undone if this fold
    re-fuses them. A bare (single-source) locator, or two scoped instances
    from the SAME source, are untouched by this check and may still be
    folded normally.

    `folded_groups` (issue #463): surface forms identical once case,
    whitespace and punctuation are folded (`axial.name_candidates.
    fold_groups`), computed and unioned here -- BEFORE any candidate source
    or the HDBSCAN blocker ever sees them, so a pure fold group is never in
    `decision_nodes` at all; it was never proposed as a batch in the first
    place, exactly like the `polity_canonical.yaml` seed.
    """
    counts = {surface_form: count for surface_form, _kind, count in entries}
    kinds = {surface_form: kind for surface_form, kind, _count in entries}

    union = _Union()
    for surface_form, _kind, _count in entries:
        union.add(surface_form)

    for group in folded_groups:
        members = [member for member in group if member in counts]
        if not members:
            continue
        base = members[0]
        for member in members[1:]:
            if not _locator_source_conflict(base, member):
                union.union(base, member)

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
    stale_evidence_tier_reasked: int = 0,
    escalated_surfaces: int = 0,
) -> None:
    """The one place a partial run says so on disk (issue #416, founder
    correction). `alias_map.json`/`index.json` are rewritten whole from
    whatever decisions exist so far, on purpose -- that is what makes the
    pass resumable -- but it also means a map built from 30 of 19,434
    clusters is, by its own `{version, generated_at, nodes}` shape,
    indistinguishable from a finished one. Mirrors slice 04's own sibling
    `similarity_manifest.json` convention under `data/names/`: a reader must
    check `complete` here before treating the map as the whole corpus's
    answer, not just count its own nodes.

    `stale_evidence_tier_reasked` (issue #449's rollout) is how many of
    THIS run's decided batches were already answered once, at a different
    evidence_tier, before this run purged and re-asked them -- the on-disk
    record of the invalidated count, alongside the confirmation gate that
    already made the operator see it before the spend.

    `escalated_surfaces` (issue #450) is the total count of surface forms
    marked "cannot tell" across EVERY decision currently in the log -- not
    just the ones this run decided -- so the escalation rate is readable
    off the manifest alone, without re-parsing the whole of
    `merge_decisions.jsonl` to sum it. The escalated surfaces themselves are
    addressable by name only in the decision log, which is the one copy;
    this is a count, not a list."""
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
                "stale_evidence_tier_reasked": stale_evidence_tier_reasked,
                "escalated_surfaces": escalated_surfaces,
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


def purge_decisions(path: Path, batch_keys: set[str]) -> int:
    """Remove exactly these `batch_key`s from the decision log, rewriting it
    whole -- the targeted counterpart to `load_decisions`/`append_checkpoint_
    record`, so a specific set of already-recorded merge decisions can be
    forced back to "not yet decided" without touching any other line.

    Issue #449's rollout: #441's own repair purged 2,032 damaged clusters
    from `merge_decisions.jsonl` by hand before re-running; this is that
    same move made into a reusable primitive rather than a second one-off
    script the next repair has to reinvent. Returns how many lines were
    actually removed; a no-op (0) when `path` doesn't exist yet or none of
    `batch_keys` are present."""
    if not path.is_file():
        return 0
    records = load_checkpoint_records(path, MergeDecisionsCorruptError)
    kept = [record for record in records if record["batch_key"] not in batch_keys]
    removed = len(records) - len(kept)
    if removed:
        with path.open("w", encoding="utf-8") as handle:
            for record in kept:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return removed


def _stale_evidence_tier_reasks(
    candidates: list[MergeBatch],
    decisions: dict[str, dict[str, Any]],
) -> tuple[list[MergeBatch], set[str]]:
    """Which of `candidates` are pending only because they were decided
    before evidence was attached at all -- not because the cluster is
    genuinely new.

    `MergeBatch.key` folds in evidence (trap 3), so a batch already decided
    without it gets a different key and looks, to a plain key lookup,
    exactly like a brand-new cluster. Detected instead by bare membership:
    every decision record already carries its own `members` (the bare
    surface forms, unaffected by evidence), so a candidate batch whose bare
    member set matches an existing record stamped with a DIFFERENT
    `evidence_tier` (missing entirely on any pre-#449 record, read as tier
    0) is exactly that -- already answered once, just not with evidence.

    `candidates` MUST already be `limit`-bounded (`run_merge_names` passes
    its own `to_attempt`, never the full `pending`): the return value drives
    BOTH the confirmation count AND what `purge_decisions` deletes, so
    checking the unbounded set would purge every stale decision in the
    corpus -- including the ones this run has no intention of re-asking --
    while a `--limit` run only ever re-asks a handful. The log is the only
    copy; a `--limit` run must leave every decision it did not re-ask
    untouched on disk.

    Returns `(stale_batches, stale_record_keys)`: the candidate batches this
    applies to, and the OLD records' own `batch_key`s (candidates for
    `purge_decisions`) -- two different key spaces, since the old and new
    keys for the same cluster never collide."""
    records_by_members: dict[frozenset[str], list[dict[str, Any]]] = {}
    for record in decisions.values():
        records_by_members.setdefault(frozenset(record["members"]), []).append(record)

    stale_batches: list[MergeBatch] = []
    stale_keys: set[str] = set()
    for batch in candidates:
        matches = [
            record
            for record in records_by_members.get(frozenset(batch.members), [])
            if record.get("evidence_tier", 0) != EVIDENCE_TIER
        ]
        if matches:
            stale_batches.append(batch)
            stale_keys.update(record["batch_key"] for record in matches)
    return stale_batches, stale_keys


# ---------------------------------------------------------------------------
# Issue #461: a read-only listing over the decision log -- no queue, no
# resolution state, no write path.
# ---------------------------------------------------------------------------


def _load_inventory_lookup(path: Path) -> dict[str, tuple[str | None, tuple[str, ...]]]:
    """`{surface_form: (kind, chunk_ids)}` off the persisted inventory
    (§7.16's `{surface, kind, count, chunk_ids[]}` shape). A decision record
    carries no kind and no structured chunk_ids for its own escalated
    members -- evidence rides inside the rendered prompt line, not as a
    separate field -- so this is the escalations listing's one read of the
    inventory. A missing file yields an empty lookup, same as a fresh corpus
    with no inventory built yet: this listing never raises."""
    lookup: dict[str, tuple[str | None, tuple[str, ...]]] = {}
    if not path.is_file():
        return lookup
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            lookup[row["surface"]] = (row.get("kind"), tuple(row.get("chunk_ids", [])))
    return lookup


@dataclass(frozen=True)
class EscalationEntry:
    """One escalated surface form, from one decision record (issue #461).
    `co_members` is that decision's own batch membership minus the surface
    itself; `source_ids` is which source book(s) the surface's own
    occurrences (the inventory's `chunk_ids`) resolve to. The same surface
    form escalated in two different batches -- a real HDBSCAN cluster and
    issue #446's candidate generation both proposing it, say -- yields two
    entries, since the co-members differ and that difference is exactly
    what the operator is judging."""

    surface_form: str
    kind: str | None
    cluster_label: int
    co_members: tuple[str, ...]
    source_ids: tuple[str, ...]


def list_escalations(
    decisions_path: Path = DEFAULT_DECISIONS_PATH,
    inventory_path: Path = DEFAULT_INVENTORY_PATH,
) -> list[EscalationEntry]:
    """Every escalated surface form recorded in `decisions_path`, joined to
    the co-members it was proposed with and the source book(s) it appears
    in -- issue #461's minimum useful listing, so the operator can see the
    *shape* of the escalated set (one problem or five) without a resolution
    UI, a queue, or any write path. Deterministic: sorted by surface form,
    then cluster label."""
    decisions = load_decisions(decisions_path)
    inventory = _load_inventory_lookup(inventory_path)

    entries: list[EscalationEntry] = []
    for record in decisions.values():
        escalated = record.get("escalated") or []
        if not escalated:
            continue
        members = record.get("members", [])
        for surface_form in escalated:
            kind, chunk_ids = inventory.get(surface_form, (None, ()))
            source_ids: list[str] = []
            for chunk_id in chunk_ids:
                try:
                    source_id = source_id_from_chunk_id(chunk_id)
                except MalformedChunkIdError:
                    continue
                if source_id not in source_ids:
                    source_ids.append(source_id)
            entries.append(
                EscalationEntry(
                    surface_form=surface_form,
                    kind=kind,
                    cluster_label=record["cluster_label"],
                    co_members=tuple(member for member in members if member != surface_form),
                    source_ids=tuple(sorted(source_ids)),
                )
            )
    entries.sort(key=lambda entry: (entry.surface_form, entry.cluster_label))
    return entries


def escalations_to_json(entries: list[EscalationEntry]) -> list[dict[str, Any]]:
    """The machine-readable form of `list_escalations`' own output -- the
    same data `format_escalations_report` renders as text, so a caller that
    wants to filter or re-ask programmatically (issue #460's "re-ask exactly
    these" option) never has to re-parse the human report."""
    return [
        {
            "surface": entry.surface_form,
            "kind": entry.kind,
            "cluster_label": entry.cluster_label,
            "co_members": list(entry.co_members),
            "source_ids": list(entry.source_ids),
        }
        for entry in entries
    ]


def format_escalations_report(entries: list[EscalationEntry]) -> str:
    """Human-readable rendering of `list_escalations`' output: a per-kind
    count (falls out of the same data at no extra cost -- the cheapest
    answer to "one problem or five") followed by one line per escalated
    surface with its co-members and source book(s)."""
    lines: list[str] = [f"names escalations: {len(entries)} escalated surface occurrence(s)"]

    distinct = len({entry.surface_form for entry in entries})
    if distinct != len(entries):
        lines.append(
            f"  ({distinct} distinct surface form(s) -- some escalated in more than one batch)"
        )

    by_kind: dict[str, int] = {}
    for entry in entries:
        key = entry.kind or "(no kind)"
        by_kind[key] = by_kind.get(key, 0) + 1
    lines.append("")
    lines.append("by kind:")
    if not by_kind:
        lines.append("  (none)")
    for kind, count in sorted(by_kind.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"  {kind}: {count}")

    lines.append("")
    lines.append("escalated surfaces:")
    if not entries:
        lines.append("  (none)")
    for entry in entries:
        kind = f" ({entry.kind})" if entry.kind else ""
        co_members = ", ".join(entry.co_members) if entry.co_members else "(none)"
        sources = ", ".join(entry.source_ids) if entry.source_ids else "(none)"
        lines.append(
            f"  {entry.surface_form!r}{kind} -- proposed with: {co_members} -- source(s): {sources}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def run_merge_names(
    embeddings_dir: Path | None = None,
    alias_map_path: Path | None = None,
    index_path: Path | None = None,
    decisions_path: Path | None = None,
    manifest_path: Path | None = None,
    failures_path: Path | None = None,
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
    confirm_reask: bool = False,
    similarity_manifest_path: Path | None = None,
    recluster: bool = False,
    cluster_heartbeat_seconds: float = DEFAULT_CLUSTER_HEARTBEAT_SECONDS,
) -> dict[str, Any]:
    """Merge the name inventory into a reversible alias map and return the
    run summary.

    Every surface form's prompt line carries source provenance (issue #449:
    which book(s) it appears in, joined from the inventory's own `chunk_id`s
    at zero extra file I/O). Two costlier tiers were built alongside this
    one for measurement and are now gone (issue #453, DEC-51): this is
    unconditional, not a dial.

    `confirm_reask` guards a rollout hazard evidence attachment introduces:
    `MergeBatch.key` folds in evidence (trap 3), so a corpus decided before
    evidence existed looks, key-for-key, exactly like an undecided one --
    moving those decisions from "reused" to "re-asked" as a side effect of
    the code change that turned evidence on, not a choice. `run_merge_names`
    detects this by bare membership (`_stale_evidence_tier_reasks`), scoped
    to `to_attempt` (this run's own `limit`-bounded batch list, never the
    full `pending` set), and raises `MergeReaskConfirmationRequiredError`
    naming the count THIS run would actually re-ask -- before building a
    client or submitting a single batch -- unless `confirm_reask` is `True`,
    in which case exactly those superseded decisions are purged
    (`purge_decisions`) and re-asked as part of this run. A `--limit` run
    purges and reports only what it is about to re-ask, never the whole
    stale population: the decision log is the only copy, and a decision
    this run does not touch is left untouched on disk, including whatever a
    later, larger run still needs to read.

    Reads slice 04's persisted similarity view and asks the model about
    pending clusters concurrently -- up to `workers` at once (default
    `DEFAULT_WORKERS`; issue #416, founder correction: this pass is I/O-bound
    and a serial ~19k-call pass costs ~12 hours of wall clock for a few cents
    of spend).

    **Issue #458: the clusters themselves are reused, not re-fit, whenever
    this run's own tightness matches what `axial names build` already
    persisted.** `similarity_manifest_path` (default `data/names/
    similarity_manifest.json`) records the `min_cluster_size`/`min_samples`/
    `pca_components` that produced the `cluster_label` column already
    sitting in `embeddings_dir`; when they match this run's own settings,
    that column is read back directly and no HDBSCAN fit runs at all. A
    mismatch (a moved tightness dial) or `recluster=True` re-fits exactly as
    before -- reducing the vectors once and clustering them once -- and that
    fit prints an elapsed-time heartbeat to stderr every
    `cluster_heartbeat_seconds` while it runs, because a full-corpus fit is
    10+ minutes and printing nothing for that long reads as a hang (the bug
    the founder actually hit). `cluster_fn`, when given, bypasses this
    reuse-or-refit decision entirely (see below). Writes
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

    `failures_path` (issue #469, default `DEFAULT_FAILURES_PATH`) is where a
    batch that exhausted `complete_json`'s own re-ask budget without ever
    producing a parseable/well-shaped answer gets a durable record -- see
    `DEFAULT_FAILURES_PATH`'s own comment for why this is a SEPARATE,
    write-only log rather than a new field on `merge_decisions.jsonl`: a
    failed batch must stay retryable by the next run, exactly as before this
    file existed, so nothing here is ever read back by this function.
    """
    embeddings_dir = Path(embeddings_dir or DEFAULT_EMBEDDINGS_DIR)
    alias_map_path = Path(alias_map_path or DEFAULT_ALIAS_MAP_PATH)
    index_path = Path(index_path or DEFAULT_INDEX_PATH)
    decisions_path = Path(decisions_path or DEFAULT_DECISIONS_PATH)
    failures_path = Path(failures_path or DEFAULT_FAILURES_PATH)
    manifest_path = Path(manifest_path or DEFAULT_MERGE_MANIFEST_PATH)
    similarity_manifest_path = Path(similarity_manifest_path or DEFAULT_SIMILARITY_MANIFEST_PATH)
    if domain_dir is None:
        domain_dir = _default_domain_dir(config_path)

    configured_min_cluster_size, configured_min_samples = _resolve_merge_tightness(config_path)
    if min_cluster_size is None:
        min_cluster_size = configured_min_cluster_size
    if min_samples is None:
        min_samples = configured_min_samples

    rows = _load_name_rows(embeddings_dir)
    full_entries = [(row["surface_form"], row["kind"] or None, int(row["count"])) for row in rows]
    all_surface_forms = [surface_form for surface_form, _kind, _count in full_entries]
    kinds = {surface_form: kind for surface_form, kind, _count in full_entries}

    # Issue #463: fold case, whitespace and punctuation UPSTREAM of every
    # candidate source and the HDBSCAN blocker -- computed over the whole
    # inventory, before anything below builds a cluster or a batch. A group
    # identical under the fold is unioned straight into the alias map
    # (`build_alias_map_nodes`, below), never proposed to the model: widening
    # the candidate net does not work here (the retired family 3 measured a
    # 295-of-~305 refusal rate on exactly these pairs). Only ONE
    # representative per group -- the lexicographically first, an arbitrary
    # but deterministic pick that never influences which spelling is
    # canonical (`_elect_canonical` runs on the full, unfiltered inventory
    # below) -- goes on to clustering and candidate generation, so a
    # fold-only pair is never split into an HDBSCAN batch, or proposed by
    # family 1/2/3, alongside anything else.
    folded_groups = fold_groups(all_surface_forms)
    folded_away: set[str] = set()
    for group in folded_groups:
        _representative, *duplicates = sorted(group)
        folded_away.update(duplicates)

    # Fix (2026-07-29): a bare page number or a plain century
    # (`is_numeral_only_surface`) is locator residue, not a name -- it must
    # never reach a merge call, on its own or as a cluster co-member. Applied
    # here, at the same point the fold above filters `rows`, not by touching
    # `axial names build`'s own persisted inventory/embeddings: the default
    # reuse-persisted-labels path below reads this run's already-computed
    # `cluster_label` column unchanged, so this takes effect on the very next
    # `axial names merge` run with no re-embed and no re-cluster. It still
    # survives in `full_entries` (below), so it keeps its own unmerged
    # canonical node in the alias map -- this only ever removes it from what
    # a merge call is asked about, never from the map itself.
    numeral_gated = {
        surface_form for surface_form in all_surface_forms if is_numeral_only_surface(surface_form)
    }

    # Fix (2026-07-29): a chapter/footnote/endnote/appendix/table/figure
    # POINTER (`is_apparatus_pointer_shaped`) is the same family of residue,
    # gated at this same point for the same reason -- see that predicate's
    # own comment in `axial.names`.
    apparatus_gated = {
        surface_form
        for surface_form in all_surface_forms
        if is_apparatus_pointer_shaped(surface_form)
    }

    rows = [
        row
        for row in rows
        if row["surface_form"] not in folded_away
        and row["surface_form"] not in numeral_gated
        and row["surface_form"] not in apparatus_gated
    ]
    entries = [(row["surface_form"], row["kind"] or None, int(row["count"])) for row in rows]
    surface_forms = [surface_form for surface_form, _kind, _count in entries]

    # Issue #449: the join is already in hand -- each row's own chunk_ids_json
    # -- so no new extraction runs. The whole evidence index is built ONCE,
    # here, before any batch is built or any worker starts (trap 4: a chunk
    # file read is not something to redo per member on a worker thread).
    chunk_ids_by_surface = {
        row["surface_form"]: tuple(json.loads(row["chunk_ids_json"])) for row in rows
    }
    evidence = build_evidence_index(chunk_ids_by_surface)

    vectors = [row["vector"] for row in rows]
    if cluster_fn is not None:
        labels = cluster_fn(vectors)
    else:
        manifest = _read_similarity_manifest(similarity_manifest_path)
        if not recluster and _manifest_matches_request(
            manifest, min_cluster_size, min_samples, pca_components
        ):
            labels = [int(row["cluster_label"]) for row in rows]
            print(
                f"reconcile: reusing persisted cluster labels from {similarity_manifest_path} "
                f"(min_cluster_size={min_cluster_size} min_samples={min_samples} "
                f"pca_components={pca_components} match `axial names build`'s own fit; "
                "pass --recluster to force a fresh HDBSCAN fit)",
                file=sys.stderr,
            )
        else:
            reason = (
                "--recluster was passed"
                if recluster
                else f"no persisted fit at these settings ({similarity_manifest_path})"
            )
            print(
                f"reconcile: clustering {len(vectors)} name vector(s) with HDBSCAN "
                f"(min_cluster_size={min_cluster_size} min_samples={min_samples} "
                f"pca_components={pca_components}; {reason}) -- this can take 10+ minutes "
                "over the full corpus",
                file=sys.stderr,
            )
            started = time.monotonic()
            reduced = _reduce_vectors(vectors, pca_components)
            labels = _cluster_with_heartbeat(
                reduced, min_cluster_size, min_samples, cluster_heartbeat_seconds
            )
            print(
                f"reconcile: clustering finished in {time.monotonic() - started:.1f}s "
                f"({len({label for label in labels if label != NOISE_LABEL})} cluster(s), "
                f"{sum(1 for label in labels if label == NOISE_LABEL)} noise)",
                file=sys.stderr,
            )

    batches = build_batches(labels, surface_forms, kinds, evidence, member_char_budget)
    # Issue #446: the same corpus's variants routinely land in different
    # HDBSCAN clusters, so no merge call ever sees them together. This is a
    # second, deterministic candidate-generation step over the SAME
    # inventory, proposing the missing pairs as additional cluster-shaped
    # batches for the exact same, unchanged merge call -- it decides nothing.
    candidate_batches = _candidate_batches(
        entries, kinds, evidence, {batch.key for batch in batches}, member_char_budget
    )
    batches = batches + candidate_batches
    decisions = load_decisions(decisions_path)
    pending = [batch for batch in batches if batch.key not in decisions]
    reused = len(batches) - len(pending)
    to_attempt = pending if limit is None else pending[:limit]

    # Issue #449's rollout hazard: a batch pending only because it was
    # decided before evidence existed is indistinguishable, BY KEY, from a
    # genuinely new cluster -- so it must be found by bare membership
    # before a single call goes out.
    #
    # Computed over `to_attempt`, NOT all of `pending`: a `--limit`-bounded
    # run must purge (and report) only the stale decisions it is actually
    # about to re-ask. Purging the WHOLE stale population regardless of
    # `limit` would delete every decision behind clusters this run never
    # touches -- the log is the only copy, and those decisions would be gone
    # with no way back, for a spend the operator never made.
    stale_batches, stale_keys = _stale_evidence_tier_reasks(to_attempt, decisions)
    if stale_batches and not confirm_reask:
        raise MergeReaskConfirmationRequiredError(len(stale_batches), len(stale_keys))
    if stale_keys:
        purge_decisions(decisions_path, stale_keys)
        for key in stale_keys:
            decisions.pop(key, None)

    print(
        f"reconcile: {len(all_surface_forms)} surface form(s), "
        f"{len(folded_groups)} case/whitespace/punctuation fold group(s) auto-merged "
        f"(issue #463, no model call), {len(numeral_gated)} numeral-only surface(s) "
        f"and {len(apparatus_gated)} apparatus-pointer surface(s) "
        "gated out of every merge call (never a name), "
        f"{len(batches)} cluster batch(es) "
        f"({len(candidate_batches)} from candidate generation, issue #446) "
        f"at min_cluster_size={min_cluster_size} min_samples={min_samples}; "
        f"{reused} already decided, {len(to_attempt)} to decide now "
        f"({len(pending) - len(to_attempt)} more pending) across {max(workers, 1)} worker(s); "
        f"{len(stale_batches)} of those are a re-ask onto evidence "
        "(purged from the decision log)",
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
                executor.submit(_decide_batch, batch, kinds, client, evidence): batch
                for batch in to_attempt
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
                    # Issue #469: a durable trace of WHICH surface forms this
                    # was, so it survives past this run's own stderr. Never
                    # added to `decisions` -- the batch must stay pending and
                    # be retried by a later run, exactly as before this file
                    # existed.
                    append_checkpoint_record(
                        failures_path,
                        {
                            "batch_key": batch.key,
                            "cluster_label": batch.cluster_label,
                            "members": list(batch.members),
                            "reason": failure_reason,
                            "failed_at": _utc_now(),
                        },
                    )
                    failed += 1
                    continue

                # Persisted so a LATER run can tell this decision apart from
                # a pre-#449, evidence-free one (`_stale_evidence_tier_
                # reasks`) without depending on the key alone.
                record["evidence_tier"] = EVIDENCE_TIER
                append_checkpoint_record(decisions_path, record)
                decisions[batch.key] = record
                model = record["model"]
                called += 1
                print(
                    f"reconcile: cluster {batch.cluster_label} recorded "
                    f"({called + failed}/{len(to_attempt)} settled)",
                    file=sys.stderr,
                )

    seed_groups, seed_note = _seed_groups(all_surface_forms, Path(domain_dir))
    decision_nodes = [node for record in decisions.values() for node in record["nodes"]]
    nodes = build_alias_map_nodes(full_entries, decision_nodes, seed_groups, folded_groups)

    # Issue #450: the escalated count is summed over EVERY decision currently
    # in the log, not just this run's own `to_attempt` -- so the manifest
    # reads the corpus-wide rate without a caller re-parsing
    # `merge_decisions.jsonl` line by line. `build_alias_map_nodes` needs no
    # change: an escalated member never appears in a decision's `nodes`, so
    # it already falls through `entries` as its own standalone canonical,
    # same as any member the response never mentioned (D10's asymmetry).
    escalated_surfaces = sum(len(record.get("escalated", [])) for record in decisions.values())

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
        stale_evidence_tier_reasked=len(stale_batches),
        escalated_surfaces=escalated_surfaces,
    )

    merged = sum(len(node["aliases"]) for node in nodes)
    return {
        "pass": RECONCILE_PASS_NAME,
        "model": model,
        "alias_map_path": str(alias_map_path),
        "index_path": str(index_path),
        "decisions_path": str(decisions_path),
        "manifest_path": str(manifest_path),
        "failures_path": str(failures_path),
        "surface_forms": len(all_surface_forms),
        "fold_groups": len(folded_groups),
        "numeral_gated_surfaces": len(numeral_gated),
        "apparatus_gated_surfaces": len(apparatus_gated),
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
        "evidence_tier": EVIDENCE_TIER,
        "stale_evidence_tier_reasked": len(stale_batches),
        "escalated_surfaces": escalated_surfaces,
        # A cluster is complete when its decision is on disk; a failed or
        # unreached one is not, and a later run picks it up.
        "complete": complete,
    }
