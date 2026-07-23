"""Minimal bounded tool-calling Agent loop."""

from __future__ import annotations

from reposuture.agent.base import AgentMessage, LLMClient
from reposuture.agent.state import AgentExecutionStatus, AgentFinalResult, AgentState
from reposuture.agent.tools import ToolExecutor


class AgentLoop:
    """Drive an LLMClient until finish, failure, or a configured resource limit."""

    def __init__(self, *, llm: LLMClient, tool_executor: ToolExecutor) -> None:
        self.llm = llm
        self.tool_executor = tool_executor

    def run(self, state: AgentState) -> AgentState:
        if state.execution_status is not AgentExecutionStatus.READY:
            raise ValueError("AgentState must be READY before execution")
        if state.iteration_count != 0 or state.tool_call_count != 0 or state.tool_history:
            raise ValueError("AgentState counters and tool history must be empty before execution")

        specs = self.tool_executor.specs
        state.available_tools = [spec.name for spec in specs]
        if not state.messages:
            state.messages.append(
                AgentMessage(role="user", content=state.issue_description)
            )
        state.execution_status = AgentExecutionStatus.RUNNING
        continuation = None

        while True:
            if state.iteration_count >= state.max_iterations:
                return self._terminate(
                    state,
                    status=AgentExecutionStatus.ITERATION_LIMIT_REACHED,
                    failure_reason="maximum agent iterations reached",
                )

            state.iteration_count += 1
            try:
                response = self.llm.chat(
                    tuple(state.messages), specs, continuation=continuation
                )
            except Exception as exc:
                detail = str(exc).strip() or type(exc).__name__
                return self._terminate(
                    state,
                    status=AgentExecutionStatus.FAILED,
                    failure_reason=f"LLM client failure: {type(exc).__name__}: {detail}",
                )

            state.messages.append(
                AgentMessage(
                    role="assistant",
                    content=response.message,
                    tool_call=response.tool_call,
                )
            )
            continuation = response.continuation
            if response.finish_requested:
                state.execution_status = AgentExecutionStatus.FINISHED
                state.final_result = AgentFinalResult(
                    message=response.message,
                    repair_verified=False,
                )
                return state

            tool_call = response.tool_call
            if tool_call is None:
                return self._terminate(
                    state,
                    status=AgentExecutionStatus.FAILED,
                    failure_reason="LLM client returned no executable action",
                )
            if state.tool_call_count >= state.max_tool_calls:
                return self._terminate(
                    state,
                    status=AgentExecutionStatus.TOOL_CALL_LIMIT_REACHED,
                    failure_reason="maximum agent tool calls reached",
                )

            result = self.tool_executor.execute(tool_call)
            state.tool_call_count += 1
            state.tool_history.append(result)
            if result.verifier_passed is not None:
                state.last_verifier_passed = result.verifier_passed
            state.messages.append(
                AgentMessage(role="tool", tool_result=result)
            )

    @staticmethod
    def _terminate(
        state: AgentState,
        *,
        status: AgentExecutionStatus,
        failure_reason: str,
    ) -> AgentState:
        state.execution_status = status
        state.final_result = AgentFinalResult(
            repair_verified=False,
            failure_reason=failure_reason[:4_000],
        )
        return state
