"""CLI: serve the extractor (harness/e2e mode) or run the pipeline on transcript
files (make demo-phase3 / manual runs).

  python -m brief_extractor --serve [--port 0]           # prints "LISTENING <port>"
  python -m brief_extractor s1.txt s2.txt [--live]       # brief JSON + contradiction diff
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

TEST_PROJECT_ID = "1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01"


def main() -> int:
    parser = argparse.ArgumentParser(prog="brief-extractor")
    parser.add_argument("transcripts", nargs="*", help="transcript files, chronological order")
    parser.add_argument("--serve", action="store_true", help="run the HTTP service")
    parser.add_argument("--port", type=int, default=0, help="port for --serve (0 = ephemeral)")
    parser.add_argument("--live", action="store_true", help="use the real Anthropic API")
    parser.add_argument("--project-id", default=TEST_PROJECT_ID)
    args = parser.parse_args()

    if args.serve:
        import uvicorn

        from brief_extractor.server import app

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", args.port))
        sock.listen(128)
        print(f"LISTENING {sock.getsockname()[1]}", flush=True)
        uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
        return 0

    if not args.transcripts:
        parser.error("either --serve or transcript files are required")

    from brief_extractor.extract import (
        ExtractError,
        ExtractOptions,
        Session,
        contradiction_diff,
        extract_brief,
    )

    if args.live:
        from brief_extractor.llm import AnthropicLLM

        llm = AnthropicLLM()
    else:
        from brief_extractor.fixtures import FixtureLLM

        llm = FixtureLLM()

    sessions = [Session(Path(p).stem, Path(p).read_text()) for p in args.transcripts]
    try:
        result = extract_brief(
            sessions, ExtractOptions(project_id=args.project_id, brief_version=1), llm
        )
    except ExtractError as err:
        print(json.dumps({"error": err.code, "message": err.message}, indent=2))
        return 1
    print(json.dumps(result["brief"], indent=2))
    print()
    print(contradiction_diff(result["brief"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
