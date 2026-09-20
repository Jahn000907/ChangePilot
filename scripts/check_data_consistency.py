"""ChangePilot cross-database consistency check (read-only).

Usage::

    python scripts/check_data_consistency.py

Checks the PostgreSQL golden ERP facts, the Neo4j product / BOM graph, the
PostgreSQL -> Neo4j reference integrity and the readiness of the golden EOL
scenario. Nothing is written: the script only runs SELECT / MATCH queries.

Exit code is 0 when every check passes and non-zero otherwise, so it can be used
directly in CI.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# scripts/check_data_consistency.py -> scripts -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.db.neo4j.driver import close_driver, get_driver
from app.seed.golden.consistency import all_checks, all_passed, count_checks

log = logging.getLogger("changepilot.check_data_consistency")


def main() -> int:
    """Run every consistency check and print the report."""
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(levelname)-5.5s [%(name)s] %(message)s",
    )
    logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

    try:
        get_driver().verify_connectivity()
        grouped = all_checks()
    except Exception:
        log.exception("一致性检查无法完成")
        return 2
    finally:
        close_driver()

    total = count_checks(grouped)
    failed = sum(
        1 for _section, checks in grouped for check in checks if not check.passed
    )

    print("ChangePilot 数据一致性检查")
    for section, checks in grouped:
        print(f"\n[{section}]")
        for check in checks:
            status = "PASS" if check.passed else "FAIL"
            print(f"  [{status}] {check.name}")
            print(f"         实际: {check.detail}")

    print(f"\n汇总: 共 {total} 项检查，通过 {total - failed} 项，失败 {failed} 项")
    passed = all_passed(grouped)
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
