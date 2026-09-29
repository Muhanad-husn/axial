"""Build notes.db with the pre-#853 code (aea4714) into a side directory, so the
new store can be diffed against it on identical inputs. Run from D:/axial-runs
with PYTHONPATH pointing at the pre-#853 worktree's src."""

from pathlib import Path

import axial
from axial.materialize import (
    DEFAULT_ALIAS_MAP_PATH,
    DEFAULT_INVENTORY_PATH,
    SOURCE_META_DIR,
    _default_answers_dir,
    _default_envelopes_dir,
    build_note_store,
)

print("code:", axial.__file__)
out = Path("data/logs/2026-09-29-853-materialize/old-vault")
out.mkdir(exist_ok=True)
print(
    build_note_store(
        alias_map_path=DEFAULT_ALIAS_MAP_PATH,
        inventory_path=DEFAULT_INVENTORY_PATH,
        answers_dir=_default_answers_dir(Path("config/pipeline.yaml")),
        source_meta_dir=SOURCE_META_DIR,
        envelopes_dir=_default_envelopes_dir(Path("config/pipeline.yaml")),
        vault_dir=out,
    )
)
