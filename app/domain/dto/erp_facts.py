"""Data transfer objects for the ERP fact queries.

The DTOs mirror the stored facts exactly: quantities and amounts stay
``decimal.Decimal``, dates stay ``date`` / ``datetime``, and no SQLAlchemy type
crosses this boundary. Derived business values (available quantity, open
purchase quantity, sales exposure, cost impact) are intentionally absent: they
belong to the rule layer of a later task.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _FactModel(BaseModel):
    """Base model that can be built straight from a repository dataclass."""

    model_config = ConfigDict(from_attributes=True)


class SupplierFact(_FactModel):
    """One supplier / part supply relationship (v0.4 section 27)."""

    supplier_code: str
    supplier_name: str
    supplier_status: str
    part_number: str
    revision_code: str | None = None
    manufacturer_part_number: str
    qualification_status: str
    supplier_part_status: str
    unit_price: Decimal
    currency: str
    lead_time_days: int = Field(ge=0)
    minimum_order_qty: Decimal
    last_time_buy_date: date | None = None
    eol_date: date | None = None


class SupplierFactResult(_FactModel):
    """All supply relationships of one part revision."""

    part_number: str
    revision_code: str
    rows: list[SupplierFact]


class InventoryFact(_FactModel):
    """One inventory balance row (v0.4 section 28)."""

    plant_code: str
    warehouse_code: str
    part_number: str
    revision_code: str
    qty_on_hand: Decimal
    qty_reserved: Decimal
    unit_cost: Decimal
    currency: str
    updated_at: datetime


class InventoryFactResult(_FactModel):
    """Inventory balances of one part revision."""

    part_number: str
    revision_code: str | None
    plant_code: str | None = None
    warehouse_code: str | None = None
    rows: list[InventoryFact]


class PurchaseOrderFact(_FactModel):
    """One purchase order line with its order header facts (v0.4 sections 29/30)."""

    po_number: str
    po_status: str
    po_order_date: date
    po_expected_date: date | None = None
    supplier_code: str
    supplier_name: str
    line_number: int = Field(ge=1)
    part_number: str
    revision_code: str
    ordered_qty: Decimal
    received_qty: Decimal
    unit_price: Decimal
    currency: str
    expected_date: date | None = None
    line_status: str


class PurchaseOrderFactResult(_FactModel):
    """Purchase order lines that order one part revision."""

    part_number: str
    revision_code: str
    rows: list[PurchaseOrderFact]


class ProductionRequirementFact(_FactModel):
    """One frozen material requirement of a production order (section 32)."""

    order_number: str
    order_status: str
    product_part_number: str
    product_revision: str
    line_number: int = Field(ge=1)
    part_number: str
    revision_code: str
    required_qty: Decimal
    reserved_qty: Decimal
    issued_qty: Decimal
    planned_start: datetime
    planned_end: datetime


class ProductionRequirementFactResult(_FactModel):
    """Frozen requirements that mention one part revision."""

    part_number: str
    revision_code: str
    order_statuses: tuple[str, ...] | None = None
    rows: list[ProductionRequirementFact]


class SalesOrderFact(_FactModel):
    """One sales order line for a finished product (v0.4 sections 33/34)."""

    order_number: str
    order_status: str
    customer_code: str
    order_date: date
    line_number: int = Field(ge=1)
    product_part_number: str
    product_revision: str
    ordered_qty: Decimal
    delivered_qty: Decimal
    requested_delivery_date: date | None = None


class SalesOrderFactResult(_FactModel):
    """Sales order lines of a set of affected product revisions."""

    product_references: tuple[tuple[str, str], ...]
    rows: list[SalesOrderFact]
