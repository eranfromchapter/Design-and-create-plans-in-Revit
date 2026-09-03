"""CLI: serve the bridge (harness/e2e mode) or build control maps + a mock render for PNG
files (manual runs).

  python -m aidm_bridge --serve [--port 0]                 # prints "LISTENING <port>"
  python -m aidm_bridge render plan.png [more.png ...] --out-dir DIR
"""

from __future__ import annotations

import argparse
import base64
import json
import socket
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="aidm-bridge")
    parser.add_argument("command", nargs="?", choices=["render"], help="manual run mode")
    parser.add_argument("pngs", nargs="*", help="exported view PNG files (render mode)")
    parser.add_argument("--serve", action="store_true", help="run the HTTP service")
    parser.add_argument("--port", type=int, default=0, help="port for --serve (0 = ephemeral)")
    parser.add_argument("--out-dir", default="out/aidm-bridge", help="render mode output dir")
    parser.add_argument("--tier", default="standard", help="finish tier for the prompt")
    parser.add_argument("--tags", default="", help="comma-separated style tags")
    args = parser.parse_args()

    if args.serve:
        import uvicorn

        from aidm_bridge.server import app

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", args.port))
        sock.listen(128)
        print(f"LISTENING {sock.getsockname()[1]}", flush=True)
        uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
        return 0

    if args.command != "render" or not args.pngs:
        parser.error("either --serve or: render <view.png> [...] [--out-dir DIR]")

    from aidm_bridge.aidm import MockRenderer
    from aidm_bridge.render import RenderError, RenderOptions, render_views

    views = []
    for path in args.pngs:
        name = Path(path).stem.lower().replace(" ", "-")
        kind = "section" if "section" in name else ("3d_hidden" if "3d" in name else "plan")
        views.append(
            {
                "name": name,
                "kind": kind,
                "px": 2048,
                "png_base64": base64.b64encode(Path(path).read_bytes()).decode(),
            }
        )
    request = {
        "project_id": "00000000-0000-4000-8000-000000000000",
        "render_id": "cli",
        "views": views,
        "style_tags": [t.strip() for t in args.tags.split(",") if t.strip()],
        "finish_tier": args.tier,
        "rooms": [],
        "allow_placeholders": True,
    }
    try:
        result = render_views(request, MockRenderer(), RenderOptions("cli", True))
    except RenderError as err:
        print(json.dumps({"error": err.code, "message": err.message}, indent=2))
        return 1
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for cmap, render in zip(result["control_maps"], result["renders"], strict=True):
        for key, suffix in (("canny_png_base64", "canny"), ("lines_png_base64", "lines")):
            (out / f"{cmap['name']}_{suffix}.png").write_bytes(base64.b64decode(cmap[key]))
        if render["png_base64"]:
            (out / f"{cmap['name']}_render_mock.png").write_bytes(
                base64.b64decode(render["png_base64"])
            )
    (out / "prompt.txt").write_text(result["prompt"]["text"] + "\n")
    print(f"wrote {len(views)} view(s) of control maps + mock renders to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
