"""Envelope execution with the plugin's exact semantics (Part G):

- verification identical to the plugin (Ed25519 over received payload bytes via
  chapter_contracts, TTL at enqueue AND re-checked at dequeue, Execute-time seq
  against the PERSISTED last-committed seq),
- plus the executor-identity checks the shared verifier can't do: project binding
  (wrong_document) and workstation binding (wrong_workstation),
- one envelope per pass, applied to a model COPY — all-or-nothing swap is the sim's
  TransactionGroup; seq + id-map persist atomically with the commit,
- a rolled-back envelope does NOT consume its seq (the gateway may re-issue).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chapter_contracts import verify_envelope

from revit_sim.model import Catalogs, OpError, SimModel
from revit_sim.render.png import rasterize
from revit_sim.render.svg import render_plan
from revit_sim.state import SimState

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Executor:
    state: SimState
    blob_dir: Path
    project_id: str
    workstation_id: str
    public_key_hex: str
    clock: Clock = utc_now
    catalogs: Catalogs = field(default_factory=Catalogs.load)
    model: SimModel = field(default_factory=SimModel)

    def hello(self) -> dict[str, Any]:
        return {
            "type": "hello",
            "workstation_id": self.workstation_id,
            "plugin_version": "sim-0.1.0",
            "last_committed_seq": self.state.last_committed_seq,
            "id_map_hash": self.state.hash(),
        }

    def handle_envelope(self, wire: dict[str, str]) -> list[dict[str, Any]]:
        """Process one wire envelope; returns the WSS messages to send back."""
        # Enqueue-time verification (network thread on the plugin).
        result = verify_envelope(
            wire, self.public_key_hex, self.clock(), self.state.last_committed_seq
        )
        if result.status == "rejected":
            return [self._ack_rejected(wire, result.reason or "internal")]
        body = result.body
        assert body is not None

        if body["project_id"] != self.project_id:
            return [self._ack(body, "rejected", "wrong_document")]
        if body["workstation_id"] != self.workstation_id:
            return [self._ack(body, "rejected", "wrong_workstation")]

        messages: list[dict[str, Any]] = [self._ack(body, "accepted")]

        # Dequeue-time TTL re-check (SI-3): an envelope deferred past expiry never runs.
        issued = datetime.fromisoformat(body["issued_at"].replace("Z", "+00:00"))
        if self.clock().timestamp() > issued.timestamp() + body["ttl_s"]:
            messages.append(
                self._commit_result(
                    body,
                    committed=False,
                    errors=[{"code": "expired_ttl", "message": "expired before execution"}],
                )
            )
            return messages

        # One envelope per pass: apply to a COPY, swap on success (the TransactionGroup).
        # Element ids are allocated only at commit, so a rolled-back envelope burns
        # nothing and a re-issued one produces identical ids (golden determinism).
        working = self.model.clone()
        created: list[str] = []
        side_messages: list[dict[str, Any]] = []
        try:
            for index, op_call in enumerate(body["ops"]):
                try:
                    side = self._apply(working, op_call["op"], op_call["args"], created)
                    side_messages.extend(side)
                except OpError as err:
                    raise _EnvelopeFailure(index, err) from err
        except _EnvelopeFailure as failure:
            messages.append(
                self._commit_result(
                    body,
                    committed=False,
                    errors=[
                        {
                            "op_index": failure.index,
                            "code": failure.error.code,
                            "message": failure.error.message,
                        }
                    ],
                )
            )
            if failure.error.code == "interference":
                a_id, b_id = failure.error.message.split("~", 1)
                messages.append(
                    {
                        "type": "clash_delta",
                        "envelope_id": body["envelope_id"],
                        "pairs": [{"a_id": a_id, "b_id": b_id, "kind": "hard_interference"}],
                    }
                )
            return messages

        # Commit: model swap + seq + id-map persist together (Extensible Storage twin).
        self.model = working
        self.state.last_committed_seq = body["seq"]
        delta = [
            {"logical_id": logical_id, "element_id": self.state.allocate_element_id()}
            for logical_id in created
        ]
        for entry in delta:
            self.state.id_map[entry["logical_id"]] = entry["element_id"]
        self.state.save()
        # Debug/demo artifact (not a wire contract): the current plan, canonical bytes.
        # `make demo-phase1` and the e2e golden comparison read this file directly.
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        (self.blob_dir / "current_plan.svg").write_text(render_plan(self.model))

        messages.append(self._commit_result(body, committed=True, delta=delta))
        messages.extend(side_messages)
        return messages

    # ---- helpers -----------------------------------------------------------

    def _apply(
        self,
        working: SimModel,
        op: str,
        args: dict[str, Any],
        created: list[str],
    ) -> list[dict[str, Any]]:
        """Apply one op to the working model; returns side messages (exports)."""
        if op == "export_views":
            out: list[dict[str, Any]] = []
            for view in args["views"]:
                if view["kind"] == "plan":
                    svg = render_plan(working)
                    png = rasterize(svg, view["px"])
                else:
                    # section/3d_hidden: not modeled in the Phase 1 sim; a 1x1 placeholder
                    # keeps the export contract exercised without pretending geometry.
                    png = rasterize('<svg xmlns="http://www.w3.org/2000/svg"/>', 1)
                out.append(
                    {
                        "type": "export_ready",
                        "kind": "view",
                        "blob_ref": self._store_blob(png),
                    }
                )
            return out
        if op == "export_parameters":
            doc = json.dumps(working.parameters, sort_keys=True).encode()
            return [
                {"type": "export_ready", "kind": "parameters", "blob_ref": self._store_blob(doc)}
            ]
        if op == "verify_deviation":
            doc = json.dumps({"walls": args["wall_ids"], "pass": True}, sort_keys=True).encode()
            return [
                {"type": "export_ready", "kind": "deviation", "blob_ref": self._store_blob(doc)}
            ]
        if op == "verify_model_state":
            doc = json.dumps(
                {"id_map_hash": self.state.hash(), "elements": sorted(working.all_ids())},
                sort_keys=True,
            ).encode()
            return [
                {"type": "export_ready", "kind": "model_state", "blob_ref": self._store_blob(doc)}
            ]

        logical_id = working.apply(op, args, self.catalogs)
        if logical_id is not None:
            created.append(logical_id)
        return []

    def _store_blob(self, content: bytes) -> str:
        """Content-addressed local blob store (Azure Blob in later phases)."""
        ref = hashlib.sha256(content).hexdigest()
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        (self.blob_dir / ref).write_bytes(content)
        return ref

    def _ack(self, body: dict[str, Any], status: str, reason: str | None = None) -> dict[str, Any]:
        msg: dict[str, Any] = {"type": "ack", "envelope_id": body["envelope_id"], "status": status}
        if reason:
            msg["reason"] = reason
        return msg

    def _ack_rejected(self, wire: dict[str, str], reason: str) -> dict[str, Any]:
        # The envelope may be unparseable; recover the id when possible for the ack.
        try:
            envelope_id = json.loads(wire["payload"])["envelope_id"]
        except Exception:
            envelope_id = "00000000-0000-0000-0000-000000000000"
        return {"type": "ack", "envelope_id": envelope_id, "status": "rejected", "reason": reason}

    def _commit_result(
        self,
        body: dict[str, Any],
        committed: bool,
        delta: list[dict[str, Any]] | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "commit_result",
            "envelope_id": body["envelope_id"],
            "status": "committed" if committed else "rolled_back",
            "id_map_delta": delta or [],
            "errors": errors or [],
        }


class _EnvelopeFailure(Exception):
    def __init__(self, index: int, error: OpError):
        super().__init__(str(error))
        self.index = index
        self.error = error
