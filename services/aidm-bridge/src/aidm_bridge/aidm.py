"""The render seam (docs/PHASE7_DESIGN.md P7-06): `Renderer` is the interface, `MockRenderer`
is deterministic (selected when AIDM_ENDPOINT is empty), `HttpRenderer` implements OUR
proposed AIDM job contract (AIDM_CONTRACT.md — an assumption until Chapter's AIDM API is
confirmed). Everything is bounded: attempts, polls, per-call timeouts and the caller's
deadline. The clock and sleep are injected so tests never wait."""

from __future__ import annotations

import base64
import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import cv2
import httpx
import numpy as np

from aidm_bridge.control_maps import decode_png, encode_png

MAX_ATTEMPTS = 3
RETRY_SLEEPS_S = (0.5, 1.0, 2.0)  # sleep k-1 before retry k: 3 attempts sleep 0.5 and 1.0
POLL_INTERVAL_S = 1.0
MAX_POLLS = 120
HTTP_TIMEOUT_S = 10.0
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
REF_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# a flat tint per tier so the mock "render" is visibly a render, not the line map (BGR)
TIER_TINT_BGR = {
    "economy": (235, 235, 235),
    "standard": (214, 232, 244),
    "premium": (205, 222, 240),
    "luxury": (226, 214, 238),
}
TINT_WEIGHT = 0.2


class AidmError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RenderJob:
    render_id: str
    view_name: str
    view_kind: str
    prompt: str
    finish_tier: str
    canny_png: bytes
    lines_png: bytes
    width: int
    height: int
    seed: int


@dataclass(frozen=True)
class RenderOutcome:
    status: str  # ok | failed | timeout | skipped_deadline
    png: bytes | None
    ref: str
    attempts: int
    error: str | None = None


class Renderer(Protocol):
    provider: str

    def render(self, job: RenderJob, deadline_remaining_s: float) -> RenderOutcome: ...


def job_seed(render_id: str, view_name: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{render_id}/{view_name}".encode()).digest()[:4], "big")


def safe_ref(text: str) -> str:
    ref = re.sub(r"[^a-z0-9_-]", "-", text.lower()).lstrip("-_")[:64]
    return ref if REF_RE.match(ref) else "ref-" + hashlib.sha256(text.encode()).hexdigest()[:40]


class MockRenderer:
    """Deterministic stand-in: the line map inverted (black lines on white) blended with a
    flat per-tier tint. Same job -> same bytes; never touches the network."""

    provider = "mock"

    def render(self, job: RenderJob, deadline_remaining_s: float) -> RenderOutcome:
        lines = decode_png(job.lines_png)
        if lines.ndim == 3:
            lines = cv2.cvtColor(lines, cv2.COLOR_BGR2GRAY)
        inverted = cv2.cvtColor(255 - lines, cv2.COLOR_GRAY2BGR).astype(np.uint16)
        tint = np.array(TIER_TINT_BGR.get(job.finish_tier, TIER_TINT_BGR["standard"]), np.uint16)
        weight = int(TINT_WEIGHT * 100)
        blended = (inverted * (100 - weight) + tint * weight) // 100
        png = encode_png(blended.astype(np.uint8))
        return RenderOutcome("ok", png, safe_ref(f"mock-{job.render_id}-{job.view_name}"), 1)


class HttpRenderer:
    """AIDM_CONTRACT.md: POST /v1/renders -> 202 {job_id}; GET /v1/jobs/{id} -> {status,
    images, error}. Retries submit on 429/5xx/transport errors with the fixed backoff,
    never on other 4xx; polls until succeeded/failed, the caller's deadline or MAX_POLLS."""

    provider = "aidm"

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(
            base_url=endpoint.rstrip("/"),
            timeout=HTTP_TIMEOUT_S,
            transport=transport,
            headers=headers,
        )
        self._clock = clock
        self._sleep = sleep

    def render(self, job: RenderJob, deadline_remaining_s: float) -> RenderOutcome:
        deadline = self._clock() + deadline_remaining_s
        body = {
            "render_id": job.render_id,
            "view": {"name": job.view_name, "kind": job.view_kind},
            "prompt": job.prompt,
            "control_maps": {
                "canny_png_base64": base64.b64encode(job.canny_png).decode(),
                "lines_png_base64": base64.b64encode(job.lines_png).decode(),
            },
            "size": {"width": job.width, "height": job.height},
            "seed": job.seed,
        }
        job_id: str | None = None
        attempts = 0
        last_error = "not submitted"
        while attempts < MAX_ATTEMPTS and job_id is None:
            if attempts:
                self._sleep(RETRY_SLEEPS_S[attempts - 1])
            attempts += 1
            try:
                response = self._client.post("/v1/renders", json=body)
            except httpx.TransportError as err:
                last_error = f"transport: {err.__class__.__name__}"
                continue
            if response.status_code == 202:
                job_id = str(response.json().get("job_id", ""))
                if not job_id:
                    return RenderOutcome("failed", None, "", attempts, "202 without job_id")
                break
            last_error = f"HTTP {response.status_code}"
            if response.status_code not in RETRYABLE_STATUSES:
                return RenderOutcome("failed", None, "", attempts, last_error)
        if job_id is None:
            return RenderOutcome("failed", None, "", attempts, f"submit exhausted: {last_error}")

        ref = safe_ref(f"aidm-{job_id}")
        polls = 0
        while polls < MAX_POLLS:
            if self._clock() >= deadline:
                return RenderOutcome(
                    "timeout", None, ref, attempts, "deadline reached while polling"
                )
            polls += 1
            try:
                response = self._client.get(f"/v1/jobs/{job_id}")
                payload: dict[str, Any] = response.json() if response.status_code == 200 else {}
            except (httpx.TransportError, ValueError):
                payload = {}
            status = payload.get("status")
            if status == "succeeded":
                images = payload.get("images") or []
                if not images or "png_base64" not in images[0]:
                    return RenderOutcome(
                        "failed", None, ref, attempts, "succeeded without an image"
                    )
                try:
                    png = base64.b64decode(images[0]["png_base64"], validate=True)
                except ValueError:
                    return RenderOutcome("failed", None, ref, attempts, "image is not base64")
                return RenderOutcome("ok", png, ref, attempts)
            if status == "failed":
                return RenderOutcome(
                    "failed", None, ref, attempts, str(payload.get("error", "failed"))
                )
            self._sleep(POLL_INTERVAL_S)
        return RenderOutcome("timeout", None, ref, attempts, f"no result after {MAX_POLLS} polls")
