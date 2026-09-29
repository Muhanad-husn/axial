# 2026-09-29 — #859 extraction on glm-5.3, capped at $4

## Command

```
python watch_run.py  D:\axial-runs\.venv\Scripts\python.exe -m axial.cli map build --extract-model z-ai/glm-5.3
```

Run from `D:/axial-runs`, detached with `Start-Process`. Bags reused from `9b796b3a6312b329/bag_state.json`; output `data/map/9b796b3a6312b329-variant-z-ai-glm-5.3/`. Reasoning unchanged (high, per `config/pipeline.yaml`). `watch_run.py` samples OpenRouter key usage every 30s to `spend.jsonl` and kills the tree at $4.

## Result

- **Capped**, not finished: 287 of 679 extraction reads in 272s, then killed (exit 15). No relations pass yet.
- **Spend:** $4.03 by OpenRouter key usage delta (includes any other use of the key in that window). Price-table estimate from logged tokens: $4.78 (the table runs high, see `llm.py`).
- **Tokens:** 305,237 prompt, 989,926 completion over 287 reads, about 3,450 completion tokens per read, mostly reasoning.
- **Projected full extraction:** about $9.5 (linear in reads; read order is not random, so rough). About $5.5 to finish, plus about $0.40 relations on flash.

## Launch notes

- Launch 1 failed at the key check (no spend): the session env carries `AXIAL_SECRETS_PATH=/secrets/secrets.toml`.
- Launch 2 (PowerShell `$env:AXIAL_SECRETS_PATH` set) is the run above.
- Launch 3 was refused by the build's own `RUNNING.pid` lock; no duplicate reads (287 distinct bag/slice keys).
- `RUNNING.pid` is left behind by the kill; the ledger is resumable by relaunching the same command.

## Next

Founder decision: pay about $5.5 to finish and score D1 to D5 with `axial map compare`, or stop here.

## Discarded

Founder, 2026-09-29: too expensive for this experiment; the variant build directory was deleted. #859 re-runs on `openai/gpt-6-luna` in `2026-09-29-859-extract-luna/`.
