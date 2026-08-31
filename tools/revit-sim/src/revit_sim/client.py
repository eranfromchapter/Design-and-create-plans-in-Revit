"""Outbound WSS client (the plugin's transport twin): connect with the workstation
bearer token, send hello (persisted seq + id-map hash), TOFU-pin the delivered
signing key, then execute envelopes strictly serially.

Test hook (--control-port): a local TCP line protocol used by the e2e drift test to
inject the same signal DocumentChangedWatcher produces on the real plugin —
"diverge\\n" perturbs the local id-map and emits state_divergence."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import websockets

from revit_sim.executor import Executor
from revit_sim.state import SimState

log = logging.getLogger("revit_sim")


class SimClient:
    def __init__(
        self,
        gateway_url: str,
        token: str,
        workstation_id: str,
        state_dir: Path,
        blob_dir: Path,
        control_port: int | None = None,
    ):
        self.gateway_url = gateway_url
        self.token = token
        self.workstation_id = workstation_id
        self.state_dir = state_dir
        self.blob_dir = blob_dir
        self.control_port = control_port
        self.executor: Executor | None = None
        self._ws: websockets.ClientConnection | None = None

    async def run(self) -> None:
        state = SimState.load(self.state_dir)
        async with websockets.connect(
            self.gateway_url,
            additional_headers={"Authorization": f"Bearer {self.token}"},
        ) as ws:
            self._ws = ws
            # hello first; auth_ok delivers project id + signing public key (D3).
            hello = {
                "type": "hello",
                "workstation_id": self.workstation_id,
                "plugin_version": "sim-0.1.0",
                "last_committed_seq": state.last_committed_seq,
                "id_map_hash": state.hash(),
            }
            await ws.send(json.dumps(hello))
            first = json.loads(await ws.recv())
            if first.get("type") != "auth_ok":
                raise RuntimeError(f"expected auth_ok, got {first}")
            state.pin_public_key(first["signing_public_key"])

            self.executor = Executor(
                state=state,
                blob_dir=self.blob_dir,
                project_id=first["project_id"],
                workstation_id=self.workstation_id,
                public_key_hex=state.pinned_public_key or first["signing_public_key"],
            )

            if self.control_port is not None:
                server = await asyncio.start_server(
                    self._control, host="127.0.0.1", port=self.control_port
                )
                port = server.sockets[0].getsockname()[1]
                print(f"CONTROL {port}", flush=True)

            print("READY", flush=True)
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "envelope":
                    # strictly serial: one envelope per pass (Part G)
                    for out in self.executor.handle_envelope(
                        {"payload": msg["payload"], "sig": msg["sig"]}
                    ):
                        await ws.send(json.dumps(out))
                elif msg.get("type") == "error":
                    log.warning("gateway error: %s", msg)

    async def _control(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        line = (await reader.readline()).decode().strip()
        if line == "diverge" and self.executor and self._ws:
            # Simulate a manual edit/undo detected by DocumentChangedWatcher: the local
            # id-map no longer matches what the gateway believes.
            self.executor.state.id_map["W-666"] = 9_999_999
            self.executor.state.save()
            await self._ws.send(
                json.dumps(
                    {
                        "type": "state_divergence",
                        "last_valid_seq": self.executor.state.last_committed_seq,
                        "id_map_hash": self.executor.state.hash(),
                        "detail": "test hook: simulated manual edit",
                    }
                )
            )
            writer.write(b"ok\n")
        else:
            writer.write(b"unknown\n")
        await writer.drain()
        writer.close()
