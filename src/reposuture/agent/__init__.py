"""Internal provider-independent Agent Runtime foundation."""

from reposuture.agent.base import (
    AgentMessage,
    AgentResponse,
    LLMClient,
    ModelUsage,
    ProviderContinuation,
    ToolCall,
    ToolError,
    ToolErrorCode,
    ToolResult,
    ToolSpec,
)
from reposuture.agent.fake_llm import FakeLLM, FakeLLMExhaustedError
from reposuture.agent.loop import AgentLoop
from reposuture.agent.state import (
    AgentExecutionStatus,
    AgentFinalResult,
    AgentState,
)
from reposuture.agent.tools import (
    PatchAttemptRecord,
    PatchPilotToolEnvironment,
    RepoSutureToolEnvironment,
    ToolDefinition,
    ToolExecutor,
    create_patchpilot_tool_executor,
    create_reposuture_tool_executor,
)

__all__ = [
    "AgentExecutionStatus",
    "AgentFinalResult",
    "AgentLoop",
    "AgentMessage",
    "AgentResponse",
    "AgentState",
    "FakeLLM",
    "FakeLLMExhaustedError",
    "LLMClient",
    "ModelUsage",
    "PatchAttemptRecord",
    "PatchPilotToolEnvironment",
    "ProviderContinuation",
    "RepoSutureToolEnvironment",
    "ToolCall",
    "ToolDefinition",
    "ToolError",
    "ToolErrorCode",
    "ToolExecutor",
    "ToolResult",
    "ToolSpec",
    "create_patchpilot_tool_executor",
    "create_reposuture_tool_executor",
]
