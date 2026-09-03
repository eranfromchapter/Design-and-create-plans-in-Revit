"""AIDM contract test against the in-process fake (PLAN Phase 7 acceptance: AIDM contract
test against mock; retry/backoff) and the request deadline."""

import base64

from fake_aidm import FakeAidm, FakeClock
from helpers import render_request, tiny_png, view

from aidm_bridge import render as render_module
from aidm_bridge.aidm import (
    MAX_ATTEMPTS,
    MAX_POLLS,
    REF_RE,
    HttpRenderer,
    MockRenderer,
    RenderJob,
    job_seed,
)
from aidm_bridge.control_maps import build_control_map
from aidm_bridge.render import RENDER_TIME_LIMIT_S, RenderOptions, render_views


def _job() -> RenderJob:
    cmap = build_control_map("plan", "plan", tiny_png())
    return RenderJob(
        "r1", "plan", "plan", "prompt", "standard", cmap.canny_png, cmap.lines_png, 96, 96, 7
    )


def _renderer(fake: FakeAidm, clock: FakeClock, key: str | None = "k") -> HttpRenderer:
    return HttpRenderer(
        "http://aidm.test/",
        key,
        transport=fake.transport(),
        clock=clock.monotonic,
        sleep=clock.sleep,
    )


def test_http_renderer_success_follows_the_contract():
    fake, clock = FakeAidm(job_statuses=["running", "succeeded"]), FakeClock()
    outcome = _renderer(fake, clock).render(_job(), 60.0)
    assert outcome.status == "ok" and outcome.png == fake.image_png and outcome.attempts == 1
    assert REF_RE.match(outcome.ref) and outcome.ref.startswith("aidm-job-42")
    body = fake.posts[0]["body"]
    assert set(body) == {"render_id", "view", "prompt", "control_maps", "size", "seed"}
    assert body["view"] == {"name": "plan", "kind": "plan"} and body["seed"] == 7
    assert base64.b64decode(body["control_maps"]["canny_png_base64"])
    assert fake.posts[0]["headers"]["authorization"] == "Bearer k"
    assert fake.gets == 2 and clock.slept == [1.0]  # one poll interval between the two GETs


def test_retry_500_then_success_backoff_schedule():
    fake, clock = FakeAidm(submit_statuses=[500, 202]), FakeClock()
    outcome = _renderer(fake, clock).render(_job(), 60.0)
    assert outcome.status == "ok" and outcome.attempts == 2
    assert clock.slept[0] == 0.5
    fake, clock = FakeAidm(submit_statuses=[500, 503, 202]), FakeClock()
    outcome = _renderer(fake, clock).render(_job(), 60.0)
    assert outcome.attempts == 3 and clock.slept[:2] == [0.5, 1.0]


def test_retry_exhausted_after_three_attempts():
    fake, clock = FakeAidm(submit_statuses=[500, 500, 500, 202]), FakeClock()
    outcome = _renderer(fake, clock).render(_job(), 60.0)
    assert outcome.status == "failed" and outcome.attempts == MAX_ATTEMPTS == 3
    assert len(fake.posts) == 3 and clock.slept == [0.5, 1.0]
    assert "exhausted" in (outcome.error or "")


def test_4xx_is_not_retried():
    fake, clock = FakeAidm(submit_statuses=[400]), FakeClock()
    outcome = _renderer(fake, clock, key=None).render(_job(), 60.0)
    assert outcome.status == "failed" and len(fake.posts) == 1 and clock.slept == []
    assert "authorization" not in fake.posts[0]["headers"]


def test_poll_deadline_timeout_is_bounded():
    fake, clock = FakeAidm(job_statuses=["running"] * 1000), FakeClock()
    outcome = _renderer(fake, clock).render(_job(), 5.0)
    assert outcome.status == "timeout"
    assert fake.gets <= 6 and fake.gets <= MAX_POLLS
    fake, clock = FakeAidm(job_statuses=["failed"]), FakeClock()
    assert _renderer(fake, clock).render(_job(), 5.0).status == "failed"


def test_render_views_skips_views_after_the_deadline(monkeypatch):
    clock = FakeClock()

    class SlowRenderer:
        provider = "slow"
        calls = 0

        def render(self, job, deadline_remaining_s):
            SlowRenderer.calls += 1
            clock.t += RENDER_TIME_LIMIT_S  # the first view eats the whole budget
            return render_module.RenderOutcome("timeout", None, "slow-1", 1, "took too long")

    req = render_request(
        views=[
            view("plan", "plan", tiny_png()),
            view("section", "section", tiny_png()),
            view("3d", "3d_hidden", tiny_png()),
        ]
    )
    result = render_views(req, SlowRenderer(), RenderOptions("p", True), clock=clock.monotonic)
    assert [r["status"] for r in result["renders"]] == [
        "timeout",
        "skipped_deadline",
        "skipped_deadline",
    ]
    assert SlowRenderer.calls == 1 and len(result["control_maps"]) == 3
    codes = [i["code"] for i in result["review_items"]]
    assert codes.count("render_timeout") == 3 and "render_failed" not in codes


def test_mock_renderer_is_deterministic_and_seed_is_stable():
    job = _job()
    a, b = MockRenderer().render(job, 10.0), MockRenderer().render(job, 10.0)
    assert a.status == "ok" and a.png == b.png and a.ref == "mock-r1-plan"
    assert job_seed("r1", "plan") == job_seed("r1", "plan") != job_seed("r1", "section")
