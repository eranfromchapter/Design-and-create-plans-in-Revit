"""Unit detection (PLAN.md Phase 2): trust $INSUNITS when set; when 0/absent fall
back to the bounding-box span heuristic and require review-card confirmation."""

from __future__ import annotations

from dataclasses import dataclass

INSUNITS_TO_NAME = {1: "inch", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
NAME_TO_MM = {"inch": 25.4, "ft": 304.8, "mm": 1.0, "cm": 10.0, "m": 1000.0}

# Disjoint plausible-apartment span bands (largest bbox dimension of the WALLS
# entities, raw drawing units). A span outside every band is undetectable.
HEURISTIC_BANDS = [
    ("mm", 3_000.0, 30_000.0),
    ("inch", 118.0, 1_181.0),
    ("m", 3.0, 30.0),
]


class UnitError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UnitInfo:
    detected: str
    scale_to_mm: float
    source: str  # "insunits" | "heuristic" | "override"
    confirmation_required: bool
    insunits: int
    bbox_span_raw: float
    bbox_span_mm: float


def detect_units(insunits: int, bbox_span_raw: float, unit_override: str | None) -> UnitInfo:
    if unit_override is not None:
        if unit_override not in NAME_TO_MM:
            raise UnitError("unit_undetectable", f"unknown unit_override {unit_override!r}")
        scale = NAME_TO_MM[unit_override]
        return UnitInfo(
            detected=unit_override,
            scale_to_mm=scale,
            source="override",
            confirmation_required=False,
            insunits=insunits,
            bbox_span_raw=bbox_span_raw,
            bbox_span_mm=bbox_span_raw * scale,
        )

    if insunits in INSUNITS_TO_NAME:
        name = INSUNITS_TO_NAME[insunits]
        scale = NAME_TO_MM[name]
        return UnitInfo(
            detected=name,
            scale_to_mm=scale,
            source="insunits",
            confirmation_required=False,
            insunits=insunits,
            bbox_span_raw=bbox_span_raw,
            bbox_span_mm=bbox_span_raw * scale,
        )

    for name, lo, hi in HEURISTIC_BANDS:
        if lo <= bbox_span_raw <= hi:
            scale = NAME_TO_MM[name]
            return UnitInfo(
                detected=name,
                scale_to_mm=scale,
                source="heuristic",
                confirmation_required=True,
                insunits=insunits,
                bbox_span_raw=bbox_span_raw,
                bbox_span_mm=bbox_span_raw * scale,
            )
    raise UnitError(
        "unit_undetectable",
        f"$INSUNITS={insunits} and wall bbox span {bbox_span_raw:.1f} "
        "matches no plausible apartment scale (mm/inch/m bands)",
    )
