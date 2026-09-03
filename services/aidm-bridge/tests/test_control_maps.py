"""Control-map golden + determinism (PLAN Phase 7 acceptance: fixture PNG -> deterministic
edge outputs) and the RGBA-composite pitfall."""

import cv2
import numpy as np
import pytest
from helpers import tiny_png
from revit_sim.render.png import rasterize

from aidm_bridge.control_maps import (
    MAX_DIM_PX,
    MAX_PNG_BYTES,
    MIN_DIM_PX,
    PREVIEW_PX,
    MapError,
    build_control_map,
    decode_base64_png,
    decode_png,
    hough_params,
)
from aidm_bridge.golden_render import FILES, PX, VIEWS

EDGE_PX_TOL = 0.02
LINE_COUNT_TOL = 0.05


@pytest.mark.parametrize("name,kind", VIEWS)
def test_golden_maps_byte_identical(name, kind):
    cmap = build_control_map(name, kind, FILES[f"png_{name}"].read_bytes())
    assert cmap.canny_png == FILES[f"canny_{name}"].read_bytes()
    assert cmap.lines_png == FILES[f"lines_{name}"].read_bytes()
    assert cmap.stats["edge_px"] > 0 and cmap.stats["width"] == PX


def test_maps_deterministic_twice():
    png = FILES["png_plan"].read_bytes()
    a = build_control_map("plan", "plan", png)
    b = build_control_map("plan", "plan", png)
    assert (a.canny_png, a.lines_png, a.preview_png, a.stats) == (
        b.canny_png,
        b.lines_png,
        b.preview_png,
        b.stats,
    )


@pytest.mark.parametrize("name,kind", VIEWS)
def test_live_sim_rasterization_within_tolerance(golden, name, kind):
    """The live sim -> resvg -> maps path stays within tolerance of the committed goldens,
    so a resvg re-pin never breaks CI silently (the byte goldens catch OpenCV drift)."""
    live = build_control_map(name, kind, rasterize(golden["svgs"][name], PX))
    pinned = build_control_map(name, kind, FILES[f"png_{name}"].read_bytes())
    assert (
        abs(live.stats["edge_px"] - pinned.stats["edge_px"])
        <= EDGE_PX_TOL * pinned.stats["edge_px"]
    )
    assert abs(live.stats["line_count"] - pinned.stats["line_count"]) <= max(
        2, LINE_COUNT_TOL * pinned.stats["line_count"]
    )


def test_transparent_background_composited_on_white():
    png = tiny_png(rgba=True)
    cmap = build_control_map("t", "plan", png)
    assert cmap.stats["edge_px"] > 0
    # the pitfall: decoding RGBA as BGR drops alpha -> an all-black image -> zero edges
    naive = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    assert cv2.countNonZero(cv2.Canny(cv2.cvtColor(naive, cv2.COLOR_BGR2GRAY), 100, 200)) == 0


def test_opaque_input_gives_the_same_edges_as_transparent():
    a = build_control_map("a", "plan", tiny_png(rgba=True))
    b = build_control_map("b", "plan", tiny_png(rgba=False))
    assert a.canny_png == b.canny_png


def test_hough_params_scale_with_px():
    assert hough_params(256) == (20, 8, 2)
    assert hough_params(2048) == (51, 32, 8)
    assert hough_params(4096) == (102, 64, 16)


def test_invalid_png_and_limits():
    with pytest.raises(MapError) as err:
        decode_png(b"not a png at all")
    assert err.value.code == "png_invalid"
    with pytest.raises(MapError) as err:
        decode_png(b"\x00" * (MAX_PNG_BYTES + 1))
    assert err.value.code == "png_too_large"
    with pytest.raises(MapError) as err:
        build_control_map("s", "plan", tiny_png(MIN_DIM_PX - 32, MIN_DIM_PX - 32))
    assert err.value.code == "view_dims_invalid"
    with pytest.raises(MapError) as err:
        decode_base64_png("@@@not-base64@@@")
    assert err.value.code == "png_invalid"
    assert MAX_DIM_PX == 4096


def test_preview_is_512_wide():
    cmap = build_control_map("plan", "plan", FILES["png_plan"].read_bytes())
    img = cv2.imdecode(np.frombuffer(cmap.preview_png, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[1] == PREVIEW_PX
