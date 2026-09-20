"""Customer sales order facts (v0.4 sections 33 / 34)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select, tuple_

from app.db.postgres.models.erp import SalesOrder, SalesOrderLine
from app.db.postgres.repositories.base import ReadOnlyRepository


@dataclass(frozen=True)
class SalesOrderLineFact:
    """One sales order line for a finished product revision."""

    order_number: str
    order_status: str
    customer_code: str
    order_date: date
    line_number: int
    product_part_number: str
    product_revision: str
    ordered_qty: Decimal
    delivered_qty: Decimal
    requested_delivery_date: date | None


class SalesRepository(ReadOnlyRepository):
    """Read sales order facts for a set of affected products."""

    def find_sales_order_lines(
        self, product_references: Sequence[tuple[str, str]]
    ) -> list[SalesOrderLineFact]:
        """Return sales order lines for the given ``(product, revision)`` set.

        Sales orders are placed for finished products, not for a component, so
        the caller passes the affected product revisions collected from the
        product structure query.
        """
        if not product_references:
            return []
        statement = (
            select(
                SalesOrder.order_number.label("order_number"),
                SalesOrder.status.label("order_status"),
                SalesOrder.customer_code.label("customer_code"),
                SalesOrder.order_date.label("order_date"),
                SalesOrderLine.line_number.label("line_number"),
                SalesOrderLine.product_part_number.label("product_part_number"),
                SalesOrderLine.product_revision.label("product_revision"),
                SalesOrderLine.ordered_qty.label("ordered_qty"),
                SalesOrderLine.delivered_qty.label("delivered_qty"),
                SalesOrderLine.requested_delivery_date.label(
                    "requested_delivery_date"
                ),
            )
            .join(SalesOrder, SalesOrderLine.sales_order_id == SalesOrder.sales_order_id)
            .where(
                tuple_(
                    SalesOrderLine.product_part_number,
                    SalesOrderLine.product_revision,
                ).in_([(number, revision) for number, revision in product_references])
            )
            .order_by(SalesOrder.order_number, SalesOrderLine.line_number)
        )
        return [
            SalesOrderLineFact(
                order_number=str(row.order_number),
                order_status=str(row.order_status),
                customer_code=str(row.customer_code),
                order_date=row.order_date,
                line_number=int(row.line_number),
                product_part_number=str(row.product_part_number),
                product_revision=str(row.product_revision),
                ordered_qty=Decimal(row.ordered_qty),
                delivered_qty=Decimal(row.delivered_qty),
                requested_delivery_date=row.requested_delivery_date,
            )
            for row in self._fetch_all(statement)
        ]
