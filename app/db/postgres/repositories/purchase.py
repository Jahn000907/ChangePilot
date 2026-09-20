"""Purchase order line facts (v0.4 sections 29 / 30)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.postgres.models.erp import (
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.db.postgres.repositories.base import ReadOnlyRepository


@dataclass(frozen=True)
class PurchaseOrderLineFact:
    """One purchase order line together with its order header facts.

    The order and line statuses are returned as-is: classifying an order as
    "open" or "at risk" is a rule of a later task, not a fact query.
    """

    po_number: str
    po_status: str
    po_order_date: date
    po_expected_date: date | None
    supplier_code: str
    supplier_name: str
    line_number: int
    part_number: str
    revision_code: str
    ordered_qty: Decimal
    received_qty: Decimal
    unit_price: Decimal
    currency: str
    expected_date: date | None
    line_status: str


class PurchaseRepository(ReadOnlyRepository):
    """Read purchase order facts."""

    def find_purchase_order_lines(
        self, part_number: str, revision_code: str
    ) -> list[PurchaseOrderLineFact]:
        """Return every purchase order line that orders the part revision."""
        statement = (
            select(
                PurchaseOrder.po_number.label("po_number"),
                PurchaseOrder.status.label("po_status"),
                PurchaseOrder.order_date.label("po_order_date"),
                PurchaseOrder.expected_date.label("po_expected_date"),
                Supplier.supplier_code.label("supplier_code"),
                Supplier.supplier_name.label("supplier_name"),
                PurchaseOrderLine.line_number.label("line_number"),
                PurchaseOrderLine.part_number.label("part_number"),
                PurchaseOrderLine.revision_code.label("revision_code"),
                PurchaseOrderLine.ordered_qty.label("ordered_qty"),
                PurchaseOrderLine.received_qty.label("received_qty"),
                PurchaseOrderLine.unit_price.label("unit_price"),
                PurchaseOrder.currency.label("currency"),
                PurchaseOrderLine.expected_date.label("expected_date"),
                PurchaseOrderLine.status.label("line_status"),
            )
            .join(
                PurchaseOrder,
                PurchaseOrderLine.po_id == PurchaseOrder.po_id,
            )
            .join(Supplier, PurchaseOrder.supplier_id == Supplier.supplier_id)
            .where(PurchaseOrderLine.part_number == part_number)
            .where(PurchaseOrderLine.revision_code == revision_code)
            .order_by(PurchaseOrder.po_number, PurchaseOrderLine.line_number)
        )
        return [
            PurchaseOrderLineFact(
                po_number=str(row.po_number),
                po_status=str(row.po_status),
                po_order_date=row.po_order_date,
                po_expected_date=row.po_expected_date,
                supplier_code=str(row.supplier_code),
                supplier_name=str(row.supplier_name),
                line_number=int(row.line_number),
                part_number=str(row.part_number),
                revision_code=str(row.revision_code),
                ordered_qty=Decimal(row.ordered_qty),
                received_qty=Decimal(row.received_qty),
                unit_price=Decimal(row.unit_price),
                currency=str(row.currency),
                expected_date=row.expected_date,
                line_status=str(row.line_status),
            )
            for row in self._fetch_all(statement)
        ]
