"""Names in five or more sources, reconciled to Wikidata QIDs (issue #856,
DEC-75 step 3, docs/architecture-review-2026-09-28.md §5).

The usable band of the name index -- a name whose notes span five or more
sources -- gets an identity from outside the corpus. Every surface the merge
put on a band node (its canonical and each alias) is sent to the Wikidata
reconciliation service (the OpenRefine protocol), with the node's `kind` as
the type hint. Only the service's own `match` flag is accepted; anything
else is `None`, never a guess.

Every response is cached in `data/names/wikidata/responses.jsonl`, keyed by
`(query, type)`, so a re-run is offline and a different acceptance rule can
be measured against the same responses for free.

The QIDs double as a check on the LLM merge. A node whose matched surfaces
share one QID agrees with the merge; a node whose surfaces match two QIDs
was merged apart from what Wikidata separates (`merged_apart`); two band
nodes on one QID were kept apart though Wikidata joins them (`kept_apart`).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx

from axial.paths import atomic_write_text, default_names_dir
from axial.query.reader import source_id_from_chunk_id

SERVICE_URL = "https://wikidata.reconci.link/en/api"
BAND_MIN_SOURCES = 5
BATCH_SIZE = 10

# The issue's own mapping, with two measured exceptions. Places: typed
# Q56061 (administrative territorial entity) the service matched `Europe` to
# the European Union; Q2221906 (geographic location) put the right item
# first on every probe. Events: typed Q1190554 (occurrence) the service
# answers 403 to every query, and untyped puts the right item first.
# `concept` and `movement/religion` have no useful single type either.
_TYPE_BY_KIND = {
    "person": "Q5",
    "country/state/place": "Q2221906",
    "work": "Q47461344",
    "institution/group": "Q43229",
    "period": "Q186081",
}

Post = Callable[[dict[str, dict[str, Any]]], dict[str, Any]]


def type_for_kind(kind: str | None) -> str | None:
    return _TYPE_BY_KIND.get(kind or "")


def band_nodes(
    nodes: Iterable[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
    *,
    min_sources: int = BAND_MIN_SOURCES,
) -> list[dict[str, Any]]:
    """The alias-map nodes whose surfaces' notes span `min_sources` or more
    distinct sources."""
    band = []
    for node in nodes:
        sources = {
            source_id_from_chunk_id(chunk_id)
            for surface in (node["canonical"], *node.get("aliases", []))
            for chunk_id in (inventory.get(surface) or {}).get("chunk_ids", [])
        }
        if len(sources) >= min_sources:
            band.append(node)
    return band


def post_to_service(batch: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One HTTP call to the reconciliation service for a batch of queries,
    retried with backoff on a transient failure.

    The backoff is long on purpose: the hosted service throttled the first
    live pass with a 403 after 40 surfaces and then stopped answering for
    minutes. Waiting it out costs nothing, since every answer is cached."""
    for attempt in range(8):
        try:
            response = httpx.post(
                SERVICE_URL,
                data={"queries": json.dumps(batch)},
                timeout=120,
                follow_redirects=True,
                headers={
                    "User-Agent": "axial-reconcile/1.0 (https://github.com/Muhanad-husn/axial)"
                },
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            if attempt == 7:
                raise
            time.sleep(min(30 * 2**attempt, 1200))
    raise AssertionError("unreachable")


def _load_cache(cache_path: Path) -> dict[tuple[str, str | None], list[dict[str, Any]]]:
    cached: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    if cache_path.is_file():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                cached[(record["query"], record["type"])] = record["result"]
    return cached


def reconcile(
    queries: Iterable[tuple[str, str | None]],
    *,
    cache_path: Path,
    post: Post = post_to_service,
    batch_size: int = BATCH_SIZE,
    on_batch: Callable[[int, int], None] | None = None,
) -> dict[tuple[str, str | None], list[dict[str, Any]]]:
    """`(query, type) -> candidates` for every query. A query already in the
    cache is never sent; each answered batch is appended to the cache before
    the next is asked, so an interrupted run resumes where it stopped."""
    wanted = list(dict.fromkeys(queries))
    cached = _load_cache(cache_path)
    missing = [query for query in wanted if query not in cached]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(missing), batch_size):
        chunk = missing[start : start + batch_size]
        batch = {
            f"q{i}": {"query": text, **({"type": type_} if type_ else {})}
            for i, (text, type_) in enumerate(chunk)
        }
        answered = post(batch)
        with cache_path.open("a", encoding="utf-8") as handle:
            for i, (text, type_) in enumerate(chunk):
                result = answered[f"q{i}"]["result"]
                cached[(text, type_)] = result
                handle.write(
                    json.dumps({"query": text, "type": type_, "result": result}, ensure_ascii=False)
                    + "\n"
                )
        if on_batch is not None:
            on_batch(start + len(chunk), len(missing))
    return {query: cached[query] for query in wanted}


def accepted_qid(candidates: list[dict[str, Any]]) -> str | None:
    """The candidate the service itself marked `match`, else `None`."""
    return next((c["id"] for c in candidates if c.get("match")), None)


def resolve_node(node: dict[str, Any], qid_by_surface: dict[str, str | None]) -> dict[str, Any]:
    """A node's QID and its verdict on the merge that built it.

    The canonical's own match wins. An unmatched canonical takes its
    aliases' QID only when every matched alias agrees. `verdict` is
    `agrees` (two or more matched surfaces, one QID), `disagrees` (two or
    more QIDs on one node) or `untested` (fewer than two matched surfaces)."""
    surfaces = (node["canonical"], *node.get("aliases", []))
    surface_qids = {s: qid_by_surface.get(s) for s in surfaces}
    matched = {qid for qid in surface_qids.values() if qid}
    qid = surface_qids[node["canonical"]] or (next(iter(matched)) if len(matched) == 1 else None)
    tested = sum(1 for qid_ in surface_qids.values() if qid_) >= 2
    verdict = "disagrees" if len(matched) > 1 else "agrees" if tested else "untested"
    return {
        "canonical": node["canonical"],
        "kind": node.get("kind"),
        "qid": qid,
        "verdict": verdict,
        "surface_qids": surface_qids,
    }


def measure(resolutions: list[dict[str, Any]]) -> dict[str, Any]:
    band = len(resolutions)
    resolved = sum(1 for r in resolutions if r["qid"])
    tested = [r for r in resolutions if r["verdict"] != "untested"]
    agrees = sum(1 for r in tested if r["verdict"] == "agrees")
    by_qid: dict[str, list[str]] = {}
    for r in resolutions:
        if r["qid"]:
            by_qid.setdefault(r["qid"], []).append(r["canonical"])
    return {
        "band": band,
        "resolved": resolved,
        "resolution_rate": resolved / band if band else None,
        "tested": len(tested),
        "agrees": agrees,
        "agreement_rate": agrees / len(tested) if tested else None,
        "merged_apart": [
            {"canonical": r["canonical"], "surface_qids": r["surface_qids"]}
            for r in resolutions
            if r["verdict"] == "disagrees"
        ],
        "kept_apart": [
            {"qid": qid, "canonicals": sorted(canonicals)}
            for qid, canonicals in sorted(by_qid.items())
            if len(canonicals) > 1
        ],
    }


def write_qids(index_path: Path, qids: dict[str, str | None]) -> None:
    """Add `qids` beside `index.json`'s `names`, leaving the name list (what
    the corpus pin hashes) untouched."""
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    index["qids"] = dict(sorted(qids.items()))
    atomic_write_text(Path(index_path), json.dumps(index, indent=2, ensure_ascii=False) + "\n")


def run_reconcile(
    *,
    names_dir: Path | None = None,
    post: Post = post_to_service,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """The whole pass over `names_dir`: reconcile every surface of every band
    node, write `qids` into `index.json`, and write `wikidata/resolutions.jsonl`
    (one line per band node) and `wikidata/report.json` (the measurement)."""
    names_dir = Path(names_dir) if names_dir is not None else default_names_dir()
    nodes = json.loads((names_dir / "alias_map.json").read_text(encoding="utf-8"))["nodes"]
    inventory = {
        record["surface"]: record
        for record in (
            json.loads(line)
            for line in (names_dir / "inventory.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    band = band_nodes(nodes, inventory)
    queries = [
        (surface, type_for_kind(node.get("kind")))
        for node in band
        for surface in (node["canonical"], *node.get("aliases", []))
    ]
    log(f"band: {len(band)} names, {len(set(queries))} surfaces to reconcile")
    responses = reconcile(
        queries,
        cache_path=names_dir / "wikidata" / "responses.jsonl",
        post=post,
        on_batch=lambda done, total: log(f"asked {done}/{total}"),
    )
    resolutions = []
    for node in band:
        type_ = type_for_kind(node.get("kind"))
        qid_by_surface = {
            surface: accepted_qid(responses[(surface, type_)])
            for surface in (node["canonical"], *node.get("aliases", []))
        }
        resolutions.append(resolve_node(node, qid_by_surface))
    report = measure(resolutions)
    write_qids(names_dir / "index.json", {r["canonical"]: r["qid"] for r in resolutions})
    out_dir = names_dir / "wikidata"
    atomic_write_text(
        out_dir / "resolutions.jsonl",
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in resolutions),
    )
    atomic_write_text(
        out_dir / "report.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    return report


def load_qids(index_path: Path) -> dict[str, str | None]:
    """`index.json`'s `qids`, `{}` when the index has none or does not exist."""
    path = Path(index_path)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("qids") or {}
