"""Lane A conversion: Polycam floor-plan DXF bytes -> ChapterLayout (phase=existing)
+ review payload for the scan_commit0 card (PLAN.md Phase 2).

Confidence model — one constant block, all values dimensionless in [0,1]:
every element's confidence is min(geometry confidence, CAP_2D); anything strictly
below LOW_CONFIDENCE_THRESHOLD is listed in the review payload. Ordinary snapped
orthogonal walls therefore sit at exactly 0.85 and stay OUT of the low-confidence
list, while every skewed/curved/odd-thickness wall and every opening (whose
height/sill/swing are assumptions) appears in it. The wall-height assumption is
NOT priced into confidence — it is a first-class review field the human confirms.
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from chapter_contracts.generated.chapter_layout import ChapterLayout
from ezdxf import recover

from scan_converter import profile
from scan_converter.geometry import (
    RawWall,
    arc_params,
    dominant_axis_deg,
    merge_endpoints,
    project_on_segment,
    snap_headings,
    tessellate_bulge,
)
from scan_converter.units import UnitError, UnitInfo, detect_units

CAP_2D = 0.85  # nothing extracted from a 2D floor plan exceeds this
CONF_ORTHO = 0.95  # snapped-to-axis straight wall (capped to 0.85)
CONF_SKEW = 0.70  # genuine skew, preserved + flagged
CONF_CHORD = 0.60  # curved_approximation chord wall
CONF_THICKNESS_MISMATCH = 0.55  # thickness outside every catalog bucket
CONF_OPENING = 0.80  # doors/windows: width measured, height/sill/swing assumed
LOW_CONFIDENCE_THRESHOLD = 0.85  # strict <: elements below this go on the review card

DOOR_WIDTH_MIN_MM = 610.0  # registry create_door bounds — out-of-range openings are
DOOR_WIDTH_MAX_MM = 1830.0  # excluded from the layout and surfaced as flags instead

CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "packages" / "contracts"


class ConvertError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ConvertOptions:
    project_id: str
    level_name: str = "Level 1"
    ceiling_default_mm: float = 2700.0
    unit_override: str | None = None
    cloud_ref: str | None = None


@cache
def _asbuilt_catalog() -> tuple[tuple[str, float], ...]:
    data = json.loads((CONTRACTS_DIR / "catalogs" / "asbuilt_types.json").read_text())
    return tuple((t["revit_type"], float(t["thickness_mm"])) for t in data["types"])


@cache
def _bucket_tolerance_mm() -> float:
    data = json.loads((CONTRACTS_DIR / "catalogs" / "asbuilt_types.json").read_text())
    return float(data["bucket_tolerance_mm"])


@cache
def _asbuilt_opening_types() -> tuple[str, str]:
    data = json.loads((CONTRACTS_DIR / "catalogs" / "asbuilt_types.json").read_text())
    return data["doors"][0]["revit_type"], data["windows"][0]["revit_type"]


def _r(value: float) -> float:
    """Emit rounding: 0.1 mm, -0.0 normalized (layout JSON must be canonical)."""
    return round(value, 1) + 0.0


def _layer_name(entity: Any) -> str:
    return str(entity.dxf.layer).upper()


def convert(dxf_bytes: bytes, opts: ConvertOptions) -> dict[str, Any]:
    """Returns {"layout": <ChapterLayout dict>, "review_payload": <dict>}.
    Raises ConvertError(code, message) for every rejection in PROFILE.md."""
    try:
        doc, _auditor = recover.read(io.BytesIO(dxf_bytes))
    except Exception as err:  # ezdxf raises several structure error types
        raise ConvertError("dxf_parse_error", str(err)) from err
    msp = doc.modelspace()

    _reject_multilevel_layers(doc, msp)

    wall_entities = [
        e
        for e in msp
        if _layer_name(e) in profile.WALL_LAYERS
        and e.dxftype() in ("LWPOLYLINE", "POLYLINE", "LINE")
    ]
    if not wall_entities:
        raise ConvertError(
            "no_walls_found",
            f"no wall entities on layers {sorted(profile.WALL_LAYERS)}; "
            f"layers present: {_populated_layers(msp)}",
        )
    _reject_profile_violations(wall_entities)

    span_raw = _bbox_span(wall_entities)
    try:
        unit = detect_units(int(doc.header.get("$INSUNITS", 0)), span_raw, opts.unit_override)
    except UnitError as err:
        raise ConvertError(err.code, err.message) from err
    scale = unit.scale_to_mm

    _reject_multilevel_elevations(wall_entities, scale)

    walls = _extract_walls(wall_entities, scale)
    axis = dominant_axis_deg(walls)
    snap_headings(walls, axis, profile.HEADING_SNAP_DEG)
    merge_endpoints(walls, profile.ENDPOINT_MERGE_MIN_MM)
    for w in walls:
        w.start = (_r(w.start[0]), _r(w.start[1]))
        w.end = (_r(w.end[0]), _r(w.end[1]))
    walls.sort(key=lambda w: (min(w.start, w.end), max(w.start, w.end)))
    wall_ids = [f"W-{i + 1:03d}" for i in range(len(walls))]

    door_segs = _opening_segments(msp, profile.DOOR_LAYERS, scale)
    window_segs = _opening_segments(msp, profile.WINDOW_LAYERS, scale)
    flags: list[dict[str, Any]] = []
    doors = _map_openings(door_segs, walls, wall_ids, "door", flags)
    windows = _map_openings(window_segs, walls, wall_ids, "window", flags)

    layout = _build_layout(walls, wall_ids, doors, windows, opts, unit, flags)
    review = _build_review(layout, walls, wall_ids, doors, windows, opts, unit, flags, msp, scale)
    ChapterLayout.model_validate(layout)  # converter output is schema-valid or it crashes
    return {"layout": layout, "review_payload": review}


# ---- rejections -------------------------------------------------------------


def _populated_layers(msp: Any) -> list[str]:
    counts: dict[str, int] = {}
    for e in msp:
        counts[_layer_name(e)] = counts.get(_layer_name(e), 0) + 1
    return [f"{name}({n})" for name, n in sorted(counts.items())]


def _reject_multilevel_layers(doc: Any, msp: Any) -> None:
    populated = {_layer_name(e) for e in msp}
    hits = sorted(name for name in populated if profile.MULTILEVEL_LAYER_RE.search(name))
    if hits:
        raise ConvertError(
            "multi_level_unsupported",
            f"multi-storey layer names found: {hits}; v1 accepts single-level "
            "floor-plan DXFs only (upload one level per bundle)",
        )


def _reject_multilevel_elevations(wall_entities: list[Any], scale: float) -> None:
    zs: set[float] = set()
    for e in wall_entities:
        if e.dxftype() == "LINE":
            zs.add(round(e.dxf.start.z * scale, 1))
            zs.add(round(e.dxf.end.z * scale, 1))
        else:
            zs.add(round(float(e.dxf.elevation) * scale, 1))
    ordered = sorted(zs)
    clusters = 1
    for a, b in zip(ordered, ordered[1:], strict=False):
        if b - a > profile.ELEVATION_CLUSTER_MM:
            clusters += 1
    if clusters > 1:
        raise ConvertError(
            "multi_level_unsupported",
            f"wall entities sit at {clusters} distinct elevations "
            f"({ordered[0]:.0f}..{ordered[-1]:.0f} mm); v1 accepts one level per bundle",
        )


def _reject_profile_violations(wall_entities: list[Any]) -> None:
    bad: list[str] = []
    for e in wall_entities:
        if e.dxftype() == "LINE":
            bad.append(f"LINE on {_layer_name(e)} (walls must be widthed LWPOLYLINEs)")
        elif e.dxftype() == "POLYLINE":
            bad.append(f"POLYLINE on {_layer_name(e)} (convert to LWPOLYLINE with const_width)")
        elif float(getattr(e.dxf, "const_width", 0.0) or 0.0) <= 0.0:
            bad.append(f"{e.dxftype()} on {_layer_name(e)} with const_width=0")
    if bad:
        raise ConvertError(
            "profile_violation",
            "wall layer entities violate DXF profile v1 (see PROFILE.md): "
            + "; ".join(sorted(set(bad))),
        )


# ---- extraction -------------------------------------------------------------


def _bbox_span(wall_entities: list[Any]) -> float:
    xs: list[float] = []
    ys: list[float] = []
    for e in wall_entities:
        if e.dxftype() == "LINE":
            xs += [e.dxf.start.x, e.dxf.end.x]
            ys += [e.dxf.start.y, e.dxf.end.y]
        else:
            for x, y, _b in e.get_points("xyb"):
                xs.append(x)
                ys.append(y)
    return max(max(xs) - min(xs), max(ys) - min(ys))


def _extract_walls(wall_entities: list[Any], scale: float) -> list[RawWall]:
    walls: list[RawWall] = []
    for e in wall_entities:
        thickness = float(e.dxf.const_width) * scale
        points = [(x * scale, y * scale, b) for x, y, b in e.get_points("xyb")]
        if getattr(e, "closed", False) and points:
            points.append(points[0])
        for (x1, y1, bulge), (x2, y2, _b2) in zip(points, points[1:], strict=False):
            p1, p2 = (x1, y1), (x2, y2)
            if bulge:
                radius, angle = arc_params(p1, p2, bulge)
                chain = tessellate_bulge(p1, p2, bulge, profile.MAX_SAGITTA_MM)
                prev = p1
                for i, pt in enumerate(chain):
                    walls.append(
                        RawWall(
                            start=prev,
                            end=pt,
                            thickness=thickness,
                            curved=True,
                            notes={
                                "radius_mm": round(radius, 1),
                                "arc_deg": round(angle, 2),
                                "chord": f"{i + 1}/{len(chain)}",
                            },
                        )
                    )
                    prev = pt
            elif p1 != p2:
                walls.append(RawWall(start=p1, end=p2, thickness=thickness))
    return walls


def _opening_segments(
    msp: Any, layers: set[str], scale: float
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for e in msp:
        if _layer_name(e) not in layers:
            continue
        if e.dxftype() == "LINE":
            segs.append(
                (
                    (e.dxf.start.x * scale, e.dxf.start.y * scale),
                    (e.dxf.end.x * scale, e.dxf.end.y * scale),
                )
            )
        elif e.dxftype() == "LWPOLYLINE":
            pts = [(x * scale, y * scale) for x, y, _b in e.get_points("xyb")]
            if len(pts) == 2:
                segs.append((pts[0], pts[1]))
    return segs


def _map_openings(
    segs: list[tuple[tuple[float, float], tuple[float, float]]],
    walls: list[RawWall],
    wall_ids: list[str],
    kind: str,
    flags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for s, e in segs:
        width = math.hypot(e[0] - s[0], e[1] - s[1])
        mid = ((s[0] + e[0]) / 2.0, (s[1] + e[1]) / 2.0)
        best: tuple[float, int] | None = None
        for wi, w in enumerate(walls):
            slack = w.thickness / 2.0 + profile.OPENING_HOST_SLACK_MM
            d1, _ = project_on_segment(s, w.start, w.end)
            d2, _ = project_on_segment(e, w.start, w.end)
            if d1 <= slack and d2 <= slack:
                worst = max(d1, d2)
                if best is None or worst < best[0]:
                    best = (worst, wi)
        if best is None:
            flags.append(
                {
                    "element_id": None,
                    "flag": "unmapped_opening",
                    "detail": f"{kind} segment {s[0]:.0f},{s[1]:.0f}->{e[0]:.0f},{e[1]:.0f} "
                    f"(width {width:.0f}) lies along no wall — excluded from layout",
                }
            )
            continue
        wi = best[1]
        host = walls[wi]
        _d, offset = project_on_segment(mid, host.start, host.end)
        if kind == "door" and not (DOOR_WIDTH_MIN_MM <= width <= DOOR_WIDTH_MAX_MM):
            flags.append(
                {
                    "element_id": None,
                    "flag": "unmapped_opening",
                    "detail": f"door width {width:.0f} outside contract bounds "
                    f"[{DOOR_WIDTH_MIN_MM:.0f}, {DOOR_WIDTH_MAX_MM:.0f}] on {wall_ids[wi]} "
                    "— excluded from layout",
                }
            )
            continue
        if offset - width / 2.0 < -0.05 or offset + width / 2.0 > host.length + 0.05:
            flags.append(
                {
                    "element_id": None,
                    "flag": "unmapped_opening",
                    "detail": f"{kind} at offset {offset:.0f} (width {width:.0f}) overruns "
                    f"host {wall_ids[wi]} (length {host.length:.0f}) — excluded from layout",
                }
            )
            continue
        mapped.append({"host_wall_id": wall_ids[wi], "offset": _r(offset), "width": _r(width)})
    mapped.sort(key=lambda o: (o["host_wall_id"], o["offset"]))
    return mapped


# ---- emission ---------------------------------------------------------------


def _wall_confidence(w: RawWall, type_matched: bool) -> float:
    if not type_matched:
        base = CONF_THICKNESS_MISMATCH
    elif w.curved:
        base = CONF_CHORD
    elif w.skewed:
        base = CONF_SKEW
    else:
        base = CONF_ORTHO
    return min(base, CAP_2D)


def _classify_thickness(thickness: float) -> tuple[str, bool]:
    catalog = _asbuilt_catalog()
    revit_type, bucket = min(catalog, key=lambda t: (abs(t[1] - thickness), t[1]))
    return revit_type, abs(bucket - thickness) <= _bucket_tolerance_mm()


def _build_layout(
    walls: list[RawWall],
    wall_ids: list[str],
    doors: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    opts: ConvertOptions,
    unit: UnitInfo,
    flags: list[dict[str, Any]],
) -> dict[str, Any]:
    door_type, window_type = _asbuilt_opening_types()
    wall_records = []
    for wall_id, w in zip(wall_ids, walls, strict=True):
        revit_type, matched = _classify_thickness(w.thickness)
        if not matched:
            flags.append(
                {
                    "element_id": wall_id,
                    "flag": "thickness_out_of_bucket",
                    "detail": f"as-built thickness {w.thickness:.1f} matches no catalog bucket "
                    f"(±{_bucket_tolerance_mm():.0f}); nearest type {revit_type}",
                }
            )
        record: dict[str, Any] = {
            "id": wall_id,
            "start": [w.start[0], w.start[1]],
            "end": [w.end[0], w.end[1]],
            "revit_type": revit_type,
            "height": opts.ceiling_default_mm,
            "as_built_thickness": _r(w.thickness),
            "confidence": _wall_confidence(w, matched),
            "source": "scan",
        }
        if w.curved:
            record["curved_approximation"] = True
        wall_records.append(record)

    door_records = [
        {
            "id": f"D-{i + 1:03d}",
            "host_wall_id": d["host_wall_id"],
            "offset": d["offset"],
            "width": d["width"],
            "height": profile.DOOR_HEIGHT_MM,
            "revit_type": door_type,
            "swing": profile.DOOR_SWING,
            "confidence": min(CONF_OPENING, CAP_2D),
        }
        for i, d in enumerate(doors)
    ]
    window_records = [
        {
            "id": f"N-{i + 1:03d}",
            "host_wall_id": n["host_wall_id"],
            "offset": n["offset"],
            "width": n["width"],
            "height": profile.WINDOW_HEIGHT_MM,
            "sill_height": profile.WINDOW_SILL_MM,
            "revit_type": window_type,
            "confidence": min(CONF_OPENING, CAP_2D),
        }
        for i, n in enumerate(windows)
    ]

    meta: dict[str, Any] = {
        "project_id": opts.project_id,
        "level": opts.level_name,
        "units": "mm",
        "origin": "revit_internal_origin",
        "schema_version": "2.3",
        "brief_version": 0,
        "phase": "existing",
        "scan": {"source": "polycam", "capture": "floorplan_dxf"},
    }
    if opts.cloud_ref:
        meta["scan"]["cloud_ref"] = opts.cloud_ref
    return {
        "meta": meta,
        "walls": wall_records,
        "doors": door_records,
        "windows": window_records,
        "rooms": [],  # Commit #0 is element geometry only; rooms are Phase 4's job
        "furniture": [],
        "constraints": {},
    }


def _build_review(
    layout: dict[str, Any],
    walls: list[RawWall],
    wall_ids: list[str],
    doors: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    opts: ConvertOptions,
    unit: UnitInfo,
    flags: list[dict[str, Any]],
    msp: Any,
    scale: float,
) -> dict[str, Any]:
    for wall_id, w in zip(wall_ids, walls, strict=True):
        if w.curved:
            flags.append(
                {
                    "element_id": wall_id,
                    "flag": "curved_approximation",
                    "detail": f"arc r={w.notes['radius_mm']}mm ({w.notes['arc_deg']}deg), "
                    f"chord {w.notes['chord']}, max sagitta {profile.MAX_SAGITTA_MM:.0f}mm",
                }
            )
        elif w.skewed:
            flags.append(
                {
                    "element_id": wall_id,
                    "flag": "skewed",
                    "detail": f"{w.skew_deg:.2f} deg off dominant axis, preserved",
                }
            )

    low_confidence = [
        {"element_id": rec["id"], "kind": kind, "confidence": rec["confidence"]}
        for kind, records in (
            ("wall", layout["walls"]),
            ("door", layout["doors"]),
            ("window", layout["windows"]),
        )
        for rec in records
        if rec["confidence"] < LOW_CONFIDENCE_THRESHOLD
    ]

    room_labels = [
        {
            "text": str(e.dxf.text),
            "at": [_r(e.dxf.insert.x * scale), _r(e.dxf.insert.y * scale)],
        }
        for e in msp
        if _layer_name(e) in profile.ROOM_LAYERS and e.dxftype() in ("TEXT", "MTEXT")
    ]
    room_labels.sort(key=lambda label: (label["text"], label["at"]))

    return {
        "layout": layout,
        "unit": {
            "detected": unit.detected,
            "insunits": unit.insunits,
            "source": unit.source,
            "confirmation_required": unit.confirmation_required,
            "bbox_span_raw": round(unit.bbox_span_raw, 3),
            "bbox_span_mm": _r(unit.bbox_span_mm),
        },
        "height_assumption_mm": opts.ceiling_default_mm,
        "assumptions": [
            {
                "field": "wall_height",
                "value": opts.ceiling_default_mm,
                "note": "2D DXF carries no heights; confirm ceiling height on approval",
            },
            {"field": "door_height", "value": profile.DOOR_HEIGHT_MM},
            {"field": "door_swing", "value": profile.DOOR_SWING},
            {"field": "window_sill", "value": profile.WINDOW_SILL_MM},
            {"field": "window_height", "value": profile.WINDOW_HEIGHT_MM},
        ],
        "flags": sorted(flags, key=lambda f: (f["element_id"] or "~", f["flag"], f["detail"])),
        "low_confidence": low_confidence,
        "room_labels": room_labels,
        "counts": {
            "walls": len(layout["walls"]),
            "doors": len(layout["doors"]),
            "windows": len(layout["windows"]),
        },
    }
