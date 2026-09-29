"""A synthetic argument map for the CLI acceptance tests (issue #863).

Since DEC-75 (issue #853) `axial brief run` always retrieves through the
argument map, so a subprocess test needs `data/envelopes/`, `data/sources/`
and `data/map/<pin>/` on disk under its own root. `write_map_fixture` writes
the smallest map that walks: one position holding `chunk_ids` in order.
Landing has no similarity floor, so the stub door's argument always lands on
it, and assembly then hands `chunk_ids` to synthesis in exactly this order --
`[c1]` is `chunk_ids[0]`, `[c2]` is `chunk_ids[1]`, and so on.

`MAP_ARM_ENV` goes into the subprocess environment: the offline stub encoder,
so no test downloads MiniLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from axial.argmap.ask import ENCODER_MODEL
from axial.argmap.build import STUB_ENCODER_ENV_VAR, compute_corpus_pin

MAP_ARM_ENV = {STUB_ENCODER_ENV_VAR: "1"}


def write_map_fixture(root: Path, chunk_ids: Sequence[str]) -> str:
    """Write the map under `root/data/map/<pin>/` and return the pin. Call it
    after anything else that writes `data/envelopes/` or `data/sources/`,
    since the pin hashes both."""
    envelopes_dir = root / "data" / "envelopes"
    sources_dir = root / "data" / "sources"
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    pin = compute_corpus_pin(envelopes_dir, sources_dir)

    position = {
        "position_id": "pos-0001",
        "argument": "A synthetic position the stub door always lands on.",
        "size": len(chunk_ids),
        "sources": ["fixture"],
        "authors": ["fixture"],
        "chunk_ids": list(chunk_ids),
    }
    pin_dir = root / "data" / "map" / pin
    pin_dir.mkdir(parents=True, exist_ok=True)
    (pin_dir / "map.json").write_text(json.dumps({"encoder": ENCODER_MODEL}), encoding="utf-8")
    (pin_dir / "positions.jsonl").write_text(json.dumps(position) + "\n", encoding="utf-8")
    return pin
