"""Structured state for one bounded Agent Runtime execution."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints

from reposuture.agent.base import AgentMessage, ToolResult


class AgentExecutionStatus(StrEnum):
    """Lifecycle status; FINISHED does not mean a repair is resolved."""

    READY = "READY"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ITERATION_LIMIT_REACHED = "ITERATION_LIMIT_REACHED"
    TOOL_CALL_LIMIT_REACHED = "TOOL_CALL_LIMIT_REACHED"
    FAILED = "FAILED"


class AgentFinalResult(BaseModel):
    """Loop termination detail, deliberately separate from final repair verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: Annotated[str, StringConstraints(strict=True, max_length=100_000)] = ""
    repair_verified: Literal[False] = False
    failure_reason: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=4_000)
    ] | None = None


class AgentState(BaseModel):
    """Mutable, validated state owned by one AgentLoop invocation."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    task_id: Annotated[
        str,
        StringConstraints(
            strict=True,
            strip_whitespace=True,
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        ),
    ]
    issue_description: Annotated[
        str,
        StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=20_000),
    ]
    messages: list[AgentMessage] = Field(default_factory=list)
    iteration_count: Annotated[StrictInt, Field(ge=0)] = 0
    tool_call_count: Annotated[StrictInt, Field(ge=0)] = 0
    max_iterations: Annotated[StrictInt, Field(ge=1, le=100)] = 20
    max_tool_calls: Annotated[StrictInt, Field(ge=0, le=100)] = 20
    available_tools: list[str] = Field(default_factory=list)
    execution_status: AgentExecutionStatus = AgentExecutionStatus.READY
    tool_history: list[ToolResult] = Field(default_factory=list)
    last_verifier_passed: bool | None = None
    final_result: AgentFinalResult | None = None
