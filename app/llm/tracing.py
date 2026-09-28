"""Optional, privacy-bounded LangSmith instrumentation for development runs."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import lru_cache

from langsmith import Client, trace, tracing_context
from langsmith.wrappers import wrap_openai
from openai import OpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import ENV_FILE

_suspended: ContextVar[bool] = ContextVar("langsmith_tracing_suspended", default=False)


class LangSmithSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "ChangePilot-V2"


@lru_cache(maxsize=1)
def _settings() -> LangSmithSettings:
    return LangSmithSettings()


@lru_cache(maxsize=1)
def _client() -> Client | None:
    settings = _settings()
    if not settings.langsmith_tracing or settings.langsmith_api_key is None:
        return None
    key = settings.langsmith_api_key.get_secret_value().strip()
    return Client(api_key=key) if key else None


def tracing_enabled() -> bool:
    return not _suspended.get() and _client() is not None


@contextmanager
def without_tracing() -> Iterator[None]:
    """Keep the default local benchmark strictly offline even if app tracing is on."""
    token = _suspended.set(True)
    try:
        yield
    finally:
        _suspended.reset(token)


def instrument_openai(client: OpenAI) -> OpenAI:
    """Wrap the existing DeepSeek client; its URL and retry settings stay intact."""
    if not tracing_enabled():
        return client
    settings = _settings()
    # pydantic-settings reads .env but LangSmith's SDK reads process env.
    # Export only when explicitly enabled; never log or serialize the secret.
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    if settings.langsmith_api_key is not None:
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key.get_secret_value())
    return wrap_openai(client)


@contextmanager
def trace_scope(name: str, inputs: dict[str, object] | None = None) -> Iterator[None]:
    """Nest a named Agent/Tool span without serializing objects or secrets."""
    client = _client() if not _suspended.get() else None
    if client is None:
        with nullcontext():
            yield
        return
    with (
        tracing_context(enabled=True, client=client, project_name=_settings().langsmith_project),
        trace(name, inputs=inputs or {}, run_type="chain", client=client),
    ):
        yield


def langsmith_project() -> str | None:
    return _settings().langsmith_project if tracing_enabled() else None
