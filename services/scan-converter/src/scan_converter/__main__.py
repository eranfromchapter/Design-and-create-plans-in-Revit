"""CLI: serve the converter (harness/e2e mode) or convert one DXF file (demo +
the live-Revit gate run).

  python -m scan_converter --serve [--port 0]      # prints "LISTENING <port>"
  python -m scan_converter plan.dxf --review       # print review payload JSON
  python -m scan_converter plan.dxf --layout       # print layout JSON
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

TEST_PROJECT_ID = "1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01"


def main() -> int:
    parser = argparse.ArgumentParser(prog="scan-converter")
    parser.add_argument("dxf", nargs="?", help="DXF file to convert (file mode)")
    parser.add_argument("--serve", action="store_true", help="run the HTTP service")
    parser.add_argument("--port", type=int, default=0, help="port for --serve (0 = ephemeral)")
    parser.add_argument("--review", action="store_true", help="print the review payload")
    parser.add_argument("--layout", action="store_true", help="print the layout JSON")
    parser.add_argument("--project-id", default=TEST_PROJECT_ID)
    parser.add_argument("--ceiling", type=float, default=2700.0)
    args = parser.parse_args()

    if args.serve:
        import uvicorn

        from scan_converter.server import app

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", args.port))
        sock.listen(128)
        # readiness line BEFORE uvicorn takes over — same convention as the gateway
        print(f"LISTENING {sock.getsockname()[1]}", flush=True)
        uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
        return 0

    if not args.dxf:
        parser.error("either --serve or a DXF file is required")
    from scan_converter.lane_a import ConvertError, ConvertOptions, convert

    try:
        result = convert(
            Path(args.dxf).read_bytes(),
            ConvertOptions(project_id=args.project_id, ceiling_default_mm=args.ceiling),
        )
    except ConvertError as err:
        print(json.dumps({"error": err.code, "message": err.message}, indent=2))
        return 1
    if args.layout:
        print(json.dumps(result["layout"], indent=2))
    else:
        print(json.dumps(result["review_payload"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
