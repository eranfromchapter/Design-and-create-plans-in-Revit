"""Control maps for the render conditioning (docs/PHASE7_DESIGN.md P7-04): the exported
PNG is alpha-composited on white (the sim's resvg output is transparent RGBA — decoding
it as BGR would yield zero edges), converted to gray, Canny(100, 200) gives the edge map
and a classical HoughLinesP over it gives the line map (deviation D-2: the stand-in for
the learned M-LSD; byte-deterministic under the pinned OpenCV wheel because HoughLinesP
seeds its RNG with a constant). Pure: no clock, no environment, no randomness."""

from __future__ import annotations

import base64
import binascii
import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

CANNY_LOW = 100
CANNY_HIGH = 200
HOUGH_RHO_PX = 1.0
HOUGH_THETA_RAD = math.pi / 180
HOUGH_THRESHOLD_DIV = 40  # threshold = max(HOUGH_THRESHOLD_MIN, px // 40)      -> 51 @ 2048
HOUGH_MIN_LEN_DIV = 64  # minLineLength = max(HOUGH_MIN_LEN_MIN, px // 64)     -> 32 @ 2048
HOUGH_MAX_GAP_DIV = 256  # maxLineGap = max(HOUGH_MAX_GAP_MIN, px // 256)      -> 8 @ 2048
HOUGH_THRESHOLD_MIN = 20
HOUGH_MIN_LEN_MIN = 8
HOUGH_MAX_GAP_MIN = 2
LINE_THICKNESS_PX = 1
LINE_COLOR = 255
PREVIEW_PX = 512
PNG_COMPRESSION = 6
MAX_PNG_BYTES = 16 * 2**20
MAX_DIM_PX = 4096
MIN_DIM_PX = 64


class MapError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ControlMap:
    name: str
    kind: str
    canny_png: bytes
    lines_png: bytes
    preview_png: bytes
    stats: dict[str, Any]


def decode_base64_png(data_b64: str) -> bytes:
    try:
        data = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError) as err:
        raise MapError("png_invalid", f"png_base64 is not valid base64: {err}") from err
    if len(data) > MAX_PNG_BYTES:
        raise MapError("png_too_large", f"{len(data)} bytes > {MAX_PNG_BYTES}")
    return data


def decode_png(data: bytes) -> np.ndarray:
    if len(data) > MAX_PNG_BYTES:
        raise MapError("png_too_large", f"{len(data)} bytes > {MAX_PNG_BYTES}")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None or img.ndim not in (2, 3):
        raise MapError("png_invalid", "not a decodable PNG")
    h, w = img.shape[:2]
    if min(h, w) < MIN_DIM_PX or max(h, w) > MAX_DIM_PX:
        raise MapError("view_dims_invalid", f"{w}x{h} outside {MIN_DIM_PX}..{MAX_DIM_PX}")
    return img


def composite_on_white(img: np.ndarray) -> np.ndarray:
    """RGBA -> BGR over white with integer math (deterministic); gray/BGR pass through."""
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    channels = img.shape[2]
    if channels == 4:
        bgr = img[:, :, :3].astype(np.uint16)
        alpha = img[:, :, 3:4].astype(np.uint16)
        out = (bgr * alpha + 255 * (255 - alpha)) // 255
        return out.astype(np.uint8)
    if channels == 3:
        return img
    raise MapError("png_invalid", f"unsupported channel count {channels}")


def canny_map(gray: np.ndarray) -> np.ndarray:
    return cv2.Canny(gray, CANNY_LOW, CANNY_HIGH)


def hough_params(px: int) -> tuple[int, int, int]:
    return (
        max(HOUGH_THRESHOLD_MIN, px // HOUGH_THRESHOLD_DIV),
        max(HOUGH_MIN_LEN_MIN, px // HOUGH_MIN_LEN_DIV),
        max(HOUGH_MAX_GAP_MIN, px // HOUGH_MAX_GAP_DIV),
    )


def lines_map(canny: np.ndarray, px: int) -> tuple[np.ndarray, int]:
    threshold, min_len, max_gap = hough_params(px)
    segments = cv2.HoughLinesP(
        canny,
        HOUGH_RHO_PX,
        HOUGH_THETA_RAD,
        threshold,
        minLineLength=min_len,
        maxLineGap=max_gap,
    )
    out = np.zeros_like(canny)
    if segments is None:
        return out, 0
    for x1, y1, x2, y2 in segments[:, 0, :]:
        cv2.line(
            out, (int(x1), int(y1)), (int(x2), int(y2)), LINE_COLOR, LINE_THICKNESS_PX, cv2.LINE_8
        )
    return out, int(len(segments))


def preview(bgr: np.ndarray) -> np.ndarray:
    h, w = bgr.shape[:2]
    if w <= PREVIEW_PX:
        return bgr
    height = max(1, round(h * PREVIEW_PX / w))
    return cv2.resize(bgr, (PREVIEW_PX, height), interpolation=cv2.INTER_AREA)


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, PNG_COMPRESSION])
    if not ok:
        raise MapError("png_encode_failed", "cv2.imencode returned false")
    return bytes(buf)


def build_control_map(name: str, kind: str, png: bytes) -> ControlMap:
    img = decode_png(png)
    bgr = composite_on_white(img)
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    canny = canny_map(gray)
    lines, line_count = lines_map(canny, w)
    return ControlMap(
        name=name,
        kind=kind,
        canny_png=encode_png(canny),
        lines_png=encode_png(lines),
        preview_png=encode_png(preview(bgr)),
        stats={
            "edge_px": int(cv2.countNonZero(canny)),
            "line_count": line_count,
            "width": int(w),
            "height": int(h),
        },
    )
