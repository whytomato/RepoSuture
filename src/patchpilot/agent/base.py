"""Provider-independent messages, model responses, and tool result contracts."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]
MessageText = Annotated[
    str,
    StringConstraints(strict=True, max_length=100_000),
]


class ToolErrorCode(StrEnum):
    """Stable categories returned by the tool boundary."""

    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    POLICY_REJECTED = "POLICY_REJECTED"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class ToolCall(BaseModel):
    """One structured request emitted by an LLM client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: Identifier
    name: Identifier
    arguments: dict[str, Any] = Field(default_factory=dict)
    argument_error: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=4_000)
    ] | None = None


class ToolError(BaseModel):
    """A bounded error that can safely be returned to the model loop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ToolErrorCode
    message: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4_000)]


class ToolResult(BaseModel):
    """Structured result of one validated tool execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: Identifier
    tool_name: Identifier
    success: bool
    output: dict[str, Any] | None = None
    error: ToolError | None = None
    verifier_passed: bool | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        if self.success and self.error is not None:
            raise ValueError("successful tool results cannot contain an error")
        if not self.success and self.error is None:
            raise ValueError("failed tool results require an error")
        if not self.success and self.verifier_passed is not None:
            raise ValueError("failed tool results cannot contain verifier evidence")
        return self


class AgentMessage(BaseModel):
    """Provider-neutral conversation entry retained by the runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant", "tool"]
    content: MessageText = ""
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None

    @model_validator(mode="after")
    def validate_role_payload(self) -> Self:
        if self.role == "user" and (self.tool_call is not None or self.tool_result is not None):
            raise ValueError("user messages cannot contain tool payloads")
        if self.role == "assistant" and self.tool_result is not None:
            raise ValueError("assistant messages cannot contain tool results")
        if self.role == "tool" and (
            self.tool_result is None or self.tool_call is not None
        ):
            raise ValueError("tool messages require exactly one tool result")
        return self


class ToolSpec(BaseModel):
    """The provider-independent tool description passed to an LLM client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Identifier
    description: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=2_000)
    ]
    input_schema: dict[str, Any]


class ModelUsage(BaseModel):
    """Provider-neutral token counters exposed by a model response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)


class ProviderContinuation(BaseModel):
    """Opaque JSON-compatible provider state retained only by the runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_items: tuple[dict[str, Any], ...] = ()
    pending_call_ids: tuple[Identifier, ...] = ()


class AgentResponse(BaseModel):
    """Exactly one next action: a tool request or a request to finish."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: MessageText = ""
    tool_call: ToolCall | None = None
    finish_requested: bool = False
    provider: Annotated[str, StringConstraints(strict=True, max_length=64)] | None = None
    model: Annotated[str, StringConstraints(strict=True, max_length=256)] | None = None
    response_id: Annotated[str, StringConstraints(strict=True, max_length=512)] | None = None
    request_id: Annotated[str, StringConstraints(strict=True, max_length=512)] | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    incomplete_reason: Annotated[
        str, StringConstraints(strict=True, max_length=512)
    ] | None = None
    latency_seconds: float = Field(default=0.0, ge=0.0)
    output_truncated: bool = False
    continuation: ProviderContinuation | None = None

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        action_count = int(self.tool_call is not None) + int(self.finish_requested)
        if action_count != 1:
            raise ValueError("an agent response must request one tool or finish")
        return self

    @classmethod
    def request_tool(cls, tool_call: ToolCall, *, message: str = "") -> AgentResponse:
        return cls(message=message, tool_call=tool_call)

    @classmethod
    def finish(cls, message: str) -> AgentResponse:
        return cls(message=message, finish_requested=True)


class LLMClient(Protocol):
    """Minimal synchronous interface implemented by any future model provider."""

    def chat(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        *,
        continuation: ProviderContinuation | None = None,
    ) -> AgentResponse:
        """Return the next structured action for the current conversation."""
        ...
