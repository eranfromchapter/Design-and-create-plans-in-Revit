"""Phase 7 golden constants and builders shared by scripts/gen_golden_render.py (the SOLE
writer of every phase7_2br_* fixture), the drift/golden tests and scripts/demo_phase7.py.
The golden model is the Phase 6 golden chain (layout-compiler, a dev-only dependency of
this service) replayed through the real SimModel; the plan view is provably the
rasterisation of fixtures/goldens/phase6_2br_mep.svg."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from revit_sim.model import Catalogs, SimModel
from revit_sim.render.svg import render_axon, render_plan, render_section

REPO_ROOT = Path(__file__).resolve().parents[4]
GOLDENS = REPO_ROOT / "fixtures" / "goldens"
RENDERS = REPO_ROOT / "fixtures" / "renders"
RENDER_ID = "phase7-2br-golden"
PX = 2048
VIEWS = [("plan", "plan"), ("section", "section"), ("3d_hidden", "3d_hidden")]
RENDER_REF = f"mock-{RENDER_ID}-plan"

FILES: dict[str, Path] = {
    **{f"png_{name}": RENDERS / f"phase7_2br_{name}_{PX}.png" for name, _ in VIEWS},
    **{f"canny_{name}": GOLDENS / f"phase7_2br_canny_{name}.png" for name, _ in VIEWS},
    **{f"lines_{name}": GOLDENS / f"phase7_2br_lines_{name}.png" for name, _ in VIEWS},
    "section_svg": GOLDENS / "phase7_2br_section.svg",
    "axon_svg": GOLDENS / "phase7_2br_axon.svg",
    "render_json": GOLDENS / "phase7_2br_render.json",
    "selection_json": GOLDENS / "phase7_2br_finish_selection.json",
}
PHASE6_MEP_SVG = GOLDENS / "phase6_2br_mep.svg"

# the golden finish selection, by room program / item kind (never by hard-coded ids)
WALL_SKU_BY_TIER = "CHPT-WALL-PAINT-STD_PLACEHOLDER"
WET_WALL_SKU = "CHPT-WALL-TILE-LUX_PLACEHOLDER"
DOOR_SKU = "CHPT-DOOR-SC-STD_PLACEHOLDER"
FIXTURE_SKU_BY_KIND = {
    "wc": "CHPT-WC-STD_PLACEHOLDER",
    "lav": "CHPT-LAV-STD_PLACEHOLDER",
    "kitchen_sink": "CHPT-SINK-STD_PLACEHOLDER",
}
WET_PROGRAMS = ("bathroom", "powder")


def dumps(obj: Any) -> str:
    """The one serializer every JSON golden is written and compared with."""
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def sha256_b64(data_b64: str) -> str:
    return hashlib.sha256(base64.b64decode(data_b64)).hexdigest()


def golden_chain_and_model() -> tuple[dict[str, Any], dict[str, Any], SimModel]:
    """(chain, merged Commit #2 result, the post-Commit-#2 SimModel)."""
    from layout_compiler.golden_mep import golden_chain, merge_golden, plan_golden
    from layout_compiler.replay import sim_model_from_layout

    chain = golden_chain()
    plan = plan_golden(chain)
    merged = merge_golden(chain, plan)
    catalogs = Catalogs.load()
    model = sim_model_from_layout(chain["commit0"])
    for op in chain["commit1_ops"]:
        model.apply(op["op"], op["args"], catalogs)
    for op in merged["ops"]:
        if op["op"] == "run_interference_check":
            continue  # rendering only; the merge gate already proved 0 clashes
        model.apply(op["op"], op["args"], catalogs)
    return chain, merged, model


def golden_svgs(model: SimModel) -> dict[str, str]:
    catalogs = Catalogs.load()
    return {
        "plan": render_plan(model),
        "section": render_section(model, catalogs),
        "3d_hidden": render_axon(model, catalogs),
    }


def golden_render_request(chain: dict[str, Any], pngs: dict[str, bytes]) -> dict[str, Any]:
    layout = chain["furnished"]
    return {
        "project_id": chain["brief"]["meta"]["project_id"],
        "render_id": RENDER_ID,
        "views": [
            {
                "name": name,
                "kind": kind,
                "px": PX,
                "png_base64": base64.b64encode(pngs[name]).decode(),
            }
            for name, kind in VIEWS
        ],
        "style_tags": list(layout.get("constraints", {}).get("style_tags", [])),
        "finish_tier": chain["brief"].get("finish_tier", "standard"),
        "rooms": [
            {"id": r["id"], "name": r["name"], "program": r["program"]} for r in layout["rooms"]
        ],
        "allow_placeholders": True,
    }


def golden_selection_request(chain: dict[str, Any], model: SimModel) -> dict[str, Any]:
    """Standard paint everywhere, luxury tile in the wet rooms (tier overrides), the
    standard door on every door, standard fixtures by kind; appliances left unselected."""
    layout = chain["furnished"]
    rooms = []
    overrides = []
    for room in layout["rooms"]:
        wet = room["program"] in WET_PROGRAMS
        rooms.append({"room_id": room["id"], "wall_sku": WET_WALL_SKU if wet else WALL_SKU_BY_TIER})
        if wet:
            overrides.append(
                {
                    "target": room["id"],
                    "sku": WET_WALL_SKU,
                    "reason": "wet-room tile (demo of tier_override)",
                }
            )
    fixtures = []
    for group in layout.get("furniture", []):
        for item in group["items"]:
            sku = FIXTURE_SKU_BY_KIND.get(item["kind"])
            if sku:
                fixtures.append({"id": item["id"], "sku": sku})
    return {
        "project_id": chain["brief"]["meta"]["project_id"],
        "layout": layout,
        "id_map_ids": sorted(model.all_ids()),
        "finish_tier": chain["brief"].get("finish_tier", "standard"),
        "catalog_version": _catalog_version(),
        "render_ref": RENDER_REF,
        "selection": {
            "rooms": rooms,
            "casework": [],
            "doors": [{"id": d["id"], "sku": DOOR_SKU} for d in layout["doors"]],
            "plumbing_fixtures": sorted(fixtures, key=lambda f: f["id"]),
            "overrides": overrides,
        },
        "allow_placeholders": True,
    }


def _catalog_version() -> str:
    from aidm_bridge.catalogs import catalog_version

    return catalog_version()


def compact_render(response: dict[str, Any]) -> dict[str, Any]:
    """The /render response with every PNG replaced by its sha256 and timings dropped."""
    out = json.loads(json.dumps(response))
    for cmap in out["control_maps"]:
        for key in ("canny_png_base64", "lines_png_base64", "preview_png_base64"):
            cmap[key] = sha256_b64(cmap[key])
    for render in out["renders"]:
        if render.get("png_base64"):
            render["png_base64"] = sha256_b64(render["png_base64"])
    out["diagnostics"].pop("elapsed_ms", None)
    return out
