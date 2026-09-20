"""Initialise the ChangePilot Neo4j schema.

Usage::

    python scripts/init_neo4j_schema.py

Creates the constraints and indexes of the product / BOM graph. The statements
use ``IF NOT EXISTS``, so the command is idempotent and safe to re-run. No
business data (Part / PartRevision / BOMVersion / BOMLine) is written.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# scripts/init_neo4j_schema.py -> scripts -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.db.neo4j.driver import close_driver, get_driver
from app.db.neo4j.schema import SCHEMA_FILE, apply_schema

log = logging.getLogger("changepilot.init_neo4j_schema")


def main() -> int:
    """Apply the Neo4j schema and report the result."""
    logging.basicConfig(
        level=getattr(logging, get_settings().log_level),
        format="%(levelname)-5.5s [%(name)s] %(message)s",
    )
    # On re-runs the server reports an "already exists" note for every
    # IF NOT EXISTS statement. Those notes are expected here, so keep the
    # driver's INFO stream out of the way while still surfacing real warnings.
    logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)
    log.info("schema file: %s", SCHEMA_FILE)
    try:
        get_driver().verify_connectivity()
        log.info("connected to Neo4j database %r", get_settings().neo4j.database)
        applied = apply_schema()
        log.info("Neo4j schema applied (%d statements, idempotent)", applied)
    except Exception:
        log.exception("Neo4j schema initialisation failed")
        return 1
    finally:
        close_driver()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
