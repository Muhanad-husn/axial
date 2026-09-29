"""Two-model agreement on the built about/move columns, measured the way #805's
examine pass measured it: a random 100 of the build's own assignments are
re-assigned by the check model (production_vocabulary_examine_check) against
the committed scheme, in one batch, and the two labels compared.

Overall agreement counts a value both models refused as agreeing; the
where-assigned rate is over the values the build model placed.
Writes agreement.json beside this script.
"""

import json
import os
import random
import sys
from pathlib import Path
from types import SimpleNamespace

from axial.llm import get_client
from axial.vocabulary import (
    CHECK_PASS_NAME,
    DEFAULT_VOCABULARY_SCHEME_PATH,
    _assign_batch,
    load_vocabulary_scheme,
)

HERE = Path(__file__).parent
VOCAB = Path("D:/axial-runs/data/vocabulary")
N = 100
SEED = int(os.environ.get("AGREEMENT_SEED", "857"))

client = get_client()
results = {}
for column in sys.argv[1:] or ["about", "move"]:
    scheme = load_vocabulary_scheme(column, DEFAULT_VOCABULARY_SCHEME_PATH)
    name_by_id = {c.id: c.name for c in scheme.categories}
    names = set(name_by_id.values())
    scheme_text = "\n".join(f"- {c.name}: {c.gloss}" for c in scheme.categories)
    records = [
        json.loads(line)
        for line in (VOCAB / column / "assignments.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    sample = random.Random(SEED).sample(records, N)
    before_cost = client.cost_for_pass(CHECK_PASS_NAME) or 0.0
    check = _assign_batch(
        client, CHECK_PASS_NAME, scheme_text, [SimpleNamespace(value=r["value"]) for r in sample], 0
    )
    agree = assigned = assigned_agree = 0
    for index, record in enumerate(sample, start=1):
        first = "none" if record["refused"] else name_by_id.get(record["category_id"], "none")
        second = check.get(index, "")
        second = second if second in names else "none"
        agree += first == second
        if first != "none":
            assigned += 1
            assigned_agree += first == second
    results[column] = {
        "n": N,
        "seed": SEED,
        "check_model": client.model_for_pass(CHECK_PASS_NAME),
        "agreement_overall": agree / N,
        "agreement_where_assigned": assigned_agree / assigned if assigned else None,
        "agreement_where_assigned_n": assigned,
        "check_cost_usd": (client.cost_for_pass(CHECK_PASS_NAME) or 0.0) - before_cost,
    }
    print(column, json.dumps(results[column]))

(HERE / f"agreement-{SEED}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
