from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel, ConfigDict

from patchpilot.agent.base import (
    AgentMessage,
    ToolCall,
    ToolError,
    ToolErrorCode,
    ToolResult,
    ToolSpec,
)
from patchpilot.agent.tools import (
    PatchPilotToolEnvironment,
    ToolDefinition,
    ToolExecution,
    ToolExecutor,
    create_patchpilot_tool_executor,
)
from patchpilot.case_spec import TargetTest
from patchpilot.models.config import OpenAIModelConfig, load_openai_model_config
from patchpilot.models.openai_responses import (
    ModelAPIError,
    ModelConfigurationError,
    ModelProtocolError,
    OpenAIResponsesClient,
    strict_function_tool,
)
from patchpilot.patching import PatchErrorCode
from patchpilot.process import ProcessRunner


class _SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str
    path: str | None = None


def _tool_spec() -> ToolSpec:
    return ToolSpec(
        name="search_code",
        description="Search repository code for a literal string.",
        input_schema=_SearchInput.model_json_schema(),
    )


class _FakeResponses:
    def __init__(self, scripted: Sequence[object]) -> None:
        self.scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if not self.scripted:
            raise AssertionError("unexpected Responses API call")
        value = self.scripted.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class _FakeSDK:
    def __init__(self, scripted: Sequence[object]) -> None:
        self.responses = _FakeResponses(scripted)


class _FakeResponse:
    def __init__(
        self,
        *,
        output: list[dict[str, Any]],
        output_text: str = "",
        status: str = "completed",
        incomplete_reason: str | None = None,
        response_id: str = "resp_123",
        request_id: str = "req_123",
    ) -> None:
        self.id = response_id
        self.model = "test-model"
        self.output = output
        self.output_text = output_text
        self.status = status
        self.incomplete_details = (
            {"reason": incomplete_reason} if incomplete_reason is not None else None
        )
        self.usage = {
            "input_tokens": 11,
            "output_tokens": 7,
            "output_tokens_details": {"reasoning_tokens": 3},
        }
        self._request_id = request_id


def _config(*, retries: int = 2) -> OpenAIModelConfig:
    return OpenAIModelConfig(
        api_key="sk-test-secret-value",
        model="test-model",
        api_timeout_seconds=17,
        max_retries=retries,
        max_output_tokens=2048,
        max_retained_model_output_bytes=32768,
        max_retained_tool_output_bytes=32768,
    )


def test_environment_loader_accepts_plaintext_api_key() -> None:
    config = load_openai_model_config(
        environ={
            "OPENAI_API_KEY": "openrouter-test-key",
            "PATCHPILOT_MODEL": "openai/o4-mini",
        }
    )

    assert config.api_key.get_secret_value() == "openrouter-test-key"
    assert config.model == "openai/o4-mini"


def test_environment_loader_distinguishes_explicit_openrouter_endpoint() -> None:
    config = load_openai_model_config(
        environ={
            "OPENAI_API_KEY": "openrouter-test-key",
            "OPENAI_BASE_URL": "https://openrouter.ai/api/v1",
            "PATCHPILOT_MODEL": "z-ai/glm-5.2",
            "OPENROUTER_API_KEY": "must-not-be-read",
        }
    )

    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.provider_name == "openrouter"
    assert config.api_key.get_secret_value() == "openrouter-test-key"


def test_environment_loader_does_not_accept_undocumented_key_alias() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        load_openai_model_config(
            environ={
                "OPENROUTER_API_KEY": "must-not-be-read",
                "OPENAI_BASE_URL": "https://openrouter.ai/api/v1",
                "PATCHPILOT_MODEL": "z-ai/glm-5.2",
            }
        )


def test_sdk_client_receives_explicit_endpoint_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def construct(**kwargs: Any) -> _FakeSDK:
        captured.update(kwargs)
        return _FakeSDK([])

    monkeypatch.setattr(openai, "OpenAI", construct)
    config = load_openai_model_config(
        environ={
            "OPENAI_API_KEY": "openrouter-test-key",
            "OPENAI_BASE_URL": "https://openrouter.ai/api/v1",
            "PATCHPILOT_MODEL": "z-ai/glm-5.2",
        }
    )

    client = OpenAIResponsesClient(config=config)

    assert client.config.provider_name == "openrouter"
    assert captured["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["api_key"] == "openrouter-test-key"
    assert "openrouter-test-key" not in repr(client.config)


def _function_response(*, arguments: str = '{"query":"email","path":null}') -> _FakeResponse:
    return _FakeResponse(
        output=[
            {
                "id": "rs_1",
                "type": "reasoning",
                "encrypted_content": "opaque-provider-continuation",
                "summary": [],
            },
            {
                "id": "fc_1",
                "type": "function_call",
                "call_id": "call_abc",
                "name": "search_code",
                "arguments": arguments,
                "status": "completed",
            },
        ]
    )


def test_responses_request_uses_strict_tools_and_safe_request_controls() -> None:
    sdk = _FakeSDK([_function_response()])
    client = OpenAIResponsesClient(config=_config(), sdk_client=sdk)

    response = client.chat(
        [AgentMessage(role="user", content="Find the email defect.")],
        [_tool_spec()],
    )

    request = sdk.responses.calls[0]
    assert request["model"] == "test-model"
    assert request["store"] is False
    assert request["parallel_tool_calls"] is False
    assert request["max_output_tokens"] == 2048
    assert request["timeout"] == 17
    assert request["include"] == ["reasoning.encrypted_content"]
    assert "previous_response_id" not in request
    assert request["tools"] == [
        {
            "type": "function",
            "name": "search_code",
            "description": "Search repository code for a literal string.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": ["query", "path"],
                "additionalProperties": False,
            },
        }
    ]
    assert response.tool_call == ToolCall(
        call_id="call_abc",
        name="search_code",
        arguments={"query": "email", "path": None},
    )
    assert response.provider == "openai"
    assert response.model == "test-model"
    assert response.response_id == "resp_123"
    assert response.request_id == "req_123"
    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 7
    assert response.usage.reasoning_tokens == 3


def test_continuation_preserves_all_output_and_matches_function_call_id() -> None:
    sdk = _FakeSDK(
        [
            _function_response(),
            _FakeResponse(
                output=[
                    {
                        "id": "msg_2",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "Inspected."}],
                    }
                ],
                output_text="Inspected.",
                response_id="resp_456",
                request_id="req_456",
            ),
        ]
    )
    client = OpenAIResponsesClient(config=_config(), sdk_client=sdk)
    user = AgentMessage(role="user", content="Find the email defect.")
    first = client.chat([user], [_tool_spec()])
    result = ToolResult(
        call_id="call_abc",
        tool_name="search_code",
        success=True,
        output={"matches": []},
    )

    second = client.chat(
        [
            user,
            AgentMessage(role="assistant", tool_call=first.tool_call),
            AgentMessage(role="tool", tool_result=result),
        ],
        [_tool_spec()],
        continuation=first.continuation,
    )

    running_input = sdk.responses.calls[1]["input"]
    assert any(item.get("type") == "reasoning" for item in running_input)
    assert any(item.get("type") == "function_call" for item in running_input)
    tool_outputs = [
        item for item in running_input if item.get("type") == "function_call_output"
    ]
    assert len(tool_outputs) == 1
    assert tool_outputs[0]["call_id"] == "call_abc"
    assert '"success":true' in tool_outputs[0]["output"]
    assert second.finish_requested is True
    assert second.message == "Inspected."


def test_openrouter_next_request_contains_structured_patch_rejection() -> None:
    first_response = _FakeResponse(
        output=[
            {
                "id": "fc_patch_1",
                "type": "function_call",
                "call_id": "patch_call_1",
                "name": "apply_patch",
                "arguments": '{"patch":"@@ -1 +1 @@\\n-old\\n+new\\n"}',
                "status": "completed",
            }
        ]
    )
    sdk = _FakeSDK(
        [
            first_response,
            _FakeResponse(output=[], output_text="Stopping after feedback."),
        ]
    )
    config = _config().model_copy(
        update={"base_url": "https://openrouter.ai/api/v1"}
    )
    client = OpenAIResponsesClient(config=config, sdk_client=sdk)
    user = AgentMessage(role="user", content="Repair the defect.")
    first = client.chat([user], [_tool_spec()])
    assert first.provider == "openrouter"
    rejection = ToolResult(
        call_id="patch_call_1",
        tool_name="apply_patch",
        success=False,
        output={
            "status": "rejected",
            "error_code": "PATCH_FILE_HEADERS_MISSING",
            "message": "The patch is missing file headers.",
            "patch_attempts_remaining": 1,
            "worktree_modified": False,
        },
        error=ToolError(
            code=PatchErrorCode.PATCH_FILE_HEADERS_MISSING,
            message="The patch is missing file headers.",
        ),
    )

    client.chat(
        [
            user,
            AgentMessage(role="assistant", tool_call=first.tool_call),
            AgentMessage(role="tool", tool_result=rejection),
        ],
        [_tool_spec()],
        continuation=first.continuation,
    )

    second_request = sdk.responses.calls[1]
    assert "previous_response_id" not in second_request
    assert any(
        item.get("type") == "function_call" and item.get("call_id") == "patch_call_1"
        for item in second_request["input"]
    )
    outputs = [
        item
        for item in second_request["input"]
        if item.get("type") == "function_call_output"
    ]
    assert len(outputs) == 1
    serialized = outputs[0]["output"]
    assert '"error_code":"PATCH_FILE_HEADERS_MISSING"' in serialized
    assert '"patch_attempts_remaining":1' in serialized
    assert '"worktree_modified":false' in serialized


def test_malformed_function_arguments_become_a_structured_tool_error() -> None:
    sdk = _FakeSDK([_function_response(arguments="{not-json")])
    client = OpenAIResponsesClient(config=_config(), sdk_client=sdk)
    response = client.chat(
        [AgentMessage(role="user", content="Inspect.")],
        [_tool_spec()],
    )
    assert response.tool_call is not None
    assert response.tool_call.argument_error is not None

    def execute(arguments: BaseModel) -> ToolExecution:
        del arguments
        return ToolExecution({"unexpected": True})

    executor = ToolExecutor(
        [
            ToolDefinition(
                name="search_code",
                description="Search.",
                input_model=_SearchInput,
                execute=execute,
            )
        ]
    )
    result = executor.execute(response.tool_call)

    assert result.success is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGUMENTS
    assert "JSON" in result.error.message


def test_missing_call_id_is_a_protocol_error() -> None:
    missing_id = _FakeResponse(
        output=[
            {
                "type": "function_call",
                "name": "search_code",
                "arguments": "{}",
            }
        ]
    )

    client = OpenAIResponsesClient(config=_config(), sdk_client=_FakeSDK([missing_id]))
    with pytest.raises(ModelProtocolError):
        client.chat([AgentMessage(role="user", content="Inspect.")], [_tool_spec()])


def test_multiple_function_calls_are_sequentialized_before_continuation() -> None:
    multiple = _FakeResponse(
        output=[
            {
                "id": f"fc_{index}",
                "type": "function_call",
                "call_id": f"call_{index}",
                "name": "search_code",
                "arguments": f'{{"query":"term-{index}","path":null}}',
            }
            for index in range(2)
        ]
    )
    sdk = _FakeSDK(
        [
            multiple,
            _FakeResponse(output=[], output_text="Observed the first result."),
        ]
    )
    client = OpenAIResponsesClient(config=_config(), sdk_client=sdk)
    user = AgentMessage(role="user", content="Inspect.")

    first = client.chat([user], [_tool_spec()])

    assert first.tool_call == ToolCall(
        call_id="call_0",
        name="search_code",
        arguments={"query": "term-0", "path": None},
    )
    assert first.discarded_tool_call_count == 1
    assert first.continuation is not None
    retained_calls = [
        item
        for item in first.continuation.input_items
        if item.get("type") == "function_call"
    ]
    assert [item["call_id"] for item in retained_calls] == ["call_0"]

    result = ToolResult(
        call_id="call_0",
        tool_name="search_code",
        success=True,
        output={"matches": []},
    )
    second = client.chat(
        [
            user,
            AgentMessage(role="assistant", tool_call=first.tool_call),
            AgentMessage(role="tool", tool_result=result),
        ],
        [_tool_spec()],
        continuation=first.continuation,
    )

    next_input = sdk.responses.calls[1]["input"]
    next_calls = [
        item for item in next_input if item.get("type") == "function_call"
    ]
    next_outputs = [
        item for item in next_input if item.get("type") == "function_call_output"
    ]
    assert [item["call_id"] for item in next_calls] == ["call_0"]
    assert [item["call_id"] for item in next_outputs] == ["call_0"]
    assert second.finish_requested is True


def test_incomplete_response_reason_is_normalized_explicitly() -> None:
    sdk = _FakeSDK(
        [
            _FakeResponse(
                output=[],
                status="incomplete",
                incomplete_reason="max_output_tokens",
            )
        ]
    )
    response = OpenAIResponsesClient(config=_config(), sdk_client=sdk).chat(
        [AgentMessage(role="user", content="Inspect.")],
        [_tool_spec()],
    )

    assert response.finish_requested is True
    assert response.incomplete_reason == "max_output_tokens"
    assert response.message == ""


def _http_error(
    factory: Callable[..., Exception], status_code: int, message: str
) -> Exception:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status_code, request=request)
    return factory(message, response=response, body={"error": "bounded"})


def test_authentication_error_is_not_retried_and_secret_is_redacted() -> None:
    error = _http_error(
        openai.AuthenticationError,
        401,
        "bad key sk-test-secret-value",
    )
    sdk = _FakeSDK([error])
    client = OpenAIResponsesClient(
        config=_config(retries=3), sdk_client=sdk, sleep=lambda _seconds: None
    )

    with pytest.raises(ModelConfigurationError) as caught:
        client.chat([AgentMessage(role="user", content="Inspect.")], [_tool_spec()])

    assert len(sdk.responses.calls) == 1
    assert "sk-test-secret-value" not in str(caught.value)
    assert "<redacted>" in str(caught.value)


def test_timeout_and_rate_limit_receive_only_bounded_retries() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    timeout = openai.APITimeoutError(request=request)
    recovered_sdk = _FakeSDK([timeout, _function_response()])
    recovered = OpenAIResponsesClient(
        config=_config(retries=2), sdk_client=recovered_sdk, sleep=lambda _seconds: None
    ).chat([AgentMessage(role="user", content="Inspect.")], [_tool_spec()])
    assert recovered.tool_call is not None
    assert len(recovered_sdk.responses.calls) == 2

    limited = _http_error(openai.RateLimitError, 429, "rate limited")
    exhausted_sdk = _FakeSDK([limited, limited, limited, limited])
    client = OpenAIResponsesClient(
        config=_config(retries=2), sdk_client=exhausted_sdk, sleep=lambda _seconds: None
    )
    with pytest.raises(ModelAPIError) as caught:
        client.chat([AgentMessage(role="user", content="Inspect.")], [_tool_spec()])
    assert caught.value.retryable is True
    assert caught.value.attempts == 3
    assert len(exhausted_sdk.responses.calls) == 3


def test_invalid_request_is_not_retried() -> None:
    error = _http_error(openai.BadRequestError, 400, "unsupported model")
    sdk = _FakeSDK([error, _function_response()])
    client = OpenAIResponsesClient(
        config=_config(retries=3), sdk_client=sdk, sleep=lambda _seconds: None
    )

    with pytest.raises(ModelAPIError) as caught:
        client.chat([AgentMessage(role="user", content="Inspect.")], [_tool_spec()])

    assert caught.value.retryable is False
    assert caught.value.attempts == 1
    assert len(sdk.responses.calls) == 1


def test_all_six_patchpilot_tools_have_closed_strict_object_schemas(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text(
        "gitdir: C:/repository/.git/worktrees/schema-test\n", encoding="utf-8"
    )
    environment = PatchPilotToolEnvironment(
        worktree=worktree,
        target_test=TargetTest(class_name="ExampleTest", method_name="fails"),
        target_test_timeout_seconds=30,
        process_runner=ProcessRunner(),
    )

    converted = [
        strict_function_tool(spec)
        for spec in create_patchpilot_tool_executor(environment).specs
    ]

    expected_properties = {
        "list_files": {"path", "max_depth"},
        "search_code": {"query", "path", "file_type"},
        "read_file": {"path", "start_line", "end_line"},
        "apply_patch": {"patch"},
        "run_target_test": set(),
        "git_diff": set(),
    }
    assert {tool["name"] for tool in converted} == set(expected_properties)
    for tool in converted:
        parameters = tool["parameters"]
        properties = parameters["properties"]
        assert tool["type"] == "function"
        assert tool["strict"] is True
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
        assert set(properties) == expected_properties[tool["name"]]
        assert set(parameters["required"]) == set(properties)
