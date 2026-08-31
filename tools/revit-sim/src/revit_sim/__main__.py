import argparse
import asyncio
import logging
from pathlib import Path

from revit_sim.client import SimClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Chapter revit-sim (headless executor)")
    parser.add_argument("--gateway-url", required=True, help="ws://host:port/wss")
    parser.add_argument("--token", required=True, help="workstation bearer token")
    parser.add_argument("--workstation-id", required=True)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--blob-dir", required=True, type=Path)
    parser.add_argument(
        "--control-port",
        type=int,
        default=None,
        help="TEST HOOK: local TCP control port (0 = ephemeral); never in production",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    client = SimClient(
        gateway_url=args.gateway_url,
        token=args.token,
        workstation_id=args.workstation_id,
        state_dir=args.state_dir,
        blob_dir=args.blob_dir,
        control_port=args.control_port,
    )
    asyncio.run(client.run())


if __name__ == "__main__":
    main()
