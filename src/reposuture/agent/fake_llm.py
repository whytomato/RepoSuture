"""Deterministic scripted LLM substitute used to prove the runtime lifecycle."""

from __future__ import annotations

from collections.abc import Sequence

from reposuture.agent.base import (
    AgentMessage,
    AgentResponse,
    ProviderContinuation,
    ToolCall,
    ToolSpec,
)


class FakeLLMExhaustedError(RuntimeError):
    """Raised when a test script requests more responses than configured."""


class FakeLLM:
    """Return a predefined sequence without network access or model inference."""

    def __init__(self, responses: Sequence[AgentResponse]) -> None:
        if not responses:
            raise ValueError("FakeLLM requires at least one scripted response")
        self._responses = tuple(responses)
        self._cursor = 0
        self._request_count = 0

    @property
    def chat_count(self) -> int:
        return self._cursor

    @property
    def model_request_count(self) -> int:
        return self._request_count

    @property
    def api_error_count(self) -> int:
        return 0

    def chat(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        *,
        continuation: ProviderContinuation | None = None,
    ) -> AgentResponse:
        del messages, tools, continuation
        self._request_count += 1
        if self._cursor >= len(self._responses):
            raise FakeLLMExhaustedError("FakeLLM response script was exhausted")
        response = self._responses[self._cursor]
        self._cursor += 1
        return response

    @classmethod
    def repair_workflow(cls, *, patch: str, source_path: str) -> FakeLLM:
        """Build the required search/read/patch/test/finish demonstration script."""

        return cls(
            [
                AgentResponse.request_tool(
                    ToolCall(
                        call_id="fake-search-1",
                        name="search_code",
                        arguments={"query": "email", "path": "."},
                    )
                ),
                AgentResponse.request_tool(
                    ToolCall(
                        call_id="fake-read-2",
                        name="read_file",
                        arguments={"path": source_path},
                    )
                ),
                AgentResponse.request_tool(
                    ToolCall(
                        call_id="fake-patch-3",
                        name="apply_patch",
                        arguments={"patch": patch},
                    )
                ),
                AgentResponse.request_tool(
                    ToolCall(
                        call_id="fake-test-4",
                        name="run_target_test",
                        arguments={},
                    )
                ),
                AgentResponse.finish(
                    "Candidate workflow finished; deterministic final verification "
                    "remains required."
                ),
            ]
        )
