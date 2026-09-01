"""LLM boundary for the compiler — the mock seam. CI runs ScriptedLLM/FixtureLLM
only; AnthropicLLM is constructed solely when a live call is explicitly wanted
(RUN_LIVE_LLM=1 smoke, or production). Model pinned via LLM_MODEL_COMPILER —
layout generation is the hardest spatial-reasoning call in the system
(.env.example pins claude-opus-5)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

TOOL_NAME = "emit_layout"
TOOL_DESCRIPTION = "Emit the new ChapterLayout floor plan for the confirmed brief."


@dataclass(frozen=True)
class LlmCall:
    system: str
    user_text: str


class CompilerLLM(Protocol):
    def compile(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        """One forced emit_layout call; returns the tool input dict."""
        ...


class AnthropicLLM:
    def __init__(self, model: str | None = None):
        import anthropic  # lazy: CI never imports a configured client

        self._client = anthropic.Anthropic()
        self._model = model or os.environ.get("LLM_MODEL_COMPILER", "claude-opus-5")

    def compile(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        # a full apartment layout is a large emission — stream to dodge HTTP timeouts
        with self._client.messages.stream(
            model=self._model,
            max_tokens=32000,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            tools=[
                {"name": TOOL_NAME, "description": TOOL_DESCRIPTION, "input_schema": tool_schema}
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        ) as stream:
            response = stream.get_final_message()
        for block in response.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                return dict(block.input)
        raise RuntimeError(
            f"no {TOOL_NAME} tool_use block in response (stop={response.stop_reason})"
        )


@dataclass
class ScriptedLLM:
    """Pops the next scripted tool input per call; records the boundary."""

    script: list[dict[str, Any]]
    calls: list[LlmCall] = field(default_factory=list)

    def compile(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(LlmCall(system=system, user_text=user_text))
        if not self.script:
            raise AssertionError("ScriptedLLM exhausted: unexpected extra LLM call")
        return self.script.pop(0)
