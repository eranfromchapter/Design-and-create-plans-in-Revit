"""CLI: serve the compiler (harness/e2e mode) or run the pipeline on files
(make demo-phase4 / manual runs).

  python -m layout_compiler --serve [--port 0]                    # prints "LISTENING <port>"
  python -m layout_compiler brief.json existing.json [--live] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="layout-compiler")
    parser.add_argument("brief", nargs="?", help="confirmed ClientBrief JSON file")
    parser.add_argument("existing", nargs="?", help="frozen Commit #0 ChapterLayout JSON file")
    parser.add_argument("--serve", action="store_true", help="run the HTTP service")
    parser.add_argument("--port", type=int, default=0, help="port for --serve (0 = ephemeral)")
    parser.add_argument("--live", action="store_true", help="use the real Anthropic API")
    parser.add_argument("--out-dir", help="write new_layout.json, ops.json and the card SVGs here")
    args = parser.parse_args()

    if args.serve:
        import uvicorn

        from layout_compiler.server import app

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", args.port))
        sock.listen(128)
        print(f"LISTENING {sock.getsockname()[1]}", flush=True)
        uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
        return 0

    if not (args.brief and args.existing):
        parser.error("either --serve or both a brief file and an existing-layout file")

    from layout_compiler.compile import CompileError, CompileOptions, compile_layout

    if args.live:
        from layout_compiler.llm import AnthropicLLM

        llm = AnthropicLLM()
    else:
        from layout_compiler.fixtures import FixtureLLM

        llm = FixtureLLM()

    brief = json.loads(Path(args.brief).read_text())
    existing = json.loads(Path(args.existing).read_text())
    try:
        result = compile_layout(
            brief, existing, CompileOptions(project_id=brief["meta"]["project_id"]), llm
        )
    except CompileError as err:
        print(json.dumps({"error": err.code, "message": err.message}, indent=2))
        return 1

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "new_layout.json").write_text(json.dumps(result["layout"], indent=2) + "\n")
        (out / "ops.json").write_text(json.dumps(result["ops"], indent=2) + "\n")
        (out / "demolition.json").write_text(json.dumps(result["demolition"], indent=2) + "\n")
        (out / "existing_plan.svg").write_text(result["svgs"]["existing"])
        (out / "new_plan.svg").write_text(result["svgs"]["new"])
        print(f"wrote {out}/new_layout.json, ops.json, demolition.json + 2 card SVGs")
    else:
        print(json.dumps(result["layout"], indent=2))
    print(
        f"# attempts={result['diagnostics']['attempts']} "
        f"ops={len(result['ops'])} demolished={len(result['demolition'])}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
