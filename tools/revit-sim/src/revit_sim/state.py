"""Persisted executor state: last-committed seq + id-map + pinned public key.

Mirrors the plugin's Extensible Storage semantics: seq and id-map roll forward (and,
on the plugin, roll BACK) together, so restart/resync reports the model's truth.
Writes are atomic (temp file + os.replace)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from chapter_contracts import id_map_hash


@dataclass
class SimState:
    path: Path
    last_committed_seq: int = 0
    id_map: dict[str, int] = field(default_factory=dict)
    next_element_ordinal: int = 1
    pinned_public_key: str | None = None

    @classmethod
    def load(cls, state_dir: Path) -> SimState:
        path = state_dir / "sim_state.json"
        if path.exists():
            doc = json.loads(path.read_text())
            return cls(
                path=path,
                last_committed_seq=doc["last_committed_seq"],
                id_map=doc["id_map"],
                next_element_ordinal=doc["next_element_ordinal"],
                pinned_public_key=doc.get("pinned_public_key"),
            )
        state_dir.mkdir(parents=True, exist_ok=True)
        return cls(path=path)

    def save(self) -> None:
        doc = {
            "last_committed_seq": self.last_committed_seq,
            "id_map": self.id_map,
            "next_element_ordinal": self.next_element_ordinal,
            "pinned_public_key": self.pinned_public_key,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=2, sort_keys=True))
        os.replace(tmp, self.path)

    def hash(self) -> str:
        return id_map_hash(self.id_map)

    def allocate_element_id(self) -> int:
        element_id = 1_000_000 + self.next_element_ordinal
        self.next_element_ordinal += 1
        return element_id

    def pin_public_key(self, key_hex: str) -> None:
        """TOFU pin: a silently changed signing key is refused (D3 key delivery)."""
        if self.pinned_public_key is None:
            self.pinned_public_key = key_hex
            self.save()
        elif self.pinned_public_key != key_hex:
            raise RuntimeError("gateway signing key changed — refusing (re-enroll to rotate)")
