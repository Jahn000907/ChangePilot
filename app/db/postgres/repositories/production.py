"""Frozen production material requirement facts (v0.4 sections 31 / 32)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.db.postgres.models.erp import (
    ProductionMaterialRequirement,
    ProductionOrder,
)
from app.db.postgres.repositories.base import ReadOnlyRepository


@dataclass(frozen=True)
class ProductionRequirementFact:
    """One frozen material requirement of a production order.

    The values come from ``erp.production_material_requirements`` exactly as the
    order was released: the current Neo4j BOM is never consulted, so historical
    demand cannot be rewritten by a later engineering change (v0.4 section 64).
    """

    order_number: str
    order_status: str
    product_part_number: str
    product_revision: str
    line_number: int
    part_number: str
    revision_code: str
    required_qty: Decimal
    reserved_qty: Decimal
    issued_qty: Decimal
    planned_start: datetime
    planned_end: datetime


class ProductionRepository(ReadOnlyRepository):
    """Read production order and frozen requirement facts."""

    def find_material_requirements(
        self,
        part_number: str,
        revision_code: str,
        order_statuses: Sequence[str] | None = None,
    ) -> list[ProductionRequirementFact]:
        """Return frozen requirements that mention the part revision."""
        statement = (
            select(
                ProductionOrder.order_number.label("order_number"),
                ProductionOrder.status.label("order_status"),
                ProductionOrder.product_part_number.label("product_part_number"),
                ProductionOrder.product_revision.label("product_revision"),
                ProductionMaterialRequirement.line_number.label("line_number"),
                ProductionMaterialRequirement.part_number.label("part_number"),
                ProductionMaterialRequirement.revision_code.label("revision_code"),
                ProductionMaterialRequirement.required_qty.label("required_qty"),
                ProductionMaterialRequirement.reserved_qty.label("reserved_qty"),
                ProductionMaterialRequirement.issued_qty.label("issued_qty"),
                ProductionOrder.planned_start.label("planned_start"),
                ProductionOrder.planned_end.label("planned_end"),
            )
            .join(
                ProductionOrder,
                ProductionMaterialRequirement.production_order_id
                == ProductionOrder.production_order_id,
            )
            .where(ProductionMaterialRequirement.part_number == part_number)
            .where(ProductionMaterialRequirement.revision_code == revision_code)
            .order_by(ProductionOrder.order_number, ProductionMaterialRequirement.line_number)
        )
        if order_statuses:
            statement = statement.where(
                ProductionOrder.status.in_(list(order_statuses))
            )
        return [
            ProductionRequirementFact(
                order_number=str(row.order_number),
                order_status=str(row.order_status),
                product_part_number=str(row.product_part_number),
                product_revision=str(row.product_revision),
                line_number=int(row.line_number),
                part_number=str(row.part_number),
                revision_code=str(row.revision_code),
                required_qty=Decimal(row.required_qty),
                reserved_qty=Decimal(row.reserved_qty),
                issued_qty=Decimal(row.issued_qty),
                planned_start=row.planned_start,
                planned_end=row.planned_end,
            )
            for row in self._fetch_all(statement)
        ]
