"""Verification of the loaded Golden Seed.

The checks mirror the CASE-EOL-001 constraints of design doc v0.4 sections
73-76 and the round-trip requirements of the loaders: correct row counts, the
BRG-6204-A impact chain, the qualified / unqualified alternatives, and empty
ECM / agent / audit schemas.

Every result is computed by deterministic queries; no language model takes part.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.db.neo4j.driver import get_driver
from app.db.postgres.session import create_session
from app.seed.golden import data as seed

ERP_TABLES: tuple[str, ...] = (
    "suppliers",
    "supplier_parts",
    "inventory_balances",
    "purchase_orders",
    "purchase_order_lines",
    "production_orders",
    "production_material_requirements",
    "sales_orders",
    "sales_order_lines",
)

ECM_AGENT_AUDIT_TABLES: tuple[tuple[str, str], ...] = (
    ("ecm", "change_cases"),
    ("ecm", "engineering_change_requests"),
    ("ecm", "change_impacts"),
    ("ecm", "change_strategies"),
    ("ecm", "change_strategy_actions"),
    ("ecm", "change_reviews"),
    ("ecm", "engineering_change_orders"),
    ("ecm", "approval_records"),
    ("ecm", "bom_redlines"),
    ("ecm", "bom_redline_lines"),
    ("ecm", "execution_jobs"),
    ("agent", "agent_runs"),
    ("agent", "agent_steps"),
    ("agent", "tool_calls"),
    ("audit", "audit_events"),
)

EOL_PART_NUMBER = "BRG-6204-A"
QUALIFIED_ALTERNATIVE = "BRG-6204-B"
UNQUALIFIED_ALTERNATIVE = "BRG-6204-C"
PRODUCT_NUMBERS: tuple[str, ...] = tuple(number for number, _n, _c in seed.PRODUCTS)


@dataclass(frozen=True)
class CheckResult:
    """One verification outcome."""

    name: str
    passed: bool
    detail: str


def erp_counts() -> dict[str, int]:
    """Return the row count of every ERP table."""
    with create_session() as session:
        return {
            table: session.execute(
                text(f"SELECT count(*) FROM erp.{table}")
            ).scalar_one()
            for table in ERP_TABLES
        }


def empty_schema_counts() -> dict[str, int]:
    """Return the row count of every ECM / agent / audit table."""
    with create_session() as session:
        return {
            f"{schema}.{table}": session.execute(
                text(f"SELECT count(*) FROM {schema}.{table}")
            ).scalar_one()
            for schema, table in ECM_AGENT_AUDIT_TABLES
        }


def graph_counts() -> tuple[dict[str, int], dict[str, int]]:
    """Return node counts per label and relationship counts per type."""
    database = get_settings().neo4j.database
    labels: dict[str, int] = {}
    relationships: dict[str, int] = {}
    with get_driver().session(database=database) as session:
        for record in session.run(
            "MATCH (n) UNWIND labels(n) AS label "
            "RETURN label, count(*) AS count ORDER BY label"
        ):
            labels[str(record["label"])] = int(record["count"])
        for record in session.run(
            "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(*) AS count "
            "ORDER BY rel_type"
        ):
            relationships[str(record["rel_type"])] = int(record["count"])
    return labels, relationships


#: One intermediate BOM level, walked strictly upwards:
#: PartRevision <- COMPONENT - BOMLine <- HAS_LINE - BOMVersion <- HAS_BOM - PartRevision.
#: The relationship types and their directions are fixed, so no other
#: relationship added to the graph later can create a false where-used path.
_WHERE_USED_LINK = (
    "<-[:COMPONENT]-(:BOMLine)<-[:HAS_LINE]-(:BOMVersion)"
    "<-[:HAS_BOM]-(:PartRevision)"
)

#: The last level ends at the named ``upper`` revision.
_WHERE_USED_LAST = (
    "<-[:COMPONENT]-(:BOMLine)<-[:HAS_LINE]-(:BOMVersion)"
    "<-[:HAS_BOM]-(upper:PartRevision)"
)

#: Maximum BOM levels the where-used helper walks by default.
DEFAULT_WHERE_USED_LEVELS = 4


def _where_used_query(levels: int) -> str:
    """Build a UNION query returning the ancestors of each BOM level."""
    branches = [
        "MATCH (leaf:PartRevision {part_number: $part_number})"
        + _WHERE_USED_LINK * (level - 1)
        + _WHERE_USED_LAST
        + " "
        + f"RETURN DISTINCT {level} AS level, upper.part_number AS part_number"
        for level in range(1, levels + 1)
    ]
    return "\nUNION\n".join(branches) + "\nORDER BY level, part_number"


def where_used_levels(
    part_number: str, levels: int = DEFAULT_WHERE_USED_LEVELS
) -> dict[str, int]:
    """Return the BOM level at which each ancestor uses ``part_number``.

    The traversal only follows the BOM chain (line -> version -> parent
    revision) and is explicit per level, so the result cannot be distorted by
    unrelated relationships.
    """
    database = get_settings().neo4j.database
    result: dict[str, int] = {}
    with get_driver().session(database=database) as session:
        for record in session.run(
            _where_used_query(levels), part_number=part_number
        ):
            name = str(record["part_number"])
            level = int(record["level"])
            if name not in result or level < result[name]:
                result[name] = level
    return result


def where_used_ancestors(
    part_number: str, levels: int = DEFAULT_WHERE_USED_LEVELS
) -> list[str]:
    """Return every part revision that uses ``part_number``, directly or above."""
    return sorted(where_used_levels(part_number, levels))


def direct_parents(part_number: str) -> list[str]:
    """Return the part revisions that use ``part_number`` as a component."""
    database = get_settings().neo4j.database
    query = (
        "MATCH (leaf:PartRevision {part_number: $part_number})"
        "<-[:COMPONENT]-(:BOMLine)<-[:HAS_LINE]-(:BOMVersion)"
        "<-[:HAS_BOM]-(parent:PartRevision) "
        "RETURN DISTINCT parent.part_number AS part_number ORDER BY part_number"
    )
    with get_driver().session(database=database) as session:
        return [
            str(record["part_number"])
            for record in session.run(query, part_number=part_number)
        ]


def alternative_parts(part_number: str) -> list[dict[str, Any]]:
    """Return the ``ALTERNATIVE_TO`` targets of one part revision."""
    database = get_settings().neo4j.database
    query = (
        "MATCH (a:PartRevision {part_number: $part_number})"
        "-[r:ALTERNATIVE_TO]->(b:PartRevision) "
        "RETURN b.part_number AS part_number, "
        "r.qualification_status AS qualification_status, "
        "r.replacement_type AS replacement_type, r.verified_by AS verified_by "
        "ORDER BY part_number"
    )
    with get_driver().session(database=database) as session:
        return [
            dict(record) for record in session.run(query, part_number=part_number)
        ]


def _scalar(sql: str, **params: Any) -> Any:
    """Run a single-value SQL query."""
    with create_session() as session:
        return session.execute(text(sql), params).scalar_one()


def case_eol_checks() -> list[CheckResult]:
    """Run the CASE-EOL-001 verification suite."""
    results: list[CheckResult] = []

    supplier_rows = _scalar(
        """
        SELECT count(*) FROM erp.supplier_parts sp
        JOIN erp.suppliers s ON s.supplier_id = sp.supplier_id
        WHERE s.supplier_code = 'SUP-001' AND sp.part_number = :part
          AND sp.status = 'LAST_TIME_BUY'
          AND sp.last_time_buy_date = DATE '2026-11-30'
          AND sp.eol_date = DATE '2027-01-31'
        """,
        part=EOL_PART_NUMBER,
    )
    results.append(
        CheckResult(
            "MotionWorks / SUP-001 EOL supply row",
            supplier_rows == 1,
            "LAST_TIME_BUY with last_time_buy 2026-11-30 and eol 2027-01-31",
        )
    )

    inventory_rows = _scalar(
        "SELECT count(*) FROM erp.inventory_balances WHERE part_number = :part",
        part=EOL_PART_NUMBER,
    )
    results.append(
        CheckResult(
            "inventory balance for BRG-6204-A",
            inventory_rows >= 1,
            f"{inventory_rows} inventory row(s)",
        )
    )

    open_purchase_orders = _scalar(
        """
        SELECT count(DISTINCT po.po_id)
        FROM erp.purchase_orders po
        JOIN erp.purchase_order_lines pol ON pol.po_id = po.po_id
        WHERE pol.part_number = :part
          AND po.status NOT IN ('COMPLETED', 'CANCELLED')
        """,
        part=EOL_PART_NUMBER,
    )
    results.append(
        CheckResult(
            "at least 3 unfinished purchase orders for BRG-6204-A",
            open_purchase_orders >= 3,
            f"{open_purchase_orders} unfinished purchase order(s)",
        )
    )

    frozen_orders = _scalar(
        """
        SELECT count(DISTINCT po.production_order_id)
        FROM erp.production_orders po
        JOIN erp.production_material_requirements pmr
          ON pmr.production_order_id = po.production_order_id
        WHERE pmr.part_number = :part
          AND po.status IN ('RELEASED', 'IN_PROGRESS')
        """,
        part=EOL_PART_NUMBER,
    )
    results.append(
        CheckResult(
            "at least 7 unfinished production orders need BRG-6204-A",
            frozen_orders >= 7,
            f"{frozen_orders} released / in-progress order(s)",
        )
    )

    frozen_example = _scalar(
        """
        SELECT pmr.required_qty
        FROM erp.production_orders po
        JOIN erp.production_material_requirements pmr
          ON pmr.production_order_id = po.production_order_id
        WHERE po.order_number = 'MO-2026-000001' AND pmr.part_number = :part
        """,
        part=EOL_PART_NUMBER,
    )
    results.append(
        CheckResult(
            "frozen requirement equals the BOM explosion (ROB-P100 x10 -> 60)",
            Decimal(str(frozen_example)) == Decimal(60),
            f"required_qty = {frozen_example}",
        )
    )

    control_orders = _scalar(
        """
        SELECT count(*)
        FROM (
            SELECT po.production_order_id
            FROM erp.production_orders po
            JOIN erp.production_material_requirements pmr
              ON pmr.production_order_id = po.production_order_id
            GROUP BY po.production_order_id
            HAVING count(*) FILTER (WHERE pmr.part_number = :part) = 0
        ) unaffected
        """,
        part=EOL_PART_NUMBER,
    )
    results.append(
        CheckResult(
            "control production orders (frozen, but without BRG-6204-A) exist",
            control_orders >= 1,
            f"{control_orders} order(s) with frozen requirements "
            "that do not mention the part",
        )
    )

    ancestors = where_used_ancestors(EOL_PART_NUMBER)
    gearboxes = sorted(name for name in ancestors if name.startswith("ASM-GEARBOX"))
    results.append(
        CheckResult(
            "at least 2 gearboxes use BRG-6204-A",
            len(gearboxes) >= 2,
            f"{gearboxes}",
        )
    )

    affected_products = sorted(set(ancestors) & set(PRODUCT_NUMBERS))
    results.append(
        CheckResult(
            "BRG-6204-A reaches all four finished products",
            affected_products == sorted(PRODUCT_NUMBERS),
            f"{affected_products}",
        )
    )

    levels = where_used_levels(EOL_PART_NUMBER)
    rob_level = levels.get("ROB-P100")
    results.append(
        CheckResult(
            "where-used path of at least 3 BOM levels exists",
            rob_level is not None and rob_level >= 3,
            f"BRG-6204-A -> ROB-P100 = {rob_level} BOM level(s)",
        )
    )

    related_sales_orders = _scalar(
        """
        SELECT count(DISTINCT so.sales_order_id)
        FROM erp.sales_orders so
        JOIN erp.sales_order_lines sol ON sol.sales_order_id = so.sales_order_id
        WHERE so.status NOT IN ('CANCELLED', 'DRAFT')
          AND sol.product_part_number = ANY(CAST(:products AS text[]))
        """,
        products=affected_products,
    )
    results.append(
        CheckResult(
            "at least 5 open sales orders for affected products",
            related_sales_orders >= 5,
            f"{related_sales_orders} open sales order(s)",
        )
    )

    alternatives = {
        item["part_number"]: item for item in alternative_parts(EOL_PART_NUMBER)
    }
    qualified = alternatives.get(QUALIFIED_ALTERNATIVE, {}).get("qualification_status")
    unqualified = alternatives.get(UNQUALIFIED_ALTERNATIVE, {}).get(
        "qualification_status"
    )
    results.append(
        CheckResult(
            "BRG-6204-B is a QUALIFIED alternative",
            qualified == "QUALIFIED",
            f"qualification_status = {qualified}",
        )
    )
    results.append(
        CheckResult(
            "BRG-6204-C is an UNQUALIFIED alternative",
            unqualified == "UNQUALIFIED",
            f"qualification_status = {unqualified}",
        )
    )

    empty = empty_schema_counts()
    dirty = {name: count for name, count in empty.items() if count}
    results.append(
        CheckResult(
            "ECM / agent / audit schemas are empty",
            not dirty,
            "all 15 tables have 0 rows" if not dirty else f"non-empty: {dirty}",
        )
    )
    return results
