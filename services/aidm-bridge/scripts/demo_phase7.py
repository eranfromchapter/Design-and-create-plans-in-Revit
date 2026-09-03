"""make demo-phase7 helper: control maps, the mock render and the finish-selection payload
side by side, written to out/phase7/ as the artifacts a human eyeballs at the Phase 7 gate."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from revit_sim.render.png import rasterize  # noqa: E402

from aidm_bridge.aidm import MockRenderer  # noqa: E402
from aidm_bridge.golden_render import (  # noqa: E402
    PX,
    REPO_ROOT,
    VIEWS,
    golden_chain_and_model,
    golden_render_request,
    golden_selection_request,
    golden_svgs,
)
from aidm_bridge.render import RenderOptions, render_views  # noqa: E402
from aidm_bridge.selection import validate_selection  # noqa: E402


def _img(b64: str) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)
    return cv2.resize(img, (512, max(1, round(img.shape[0] * 512 / img.shape[1]))))


def main() -> int:
    out = REPO_ROOT / "out" / "phase7"
    out.mkdir(parents=True, exist_ok=True)
    chain, _merged, model = golden_chain_and_model()
    svgs = golden_svgs(model)
    pngs = {name: rasterize(svgs[name], PX) for name, _ in VIEWS}
    req = golden_render_request(chain, pngs)
    resp = render_views(req, MockRenderer(), RenderOptions(req["project_id"], True))
    for cmap, render in zip(resp["control_maps"], resp["renders"], strict=True):
        name = cmap["name"]
        (out / f"{name}_source.png").write_bytes(pngs[name])
        (out / f"{name}_canny.png").write_bytes(base64.b64decode(cmap["canny_png_base64"]))
        (out / f"{name}_lines.png").write_bytes(base64.b64decode(cmap["lines_png_base64"]))
        (out / f"{name}_render_mock.png").write_bytes(base64.b64decode(render["png_base64"]))
        tiles = [_img(cmap["preview_png_base64"]), _img(cmap["canny_png_base64"])]
        tiles += [_img(cmap["lines_png_base64"]), _img(render["png_base64"])]
        height = min(t.shape[0] for t in tiles)
        cv2.imwrite(str(out / f"side_by_side_{name}.png"), cv2.hconcat([t[:height] for t in tiles]))
        print(
            f"demo-phase7: {name}: edge_px={cmap['stats']['edge_px']} "
            f"line_count={cmap['stats']['line_count']} render={render['status']}"
        )
    (out / "prompt.txt").write_text(resp["prompt"]["text"] + "\n")
    (out / "prompt.json").write_text(json.dumps(resp["prompt"], indent=2) + "\n")
    (out / "candidates.json").write_text(json.dumps(resp["candidates"], indent=2) + "\n")

    sel_req = golden_selection_request(chain, model)
    sel = validate_selection(
        sel_req["layout"],
        sel_req["id_map_ids"],
        sel_req["finish_tier"],
        sel_req["catalog_version"],
        sel_req["render_ref"],
        sel_req["selection"],
        True,
    )
    (out / "finish_selection_request.json").write_text(
        json.dumps(sel_req["selection"], indent=2) + "\n"
    )
    (out / "finish_selection_ops.json").write_text(json.dumps(sel["ops"], indent=2) + "\n")
    (out / "review_items.json").write_text(
        json.dumps(resp["review_items"] + sel["review_items"], indent=2) + "\n"
    )
    counts = sel["diagnostics"]["counts"]
    print(
        f"demo-phase7: finish selection ops={counts['ops']} "
        f"walls_applied={counts['walls_applied']} conflicts={counts['walls_conflict']} "
        f"blocking={counts['blocking']} -> {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
