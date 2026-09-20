"""ChangePilot Neo4j driver module.

Owns the process-wide Neo4j driver for the product structure / BOM graph.

- the driver is created lazily from the application settings, so importing this
  module never contacts the database;
- the connection details come from ``app.core.config`` (project root ``.env``),
  never from hardcoded values;
- every business module reuses ``get_driver()`` instead of building its own
  driver, and Cypher is always parameterised by the caller (v0.4 section 23).

This module contains no graph queries and no domain logic.
"""

from __future__ import annotations

from functools import lru_cache

from neo4j import Driver, GraphDatabase

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_driver() -> Driver:
    """Return the process-wide Neo4j driver.

    Creating a driver does not open a connection; the first real connection
    happens on first use. ``connection_timeout`` keeps an unreachable database
    from hanging the caller.
    """
    settings = get_settings().neo4j
    return GraphDatabase.driver(
        settings.uri,
        auth=(settings.user, settings.password.get_secret_value()),
        connection_timeout=5,
    )


def verify_connectivity() -> None:
    """Raise if the configured Neo4j instance cannot be reached."""
    get_driver().verify_connectivity()


def close_driver() -> None:
    """Close the shared driver and clear the cache.

    Intended for application shutdown and for tests that switch targets. The
    driver is only created-and-closed when it already exists.
    """
    if get_driver.cache_info().currsize > 0:
        get_driver().close()
    get_driver.cache_clear()
