"""Validated, secret-safe model configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictInt,
    StringConstraints,
    field_validator,
)

ModelName = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]


class OpenAIModelConfig(BaseModel):
    """All bounded settings required to construct an OpenAI client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: SecretStr
    model: ModelName
    api_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=600)] = 60
    max_retries: Annotated[StrictInt, Field(ge=0, le=5)] = 2
    max_output_tokens: Annotated[StrictInt, Field(ge=128, le=32_768)] = 4096
    max_retained_model_output_bytes: Annotated[
        StrictInt, Field(ge=1_024, le=1_048_576)
    ] = 65_536
    max_retained_tool_output_bytes: Annotated[
        StrictInt, Field(ge=1_024, le=1_048_576)
    ] = 65_536

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("OPENAI_API_KEY must be a string")
        if not value.strip():
            raise ValueError("OPENAI_API_KEY is empty")
        if len(value) > 4_096 or any(character in value for character in "\r\n\x00"):
            raise ValueError("OPENAI_API_KEY has an invalid format")
        return value


def load_openai_model_config(
    *,
    model_override: str | None = None,
    environ: Mapping[str, str] | None = None,
    api_timeout_seconds: int = 60,
    max_retries: int = 2,
    max_output_tokens: int = 4096,
    max_retained_model_output_bytes: int = 65_536,
    max_retained_tool_output_bytes: int = 65_536,
) -> OpenAIModelConfig:
    """Read only the two documented environment variables and validate them."""

    source = os.environ if environ is None else environ
    api_key = source.get("OPENAI_API_KEY", "")
    model = model_override if model_override is not None else source.get("PATCHPILOT_MODEL", "")
    return OpenAIModelConfig(
        api_key=SecretStr(api_key),
        model=model,
        api_timeout_seconds=api_timeout_seconds,
        max_retries=max_retries,
        max_output_tokens=max_output_tokens,
        max_retained_model_output_bytes=max_retained_model_output_bytes,
        max_retained_tool_output_bytes=max_retained_tool_output_bytes,
    )
