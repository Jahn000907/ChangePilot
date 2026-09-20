"""ChangePilot application configuration module.

Loads and validates the Application / PostgreSQL / Neo4j settings from the
project root ``.env`` file.

Scope and constraints:

- configuration only: this module never opens a database connection;
- business code must not call ``os.getenv()`` directly, use ``get_settings()``;
- passwords are held as ``SecretStr`` so they never appear in ``repr()``,
  ``model_dump()`` or log output (see design doc v0.4 section 86 / 87);
- the ``.env`` file is resolved from the project root, not from the current
  working directory, so scripts and tests can run from any location.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/core/config.py -> app/core -> app -> project root
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
ENV_FILE: Path = PROJECT_ROOT / ".env"

# Supported log levels, aligned with the standard Python logging levels.
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Allowed Neo4j Bolt URI schemes. The MVP uses bolt://; the encrypted schemes
# are accepted here so later deployment forms do not need a config change.
NEO4J_URI_SCHEMES: frozenset[str] = frozenset(
    {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"}
)


def _require_non_empty_password(value: SecretStr) -> SecretStr:
    """Reject empty passwords at load time instead of at the first query."""
    if not value.get_secret_value():
        raise ValueError("password must not be empty")
    return value


class PostgresSettings(BaseSettings):
    """PostgreSQL settings for the erp / ecm / agent / audit schemas."""

    model_config = SettingsConfigDict(
        env_prefix="POSTGRES_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default="localhost", min_length=1)
    port: int = Field(default=5432, ge=1, le=65535)
    db: str = Field(default="changepilot", min_length=1)
    user: str = Field(default="changepilot", min_length=1)
    password: SecretStr

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: SecretStr) -> SecretStr:
        return _require_non_empty_password(value)


class Neo4jSettings(BaseSettings):
    """Neo4j settings for the product structure and BOM graph."""

    model_config = SettingsConfigDict(
        env_prefix="NEO4J_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    uri: str = "bolt://localhost:7687"
    user: str = Field(default="neo4j", min_length=1)
    password: SecretStr
    database: str = Field(default="neo4j", min_length=1)

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: SecretStr) -> SecretStr:
        return _require_non_empty_password(value)

    @field_validator("uri")
    @classmethod
    def _validate_uri(cls, value: str) -> str:
        # The raw URI is never echoed into the error message, because a
        # connection string may carry credentials.
        scheme, separator, remainder = value.partition("://")
        if not separator or not remainder or scheme.lower() not in NEO4J_URI_SCHEMES:
            raise ValueError(
                "must look like scheme://host:port, "
                f"allowed schemes are {sorted(NEO4J_URI_SCHEMES)}"
            )
        return value


class Settings(BaseSettings):
    """Root settings object grouping application and database settings."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", min_length=1)
    log_level: LogLevel = "INFO"

    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached settings object.

    Tests that need different environment values can reset the cache with
    ``get_settings.cache_clear()``.
    """
    return Settings()
