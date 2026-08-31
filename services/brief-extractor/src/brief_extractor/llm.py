"""LLM boundary. Everything upstream of this module is deterministic; everything
that reaches this module has already been PII-scrubbed (SI-11). The interface is
the mock seam: CI runs ScriptedLLM only; AnthropicLLM is constructed solely when
a live call is explicitly wanted (RUN_LIVE_LLM=1 smoke, or production)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

TOOL_NAME = "record_brief"
TOOL_DESCRIPTION = (
    "Record the structured renovation brief extracted from the client session transcript."
)


@dataclass(frozen=True)
class LlmCall:
    """What crossed the boundary — recorded by ScriptedLLM so tests can assert the
    PII scrub and prompt structure without ever seeing a live API."""

    system: str
    user_text: str


class ExtractorLLM(Protocol):
    def extract(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        """One forced record_brief call; returns the tool input dict."""
        ...


class AnthropicLLM:
    """Real Anthropic client. Model pinned via LLM_MODEL_EXTRACTOR (.env.example);
    tool-enforced output via forced tool_choice."""

    def __init__(self, model: str | None = None):
        import anthropic  # lazy: CI never imports a configured client

        self._client = anthropic.Anthropic()
        self._model = model or os.environ.get("LLM_MODEL_EXTRACTOR", "claude-sonnet-5")

    def extract(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            tools=[
                {
                    "name": TOOL_NAME,
                    "description": TOOL_DESCRIPTION,
                    "input_schema": tool_schema,
                }
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                return dict(block.input)
        raise RuntimeError(
            f"no {TOOL_NAME} tool_use block in response (stop={response.stop_reason})"
        )


@dataclass
class ScriptedLLM:
    """Fixture-backed mock: pops the next scripted tool input per call and records
    everything that crossed the boundary."""

    script: list[dict[str, Any]]
    calls: list[LlmCall] = field(default_factory=list)

    def extract(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(LlmCall(system=system, user_text=user_text))
        if not self.script:
            raise AssertionError("ScriptedLLM exhausted: unexpected extra LLM call")
        return self.script.pop(0)
