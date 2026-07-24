"""Validated, secret-safe model configuration."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import Annotated
from urllib.parse import urlsplit

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

PRIMARY_MODEL_ENV = "REPOSUTURE_MODEL"
LEGACY_MODEL_ENV = "PATCHPILOT_MODEL"
PRIMARY_COMPARISON_MODEL_ENV = "REPOSUTURE_COMPARISON_MODEL"
LEGACY_COMPARISON_MODEL_ENV = "PATCHPILOT_COMPARISON_MODEL"
_DEPRECATION_WARNED: set[str] = set()


def _deprecated_model_warning(name: str, replacement: str) -> None:
    if name in _DEPRECATION_WARNED:
        return
    _DEPRECATION_WARNED.add(name)
    print(f"{name} is deprecated; use {replacement}.", file=sys.stderr)


def resolve_model_environment(
    *,
    comparison: bool = False,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve the primary RepoSuture variable with one-process legacy fallback."""

    source = os.environ if environ is None else environ
    primary = PRIMARY_COMPARISON_MODEL_ENV if comparison else PRIMARY_MODEL_ENV
    legacy = LEGACY_COMPARISON_MODEL_ENV if comparison else LEGACY_MODEL_ENV
    if primary in source:
        return source[primary]
    if legacy in source:
        _deprecated_model_warning(legacy, primary)
        return source[legacy]
    return ""


class OpenAIModelConfig(BaseModel):
    """All bounded settings required to construct an OpenAI client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: SecretStr
    model: ModelName
    base_url: str | None = None
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
        if isinstance(value, SecretStr):
            plaintext = value.get_secret_value()
        elif isinstance(value, str):
            plaintext = value
        else:
            raise ValueError("OPENAI_API_KEY must be a string")
        if not plaintext.strip():
            raise ValueError("OPENAI_API_KEY is empty")
        if len(plaintext) > 4_096 or any(
            character in plaintext for character in "\r\n\x00"
        ):
            raise ValueError("OPENAI_API_KEY has an invalid format")
        return value

    @field_validator("base_url", mode="before")
    @classmethod
    def validate_base_url(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("OPENAI_BASE_URL must be a string")
        if not value or value != value.strip() or len(value) > 2_048:
            raise ValueError("OPENAI_BASE_URL has an invalid format")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OPENAI_BASE_URL must be an HTTPS API root without credentials")
        if parsed.hostname.casefold() == "openrouter.ai" and (
            parsed.path.rstrip("/") != "/api/v1"
        ):
            raise ValueError("OpenRouter OPENAI_BASE_URL must end with /api/v1")
        return value.rstrip("/")

    @property
    def provider_name(self) -> str:
        if self.base_url is None:
            return "openai"
        hostname = urlsplit(self.base_url).hostname
        return "openrouter" if hostname and hostname.casefold() == "openrouter.ai" else "openai"


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
    """Read only the three documented live-model variables and validate them."""

    source = os.environ if environ is None else environ
    api_key = source.get("OPENAI_API_KEY", "")
    model = (
        model_override
        if model_override is not None
        else resolve_model_environment(environ=source)
    )
    base_url = source.get("OPENAI_BASE_URL") or None
    return OpenAIModelConfig(
        api_key=SecretStr(api_key),
        model=model,
        base_url=base_url,
        api_timeout_seconds=api_timeout_seconds,
        max_retries=max_retries,
        max_output_tokens=max_output_tokens,
        max_retained_model_output_bytes=max_retained_model_output_bytes,
        max_retained_tool_output_bytes=max_retained_tool_output_bytes,
    )
