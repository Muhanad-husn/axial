"""Run a command under a dollar cap, journaling OpenRouter spend and progress.

Every 30s writes one JSON line to spend.jsonl (fsynced): key usage delta since
start, reads written to the variant ledger, and a projected total. Kills the
process tree when the delta reaches CAP_USD. The child's output goes to
console.log. The map build's ledger is resumable, so a capped run can be
continued by relaunching the same command.
"""

import json
import os
import subprocess
import sys
import time
import tomllib
import urllib.request

import psutil

CAP_USD = 5.0
EXPECTED_READS = 45  # (brief, draw) records over three arms, #879
RUNS = "D:/axial-runs/data/runs"
SECRETS = r"D:\axial-runs\secrets\secrets.toml"

log_dir = os.path.dirname(os.path.abspath(__file__))
cmd = sys.argv[1:]
with open(SECRETS, "rb") as fh:
    key = tomllib.load(fh)["openrouter"]["api_key"]


def usage_usd() -> float | None:
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return float(json.load(r)["data"]["usage"])
    except Exception:
        return None


def reads_done() -> int:
    from pathlib import Path
    return sum(1 for _ in Path(RUNS).glob("879-arm-*/analyses/S-*/draw*/*.json"))


def tree_mb(pid) -> int | None:
    try:
        p = psutil.Process(pid)
        return round(sum(q.memory_info().rss for q in [p, *p.children(recursive=True)]) / 2**20)
    except psutil.Error:
        return None


def write(fh, rec):
    fh.write(json.dumps(rec) + "\n")
    fh.flush()
    os.fsync(fh.fileno())


def kill_tree(pid):
    try:
        p = psutil.Process(pid)
        for c in p.children(recursive=True):
            c.kill()
        p.kill()
    except psutil.Error:
        pass


with open(os.path.join(log_dir, "console.log"), "ab") as out, open(
    os.path.join(log_dir, "spend.jsonl"), "a", encoding="utf-8"
) as spend:
    base = usage_usd()
    start = time.time()
    env = {**os.environ, "AXIAL_SECRETS_PATH": SECRETS}
    proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, env=env)
    write(spend, {"event": "start", "cmd": cmd, "pid": proc.pid, "t": start,
                  "usage_at_start": base, "cap_usd": CAP_USD})
    capped = False
    while proc.poll() is None:
        time.sleep(30)
        now = usage_usd()
        delta = None if (now is None or base is None) else round(now - base, 4)
        done = reads_done()
        proj = round(delta * EXPECTED_READS / done, 2) if (delta and done) else None
        write(spend, {"t": round(time.time() - start, 1), "spent_usd": delta,
                      "reads": done, "projected_usd": proj,
                      "tree_mb": tree_mb(proc.pid),
                      "free_mb": round(psutil.virtual_memory().available / 2**20)})
        if delta is not None and delta >= CAP_USD:
            kill_tree(proc.pid)
            capped = True
            break
    proc.wait()
    now = usage_usd()
    write(spend, {"event": "end", "returncode": proc.returncode, "capped": capped,
                  "elapsed_s": round(time.time() - start, 1), "reads": reads_done(),
                  "spent_usd": None if (now is None or base is None) else round(now - base, 4)})
