"""ChangePilot Neo4j schema initialisation module.

Executes ``infra/neo4j/schema.cypher`` against the configured Neo4j database.
The statements are the constraints and indexes of design doc v0.4 sections
11.4, 12.3, 14.3, 16.2 and 22 — nothing else, and no business node is written.

Every statement uses ``IF NOT EXISTS``, so running this module repeatedly is
safe: an already existing constraint or index is simply skipped.
"""

from __future__ import annotations

from pathlib import Path

from neo4j import Driver

from app.core.config import get_settings
from app.db.neo4j.driver import get_driver

# app/db/neo4j/schema.py -> app/db/neo4j -> app/db -> app -> project root
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
SCHEMA_FILE: Path = PROJECT_ROOT / "infra" / "neo4j" / "schema.cypher"


def load_schema_statements(path: Path | None = None) -> list[str]:
    """Return the individual Cypher statements of the schema file.

    Comment lines starting with ``//`` are removed first, then the remaining
    text is split on ``;``. The order matters: a ``;`` inside a comment must not
    split a statement.
    """
    schema_path = path if path is not None else SCHEMA_FILE
    lines = [
        line
        for line in schema_path.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("//")
    ]
    statements: list[str] = []
    for chunk in "\n".join(lines).split(";"):
        statement = chunk.strip()
        if statement:
            statements.append(statement)
    return statements


def apply_schema(driver: Driver | None = None) -> int:
    """Apply the schema and return the number of statements executed.

    Passing a driver is only useful for tests; production callers use the shared
    driver from ``app.db.neo4j.driver``.
    """
    active_driver = driver if driver is not None else get_driver()
    statements = load_schema_statements()
    database = get_settings().neo4j.database
    with active_driver.session(database=database) as session:
        for statement in statements:
            session.run(statement).consume()
    return len(statements)
