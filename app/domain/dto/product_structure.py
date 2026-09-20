"""Data transfer objects for the product structure (BOM) graph.

These models are the boundary between the data layer and everything above it:
no ``neo4j.Record``, ``neo4j.Node`` or driver type ever crosses into the
service or the future tools. Quantities are always ``decimal.Decimal``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

#: Qualification values of ``ALTERNATIVE_TO`` (design doc v0.4 section 21).
QualificationStatus = Literal["QUALIFIED", "CONDITIONAL", "UNQUALIFIED"]

#: Replacement types of ``ALTERNATIVE_TO`` (design doc v0.4 section 21).
ReplacementType = Literal["DIRECT", "CONDITIONAL", "TEMPORARY"]


class PartRevisionDTO(BaseModel):
    """One part revision with the identity data of its part."""

    part_number: str
    revision_code: str
    part_type: str
    name: str
    category: str
    make_or_buy: str
    base_unit: str
    lifecycle_state: str
    effective_from: date | None = None
    effective_to: date | None = None


class BomExplosionRow(BaseModel):
    """One exploded BOM line: a component of exactly one parent revision."""

    bom_level: int = Field(ge=1)
    parent_part_number: str
    parent_revision_code: str
    component_part_number: str
    component_revision_code: str
    line_number: int = Field(ge=1)
    quantity_per: Decimal = Field(gt=0)
    cumulative_quantity: Decimal = Field(gt=0)
    unit: str
    bom_version_id: str
    bom_line_id: str


class BomExplosionResult(BaseModel):
    """The full explosion of one product revision."""

    part_number: str
    revision_code: str
    #: Business date the BOM effectivity was evaluated against.
    as_of_date: date
    #: BOM version of the input revision that was effective on ``as_of_date``.
    bom_version_id: str
    bom_code: str
    bom_statuses: tuple[str, ...]
    max_depth: int
    rows: list[BomExplosionRow]
    #: Quantity of one component per single unit of the product, keyed "PART|REV".
    totals: dict[str, Decimal]

    def quantity_of(
        self, part_number: str, revision_code: str = "A"
    ) -> Decimal:
        """Return the total quantity of one component per product unit."""
        return self.totals.get(f"{part_number}|{revision_code}", Decimal(0))

    @property
    def component_part_numbers(self) -> list[str]:
        """Return every distinct component part number, sorted."""
        return sorted(
            {row.component_part_number for row in self.rows}
        )


class WhereUsedRow(BaseModel):
    """One place where a part revision is used by an ancestor revision."""

    bom_level: int = Field(ge=1)
    ancestor_part_number: str
    ancestor_revision_code: str
    ancestor_part_type: str
    #: BOM version of the ancestor that was effective on ``as_of_date``.
    bom_version_id: str
    bom_code: str
    #: Part numbers from the searched part up to the ancestor.
    path: list[str]


class WhereUsedResult(BaseModel):
    """The upward usage structure of one part revision."""

    part_number: str
    revision_code: str
    #: Business date the BOM effectivity was evaluated against.
    as_of_date: date
    bom_statuses: tuple[str, ...]
    max_depth: int
    rows: list[WhereUsedRow]
    ancestors: list[str]
    products: list[str]


class AlternativeRow(BaseModel):
    """One ``ALTERNATIVE_TO`` relationship leaving a part revision."""

    alternative_part_number: str
    alternative_revision_code: str
    qualification_status: QualificationStatus
    replacement_type: ReplacementType
    verified_at: datetime | None = None
    verified_by: str | None = None
    alternative_id: str | None = None


class AlternativeResult(BaseModel):
    """The alternatives of one part revision, as deterministic facts only.

    The result never marks one alternative as "the" choice: selecting a
    replacement is a later business decision.
    """

    part_number: str
    revision_code: str
    rows: list[AlternativeRow]
