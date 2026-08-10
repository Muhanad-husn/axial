"""The analyst service layer (`plans/multiuser-analyst-service/README.md`,
issue #681 onward): a new layer in front of the existing Phase A/B/C
pipeline, not a change to it. Nothing under `axial.service` is imported by
`src/axial` core, and core is imported by this package only through its
existing public entry points (e.g. `axial.ask.engine.ask`).
"""

from __future__ import annotations
