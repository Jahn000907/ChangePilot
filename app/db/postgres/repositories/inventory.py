"""Inventory balance facts (v0.4 section 28)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.db.postgres.models.erp import InventoryBalance
from app.db.postgres.repositories.base import ReadOnlyRepository


@dataclass(frozen=True)
class InventoryFact:
    """One inventory balance row.

    Only stored facts are exposed; ``available_qty`` is deliberately not
    computed here (that belongs to the impact rules of a later task).
    """

    plant_code: str
    warehouse_code: str
    part_number: str
    revision_code: str
    qty_on_hand: Decimal
    qty_reserved: Decimal
    unit_cost: Decimal
    currency: str
    updated_at: datetime


class InventoryRepository(ReadOnlyRepository):
    """Read inventory balance facts."""

    def find_inventory(
        self,
        part_number: str,
        revision_code: str,
        plant_code: str | None = None,
        warehouse_code: str | None = None,
    ) -> list[InventoryFact]:
        """Return inventory balances for a part revision, optionally filtered."""
        statement = (
            select(
                InventoryBalance.plant_code.label("plant_code"),
                InventoryBalance.warehouse_code.label("warehouse_code"),
                InventoryBalance.part_number.label("part_number"),
                InventoryBalance.revision_code.label("revision_code"),
                InventoryBalance.qty_on_hand.label("qty_on_hand"),
                InventoryBalance.qty_reserved.label("qty_reserved"),
                InventoryBalance.unit_cost.label("unit_cost"),
                InventoryBalance.currency.label("currency"),
                InventoryBalance.updated_at.label("updated_at"),
            )
            .where(InventoryBalance.part_number == part_number)
            .where(InventoryBalance.revision_code == revision_code)
            .order_by(InventoryBalance.plant_code, InventoryBalance.warehouse_code)
        )
        if plant_code is not None:
            statement = statement.where(InventoryBalance.plant_code == plant_code)
        if warehouse_code is not None:
            statement = statement.where(
                InventoryBalance.warehouse_code == warehouse_code
            )
        return [
            InventoryFact(
                plant_code=str(row.plant_code),
                warehouse_code=str(row.warehouse_code),
                part_number=str(row.part_number),
                revision_code=str(row.revision_code),
                qty_on_hand=Decimal(row.qty_on_hand),
                qty_reserved=Decimal(row.qty_reserved),
                unit_cost=Decimal(row.unit_cost),
                currency=str(row.currency),
                updated_at=row.updated_at,
            )
            for row in self._fetch_all(statement)
        ]
