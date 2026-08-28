import json, sys, time, pathlib
LOG = pathlib.Path("data/logs/2026-08-28-816-map-arm-restore/run.jsonl")
def emit(event, **fields):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event}
    rec.update(fields)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as h:
        h.write(json.dumps(rec, ensure_ascii=False) + "\n")
        h.flush()
        import os; os.fsync(h.fileno())
    print(json.dumps(rec, ensure_ascii=False))
