"""Official OpenAI Responses API adapter for the provider-neutral Agent protocol."""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, cast

import openai
from pydantic import BaseModel, ValidationError

from patchpilot.agent.base import (
    AgentMessage,
    AgentResponse,
    ModelUsage,
    ProviderContinuation,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from patchpilot.models.config import OpenAIModelConfig

MAX_PROVIDER_ERROR_CHARS = 2_000


class ModelProviderError(RuntimeError):
    """Base class for safe provider failures."""


class ModelConfigurationError(ModelProviderError):
    """Non-retryable credentials or model configuration failure."""


class ModelProtocolError(ModelProviderError):
    """Malformed or unsupported provider response structure."""


class ModelAPIError(ModelProviderError):
    """Bounded Responses API failure with retry metadata."""

    def __init__(self, message: str, *, retryable: bool, attempts: int) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.attempts = attempts


class _ResponsesResource(Protocol):
    def create(self, **kwargs: Any) -> object:
        ...


class _SDKClient(Protocol):
    responses: _ResponsesResource


class OpenAIResponsesClient:
    """Normalize Responses API function calls without leaking SDK types into core."""

    def __init__(
        self,
        *,
        config: OpenAIModelConfig,
        sdk_client: _SDKClient | None = None,
        instructions: str = "",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.instructions = instructions
        self._sleep = sleep
        self._model_request_count = 0
        self._api_error_count = 0
        if sdk_client is None:
            sdk_client = cast(
                _SDKClient,
                openai.OpenAI(
                    api_key=config.api_key.get_secret_value(),
                    base_url=config.base_url or "https://api.openai.com/v1",
                    timeout=config.api_timeout_seconds,
                    max_retries=0,
                ),
            )
        self._client = sdk_client

    @property
    def model_request_count(self) -> int:
        return self._model_request_count

    @property
    def api_error_count(self) -> int:
        return self._api_error_count

    def chat(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        *,
        continuation: ProviderContinuation | None = None,
    ) -> AgentResponse:
        running_input = self._build_running_input(messages, continuation)
        request: dict[str, Any] = {
            "model": self.config.model,
            "input": running_input,
            "tools": [strict_function_tool(tool) for tool in tools],
            "store": False,
            "parallel_tool_calls": False,
            "max_output_tokens": self.config.max_output_tokens,
            "timeout": self.config.api_timeout_seconds,
            "include": ["reasoning.encrypted_content"],
        }
        if self.instructions:
            request["instructions"] = self.instructions

        started = time.perf_counter()
        raw_response = self._create_with_retries(request)
        latency = max(0.0, time.perf_counter() - started)
        output_items = self._output_items(raw_response)
        retained_output, discarded_tool_calls = _retain_first_function_call(
            output_items
        )
        calls = [
            item for item in retained_output if item.get("type") == "function_call"
        ]

        response_id = _optional_string(_get_value(raw_response, "id"))
        request_id = _optional_string(_get_value(raw_response, "_request_id"))
        model = _optional_string(_get_value(raw_response, "model")) or self.config.model
        usage = _normalize_usage(_get_value(raw_response, "usage"))
        incomplete_reason = _incomplete_reason(raw_response)
        visible_text, output_truncated = _bounded_utf8(
            _visible_text(
                raw_response if discarded_tool_calls == 0 else None,
                retained_output,
            ),
            self.config.max_retained_model_output_bytes,
        )

        tool_call: ToolCall | None = None
        if calls:
            tool_call = _normalize_tool_call(calls[0])
        next_input = tuple(copy.deepcopy([*running_input, *retained_output]))
        pending = (tool_call.call_id,) if tool_call is not None else ()
        normalized_continuation = ProviderContinuation(
            input_items=next_input,
            pending_call_ids=pending,
        )
        common: dict[str, Any] = {
            "message": visible_text,
            "provider": self.config.provider_name,
            "model": model,
            "response_id": response_id,
            "request_id": request_id,
            "usage": usage,
            "incomplete_reason": incomplete_reason,
            "latency_seconds": latency,
            "output_truncated": output_truncated,
            "discarded_tool_call_count": discarded_tool_calls,
            "continuation": normalized_continuation,
        }
        if tool_call is not None:
            return AgentResponse(tool_call=tool_call, **common)
        return AgentResponse(finish_requested=True, **common)

    def _create_with_retries(self, request: dict[str, Any]) -> object:
        maximum_attempts = self.config.max_retries + 1
        for attempt in range(1, maximum_attempts + 1):
            try:
                self._model_request_count += 1
                return self._client.responses.create(**request)
            except Exception as exc:
                self._api_error_count += 1
                retryable, configuration = _classify_provider_error(exc)
                message = self._safe_error_message(exc)
                if configuration:
                    raise ModelConfigurationError(message) from exc
                if retryable and attempt < maximum_attempts:
                    self._sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
                    continue
                raise ModelAPIError(
                    message,
                    retryable=retryable,
                    attempts=attempt,
                ) from exc
        raise AssertionError("bounded retry loop did not terminate")

    def _safe_error_message(self, exc: Exception) -> str:
        detail = str(exc).strip() or type(exc).__name__
        secret = self.config.api_key.get_secret_value()
        if secret:
            detail = detail.replace(secret, "<redacted>")
        return f"{type(exc).__name__}: {detail}"[:MAX_PROVIDER_ERROR_CHARS]

    def _build_running_input(
        self,
        messages: Sequence[AgentMessage],
        continuation: ProviderContinuation | None,
    ) -> list[dict[str, Any]]:
        if continuation is None:
            initial: list[dict[str, Any]] = []
            for message in messages:
                if message.role == "tool":
                    raise ModelProtocolError(
                        "tool results require matching provider continuation state"
                    )
                if message.content:
                    initial.append({"role": message.role, "content": message.content})
            return initial

        running = copy.deepcopy(list(continuation.input_items))
        for call_id in continuation.pending_call_ids:
            matches = [
                message.tool_result
                for message in messages
                if message.role == "tool"
                and message.tool_result is not None
                and message.tool_result.call_id == call_id
            ]
            if len(matches) != 1:
                raise ModelProtocolError(
                    f"expected exactly one tool result for function call {call_id}"
                )
            running.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": self._serialize_tool_result(matches[0]),
                }
            )
        return running

    def _serialize_tool_result(self, result: ToolResult) -> str:
        encoded = json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        bounded, truncated = _bounded_utf8(
            encoded, self.config.max_retained_tool_output_bytes
        )
        if not truncated:
            return bounded
        summary = {
            "call_id": result.call_id,
            "tool_name": result.tool_name,
            "success": result.success,
            "error": result.error.model_dump(mode="json") if result.error else None,
            "output_truncated": True,
        }
        return json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _output_items(response: object) -> list[dict[str, Any]]:
        raw_output = _get_value(response, "output")
        if not isinstance(raw_output, Sequence) or isinstance(raw_output, (str, bytes)):
            raise ModelProtocolError("Responses API output is not a list")
        return [_json_mapping(item) for item in raw_output]


def strict_function_tool(spec: ToolSpec) -> dict[str, Any]:
    """Convert one provider-neutral schema to an OpenAI strict function tool."""

    parameters = _strict_schema(copy.deepcopy(spec.input_schema))
    if parameters.get("type") != "object" or not isinstance(
        parameters.get("properties"), dict
    ):
        raise ModelConfigurationError(
            f"tool {spec.name} must use an object input schema with explicit properties"
        )
    return {
        "type": "function",
        "name": spec.name,
        "description": spec.description,
        "strict": True,
        "parameters": parameters,
    }


def _strict_schema(value: object) -> Any:
    if isinstance(value, list):
        return [_strict_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    unsupported = {"oneOf", "allOf", "not", "if", "then", "else", "patternProperties"}
    present = unsupported.intersection(value)
    if present:
        raise ModelConfigurationError(
            f"unsupported strict tool schema keywords: {', '.join(sorted(present))}"
        )
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"title", "default", "$schema"}:
            continue
        cleaned[key] = _strict_schema(item)
    if cleaned.get("type") == "object":
        properties = cleaned.get("properties", {})
        if not isinstance(properties, dict):
            raise ModelConfigurationError("object tool schema properties must be a mapping")
        cleaned["properties"] = properties
        cleaned["required"] = list(properties)
        cleaned["additionalProperties"] = False
    return cleaned


def _normalize_tool_call(item: dict[str, Any]) -> ToolCall:
    call_id = item.get("call_id")
    name = item.get("name")
    if not isinstance(call_id, str) or not call_id.strip():
        raise ModelProtocolError("function_call item is missing a valid call_id")
    if not isinstance(name, str) or not name.strip():
        raise ModelProtocolError("function_call item is missing a valid name")
    raw_arguments = item.get("arguments")
    argument_error: str | None = None
    arguments: dict[str, Any] = {}
    if not isinstance(raw_arguments, str):
        argument_error = "function-call arguments were not a JSON string"
    else:
        try:
            parsed = json.loads(raw_arguments)
            if isinstance(parsed, dict):
                arguments = parsed
            else:
                argument_error = "function-call arguments JSON must be an object"
        except json.JSONDecodeError as exc:
            argument_error = f"function-call arguments contained malformed JSON: {exc.msg}"
    try:
        return ToolCall(
            call_id=call_id,
            name=name,
            arguments=arguments,
            argument_error=argument_error,
        )
    except ValidationError as exc:
        raise ModelProtocolError("function_call identifiers are invalid") from exc


def _retain_first_function_call(
    output_items: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Enforce the runtime's one-action contract at a provider boundary.

    Some OpenAI-compatible providers can return multiple calls even when the
    request disables parallel calls. The Agent must observe the first result
    before choosing another action, so output from the second call onward is
    deliberately excluded from stateless continuation state.
    """

    call_indexes = [
        index
        for index, item in enumerate(output_items)
        if item.get("type") == "function_call"
    ]
    if len(call_indexes) <= 1:
        return list(output_items), 0
    return list(output_items[: call_indexes[1]]), len(call_indexes) - 1


def _normalize_usage(raw: object) -> ModelUsage:
    input_tokens = _nonnegative_int(_get_value(raw, "input_tokens"))
    output_tokens = _nonnegative_int(_get_value(raw, "output_tokens"))
    details = _get_value(raw, "output_tokens_details")
    reasoning_tokens = _nonnegative_int(_get_value(details, "reasoning_tokens"))
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def _incomplete_reason(response: object) -> str | None:
    details = _get_value(response, "incomplete_details")
    return _optional_string(_get_value(details, "reason"))


def _visible_text(response: object, output_items: Sequence[dict[str, Any]]) -> str:
    direct = _get_value(response, "output_text")
    if isinstance(direct, str):
        return direct
    chunks: list[str] = []
    for item in output_items:
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            ):
                chunks.append(cast(str, part["text"]))
    return "\n".join(chunks)


def _classify_provider_error(exc: Exception) -> tuple[bool, bool]:
    if isinstance(exc, openai.AuthenticationError):
        return False, True
    if isinstance(exc, (openai.BadRequestError, openai.PermissionDeniedError)):
        return False, False
    if isinstance(
        exc,
        (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError),
    ):
        return True, False
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code in {408, 409, 429} or exc.status_code >= 500, False
    return False, False


def _get_value(value: object, name: str) -> object:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(name)
    return cast(object, getattr(value, name, None))


def _json_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        raw = value.model_dump(mode="json", exclude_none=True)
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise ModelProtocolError("Responses API output item is not serializable")
    try:
        copied = json.loads(json.dumps(raw, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ModelProtocolError("Responses API output item is not JSON-compatible") from exc
    if not isinstance(copied, dict):
        raise ModelProtocolError("Responses API output item must be an object")
    return cast(dict[str, Any], copied)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _bounded_utf8(value: str, maximum_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return value, False
    bounded = encoded[:maximum_bytes]
    while bounded:
        try:
            return bounded.decode("utf-8"), True
        except UnicodeDecodeError:
            bounded = bounded[:-1]
    return "", True
