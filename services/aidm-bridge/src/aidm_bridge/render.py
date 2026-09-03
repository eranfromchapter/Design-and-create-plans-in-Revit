"""POST /render orchestration (docs/PHASE7_DESIGN.md §3.1-3.3): control maps first (fail fast),
the prompt once, then one render per view under a single request deadline; candidates are
the products catalog filtered by tier and surface class. This module owns the clock."""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import cv2

from aidm_bridge.aidm import Renderer, RenderJob, RenderOutcome, job_seed, safe_ref
from aidm_bridge.catalogs import catalog_version, products
from aidm_bridge.control_maps import (
    ControlMap,
    MapError,
    build_control_map,
    decode_base64_png,
)
from aidm_bridge.csi import SURFACES, surface_of
from aidm_bridge.prompts import TEMPLATE_VERSION, compose_prompt, sanitize_tags
from aidm_bridge.selection import PLACEHOLDER_MARK

RENDER_TIME_LIMIT_S = 120.0


class RenderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RenderOptions:
    project_id: str
    allow_placeholders: bool = False


def _b64(data: bytes | None) -> str | None:
    return None if data is None else base64.b64encode(data).decode()


def candidates(finish_tier: str, allow_placeholders: bool) -> tuple[dict[str, list], list[dict]]:
    """products.json rows of this tier grouped by surface class (sorted by sku); info items
    for unmapped CSI sections and for a tier whose only rows are placeholders."""
    grouped: dict[str, list[dict[str, Any]]] = {surface: [] for surface in SURFACES}
    items: list[dict[str, Any]] = []
    tier_rows = 0
    for row in products()["skus"]:
        surface = surface_of(row["csi_section"])
        if surface is None:
            items.append(
                {
                    "code": "unmapped_csi",
                    "severity": "info",
                    "refs": [row["sku"]],
                    "message": f"csi_section {row['csi_section']!r} maps to no surface class",
                }
            )
            continue
        if row["finish_tier"] != finish_tier:
            continue
        tier_rows += 1
        if PLACEHOLDER_MARK in row["sku"] and not allow_placeholders:
            continue
        grouped[surface].append(dict(row))
    if tier_rows and not any(grouped.values()):
        items.append(
            {
                "code": "catalog_placeholder_only",
                "severity": "info",
                "refs": [finish_tier],
                "message": "every SKU of this tier is a placeholder; ask Eran for the real catalog",
            }
        )
    for rows in grouped.values():
        rows.sort(key=lambda r: r["sku"])
    return grouped, items


def render_views(
    req: dict[str, Any],
    renderer: Renderer,
    opts: RenderOptions,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    started = clock()
    deadline = started + RENDER_TIME_LIMIT_S
    maps: list[ControlMap] = []
    for view in req["views"]:
        try:
            png = decode_base64_png(view["png_base64"])
            maps.append(build_control_map(view["name"], view["kind"], png))
        except MapError as err:
            raise RenderError(err.code, f"{view['name']}: {err.message}") from err

    tags_used, tags_dropped = sanitize_tags(list(req.get("style_tags", [])))
    programs = [room["program"] for room in req.get("rooms", [])]
    finish_tier = req["finish_tier"]
    text = compose_prompt(tags_used, finish_tier, programs)

    renders: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    for view, cmap in zip(req["views"], maps, strict=True):
        remaining = deadline - clock()
        ref = safe_ref(f"{renderer.provider}-{req['render_id']}-{view['name']}")
        if remaining <= 0:
            outcome = RenderOutcome("skipped_deadline", None, ref, 0, "request deadline exhausted")
        else:
            job = RenderJob(
                render_id=req["render_id"],
                view_name=view["name"],
                view_kind=view["kind"],
                prompt=text,
                finish_tier=finish_tier,
                canny_png=cmap.canny_png,
                lines_png=cmap.lines_png,
                width=cmap.stats["width"],
                height=cmap.stats["height"],
                seed=job_seed(req["render_id"], view["name"]),
            )
            try:
                outcome = renderer.render(job, remaining)
            except Exception as err:  # a renderer bug is this view's failure, never a 500
                outcome = RenderOutcome(
                    "failed", None, ref, 0, f"renderer error: {type(err).__name__}: {err}"[:300]
                )
        renders.append(
            {
                "name": view["name"],
                "provider": renderer.provider,
                "png_base64": _b64(outcome.png),
                "ref": outcome.ref or ref,
                "status": outcome.status,
                "attempts": outcome.attempts,
            }
        )
        if outcome.status != "ok":
            code = "render_failed" if outcome.status == "failed" else "render_timeout"
            review_items.append(
                {
                    "code": code,
                    "severity": "info",
                    "refs": [view["name"]],
                    "message": outcome.error or outcome.status,
                }
            )

    grouped, catalog_items = candidates(finish_tier, opts.allow_placeholders)
    review_items.extend(catalog_items)
    for drop in tags_dropped:
        review_items.append(
            {
                "code": "style_tag_dropped",
                "severity": "info",
                "refs": [drop["tag"]],
                "message": f"style tag dropped: {drop['reason']}",
            }
        )
    review_items.sort(key=lambda i: (i["severity"], i["code"], i["refs"]))

    return {
        "control_maps": [
            {
                "name": m.name,
                "kind": m.kind,
                "canny_png_base64": _b64(m.canny_png),
                "lines_png_base64": _b64(m.lines_png),
                "preview_png_base64": _b64(m.preview_png),
                "stats": m.stats,
            }
            for m in maps
        ],
        "prompt": {
            "template_version": TEMPLATE_VERSION,
            "text": text,
            "tags_used": tags_used,
            "tags_dropped": tags_dropped,
        },
        "renders": renders,
        "candidates": grouped,
        "review_items": review_items,
        "diagnostics": {
            "elapsed_ms": int((clock() - started) * 1000),
            "provider": renderer.provider,
            "opencv_version": cv2.__version__,
            "catalog_version": catalog_version(),
            "views": [
                {"name": m.name, "width": m.stats["width"], "height": m.stats["height"]}
                for m in maps
            ],
        },
    }
