"""Input contracts for the ChangePilot application tool layer."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.product_structure import DEFAULT_MAX_DEPTH, MAX_ALLOWED_DEPTH


class SupplierEOLImpactInput(BaseModel):
    """Validated input for the Supplier EOL impact analysis tool."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    part_number: str = Field(min_length=1, max_length=64)
    revision_code: str = Field(min_length=1, max_length=16)
    as_of_date: date
    max_depth: int = Field(default=DEFAULT_MAX_DEPTH, ge=1, le=MAX_ALLOWED_DEPTH)

    @field_validator("as_of_date", mode="before")
    @classmethod
    def _require_calendar_date(cls, value: object) -> object:
        """Reject timestamps so every run has an explicit business date."""
        if isinstance(value, datetime):
            # Pydantic turns ValueError into the input model's ValidationError.
            raise ValueError(  # noqa: TRY004
                "as_of_date must be a date, not a datetime"
            )
        return value


class _PartRevisionInput(BaseModel):
    """Shared validated identity used by read-only part tools."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    part_number: str = Field(min_length=1, max_length=64)
    revision_code: str = Field(min_length=1, max_length=16)


class _EffectiveStructureInput(_PartRevisionInput):
    """Shared effectivity and traversal inputs for product structure tools."""

    as_of_date: date | None = None
    max_depth: int = Field(default=DEFAULT_MAX_DEPTH, ge=1, le=MAX_ALLOWED_DEPTH)

    @field_validator("as_of_date", mode="before")
    @classmethod
    def _require_calendar_date(cls, value: object) -> object:
        if isinstance(value, datetime):
            raise ValueError(  # noqa: TRY004
                "as_of_date must be a date, not a datetime"
            )
        return value


class GetBOMStructureInput(_EffectiveStructureInput):
    """Input for retrieving an effective BOM structure."""


class FindWhereUsedInput(_EffectiveStructureInput):
    """Input for finding effective parent assemblies and products."""


class GetInventoryInput(BaseModel):
    """Input for retrieving inventory facts, optionally by location."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    part_number: str = Field(min_length=1, max_length=64)
    revision_code: str | None = Field(default=None, min_length=1, max_length=16)
    plant_code: str | None = Field(default=None, min_length=1, max_length=20)
    warehouse_code: str | None = Field(default=None, min_length=1, max_length=20)


class GetPurchaseOrdersInput(_PartRevisionInput):
    """Input for retrieving purchase order facts."""

    open_only: bool = False


class GetProductionRequirementsInput(_PartRevisionInput):
    """Input for retrieving production orders using one part revision."""


class GetAlternativesInput(_PartRevisionInput):
    """Input for retrieving qualified and unqualified alternative facts."""
