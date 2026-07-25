"""The sealed-packet peer-reviewer panel (issue #385, specs/PHASE-B.md §9.4,
DEC-40/DEC-43): eval #1's answer-quality instrument.

**An offline eval method, not a pipeline stage.** No production brief run
dispatches a reviewer, no analysis record gains a reviewer field, and no
rung-3 gate report waits on a verdict from here. A panel run is an
occasional, deliberate act against a sample chosen across performance tiers
and model combinations.

Four modules, one per property that has to hold:

- `packet` -- assembly and the content half of the seal (properties 1, 2, 7)
- `vendor` -- the different-training-lab bar (property 3)
- `review` -- N >= 3 dispatch, structured verdicts, the spread (4, 5)
- `control` -- planted defects and the trust condition (property 6)

`run` composes them: control first, and its verdict is what `trusted` means.
"""

from axial.panel.control import (
    ControlError,
    ControlReport,
    Plant,
    PlantNotApplicableError,
    PlantOutcome,
    format_control_report,
    plant_all,
    score_control,
)
from axial.panel.packet import (
    PacketError,
    ReviewPacket,
    SealBreachError,
    UnresolvableGroundsError,
    assert_sealed,
    build_packet,
)
from axial.panel.review import (
    BANDS,
    DEFECT_KINDS,
    DIMENSIONS,
    MIN_REVIEWERS,
    Defect,
    DimensionSummary,
    PanelError,
    PanelReport,
    ReviewerCallFailedError,
    ReviewerVerdict,
    TooFewReviewersError,
    format_panel_report,
    review_packet,
    reviewer_pass_name,
)
from axial.panel.run import PanelRun, format_panel_run, run_control, run_panel
from axial.panel.vendor import (
    UnknownVendorError,
    VendorCollisionError,
    VendorError,
    guard_distinct_vendor,
    vendor_of,
)

__all__ = [
    "BANDS",
    "DEFECT_KINDS",
    "DIMENSIONS",
    "MIN_REVIEWERS",
    "ControlError",
    "ControlReport",
    "Defect",
    "DimensionSummary",
    "PacketError",
    "PanelError",
    "PanelReport",
    "PanelRun",
    "Plant",
    "PlantNotApplicableError",
    "PlantOutcome",
    "ReviewPacket",
    "ReviewerCallFailedError",
    "ReviewerVerdict",
    "SealBreachError",
    "TooFewReviewersError",
    "UnknownVendorError",
    "UnresolvableGroundsError",
    "VendorCollisionError",
    "VendorError",
    "assert_sealed",
    "build_packet",
    "format_control_report",
    "format_panel_report",
    "format_panel_run",
    "guard_distinct_vendor",
    "plant_all",
    "review_packet",
    "reviewer_pass_name",
    "run_control",
    "run_panel",
    "score_control",
    "vendor_of",
]
