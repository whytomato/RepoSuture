"""Internal provider-independent Agent Runtime foundation."""

from patchpilot.agent.base import (
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
from patchpilot.agent.fake_llm import FakeLLM, FakeLLMExhaustedError
from patchpilot.agent.loop import AgentLoop
from patchpilot.agent.state import (
    AgentExecutionStatus,
    AgentFinalResult,
    AgentState,
)
from patchpilot.agent.tools import (
    PatchAttemptRecord,
    PatchPilotToolEnvironment,
    ToolDefinition,
    ToolExecutor,
    create_patchpilot_tool_executor,
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
    "ToolCall",
    "ToolDefinition",
    "ToolError",
    "ToolErrorCode",
    "ToolExecutor",
    "ToolResult",
    "ToolSpec",
    "create_patchpilot_tool_executor",
]
