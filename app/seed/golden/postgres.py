"""Load the Golden Seed ERP data into PostgreSQL.

Generation order follows design doc v0.4 section 63: suppliers, supply
relationships, sales demand, production orders, the frozen material
requirements produced by the BOM explosion, inventory and finally purchase
orders. Nothing is generated independently of the product structure.

Idempotency: every row carries a deterministic primary key derived from its
business key, and every write is an ``INSERT ... ON CONFLICT DO UPDATE`` on that
key. Re-running the loader refreshes the rows instead of duplicating them, and
no table is truncated or deleted from.

``production_material_requirements`` is filled from
``data.explode_leaf_requirements`` at load time: the values are frozen rows, so
reading historical demand never touches the current Neo4j BOM (v0.4 section 64).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.postgres import models  # noqa: F401  (registers the ORM models)
from app.db.postgres.base import Base
from app.db.postgres.session import create_session
from app.seed.golden import data as seed

_UNFINISHED_PRODUCTION_STATES = ("RELEASED", "IN_PROGRESS")


def _table(name: str):
    """Return one ORM table by its fully qualified name."""
    return Base.metadata.tables[name]


def _upsert(session: Session, table_name: str, rows: list[dict[str, Any]], pk: str) -> int:
    """Upsert rows on their deterministic primary key and return the row count."""
    if not rows:
        return 0
    table = _table(table_name)
    statement = pg_insert(table).values(rows)
    update_columns = {
        column: statement.excluded[column]
        for column in rows[0]
        if column != pk
    }
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[table.c[pk]], set_=update_columns
        )
    )
    return len(rows)


# --------------------------------------------------------------------------
# Row builders
# --------------------------------------------------------------------------
def supplier_rows() -> list[dict[str, Any]]:
    """Rows for ``erp.suppliers`` (v0.4 section 26)."""
    return [
        {
            "supplier_id": seed.golden_id("supplier", supplier.supplier_code),
            "supplier_code": supplier.supplier_code,
            "supplier_name": supplier.supplier_name,
            "status": supplier.status,
            "quality_rating": supplier.quality_rating,
            "delivery_rating": supplier.delivery_rating,
            "created_at": seed.SEED_TIMESTAMP,
            "updated_at": seed.SEED_TIMESTAMP,
        }
        for supplier in seed.SUPPLIERS
    ]


def supplier_part_rows() -> list[dict[str, Any]]:
    """Rows for ``erp.supplier_parts`` (v0.4 section 27)."""
    return [
        {
            "supplier_part_id": seed.golden_id(
                "supplier_part", f"{item.supplier_code}:{item.part_number}"
            ),
            "supplier_id": seed.golden_id("supplier", item.supplier_code),
            "part_number": item.part_number,
            "revision_code": seed.DEFAULT_REVISION_CODE,
            "manufacturer_part_number": item.manufacturer_part_number,
            "qualification_status": item.qualification_status,
            "unit_price": item.unit_price,
            "currency": seed.CURRENCY,
            "lead_time_days": item.lead_time_days,
            "minimum_order_qty": item.minimum_order_qty,
            "last_time_buy_date": item.last_time_buy_date,
            "eol_date": item.eol_date,
            "status": item.status,
            "created_at": seed.SEED_TIMESTAMP,
            "updated_at": seed.SEED_TIMESTAMP,
        }
        for item in seed.SUPPLIER_PARTS
    ]


def inventory_rows() -> list[dict[str, Any]]:
    """Rows for ``erp.inventory_balances`` (v0.4 section 28)."""
    return [
        {
            "inventory_id": seed.golden_id(
                "inventory",
                f"{seed.PLANT_CODE}:{seed.WAREHOUSE_CODE}:"
                f"{item.part_number}:{item.revision_code}",
            ),
            "plant_code": seed.PLANT_CODE,
            "warehouse_code": seed.WAREHOUSE_CODE,
            "part_number": item.part_number,
            "revision_code": item.revision_code,
            "qty_on_hand": item.qty_on_hand,
            "qty_reserved": item.qty_reserved,
            "unit_cost": item.unit_cost,
            "currency": seed.CURRENCY,
            "created_at": seed.SEED_TIMESTAMP,
            "updated_at": seed.SEED_TIMESTAMP,
        }
        for item in seed.INVENTORY
    ]


def purchase_order_rows() -> list[dict[str, Any]]:
    """Rows for ``erp.purchase_orders`` (v0.4 section 29)."""
    return [
        {
            "po_id": seed.golden_id("purchase_order", order.po_number),
            "po_number": order.po_number,
            "supplier_id": seed.golden_id("supplier", order.supplier_code),
            "status": order.status,
            "order_date": order.order_date,
            "expected_date": order.expected_date,
            "currency": seed.CURRENCY,
            "created_at": seed.SEED_TIMESTAMP,
            "updated_at": seed.SEED_TIMESTAMP,
        }
        for order in seed.PURCHASE_ORDERS
    ]


def purchase_order_line_rows() -> list[dict[str, Any]]:
    """Rows for ``erp.purchase_order_lines`` (v0.4 section 30)."""
    rows: list[dict[str, Any]] = []
    for order in seed.PURCHASE_ORDERS:
        for line_number, line in enumerate(order.lines, start=1):
            rows.append(
                {
                    "po_line_id": seed.golden_id(
                        "purchase_order_line", f"{order.po_number}:{line_number}"
                    ),
                    "po_id": seed.golden_id("purchase_order", order.po_number),
                    "line_number": line_number,
                    "part_number": line.part_number,
                    "revision_code": line.revision_code,
                    "ordered_qty": line.ordered_qty,
                    "received_qty": line.received_qty,
                    "unit_price": line.unit_price,
                    "expected_date": line.expected_date,
                    "status": line.status,
                    "created_at": seed.SEED_TIMESTAMP,
                }
            )
    return rows


def production_order_rows() -> list[dict[str, Any]]:
    """Rows for ``erp.production_orders`` (v0.4 section 31)."""
    return [
        {
            "production_order_id": seed.golden_id(
                "production_order", order.order_number
            ),
            "order_number": order.order_number,
            "product_part_number": order.product_part_number,
            "product_revision": order.product_revision,
            "planned_qty": order.planned_qty,
            "completed_qty": order.completed_qty,
            "planned_start": order.planned_start,
            "planned_end": order.planned_end,
            "status": order.status,
            "created_at": seed.SEED_TIMESTAMP,
            "updated_at": seed.SEED_TIMESTAMP,
        }
        for order in seed.PRODUCTION_ORDERS
    ]


def material_requirement_rows() -> list[dict[str, Any]]:
    """Rows for ``erp.production_material_requirements`` (v0.4 section 32).

    The quantity of every leaf part comes from the deterministic BOM explosion
    of the order's product and planned quantity, so the requirement is frozen at
    the values that were valid when the order was released. Issued quantities
    are set only for completed orders; reserved quantities stay zero because
    allocation is not part of the MVP.

    Only orders in :data:`FROZEN_REQUIREMENT_STATUSES` are expanded: a
    ``PLANNED`` order has not been released, so nothing has been frozen for it.
    """
    rows: list[dict[str, Any]] = []
    for order in seed.production_orders_with_frozen_requirements():
        requirements = seed.explode_leaf_requirements(
            order.product_part_number, order.planned_qty
        )
        issued_full = order.status == "COMPLETED"
        for line_number, key in enumerate(sorted(requirements), start=1):
            required_qty = requirements[key]
            rows.append(
                {
                    "requirement_id": seed.golden_id(
                        "material_requirement", f"{order.order_number}:{line_number}"
                    ),
                    "production_order_id": seed.golden_id(
                        "production_order", order.order_number
                    ),
                    "line_number": line_number,
                    "part_number": key[0],
                    "revision_code": key[1],
                    "required_qty": required_qty,
                    "reserved_qty": Decimal(0),
                    "issued_qty": required_qty if issued_full else Decimal(0),
                    "created_at": seed.SEED_TIMESTAMP,
                }
            )
    return rows


def prune_stale_requirement_rows(session: Session) -> int:
    """Delete frozen requirements of orders that must not have any.

    The delete is restricted to the deterministic ids of the golden seed's own
    production orders, so no unknown business data can be removed: only rows
    that this seed previously created for a not-yet-released order disappear.
    """
    stale_orders = seed.production_orders_without_frozen_requirements()
    if not stale_orders:
        return 0
    table = _table("erp.production_material_requirements")
    stale_ids = [
        seed.golden_id("production_order", order.order_number)
        for order in stale_orders
    ]
    result = session.execute(
        table.delete().where(table.c.production_order_id.in_(stale_ids))
    )
    return int(result.rowcount or 0)


def sales_order_rows() -> list[dict[str, Any]]:
    """Rows for ``erp.sales_orders`` (v0.4 section 33)."""
    return [
        {
            "sales_order_id": seed.golden_id("sales_order", order.order_number),
            "order_number": order.order_number,
            "customer_code": order.customer_code,
            "status": order.status,
            "order_date": order.order_date,
            "requested_delivery_date": order.requested_delivery_date,
            "created_at": seed.SEED_TIMESTAMP,
            "updated_at": seed.SEED_TIMESTAMP,
        }
        for order in seed.SALES_ORDERS
    ]


def sales_order_line_rows() -> list[dict[str, Any]]:
    """Rows for ``erp.sales_order_lines`` (v0.4 section 34)."""
    rows: list[dict[str, Any]] = []
    for order in seed.SALES_ORDERS:
        for line_number, (product, ordered, delivered) in enumerate(
            order.lines, start=1
        ):
            rows.append(
                {
                    "sales_order_line_id": seed.golden_id(
                        "sales_order_line", f"{order.order_number}:{line_number}"
                    ),
                    "sales_order_id": seed.golden_id(
                        "sales_order", order.order_number
                    ),
                    "line_number": line_number,
                    "product_part_number": product,
                    "product_revision": seed.DEFAULT_REVISION_CODE,
                    "ordered_qty": Decimal(ordered),
                    "delivered_qty": Decimal(delivered),
                    "requested_delivery_date": order.requested_delivery_date,
                    "created_at": seed.SEED_TIMESTAMP,
                }
            )
    return rows


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def load_golden_erp() -> dict[str, int]:
    """Write the whole golden ERP data set and return row counts per table."""
    session = create_session()
    try:
        counts = {
            "erp.suppliers": _upsert(
                session, "erp.suppliers", supplier_rows(), "supplier_id"
            ),
            "erp.supplier_parts": _upsert(
                session,
                "erp.supplier_parts",
                supplier_part_rows(),
                "supplier_part_id",
            ),
            "erp.sales_orders": _upsert(
                session, "erp.sales_orders", sales_order_rows(), "sales_order_id"
            ),
            "erp.sales_order_lines": _upsert(
                session,
                "erp.sales_order_lines",
                sales_order_line_rows(),
                "sales_order_line_id",
            ),
            "erp.production_orders": _upsert(
                session,
                "erp.production_orders",
                production_order_rows(),
                "production_order_id",
            ),
            "erp.production_material_requirements": _upsert(
                session,
                "erp.production_material_requirements",
                material_requirement_rows(),
                "requirement_id",
            ),
            "erp.production_material_requirements.removed_stale": (
                prune_stale_requirement_rows(session)
            ),
            "erp.inventory_balances": _upsert(
                session,
                "erp.inventory_balances",
                inventory_rows(),
                "inventory_id",
            ),
            "erp.purchase_orders": _upsert(
                session, "erp.purchase_orders", purchase_order_rows(), "po_id"
            ),
            "erp.purchase_order_lines": _upsert(
                session,
                "erp.purchase_order_lines",
                purchase_order_line_rows(),
                "po_line_id",
            ),
        }
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return counts
