"""An in-process AIDM per AIDM_CONTRACT.md, scripted per test, served through
httpx.MockTransport (sync, no sockets), plus a fake monotonic clock whose sleep advances it."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field

import httpx
from helpers import tiny_png


@dataclass
class FakeAidm:
    submit_statuses: list[int] = field(default_factory=list)  # consumed per POST; then 202
    job_statuses: list[str] = field(default_factory=list)  # consumed per GET; then succeeded
    image_png: bytes = field(default_factory=tiny_png)
    posts: list[dict] = field(default_factory=list)
    gets: int = 0
    job_id: str = "job-42"

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/renders":
            self.posts.append(
                {"headers": dict(request.headers), "body": json.loads(request.content)}
            )
            status = self.submit_statuses.pop(0) if self.submit_statuses else 202
            if status == 202:
                return httpx.Response(202, json={"job_id": self.job_id})
            return httpx.Response(status, json={"error": f"status {status}"})
        if request.method == "GET" and request.url.path == f"/v1/jobs/{self.job_id}":
            self.gets += 1
            status = self.job_statuses.pop(0) if self.job_statuses else "succeeded"
            if status == "succeeded":
                return httpx.Response(
                    200,
                    json={
                        "status": "succeeded",
                        "images": [{"png_base64": base64.b64encode(self.image_png).decode()}],
                    },
                )
            if status == "failed":
                return httpx.Response(200, json={"status": "failed", "error": "gpu on fire"})
            return httpx.Response(200, json={"status": status})
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.t = start
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds
