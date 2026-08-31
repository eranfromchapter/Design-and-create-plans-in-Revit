"""PNG rasterization of the canonical SVG (export_views): one image format from both
executors (amendment critic-2). PNG bytes are never goldened — only the SVG is —
so rasterizer determinism is not load-bearing. resvg (Rust, bundled wheels); if the
wheels ever become unavailable, swap this one function for cairosvg + libcairo2."""

from __future__ import annotations

import resvg_py


def rasterize(svg: str, px: int) -> bytes:
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=px))
