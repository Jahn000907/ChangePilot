"""DTOs for the deterministic impact calculations.

These are the outputs of the rule layer: every quantity and amount is a
``Decimal``, dates are ``date`` / ``datetime``, and classifications use the
controlled enums defined here so no rule vocabulary is spelled out in the
callers.

Nothing in this module decides *what to do*: there is no shortage, no risk
level, no recommendation and no chosen alternative. Those belong to the
cross-domain orchestration of a later task.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _MetricModel(BaseModel):
    """Base model shared by the rule layer results."""

    model_config = ConfigDict(from_attributes=True)


class SupplierEOLMetrics(_MetricModel):
    """Time metrics of one supplier relationship against a business date."""

    part_number: str
    revision_code: str
    supplier_code: str
    supplier_name: str
    supplier_part_status: str
    qualification_status: str
    as_of_date: date
    last_time_buy_date: date | None = None
    eol_date: date | None = None
    days_to_last_time_buy: int | None = None
    days_to_eol: int | None = None
    last_time_buy_passed: bool
    eol_passed: bool


class InventoryMetrics(_MetricModel):
    """Aggregated inventory of one part revision across all locations."""

    part_number: str
    revision_code: str
    total_on_hand: Decimal
    total_reserved: Decimal
    available_qty: Decimal
    line_count: int = Field(ge=0)
    locations: tuple[str, ...] = ()


class PurchaseInboundClass(StrEnum):
    """How a purchase order currently counts as inbound material."""

    COMMITTED_OPEN = "COMMITTED_OPEN"
    POTENTIAL = "POTENTIAL"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


class PurchaseLineAssessment(_MetricModel):
    """One purchase order line with its remaining quantity and class."""

    po_number: str
    po_status: str
    classification: PurchaseInboundClass
    supplier_code: str
    line_number: int = Field(ge=1)
    ordered_qty: Decimal
    received_qty: Decimal
    remaining_qty: Decimal
    currency: str
    expected_date: date | None = None


class PurchaseOrderAssessment(_MetricModel):
    """Order-level purchase classification (header status drives the class)."""

    po_number: str
    po_status: str
    classification: PurchaseInboundClass
    supplier_code: str
    remaining_qty: Decimal
    line_count: int = Field(ge=1)
    expected_date: date | None = None


class PurchaseMetrics(_MetricModel):
    """Purchase inbound metrics of one part revision."""

    part_number: str
    revision_code: str
    committed_open_qty: Decimal
    potential_qty: Decimal
    blocked_qty: Decimal
    lines: list[PurchaseLineAssessment]
    orders: list[PurchaseOrderAssessment]


class ProductionDemandClass(StrEnum):
    """Whether a production order still needs the component."""

    CURRENT_FROZEN_DEMAND = "CURRENT_FROZEN_DEMAND"
    HISTORICAL_DEMAND = "HISTORICAL_DEMAND"


class ProductionRequirementAssessment(_MetricModel):
    """One frozen requirement with its remaining quantity and class."""

    order_number: str
    order_status: str
    classification: ProductionDemandClass
    product_part_number: str
    product_revision: str
    line_number: int = Field(ge=1)
    required_qty: Decimal
    reserved_qty: Decimal
    issued_qty: Decimal
    remaining_required_qty: Decimal
    planned_start: datetime
    planned_end: datetime


class ProductionMetrics(_MetricModel):
    """Current frozen demand of one part revision.

    ``reserved_qty`` stays a separate fact: a reservation is not a consumption,
    so it is not subtracted from ``remaining_required_qty``.
    """

    part_number: str
    revision_code: str
    current_remaining_qty: Decimal
    current_order_count: int = Field(ge=0)
    historical_order_count: int = Field(ge=0)
    requirements: list[ProductionRequirementAssessment]
    remaining_by_order: dict[str, Decimal]
    remaining_by_product: dict[str, Decimal]


class SalesExposureClass(StrEnum):
    """Customer exposure of a sales order line."""

    CURRENT_EXPOSURE = "CURRENT_EXPOSURE"
    POTENTIAL_EXPOSURE = "POTENTIAL_EXPOSURE"
    NOT_EXPOSED = "NOT_EXPOSED"


class SalesLineAssessment(_MetricModel):
    """One sales order line with its remaining delivery quantity and class."""

    order_number: str
    order_status: str
    classification: SalesExposureClass
    customer_code: str
    line_number: int = Field(ge=1)
    product_part_number: str
    product_revision: str
    ordered_qty: Decimal
    delivered_qty: Decimal
    remaining_delivery_qty: Decimal
    requested_delivery_date: date | None = None


class SalesOrderAssessment(_MetricModel):
    """Order-level sales exposure (header status drives the class)."""

    order_number: str
    order_status: str
    classification: SalesExposureClass
    customer_code: str
    remaining_delivery_qty: Decimal
    line_count: int = Field(ge=1)
    requested_delivery_date: date | None = None


class SalesExposureMetrics(_MetricModel):
    """Sales exposure metrics for a set of affected product revisions."""

    product_references: tuple[tuple[str, str], ...]
    current_exposure_orders: int = Field(ge=0)
    current_exposure_qty: Decimal
    potential_exposure_orders: int = Field(ge=0)
    potential_exposure_qty: Decimal
    not_exposed_orders: int = Field(ge=0)
    lines: list[SalesLineAssessment]
    orders: list[SalesOrderAssessment]


class AlternativeClassification(StrEnum):
    """Qualification outcome of one alternative part."""

    ELIGIBLE = "ELIGIBLE"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    INELIGIBLE = "INELIGIBLE"


class AlternativeAssessment(_MetricModel):
    """Qualification classification of one alternative.

    Deliberately carries no ``recommended`` / ``best_alternative`` field:
    choosing a replacement is a later strategy decision.
    """

    alternative_part_number: str
    alternative_revision_code: str
    qualification_status: str
    replacement_type: str
    classification: AlternativeClassification
    verified_by: str | None = None
    verified_at: datetime | None = None


class PurchaseTimingClass(StrEnum):
    """Where a planned delivery date falls relative to the EOL window.

    The class only says where the *planned* date sits: it never claims the goods
    will actually arrive on time.
    """

    ARRIVES_BEFORE_LTB = "ARRIVES_BEFORE_LTB"
    ARRIVES_AFTER_LTB_BEFORE_EOL = "ARRIVES_AFTER_LTB_BEFORE_EOL"
    ARRIVES_AFTER_EOL = "ARRIVES_AFTER_EOL"
    EXPECTED_DATE_UNKNOWN = "EXPECTED_DATE_UNKNOWN"


class PurchaseTimingAssessment(_MetricModel):
    """Timing classification of one purchase order line.

    ``timing_classification`` is ``None`` when no supplier EOL window exists, so
    no delivery window can be defined at all; it is
    ``EXPECTED_DATE_UNKNOWN`` when a window exists but the line has no planned
    delivery date.
    """

    po_number: str
    line_number: int = Field(ge=1)
    po_status: str
    classification: PurchaseInboundClass
    ordered_qty: Decimal
    received_qty: Decimal
    remaining_qty: Decimal
    expected_date: date | None = None
    timing_classification: PurchaseTimingClass | None = None


class SalesMaterialEquivalentLine(_MetricModel):
    """Material-equivalent exposure of one sales order line."""

    order_number: str
    line_number: int = Field(ge=1)
    order_status: str
    classification: SalesExposureClass
    product_part_number: str
    product_revision: str
    remaining_delivery_qty: Decimal
    requirement_per_product: Decimal
    material_equivalent_qty: Decimal


class SalesMaterialEquivalentMetrics(_MetricModel):
    """Structure-equivalent exposure of the sales pipeline.

    This is the sales-side view only: it must **not** be added to the frozen
    production demand, because the model has no sales-order to production-order
    allocation and that sum would double count the same material.
    """

    current_material_equivalent_qty: Decimal
    potential_material_equivalent_qty: Decimal
    lines: list[SalesMaterialEquivalentLine]


class SupplyCoverage(_MetricModel):
    """Coverage of the current frozen demand by stored and committed material."""

    available_inventory: Decimal
    current_frozen_production_demand: Decimal
    committed_open_purchase_qty: Decimal
    inventory_coverage_delta: Decimal
    projected_coverage_delta: Decimal
    inventory_covers_current_frozen_demand: bool
    projected_supply_covers_current_frozen_demand: bool
