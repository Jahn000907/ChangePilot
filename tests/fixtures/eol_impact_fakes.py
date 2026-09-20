"""Fakes and sample DTOs for the EOL impact orchestration tests.

The fake services return prepared 2A / 2B DTOs and record the calls they
receive, so the orchestration can be tested without a database. The numbers
mirror the golden seed, which lets the unit test assert the accepted metrics
without touching PostgreSQL or Neo4j.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from app.domain.dto.erp_facts import (
    InventoryFact,
    ProductionRequirementFact,
    PurchaseOrderFact,
    SalesOrderFact,
    SupplierFact,
)
from app.domain.dto.product_structure import (
    AlternativeResult,
    AlternativeRow,
    BomExplosionResult,
    WhereUsedResult,
    WhereUsedRow,
)

EOL_PART = "BRG-6204-A"
REVISION = "A"
AS_OF = date(2026, 9, 20)

#: Requirement per single unit of each affected finished product.
REQUIREMENT_PER_PRODUCT: dict[str, Decimal] = {
    "ROB-P100": Decimal(6),
    "ROB-P200": Decimal(12),
    "CON-C100": Decimal(4),
    "PAL-P300": Decimal(2),
}

#: Current frozen demand per order (golden seed values, total 322).
CURRENT_DEMAND_BY_ORDER: dict[str, Decimal] = {
    "MO-2026-000001": Decimal(60),
    "MO-2026-000002": Decimal(48),
    "MO-2026-000004": Decimal(60),
    "MO-2026-000005": Decimal(48),
    "MO-2026-000006": Decimal(72),
    "MO-2026-000007": Decimal(12),
    "MO-2026-000008": Decimal(8),
    "MO-2026-000009": Decimal(8),
    "MO-2026-000010": Decimal(6),
}

ORDER_PRODUCT: dict[str, str] = {
    "MO-2026-000001": "ROB-P100",
    "MO-2026-000002": "ROB-P100",
    "MO-2026-000004": "ROB-P200",
    "MO-2026-000005": "ROB-P200",
    "MO-2026-000006": "ROB-P100",
    "MO-2026-000007": "CON-C100",
    "MO-2026-000008": "CON-C100",
    "MO-2026-000009": "PAL-P300",
    "MO-2026-000010": "PAL-P300",
}

#: Sales lines of the four affected products: (order, status, product, qty, delivered).
SALES_LINES: tuple[tuple[str, str, str, str, str], ...] = (
    ("SO-2026-000001", "OPEN", "ROB-P100", "6", "0"),
    ("SO-2026-000002", "CONFIRMED", "ROB-P200", "3", "0"),
    ("SO-2026-000003", "OPEN", "CON-C100", "2", "0"),
    ("SO-2026-000004", "PARTIALLY_DELIVERED", "PAL-P300", "4", "1"),
    ("SO-2026-000005", "OPEN", "ROB-P100", "4", "0"),
    ("SO-2026-000006", "CONFIRMED", "ROB-P200", "2", "0"),
    ("SO-2026-000007", "COMPLETED", "ROB-P100", "3", "3"),
    ("SO-2026-000008", "OPEN", "CON-C100", "3", "0"),
    ("SO-2026-000009", "PARTIALLY_DELIVERED", "ROB-P200", "4", "2"),
    ("SO-2026-000010", "CONFIRMED", "PAL-P300", "2", "0"),
    ("SO-2026-000011", "COMPLETED", "ROB-P100", "5", "5"),
    ("SO-2026-000012", "OPEN", "CON-C100", "1", "0"),
    ("SO-2026-000013", "CONFIRMED", "PAL-P300", "3", "0"),
    ("SO-2026-000014", "DRAFT", "ROB-P200", "1", "0"),
    ("SO-2026-000015", "CANCELLED", "ROB-P100", "2", "0"),
)


def supplier_facts() -> list[SupplierFact]:
    """Return the golden supply relationship of BRG-6204-A."""
    return [
        SupplierFact(
            supplier_code="SUP-001",
            supplier_name="MotionWorks",
            supplier_status="ACTIVE",
            part_number=EOL_PART,
            revision_code=REVISION,
            manufacturer_part_number="MW-6204-A",
            qualification_status="QUALIFIED",
            supplier_part_status="LAST_TIME_BUY",
            unit_price=Decimal("12.5000"),
            currency="CNY",
            lead_time_days=30,
            minimum_order_qty=Decimal(50),
            last_time_buy_date=date(2026, 11, 30),
            eol_date=date(2027, 1, 31),
        )
    ]


def inventory_facts() -> list[InventoryFact]:
    """Return the golden inventory balance (820 on hand / 120 reserved)."""
    return [
        InventoryFact(
            plant_code="CN-E01",
            warehouse_code="WH-01",
            part_number=EOL_PART,
            revision_code=REVISION,
            qty_on_hand=Decimal(820),
            qty_reserved=Decimal(120),
            unit_cost=Decimal("12.5000"),
            currency="CNY",
            updated_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    ]


def purchase_facts() -> list[PurchaseOrderFact]:
    """Return the three unfinished golden purchase orders (900 open units)."""
    orders = (
        ("PO-2026-000001", "OPEN", "500", "0", date(2026, 10, 15)),
        ("PO-2026-000004", "PARTIALLY_RECEIVED", "300", "100", date(2026, 10, 5)),
        ("PO-2026-000007", "OPEN", "200", "0", date(2026, 10, 25)),
    )
    return [
        PurchaseOrderFact(
            po_number=number,
            po_status=status,
            po_order_date=date(2026, 8, 4),
            po_expected_date=expected,
            supplier_code="SUP-001",
            supplier_name="MotionWorks",
            line_number=1,
            part_number=EOL_PART,
            revision_code=REVISION,
            ordered_qty=Decimal(ordered),
            received_qty=Decimal(received),
            unit_price=Decimal("12.5000"),
            currency="CNY",
            expected_date=expected,
            line_status=status,
        )
        for number, status, ordered, received, expected in orders
    ]


def production_facts() -> list[ProductionRequirementFact]:
    """Return nine current plus two historical frozen requirements."""
    facts = [
        ProductionRequirementFact(
            order_number=order,
            order_status="RELEASED" if index % 2 == 0 else "IN_PROGRESS",
            product_part_number=ORDER_PRODUCT[order],
            product_revision=REVISION,
            line_number=1,
            part_number=EOL_PART,
            revision_code=REVISION,
            required_qty=quantity,
            reserved_qty=Decimal(0),
            issued_qty=Decimal(0),
            planned_start=datetime(2026, 9, 7, 8, 0, tzinfo=UTC),
            planned_end=datetime(2026, 9, 25, 17, 0, tzinfo=UTC),
        )
        for index, (order, quantity) in enumerate(CURRENT_DEMAND_BY_ORDER.items())
    ]
    facts.append(
        ProductionRequirementFact(
            order_number="MO-2026-000003",
            order_status="COMPLETED",
            product_part_number="ROB-P100",
            product_revision=REVISION,
            line_number=1,
            part_number=EOL_PART,
            revision_code=REVISION,
            required_qty=Decimal(36),
            reserved_qty=Decimal(0),
            issued_qty=Decimal(36),
            planned_start=datetime(2026, 7, 6, 8, 0, tzinfo=UTC),
            planned_end=datetime(2026, 7, 31, 17, 0, tzinfo=UTC),
        )
    )
    return facts


def sales_facts() -> list[SalesOrderFact]:
    """Return the golden sales lines of the four affected products."""
    return [
        SalesOrderFact(
            order_number=order,
            order_status=status,
            customer_code="CUST-001",
            order_date=date(2026, 8, 3),
            line_number=1,
            product_part_number=product,
            product_revision=REVISION,
            ordered_qty=Decimal(ordered),
            delivered_qty=Decimal(delivered),
            requested_delivery_date=date(2026, 11, 15),
        )
        for order, status, product, ordered, delivered in SALES_LINES
    ]


def where_used_result(max_depth: int = 5, as_of_date: date = AS_OF) -> WhereUsedResult:
    """Return the golden where-used structure of BRG-6204-A."""
    rows = (
        (1, "ASM-GEARBOX100", "ASSEMBLY"),
        (1, "ASM-GEARBOX200", "ASSEMBLY"),
        (1, "ASM-GEARBOX300", "ASSEMBLY"),
        (1, "ASM-GEARBOX400", "ASSEMBLY"),
        (2, "ASM-JOINT100", "ASSEMBLY"),
        (3, "ASM-ARM100", "ASSEMBLY"),
        (3, "CON-C100", "FINISHED_PRODUCT"),
        (3, "PAL-P300", "FINISHED_PRODUCT"),
        (4, "ROB-P100", "FINISHED_PRODUCT"),
        (4, "ROB-P200", "FINISHED_PRODUCT"),
    )
    where_rows = [
        WhereUsedRow(
            bom_level=level,
            ancestor_part_number=name,
            ancestor_revision_code=REVISION,
            ancestor_part_type=part_type,
            bom_version_id=f"bv-{name}",
            bom_code=f"BOM-{name}-01",
            path=[EOL_PART] + [name],
        )
        for level, name, part_type in rows
    ]
    return WhereUsedResult(
        part_number=EOL_PART,
        revision_code=REVISION,
        as_of_date=as_of_date,
        bom_statuses=("RELEASED",),
        max_depth=max_depth,
        rows=where_rows,
        ancestors=sorted({row.ancestor_part_number for row in where_rows}),
        products=sorted(
            {
                row.ancestor_part_number
                for row in where_rows
                if row.ancestor_part_type == "FINISHED_PRODUCT"
            }
        ),
    )


def explosion_result(
    product: str, as_of_date: date = AS_OF, max_depth: int = 5
) -> BomExplosionResult:
    """Return a BOM explosion result carrying the golden per-product total."""
    requirement = REQUIREMENT_PER_PRODUCT.get(product, Decimal(0))
    return BomExplosionResult(
        part_number=product,
        revision_code=REVISION,
        as_of_date=as_of_date,
        bom_version_id=f"bv-{product}",
        bom_code=f"BOM-{product}-01",
        bom_statuses=("RELEASED",),
        max_depth=max_depth,
        rows=[],
        totals={f"{EOL_PART}|{REVISION}": requirement},
    )


def alternative_result() -> AlternativeResult:
    """Return the golden alternatives of BRG-6204-A."""
    return AlternativeResult(
        part_number=EOL_PART,
        revision_code=REVISION,
        rows=[
            AlternativeRow(
                alternative_part_number="BRG-6204-B",
                alternative_revision_code=REVISION,
                qualification_status="QUALIFIED",
                replacement_type="DIRECT",
                verified_at=None,
                verified_by="quality.engineer",
                alternative_id="alt-1",
            ),
            AlternativeRow(
                alternative_part_number="BRG-6204-C",
                alternative_revision_code=REVISION,
                qualification_status="UNQUALIFIED",
                replacement_type="CONDITIONAL",
                verified_at=None,
                verified_by="quality.engineer",
                alternative_id="alt-2",
            ),
        ],
    )


@dataclass
class FakeProductStructureService:
    """Product structure service stand-in returning prepared DTOs."""

    where_used_result: WhereUsedResult | None = None
    explosion_results: dict[str, BomExplosionResult] = field(default_factory=dict)
    alternatives: AlternativeResult | None = None
    error: Exception | None = None
    where_used_calls: list[tuple[str, str, int, date]] = field(default_factory=list)
    explosion_calls: list[tuple[str, str, int, date]] = field(default_factory=list)
    alternative_calls: list[tuple[str, str]] = field(default_factory=list)

    def where_used(
        self,
        part_number: str,
        revision_code: str,
        max_depth: int = 5,
        as_of_date: date | None = None,
        statuses: Sequence[str] | None = None,
    ) -> WhereUsedResult:
        if self.error is not None:
            raise self.error
        self.where_used_calls.append(
            (part_number, revision_code, max_depth, as_of_date)
        )
        assert self.where_used_result is not None
        return self.where_used_result

    def explode_bom(
        self,
        part_number: str,
        revision_code: str,
        max_depth: int = 5,
        as_of_date: date | None = None,
        statuses: Sequence[str] | None = None,
    ) -> BomExplosionResult:
        if self.error is not None:
            raise self.error
        self.explosion_calls.append((part_number, revision_code, max_depth, as_of_date))
        return self.explosion_results[part_number]

    def find_alternatives(
        self, part_number: str, revision_code: str
    ) -> AlternativeResult:
        self.alternative_calls.append((part_number, revision_code))
        return self.alternatives or AlternativeResult(
            part_number=part_number, revision_code=revision_code, rows=[]
        )


@dataclass
class FakeERPFactService:
    """ERP fact service stand-in returning prepared DTOs."""

    suppliers: list[SupplierFact] = field(default_factory=list)
    inventory_facts: list[InventoryFact] = field(default_factory=list)
    purchase_facts: list[PurchaseOrderFact] = field(default_factory=list)
    production_facts: list[ProductionRequirementFact] = field(default_factory=list)
    sales_facts: list[SalesOrderFact] = field(default_factory=list)
    calls: list[tuple] = field(default_factory=list)

    def supplier_parts(self, part_number: str, revision_code: str):
        self.calls.append(("supplier_parts", part_number, revision_code))
        return _Result(self.suppliers)

    def inventory(
        self,
        part_number: str,
        revision_code: str,
        plant_code: str | None = None,
        warehouse_code: str | None = None,
    ):
        self.calls.append(("inventory", part_number, revision_code))
        return _Result(self.inventory_facts)

    def purchase_order_lines(self, part_number: str, revision_code: str):
        self.calls.append(("purchase_order_lines", part_number, revision_code))
        return _Result(self.purchase_facts)

    def production_requirements(
        self,
        part_number: str,
        revision_code: str,
        order_statuses: Sequence[str] | None = None,
    ):
        self.calls.append(("production_requirements", part_number, revision_code))
        return _Result(self.production_facts)

    def sales_order_lines(self, product_references):
        self.calls.append(("sales_order_lines", tuple(product_references)))
        return _Result(self.sales_facts)


@dataclass(frozen=True)
class _Result:
    """Minimal stand-in for the ``*FactResult`` DTOs (only ``rows`` is used)."""

    rows: list
