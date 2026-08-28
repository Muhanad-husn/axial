import sys, pathlib, json
sys.path.insert(0, "data/logs/2026-08-28-816-map-arm-restore")
from _journal import emit
from axial.argmap.build import compute_corpus_pin
from axial.eval.corpus_pin import _build_sources

env = pathlib.Path("data/envelopes"); src = pathlib.Path("data/sources")
sources = _build_sources(env, src)
emit("pin_sources_built", count=len(sources))
pin = compute_corpus_pin(env, src)
emit("pin_computed", corpus_pin=pin)

# 1. per-source content hash vs the committed pin every analysis records
committed = json.load(open("evals/corpus_pin/sim-2026-07-30.json", encoding="utf-8"))
committed_by_id = {s["source_id"]: s["content_hash"] for s in committed["sources"]}
live_by_id = {s["source_id"]: s["content_hash"] for s in sources}
b = "beshara-2011-8410a9059300"
emit("beshara_hash_check", recorded=committed_by_id.get(b), live=live_by_id.get(b),
     match=committed_by_id.get(b) == live_by_id.get(b))
overlap = [i for i in committed_by_id if i in live_by_id]
mismatch = [i for i in overlap if committed_by_id[i] != live_by_id[i]]
emit("committed_pin_overlap", committed_sources=len(committed_by_id), live_sources=len(live_by_id),
     overlapping=len(overlap), mismatching=mismatch)

# 2. map-arm pin vs the paid map builds on disk
built = sorted(p.name for p in pathlib.Path("data/map").iterdir() if p.is_dir())
emit("map_pins_on_disk", pins=built, live_pin_has_build=pin in built)
