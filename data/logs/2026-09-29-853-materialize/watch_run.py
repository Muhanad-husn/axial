"""Run a command, sampling its process tree's memory and the system's free memory.

Writes one JSON line per sample to mem.jsonl (fsynced), the child's output to
console.log, and a final record with the exit code and peak.
"""

import json
import os
import subprocess
import sys
import time

import psutil

log_dir = os.path.dirname(os.path.abspath(__file__))
cmd = sys.argv[1:]


def write(fh, rec):
    fh.write(json.dumps(rec) + "\n")
    fh.flush()
    os.fsync(fh.fileno())


with open(os.path.join(log_dir, "console.log"), "wb") as out, open(
    os.path.join(log_dir, "mem.jsonl"), "a", encoding="utf-8"
) as mem:
    start = time.time()
    proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT)
    write(mem, {"event": "start", "cmd": cmd, "pid": proc.pid, "t": start})
    peak = 0
    while proc.poll() is None:
        try:
            p = psutil.Process(proc.pid)
            tree = [p] + p.children(recursive=True)
            rss = sum(x.memory_info().rss for x in tree if x.is_running())
            priv = sum(x.memory_info().private for x in tree if x.is_running())
        except psutil.Error:
            rss = priv = 0
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        peak = max(peak, priv)
        write(
            mem,
            {
                "t": round(time.time() - start, 1),
                "tree_rss_mb": rss // 2**20,
                "tree_private_mb": priv // 2**20,
                "sys_avail_mb": vm.available // 2**20,
                "sys_percent": vm.percent,
                "swap_percent": sw.percent,
            },
        )
        time.sleep(2)
    write(
        mem,
        {
            "event": "end",
            "returncode": proc.returncode,
            "elapsed_s": round(time.time() - start, 1),
            "peak_private_mb": peak // 2**20,
        },
    )
