"""Deterministic per-room capacity hints for the furnish prompt (advisory
guidance, computed from the approved layout — the placer is the enforcement):
an item's shorter side must leave circulation_min of the room bbox's shorter
span; its longer side is bounded by the longer span."""

from __future__ import annotations

from typing import Any

from shapely.geometry import Polygon

from layout_compiler.validator import DEFAULT_CIRCULATION_MIN_MM


def capacity_hints(layout: dict[str, Any]) -> list[dict[str, Any]]:
    circulation_min = float(
        layout.get("constraints", {}).get("circulation_min", DEFAULT_CIRCULATION_MIN_MM)
    )
    hints: list[dict[str, Any]] = []
    for room in layout["rooms"]:
        minx, miny, maxx, maxy = Polygon(room["boundary"]).bounds
        short, long_ = sorted((maxx - minx, maxy - miny))
        hints.append(
            {
                "room_id": room["id"],
                "program": room["program"],
                "max_item_short_side_mm": max(0.0, round(short - circulation_min, 1)),
                "max_item_long_side_mm": round(long_, 1),
            }
        )
    return hints
