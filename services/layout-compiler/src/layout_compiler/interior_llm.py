"""LLM boundary for the furniture-proposal pass — a seam PARALLEL to the Phase 4
CompilerLLM (deliberately not widened: zero Phase 4 regression surface, and
fixture-key collision is structurally impossible). CI runs Scripted/Fixture
implementations only; AnthropicInteriorLLM is constructed solely when a live
call is explicitly wanted. Model pinned via LLM_MODEL_INTERIOR."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

FURNISH_TOOL_NAME = "emit_furniture"
FURNISH_TOOL_DESCRIPTION = (
    "Propose the furniture plan for the approved new layout: per-room items "
    "from the closed catalog vocabulary."
)


@dataclass(frozen=True)
class FurnishCall:
    system: str
    user_text: str


class InteriorLLM(Protocol):
    def furnish(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        """One forced emit_furniture call; returns the tool input dict."""
        ...


class AnthropicInteriorLLM:
    def __init__(self, model: str | None = None):
        import anthropic  # lazy: CI never imports a configured client

        self._client = anthropic.Anthropic()
        self._model = model or os.environ.get("LLM_MODEL_INTERIOR", "claude-opus-5")

    def furnish(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        with self._client.messages.stream(
            model=self._model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            tools=[
                {
                    "name": FURNISH_TOOL_NAME,
                    "description": FURNISH_TOOL_DESCRIPTION,
                    "input_schema": tool_schema,
                }
            ],
            tool_choice={"type": "tool", "name": FURNISH_TOOL_NAME},
        ) as stream:
            response = stream.get_final_message()
        for block in response.content:
            if block.type == "tool_use" and block.name == FURNISH_TOOL_NAME:
                return dict(block.input)
        raise RuntimeError(
            f"no {FURNISH_TOOL_NAME} tool_use block in response (stop={response.stop_reason})"
        )


@dataclass
class ScriptedInteriorLLM:
    """Pops the next scripted tool input per call; records the boundary."""

    script: list[dict[str, Any]]
    calls: list[FurnishCall] = field(default_factory=list)

    def furnish(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(FurnishCall(system=system, user_text=user_text))
        if not self.script:
            raise AssertionError("ScriptedInteriorLLM exhausted: unexpected extra LLM call")
        return self.script.pop(0)
