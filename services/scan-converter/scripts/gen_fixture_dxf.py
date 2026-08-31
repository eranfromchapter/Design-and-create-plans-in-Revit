"""Provenance script for fixtures/scans/2br_uws.dxf (run from the repo root):

    cd services/scan-converter && uv run scripts/gen_fixture_dxf.py

The committed DXF is canonical and static — ezdxf stamps $VERSIONGUID and
$TDUPDATE on every save, so regeneration is NOT drift-gated in CI; the
entity-wise comparison in tests/test_fixture_drift.py is the drift protection.
Re-run this only when fixture_2br.py deliberately changes, and re-eyeball the
Phase 2 golden SVG afterwards."""

from __future__ import annotations

from pathlib import Path

from scan_converter.dxf_build import build_fixture_doc

OUT = Path(__file__).resolve().parents[3] / "fixtures" / "scans" / "2br_uws.dxf"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    build_fixture_doc().saveas(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
