import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/signing.py helper

from signing import PROJECT_ID, PUBLIC_HEX, WORKSTATION_ID  # noqa: E402

from revit_sim.executor import Executor  # noqa: E402
from revit_sim.state import SimState  # noqa: E402


class FakeClock:
    """Injectable clock: pops queued instants, then repeats the last one. Lets tests
    make TTL valid at enqueue but expired at dequeue (SI-3 re-check)."""

    def __init__(self, *instants: str):
        self.queue = [
            datetime.fromisoformat(i.replace("Z", "+00:00")).astimezone(UTC) for i in instants
        ]

    def __call__(self) -> datetime:
        return self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]


@pytest.fixture
def make_executor(tmp_path: Path):
    def factory(clock: FakeClock | None = None, state_dir: Path | None = None) -> Executor:
        directory = state_dir or tmp_path
        return Executor(
            state=SimState.load(directory / "state"),
            blob_dir=directory / "blobs",
            project_id=PROJECT_ID,
            workstation_id=WORKSTATION_ID,
            public_key_hex=PUBLIC_HEX,
            clock=clock or FakeClock("2026-01-01T00:05:00Z"),
        )

    return factory
