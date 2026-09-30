"""A second generator of relation candidates for the argument map (issue
#858, DEC-75 step 5).

`axial map build` relates positions inside neighbourhoods built by
argument-sentence similarity. This pass proposes pairs from the vocabulary
instead: two positions are a candidate when their notes were filed under the
same `mechanism` category, they share no book, and they were filed under
different `position` categories. The relate call is `axial.argmap.build`'s
own, blind and unchanged; only which positions it is shown together changes.

Three things keep it honest (approach doc section 10):

- **A pair is a proposal.** The model is shown the positions blind and may
  answer that there is no relation, which is the common answer.
- **A shared category is never a relation.** Only a relation the model
  asserts is recorded, in its own words. A relation between two positions
  that were not proposed as a pair is dropped and counted.
- **The default build does not change.** This runs as its own step over an
  existing build (`axial map relate-profile`), writes only
  `profile_relations.jsonl`, `profile_relation_reads.jsonl` and
  `profile_relations.json` beside it, and never touches `relations.jsonl` or
  `map.json`. Each relation carries `generator: "profile"`, so overlap with
  the neighbourhood pass is countable. `axial vocabulary build --column
  relation` reads the profile relations too, which is how they get kinds.

**Bounding the pair count.** On the 2026-09 build 1,721 profiled positions
give about 77,000 candidate pairs, against the 5,707 the neighbourhood pass
shows. Each position is offered its single nearest candidate partner
(argument-sentence cosine, local encoder, no model call), about 1,700 pairs.
Pairs that touch are read in one call, capped at `MAX_NEIGHBOURHOOD`
positions, so a call is the size of a neighbourhood call."""

from __future__ import annotations

import collections
import itertools
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from axial.argmap.ask import _load_map, _load_relations
from axial.argmap.build import (
    MAX_NEIGHBOURHOOD,
    RELATE_PASS_NAME,
    WORKERS,
    Neighbourhood,
    _accumulated_totals,
    _default_encoder,
    _load_json_or_none,
    _neighbourhood_key,
    compute_corpus_pin,
    run_relations,
)
from axial.argmap.vocabulary_join import (
    NoVocabularyError,
    _read_assignment_records,
)
from axial.envelope import _default_envelopes_dir
from axial.llm import LLMClient, configured_reasoning, estimate_cost, get_client
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_map_dir, default_sources_dir
from axial.pidguard import claim_single_instance
from axial.vocabulary import (
    ASSIGNMENTS_FILENAME,
    MANIFEST_FILENAME,
    PROFILE_RELATIONS_FILENAME,
    ROOT_LEVEL,
    VOCABULARY_DIR,
    relation_kind_examples,
)

Encoder = Callable[[Sequence[str]], np.ndarray]

GENERATOR = "profile"
# A relation the model asserts between two positions read in one call but
# never proposed as a pair: kept only when it crosses authors and is new to
# the map, and tagged apart so a reader can weigh it separately (#858).
CONTEXT_GENERATOR = "profile-context"
MECHANISM_COLUMN = "mechanism"
STANCE_COLUMN = "position"

PROFILE_READS_FILENAME = "profile_relation_reads.jsonl"
PROFILE_MANIFEST_FILENAME = "profile_relations.json"


@dataclass(frozen=True)
class Profile:
    """A position's category in each of the two columns the generator reads:
    the one most of its notes were filed under, ties to the lowest id."""

    mechanism: str
    stance: str


def _category_by_chunk(column: str, vocabulary_dir: Path | None) -> dict[str, str]:
    """`chunk_id -> category_id` for `column` at its finest level. A note
    with no assigned record (refused, out of scheme, never answered) is
    absent. Raises `NoVocabularyError` when the column was never built."""
    root = Path(vocabulary_dir) if vocabulary_dir is not None else VOCABULARY_DIR
    column_dir = root / column
    manifest = _load_json_or_none(column_dir / MANIFEST_FILENAME)
    if manifest is None:
        raise NoVocabularyError(column, column_dir)
    level = int(manifest.get("max_level", ROOT_LEVEL))
    by_chunk: dict[str, str] = {}
    for record in _read_assignment_records(column_dir / ASSIGNMENTS_FILENAME):
        category_id = record.get("category_id")
        if int(record.get("level", ROOT_LEVEL)) == level and isinstance(category_id, str):
            by_chunk.setdefault(str(record.get("chunk_id", "")), category_id)
    return by_chunk


def _modal(chunk_ids: Sequence[str], by_chunk: Mapping[str, str]) -> str | None:
    counts = collections.Counter(by_chunk[c] for c in chunk_ids if c in by_chunk)
    if not counts:
        return None
    top = max(counts.values())
    return min(category for category, n in counts.items() if n == top)


def position_profiles(
    positions: Sequence[Mapping[str, Any]],
    mechanism_by_chunk: Mapping[str, str],
    stance_by_chunk: Mapping[str, str],
) -> dict[str, Profile]:
    """A profile for every position with at least one note filed in both
    columns; a position without one is not proposed for any pair."""
    profiles: dict[str, Profile] = {}
    for position in positions:
        chunk_ids = position.get("chunk_ids") or []
        mechanism = _modal(chunk_ids, mechanism_by_chunk)
        stance = _modal(chunk_ids, stance_by_chunk)
        if mechanism is not None and stance is not None:
            profiles[str(position["position_id"])] = Profile(mechanism, stance)
    return profiles


def propose_pairs(
    positions: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Profile],
    encode: Encoder,
) -> tuple[list[tuple[str, str]], int]:
    """`(pairs, candidate_count)`. A candidate is two positions with the same
    mechanism, no book in common and different position categories. Each
    position keeps its single nearest candidate partner; the proposed pairs
    are those kept by either end, each as `(lower_id, higher_id)`."""
    by_id = {str(p["position_id"]): p for p in positions if str(p["position_id"]) in profiles}
    ids = sorted(by_id)
    if len(ids) < 2:
        return [], 0
    vectors = np.asarray(encode([str(by_id[i]["argument"]) for i in ids]), dtype=float)
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    row = {pid: index for index, pid in enumerate(ids)}
    sources = {pid: set(by_id[pid].get("sources") or []) for pid in ids}

    by_mechanism: dict[str, list[str]] = collections.defaultdict(list)
    for pid in ids:
        by_mechanism[profiles[pid].mechanism].append(pid)

    partners: dict[str, list[str]] = collections.defaultdict(list)
    candidates = 0
    for members in by_mechanism.values():
        for a, b in itertools.combinations(members, 2):
            if profiles[a].stance == profiles[b].stance or sources[a] & sources[b]:
                continue
            candidates += 1
            partners[a].append(b)
            partners[b].append(a)

    kept: set[tuple[str, str]] = set()
    for pid, others in partners.items():
        # Ids are sorted, so max() keeps the lowest id on a tie.
        nearest = max(
            sorted(others), key=lambda other: float(vectors[row[pid]] @ vectors[row[other]])
        )
        kept.add((min(pid, nearest), max(pid, nearest)))
    return sorted(kept), candidates


def pack_pairs(pairs: Sequence[tuple[str, str]]) -> list[Neighbourhood]:
    """Pairs that touch are read in one call. A connected set larger than
    `MAX_NEIGHBOURHOOD` is cut into consecutive blocks in breadth-first
    order; a pair split across two blocks is not shown together."""
    adjacency: dict[str, set[str]] = collections.defaultdict(set)
    for a, b in pairs:
        adjacency[a].add(b)
        adjacency[b].add(a)

    seen: set[str] = set()
    groups: list[Neighbourhood] = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        order = [start]
        seen.add(start)
        for node in order:
            for neighbour in sorted(adjacency[node]):
                if neighbour not in seen:
                    seen.add(neighbour)
                    order.append(neighbour)
        for offset in range(0, len(order), MAX_NEIGHBOURHOOD):
            block = tuple(sorted(order[offset : offset + MAX_NEIGHBOURHOOD]))
            if len(block) >= 2:
                groups.append(Neighbourhood(key=_neighbourhood_key(block), position_ids=block))
    groups.sort(key=lambda g: g.key)
    return groups


def _pair(relation: Mapping[str, Any]) -> tuple[str, str]:
    a, b = str(relation["from_position_id"]), str(relation["to_position_id"])
    return (min(a, b), max(a, b))


def run_profile_relations(
    *,
    map_dir: Path | None = None,
    pin: str | None = None,
    vocabulary_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    sources_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    client: LLMClient | None = None,
    encode: Encoder | None = None,
    workers: int = WORKERS,
    guard: bool = True,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """`axial map relate-profile`: propose pairs from the vocabulary profile
    over the map already built at this pin, relate them with the build's own
    blind call, and write `profile_relations.jsonl` and
    `profile_relations.json` beside it. Resumable by group through
    `profile_relation_reads.jsonl`. Raises `MapNotBuiltError` with no map at
    the pin and `NoVocabularyError` when `mechanism` or `position` was never
    built; neither makes a model call."""
    started = time.monotonic()
    if map_dir is None:
        map_dir = default_map_dir(config_path)
    if pin is None:
        pin = compute_corpus_pin(
            envelopes_dir if envelopes_dir is not None else _default_envelopes_dir(config_path),
            sources_dir if sources_dir is not None else default_sources_dir(config_path),
        )
    outdir = Path(map_dir) / pin
    positions, _map_manifest = _load_map(outdir)
    existing_relations = _load_relations(outdir)
    mechanism_by_chunk = _category_by_chunk(MECHANISM_COLUMN, vocabulary_dir)
    stance_by_chunk = _category_by_chunk(STANCE_COLUMN, vocabulary_dir)

    if encode is None:
        encode = _default_encoder()
    profiles = position_profiles(positions, mechanism_by_chunk, stance_by_chunk)
    pairs, candidates = propose_pairs(positions, profiles, encode)
    groups = pack_pairs(pairs)
    grouped = {pid: group for group in groups for pid in group.position_ids}
    pairs_shown = {pair for pair in pairs if grouped.get(pair[0]) is grouped.get(pair[1])}
    log(
        f"profiled positions {len(profiles)} of {len(positions)} | candidate pairs {candidates} | "
        f"proposed {len(pairs)} | read together {len(pairs_shown)} in {len(groups)} call(s)"
    )

    if guard:
        claim_single_instance(outdir)
    try:
        if client is None:
            client = get_client(config_path=config_path)
        by_id = {str(p["position_id"]): p for p in positions}
        reads = run_relations(
            groups,
            by_id,
            client=client,
            reads_path=outdir / PROFILE_READS_FILENAME,
            workers=workers,
            log=log,
            examples=relation_kind_examples(),
        )

        proposed = set(pairs_shown)
        existing_pairs = {_pair(r) for r in existing_relations}
        recorded: list[dict[str, Any]] = []
        context: list[dict[str, Any]] = []
        off_proposal = 0
        for read in reads:
            for relation in read["relations"]:
                source, target = relation["from_position_id"], relation["to_position_id"]
                if _pair(relation) not in proposed:
                    off_proposal += 1
                    if _pair(relation) not in existing_pairs and set(
                        by_id[source]["authors"]
                    ) != set(by_id[target]["authors"]):
                        context.append({**relation, "generator": CONTEXT_GENERATOR})
                    continue
                recorded.append(
                    {
                        **relation,
                        "generator": GENERATOR,
                        "mechanism": profiles[source].mechanism,
                        "positions_category": [profiles[source].stance, profiles[target].stance],
                    }
                )

        with (outdir / PROFILE_RELATIONS_FILENAME).open("w", encoding="utf-8") as handle:
            for relation in recorded + context:
                handle.write(json.dumps(relation, ensure_ascii=False) + "\n")

        failed = [read for read in reads if "error" in read]
        usage = client.usage_for_pass(RELATE_PASS_NAME)
        model = client.model_for_pass(RELATE_PASS_NAME)
        cost = (
            estimate_cost(model, usage["prompt_tokens"], usage["completion_tokens"])
            if usage
            else None
        )
        prior = _load_json_or_none(outdir / PROFILE_MANIFEST_FILENAME)
        manifest = {
            "corpus_pin": pin,
            "generator": GENERATOR,
            "counts": {
                "positions": len(positions),
                "profiled_positions": len(profiles),
                "candidate_pairs": candidates,
                "proposed_pairs": len(pairs),
                "pairs_read_together": len(pairs_shown),
                "groups_read": len(reads),
                "failed_reads": len(failed),
                "relations_asserted": len(recorded),
                "off_proposal_relations": off_proposal,
                "context_relations": len(context),
                "dropped_relations": sum(read.get("dropped", 0) for read in reads),
                "distinct_labels": len({r["relation"] for r in recorded}),
                "cross_author_relations": sum(
                    1
                    for r in recorded
                    if set(by_id[r["from_position_id"]]["authors"])
                    != set(by_id[r["to_position_id"]]["authors"])
                ),
                "neighbourhood_relations": len(existing_relations),
                "overlap_with_neighbourhood_relations": sum(
                    1 for r in recorded if _pair(r) in existing_pairs
                ),
            },
            "model": model,
            "reasoning": configured_reasoning(RELATE_PASS_NAME, config_path),
            **_accumulated_totals(prior, usage, cost, time.monotonic() - started),
        }
        (outdir / PROFILE_MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    finally:
        if guard:
            (outdir / "RUNNING.pid").unlink(missing_ok=True)
    log(f"wrote {outdir / PROFILE_RELATIONS_FILENAME}")
    return manifest
