"""Regenerate the Phase 7 fixtures and goldens. The OUTPUT of this script is the sole source
of golden truth — tests and tests/e2e copy from it, never the other way round.

  cd services/aidm-bridge && uv run python scripts/gen_golden_render.py

Writes fixtures/renders/phase7_2br_{plan,section,3d_hidden}_2048.png (the sim's rasterised
views of the Phase 6 golden model), fixtures/goldens/phase7_2br_{section,axon}.svg,
phase7_2br_{canny,lines}_<view>.png, phase7_2br_render.json (PNGs -> sha256) and
phase7_2br_finish_selection.json (request + response). Proves: the plan SVG equals the
Phase 6 golden, every emitted op applies in the real SimModel, and two runs are identical."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from revit_sim.model import Catalogs  # noqa: E402
from revit_sim.render.png import rasterize  # noqa: E402

from aidm_bridge.aidm import MockRenderer  # noqa: E402
from aidm_bridge.golden_render import (  # noqa: E402
    FILES,
    PHASE6_MEP_SVG,
    PX,
    REPO_ROOT,
    VIEWS,
    compact_render,
    dumps,
    golden_chain_and_model,
    golden_render_request,
    golden_selection_request,
    golden_svgs,
)
from aidm_bridge.render import RenderOptions, render_views  # noqa: E402
from aidm_bridge.selection import validate_ops, validate_selection  # noqa: E402


def build() -> dict[str, bytes | str]:
    chain, _merged, model = golden_chain_and_model()
    svgs = golden_svgs(model)
    assert svgs["plan"] == PHASE6_MEP_SVG.read_text(), "plan view drifted from phase6_2br_mep.svg"
    pngs = {name: rasterize(svgs[name], PX) for name, _ in VIEWS}

    render_req = golden_render_request(chain, pngs)
    render_resp = render_views(
        render_req, MockRenderer(), RenderOptions(render_req["project_id"], True)
    )
    assert render_resp["prompt"]["tags_dropped"] == [], render_resp["prompt"]["tags_dropped"]
    assert all(r["status"] == "ok" for r in render_resp["renders"]), render_resp["renders"]
    assert all(m["stats"]["edge_px"] > 0 for m in render_resp["control_maps"])

    sel_req = golden_selection_request(chain, model)
    sel_resp = validate_selection(
        sel_req["layout"],
        sel_req["id_map_ids"],
        sel_req["finish_tier"],
        sel_req["catalog_version"],
        sel_req["render_ref"],
        sel_req["selection"],
        sel_req["allow_placeholders"],
    )
    assert sel_resp["blocking"] == [], sel_resp["blocking"]
    validate_ops(sel_resp["ops"])
    # the executor's own law accepts the whole emission
    catalogs = Catalogs.load()
    replay = model.clone()
    for op in sel_resp["ops"]:
        replay.apply(op["op"], op["args"], catalogs)

    import base64

    out: dict[str, bytes | str] = {
        "section_svg": svgs["section"],
        "axon_svg": svgs["3d_hidden"],
        "render_json": dumps(compact_render(render_resp)),
        "selection_json": dumps({"request": sel_req, "response": sel_resp}),
    }
    for name, _ in VIEWS:
        out[f"png_{name}"] = pngs[name]
    for cmap in render_resp["control_maps"]:
        out[f"canny_{cmap['name']}"] = base64.b64decode(cmap["canny_png_base64"])
        out[f"lines_{cmap['name']}"] = base64.b64decode(cmap["lines_png_base64"])
    return out


def main() -> int:
    first = build()
    second = build()
    assert first == second, "two runs differ — the generator is not deterministic"
    for key, content in first.items():
        path = FILES[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content)
        else:
            path.write_bytes(content)
        print(f"wrote {path.relative_to(REPO_ROOT)} ({len(content)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
