"""Supplier master data and supplier/part supply relationships (v0.4 §26/§27)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select

from app.db.postgres.models.erp import Supplier, SupplierPart
from app.db.postgres.repositories.base import ReadOnlyRepository


@dataclass(frozen=True)
class SupplierPartFact:
    """One supplier / part supply relationship with its supplier identity."""

    supplier_code: str
    supplier_name: str
    supplier_status: str
    part_number: str
    revision_code: str | None
    manufacturer_part_number: str
    qualification_status: str
    supplier_part_status: str
    unit_price: Decimal
    currency: str
    lead_time_days: int
    minimum_order_qty: Decimal
    last_time_buy_date: date | None
    eol_date: date | None


class SupplierRepository(ReadOnlyRepository):
    """Read supplier and supply-relationship facts."""

    def find_supplier_parts(
        self, part_number: str, revision_code: str
    ) -> list[SupplierPartFact]:
        """Return every supplier that supplies the part revision.

        A supply row whose ``revision_code`` is ``NULL`` applies to the part
        regardless of revision (v0.4 section 27 allows the column to be empty),
        so those rows match as well.
        """
        statement = (
            select(
                Supplier.supplier_code.label("supplier_code"),
                Supplier.supplier_name.label("supplier_name"),
                Supplier.status.label("supplier_status"),
                SupplierPart.part_number.label("part_number"),
                SupplierPart.revision_code.label("revision_code"),
                SupplierPart.manufacturer_part_number.label(
                    "manufacturer_part_number"
                ),
                SupplierPart.qualification_status.label("qualification_status"),
                SupplierPart.status.label("supplier_part_status"),
                SupplierPart.unit_price.label("unit_price"),
                SupplierPart.currency.label("currency"),
                SupplierPart.lead_time_days.label("lead_time_days"),
                SupplierPart.minimum_order_qty.label("minimum_order_qty"),
                SupplierPart.last_time_buy_date.label("last_time_buy_date"),
                SupplierPart.eol_date.label("eol_date"),
            )
            .join(Supplier, SupplierPart.supplier_id == Supplier.supplier_id)
            .where(SupplierPart.part_number == part_number)
            .where(
                or_(
                    SupplierPart.revision_code == revision_code,
                    SupplierPart.revision_code.is_(None),
                )
            )
            .order_by(Supplier.supplier_code, SupplierPart.manufacturer_part_number)
        )
        return [
            SupplierPartFact(
                supplier_code=str(row.supplier_code),
                supplier_name=str(row.supplier_name),
                supplier_status=str(row.supplier_status),
                part_number=str(row.part_number),
                revision_code=(
                    str(row.revision_code) if row.revision_code is not None else None
                ),
                manufacturer_part_number=str(row.manufacturer_part_number),
                qualification_status=str(row.qualification_status),
                supplier_part_status=str(row.supplier_part_status),
                unit_price=Decimal(row.unit_price),
                currency=str(row.currency),
                lead_time_days=int(row.lead_time_days),
                minimum_order_qty=Decimal(row.minimum_order_qty),
                last_time_buy_date=row.last_time_buy_date,
                eol_date=row.eol_date,
            )
            for row in self._fetch_all(statement)
        ]
