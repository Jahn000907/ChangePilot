"""ERP fact service: read supplier, inventory, purchase, production and sales facts.

The service validates the request, delegates every query to a repository and
assembles the DTOs. It performs **no** business conclusion: no available
quantity, no open purchase quantity, no sales exposure, no recommendation. Those
derived values belong to the rule layer of a later task.

Infrastructure failures (for example an unreachable PostgreSQL) propagate
unchanged; only invalid input becomes a domain error, and "no rows" stays an
empty result rather than an exception.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.db.postgres.repositories.inventory import InventoryRepository
from app.db.postgres.repositories.production import ProductionRepository
from app.db.postgres.repositories.purchase import PurchaseRepository
from app.db.postgres.repositories.sales import SalesRepository
from app.db.postgres.repositories.supplier import SupplierRepository
from app.domain.dto.erp_facts import (
    InventoryFact,
    InventoryFactResult,
    ProductionRequirementFact,
    ProductionRequirementFactResult,
    PurchaseOrderFact,
    PurchaseOrderFactResult,
    SalesOrderFact,
    SalesOrderFactResult,
    SupplierFact,
    SupplierFactResult,
)
from app.domain.errors import DomainValidationError


class ERPFactService:
    """Answer "what do the ERP tables say about this part / product?"""

    def __init__(
        self,
        suppliers: SupplierRepository | None = None,
        inventory: InventoryRepository | None = None,
        purchase: PurchaseRepository | None = None,
        production: ProductionRepository | None = None,
        sales: SalesRepository | None = None,
    ) -> None:
        self._suppliers = suppliers if suppliers is not None else SupplierRepository()
        self._inventory = inventory if inventory is not None else InventoryRepository()
        self._purchase = purchase if purchase is not None else PurchaseRepository()
        self._production = (
            production if production is not None else ProductionRepository()
        )
        self._sales = sales if sales is not None else SalesRepository()

    # ------------------------------------------------------------------
    # Supplier facts
    # ------------------------------------------------------------------
    def supplier_parts(
        self, part_number: str, revision_code: str
    ) -> SupplierFactResult:
        """Return every supplier relationship of a part revision."""
        part_number = _require_identifier(part_number, "part_number")
        revision_code = _require_identifier(revision_code, "revision_code")
        rows = [
            SupplierFact.model_validate(fact)
            for fact in self._suppliers.find_supplier_parts(
                part_number, revision_code
            )
        ]
        return SupplierFactResult(
            part_number=part_number, revision_code=revision_code, rows=rows
        )

    # ------------------------------------------------------------------
    # Inventory facts
    # ------------------------------------------------------------------
    def inventory(
        self,
        part_number: str,
        revision_code: str | None,
        plant_code: str | None = None,
        warehouse_code: str | None = None,
    ) -> InventoryFactResult:
        """Return inventory balances, optionally filtered by plant / warehouse."""
        part_number = _require_identifier(part_number, "part_number")
        revision_code = _optional_identifier(revision_code, "revision_code")
        plant_code = _optional_identifier(plant_code, "plant_code")
        warehouse_code = _optional_identifier(warehouse_code, "warehouse_code")
        rows = [
            InventoryFact.model_validate(fact)
            for fact in self._inventory.find_inventory(
                part_number, revision_code, plant_code, warehouse_code
            )
        ]
        return InventoryFactResult(
            part_number=part_number,
            revision_code=revision_code,
            plant_code=plant_code,
            warehouse_code=warehouse_code,
            rows=rows,
        )

    # ------------------------------------------------------------------
    # Purchase facts
    # ------------------------------------------------------------------
    def purchase_order_lines(
        self, part_number: str, revision_code: str, *, open_only: bool = False
    ) -> PurchaseOrderFactResult:
        """Return purchase order lines for a part revision, statuses included."""
        part_number = _require_identifier(part_number, "part_number")
        revision_code = _require_identifier(revision_code, "revision_code")
        rows = [
            PurchaseOrderFact.model_validate(fact)
            for fact in self._purchase.find_purchase_order_lines(
                part_number, revision_code
            )
        ]
        if open_only:
            rows = [
                row for row in rows
                if row.po_status not in {"COMPLETED", "CANCELLED"}
                and row.line_status != "CANCELLED"
                and row.ordered_qty > row.received_qty
            ]
        return PurchaseOrderFactResult(
            part_number=part_number, revision_code=revision_code, rows=rows
        )

    # ------------------------------------------------------------------
    # Production facts (frozen requirements)
    # ------------------------------------------------------------------
    def production_requirements(
        self,
        part_number: str,
        revision_code: str,
        order_statuses: Sequence[str] | None = None,
    ) -> ProductionRequirementFactResult:
        """Return the frozen material requirements that mention a part revision.

        The rows are read from ``erp.production_material_requirements`` only; the
        current Neo4j BOM is never used to reconstruct historical demand.
        """
        part_number = _require_identifier(part_number, "part_number")
        revision_code = _require_identifier(revision_code, "revision_code")
        statuses = _normalise_order_statuses(order_statuses)
        rows = [
            ProductionRequirementFact.model_validate(fact)
            for fact in self._production.find_material_requirements(
                part_number, revision_code, statuses
            )
        ]
        return ProductionRequirementFactResult(
            part_number=part_number,
            revision_code=revision_code,
            order_statuses=statuses,
            rows=rows,
        )

    # ------------------------------------------------------------------
    # Sales facts
    # ------------------------------------------------------------------
    def sales_order_lines(
        self, product_references: Sequence[tuple[str, str]]
    ) -> SalesOrderFactResult:
        """Return sales order lines for the affected product revisions.

        Sales orders are placed for finished products, so the caller passes the
        product revisions collected from the product structure query instead of a
        component number.
        """
        references = _normalise_product_references(product_references)
        rows = [
            SalesOrderFact.model_validate(fact)
            for fact in self._sales.find_sales_order_lines(list(references))
        ]
        return SalesOrderFactResult(product_references=references, rows=rows)


def _require_identifier(value: str, field: str) -> str:
    """Return a trimmed identifier or raise a domain validation error."""
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_identifier(value: str | None, field: str) -> str | None:
    """Validate an optional filter value."""
    if value is None:
        return None
    return _require_identifier(value, field)


def _normalise_order_statuses(
    order_statuses: Sequence[str] | None,
) -> tuple[str, ...] | None:
    """Validate the optional production order status filter."""
    if order_statuses is None:
        return None
    if isinstance(order_statuses, str):
        raise DomainValidationError(
            "order_statuses must be a sequence of status values"
        )
    statuses = tuple(
        _require_identifier(status, "order_status") for status in order_statuses
    )
    return statuses or None


def _normalise_product_references(
    product_references: Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    """Validate and de-duplicate the affected product revisions."""
    if isinstance(product_references, str) or not isinstance(
        product_references, Sequence
    ):
        raise DomainValidationError(
            "product_references must be a sequence of (part_number, revision_code) pairs"
        )
    if not product_references:
        raise DomainValidationError("product_references must not be empty")
    references: list[tuple[str, str]] = []
    for item in product_references:
        if isinstance(item, str) or not isinstance(item, Sequence) or len(item) != 2:
            raise DomainValidationError(
                "each product reference must be a (part_number, revision_code) pair, "
                f"got {item!r}"
            )
        number = _require_identifier(item[0], "product_part_number")
        revision = _require_identifier(item[1], "product_revision")
        pair = (number, revision)
        if pair not in references:
            references.append(pair)
    return tuple(references)
