"""Load the ChangePilot Golden Seed into PostgreSQL and Neo4j.

Usage::

    python scripts/seed_golden.py

The loader is idempotent: ids are deterministic (uuid5) and every write is an
upsert / MERGE, so a second run refreshes the same rows instead of duplicating
them. It never deletes or truncates data, and it refuses to run outside the
development / test environments (``APP_ENV``).

No ECM, agent or audit data is written: those belong to a real ChangePilot run.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# scripts/seed_golden.py -> scripts -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.db.neo4j.driver import close_driver, get_driver
from app.seed.golden.neo4j import load_golden_graph
from app.seed.golden.postgres import load_golden_erp
from app.seed.golden.validation import case_eol_checks, erp_counts, graph_counts

log = logging.getLogger("changepilot.seed_golden")

#: The golden seed describes a development / test fixture, never production data.
ALLOWED_ENVIRONMENTS = ("development", "test")


def _print_report(
    labels: dict[str, int],
    relationships: dict[str, int],
    counts: dict[str, int],
    checks: list,
) -> bool:
    """Print the seed report and return whether every check passed."""
    print("ChangePilot Golden Seed")
    print("\nNeo4j nodes")
    for label, count in labels.items():
        print(f"  {label:<14} {count}")
    print("\nNeo4j relationships")
    for rel_type, count in relationships.items():
        print(f"  {rel_type:<14} {count}")
    print("\nPostgreSQL rows")
    for table, count in counts.items():
        print(f"  {table:<40} {count}")
    print("\nChecks")
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"  [{status}] {check.name}: {check.detail}")
    passed = all(check.passed for check in checks)
    print(f"\nRESULT: {'PASS' if passed else 'FAIL'}")
    return passed


def main() -> int:
    """Seed both databases and verify the result."""
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(levelname)-5.5s [%(name)s] %(message)s",
    )
    # The server reports "already exists" notes on the second schema run; keep
    # the driver's INFO stream out of the way.
    logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

    if settings.app_env not in ALLOWED_ENVIRONMENTS:
        log.error(
            "golden seed only runs in %s; APP_ENV=%r refused",
            " / ".join(ALLOWED_ENVIRONMENTS),
            settings.app_env,
        )
        return 2

    try:
        get_driver().verify_connectivity()
        graph_counts_written = load_golden_graph()
        log.info("Neo4j golden graph written: %s", graph_counts_written)
        erp_counts_written = load_golden_erp()
        log.info("PostgreSQL golden ERP written: %s", erp_counts_written)
        labels, relationships = graph_counts()
        counts = erp_counts()
        checks = case_eol_checks()
    except Exception:
        log.exception("golden seed failed")
        return 1
    finally:
        close_driver()

    passed = _print_report(labels, relationships, counts, checks)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
