"""In-memory fakes for the ERP fact repositories.

Each fake returns prepared facts and records the arguments it received, so the
service's validation and pass-through behaviour can be tested without a
database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from app.db.postgres.repositories.inventory import InventoryFact
from app.db.postgres.repositories.production import ProductionRequirementFact
from app.db.postgres.repositories.purchase import PurchaseOrderLineFact
from app.db.postgres.repositories.sales import SalesOrderLineFact
from app.db.postgres.repositories.supplier import SupplierPartFact


def supplier_part_fact(
    part_number: str = "BRG-TEST-A",
    revision_code: str = "A",
    supplier_code: str = "SUP-TEST-1",
) -> SupplierPartFact:
    """Build one supply relationship fact."""
    return SupplierPartFact(
        supplier_code=supplier_code,
        supplier_name="Test Supplier",
        supplier_status="ACTIVE",
        part_number=part_number,
        revision_code=revision_code,
        manufacturer_part_number="MPN-1",
        qualification_status="QUALIFIED",
        supplier_part_status="LAST_TIME_BUY",
        unit_price=Decimal("12.5000"),
        currency="CNY",
        lead_time_days=30,
        minimum_order_qty=Decimal(50),
        last_time_buy_date=date(2026, 11, 30),
        eol_date=date(2027, 1, 31),
    )


def inventory_fact(
    qty_on_hand: str = "820", qty_reserved: str = "120"
) -> InventoryFact:
    """Build one inventory fact."""
    return InventoryFact(
        plant_code="CN-E01",
        warehouse_code="WH-01",
        part_number="BRG-TEST-A",
        revision_code="A",
        qty_on_hand=Decimal(qty_on_hand),
        qty_reserved=Decimal(qty_reserved),
        unit_cost=Decimal("12.5000"),
        currency="CNY",
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def purchase_line_fact(
    po_number: str = "PO-TEST-000001",
    po_status: str = "OPEN",
    ordered_qty: str = "500",
    received_qty: str = "0",
) -> PurchaseOrderLineFact:
    """Build one purchase order line fact."""
    return PurchaseOrderLineFact(
        po_number=po_number,
        po_status=po_status,
        po_order_date=date(2026, 8, 4),
        po_expected_date=date(2026, 10, 15),
        supplier_code="SUP-TEST-1",
        supplier_name="Test Supplier",
        line_number=1,
        part_number="BRG-TEST-A",
        revision_code="A",
        ordered_qty=Decimal(ordered_qty),
        received_qty=Decimal(received_qty),
        unit_price=Decimal("12.5000"),
        currency="CNY",
        expected_date=date(2026, 10, 15),
        line_status=po_status,
    )


def production_requirement_fact(
    order_number: str = "MO-TEST-000001", order_status: str = "RELEASED"
) -> ProductionRequirementFact:
    """Build one frozen production requirement fact."""
    return ProductionRequirementFact(
        order_number=order_number,
        order_status=order_status,
        product_part_number="ROB-TEST",
        product_revision="A",
        line_number=1,
        part_number="BRG-TEST-A",
        revision_code="A",
        required_qty=Decimal("60.0000"),
        reserved_qty=Decimal(0),
        issued_qty=Decimal(0),
        planned_start=datetime(2026, 9, 7, 8, 0, tzinfo=UTC),
        planned_end=datetime(2026, 9, 25, 17, 0, tzinfo=UTC),
    )


def sales_line_fact(
    order_number: str = "SO-TEST-000001",
    order_status: str = "OPEN",
    product: str = "ROB-TEST",
) -> SalesOrderLineFact:
    """Build one sales order line fact."""
    return SalesOrderLineFact(
        order_number=order_number,
        order_status=order_status,
        customer_code="CUST-TEST",
        order_date=date(2026, 8, 3),
        line_number=1,
        product_part_number=product,
        product_revision="A",
        ordered_qty=Decimal(6),
        delivered_qty=Decimal(0),
        requested_delivery_date=date(2026, 11, 15),
    )


@dataclass
class FakeSupplierRepository:
    """Supplier repository stand-in."""

    facts: list[SupplierPartFact] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def find_supplier_parts(
        self, part_number: str, revision_code: str
    ) -> list[SupplierPartFact]:
        self.calls.append((part_number, revision_code))
        return list(self.facts)


@dataclass
class FakeInventoryRepository:
    """Inventory repository stand-in."""

    facts: list[InventoryFact] = field(default_factory=list)
    calls: list[tuple[str, str, str | None, str | None]] = field(default_factory=list)

    def find_inventory(
        self,
        part_number: str,
        revision_code: str,
        plant_code: str | None = None,
        warehouse_code: str | None = None,
    ) -> list[InventoryFact]:
        self.calls.append((part_number, revision_code, plant_code, warehouse_code))
        return list(self.facts)


@dataclass
class FakePurchaseRepository:
    """Purchase repository stand-in."""

    facts: list[PurchaseOrderLineFact] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def find_purchase_order_lines(
        self, part_number: str, revision_code: str
    ) -> list[PurchaseOrderLineFact]:
        self.calls.append((part_number, revision_code))
        return list(self.facts)


@dataclass
class FakeProductionRepository:
    """Production repository stand-in."""

    facts: list[ProductionRequirementFact] = field(default_factory=list)
    calls: list[tuple[str, str, tuple[str, ...] | None]] = field(default_factory=list)

    def find_material_requirements(
        self,
        part_number: str,
        revision_code: str,
        order_statuses: Sequence[str] | None = None,
    ) -> list[ProductionRequirementFact]:
        self.calls.append(
            (
                part_number,
                revision_code,
                tuple(order_statuses) if order_statuses else None,
            )
        )
        return list(self.facts)


@dataclass
class FakeSalesRepository:
    """Sales repository stand-in."""

    facts: list[SalesOrderLineFact] = field(default_factory=list)
    calls: list[tuple[tuple[str, str], ...]] = field(default_factory=list)

    def find_sales_order_lines(
        self, product_references: Sequence[tuple[str, str]]
    ) -> list[SalesOrderLineFact]:
        self.calls.append(tuple(product_references))
        return list(self.facts)
