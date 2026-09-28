"""Product structure service: BOM explosion, where-used and alternatives.

The service owns everything the repository must not do:

- input validation (identifier and ``max_depth`` rules);
- ``Decimal`` quantity accumulation;
- depth-limit protection;
- translation of "not found" conditions into domain errors;
- assembly of the DTOs the upper layers consume.

It never writes Cypher. Infrastructure failures (for example an unreachable
Neo4j) are *not* disguised as domain errors: they propagate unchanged so the
caller can tell "the part does not exist" from "the database is down".
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from math import prod

from pydantic import ValidationError

from app.core.business_time import current_business_date
from app.db.neo4j.repositories.product_structure import (
    DEFAULT_BOM_STATUSES,
    AlternativeFact,
    BomLineFact,
    ProductStructureRepository,
    WhereUsedFact,
)
from app.domain.dto.product_structure import (
    AlternativeResult,
    AlternativeRow,
    BomExplosionResult,
    BomExplosionRow,
    PartRevisionDTO,
    WhereUsedResult,
    WhereUsedRow,
)
from app.domain.errors import (
    AmbiguousEffectiveBOMError,
    BomNotFoundError,
    DepthLimitExceededError,
    DomainValidationError,
    NoEffectiveBOMError,
    PartRevisionNotFoundError,
)

#: Default traversal depth. The golden seed BOM is four levels deep, so five
#: levels expand it completely while still bounding the traversal.
DEFAULT_MAX_DEPTH = 5

#: Hard ceiling for ``max_depth``; anything larger is a caller mistake.
MAX_ALLOWED_DEPTH = 10


def default_business_date() -> date:
    """Return the local calendar date used when the caller passes no date.

    A BOM business date is a calendar day in the plant's local time zone, so the
    local date is the correct default; callers that need a reproducible result
    pass ``as_of_date`` explicitly (and tests inject their own provider).
    """
    return current_business_date()


class ProductStructureService:
    """Answer "what is inside a product" and "where is a part used"."""

    def __init__(
        self,
        repository: ProductStructureRepository | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._repository = (
            repository if repository is not None else ProductStructureRepository()
        )
        # The default business date is resolved here, at the service boundary,
        # and can be injected so tests never depend on the wall clock. The
        # repository never calls the system clock itself.
        self._today = today if today is not None else default_business_date

    @property
    def repository(self) -> ProductStructureRepository:
        """Return the repository used by this service."""
        return self._repository

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------
    def list_revision_codes(self, part_number: str) -> list[str]:
        """Look up available revisions without guessing one in the assistant."""
        return self._repository.list_revision_codes(_validate_identifier(part_number, "part_number"))

    def effective_revision_codes(
        self, part_number: str, as_of_date: date | None = None
    ) -> list[str]:
        """Resolve released revisions effective on the same business date as BOM queries."""
        business_date = self._resolve_as_of_date(as_of_date)
        return [
            code for code in self.list_revision_codes(part_number)
            if (revision := self.get_part_revision(part_number, code)).lifecycle_state == "RELEASED"
            and (revision.effective_from is None or revision.effective_from <= business_date)
            and (revision.effective_to is None or business_date <= revision.effective_to)
        ]

    def current_business_date(self) -> date:
        """Expose the configured business-date provider for read Tool defaults."""
        return self._resolve_as_of_date(None)

    def get_part_revision(
        self, part_number: str, revision_code: str
    ) -> PartRevisionDTO:
        """Return one part revision or raise :class:`PartRevisionNotFoundError`."""
        part_number = _validate_identifier(part_number, "part_number")
        revision_code = _validate_identifier(revision_code, "revision_code")
        fact = self._repository.get_part_revision(part_number, revision_code)
        if fact is None:
            raise PartRevisionNotFoundError(
                f"part revision not found: ({part_number}, {revision_code})"
            )
        return PartRevisionDTO(
            part_number=fact.part_number,
            revision_code=fact.revision_code,
            part_type=fact.part_type,
            name=fact.name,
            category=fact.category,
            make_or_buy=fact.make_or_buy,
            base_unit=fact.base_unit,
            lifecycle_state=fact.lifecycle_state,
            effective_from=fact.effective_from,
            effective_to=fact.effective_to,
        )

    def explode_bom(
        self,
        part_number: str,
        revision_code: str,
        max_depth: int = DEFAULT_MAX_DEPTH,
        as_of_date: date | None = None,
        statuses: Sequence[str] | None = DEFAULT_BOM_STATUSES,
    ) -> BomExplosionResult:
        """Explode a released BOM into every component, level by level.

        The input product is level 0 and its direct components are level 1.
        ``cumulative_quantity`` is the quantity of the component needed for one
        unit of the product, accumulated with ``Decimal`` multiplication.

        ``as_of_date`` selects the BOM version that is effective on that business
        date; it defaults to the current date. Every level of the explosion uses
        the same date.
        """
        part_number = _validate_identifier(part_number, "part_number")
        revision_code = _validate_identifier(revision_code, "revision_code")
        max_depth = _validate_max_depth(max_depth)
        effective_date = self._resolve_as_of_date(as_of_date)
        statuses = _normalise_statuses(statuses)

        self._require_part_revision(part_number, revision_code)
        if not self._repository.list_bom_versions(part_number, revision_code):
            raise BomNotFoundError(
                f"part revision ({part_number}, {revision_code}) has no BOM version"
            )
        root_bom = self._require_unique_effective_bom(
            (part_number, revision_code), effective_date, statuses
        )

        facts = self._repository.explode_bom(
            part_number, revision_code, max_depth + 1, effective_date, statuses
        )
        _guard_depth(facts, max_depth, part_number, revision_code)
        facts = [fact for fact in facts if fact.bom_level <= max_depth]
        self._guard_unique_effective_boms(
            [
                (fact.parent_part_number, fact.parent_revision_code)
                for fact in facts
            ],
            effective_date,
            statuses,
        )

        rows: list[BomExplosionRow] = []
        totals: dict[str, Decimal] = {}
        for fact in facts:
            cumulative = _cumulative_quantity(fact)
            rows.append(
                BomExplosionRow(
                    bom_level=fact.bom_level,
                    parent_part_number=fact.parent_part_number,
                    parent_revision_code=fact.parent_revision_code,
                    component_part_number=fact.component_part_number,
                    component_revision_code=fact.component_revision_code,
                    line_number=fact.line_number,
                    quantity_per=fact.quantity_per,
                    cumulative_quantity=cumulative,
                    unit=fact.unit,
                    bom_version_id=fact.bom_version_id,
                    bom_line_id=fact.bom_line_id,
                )
            )
            key = f"{fact.component_part_number}|{fact.component_revision_code}"
            totals[key] = totals.get(key, Decimal(0)) + cumulative

        rows.sort(
            key=lambda row: (
                row.bom_level,
                row.parent_part_number,
                row.line_number,
            )
        )
        return BomExplosionResult(
            part_number=part_number,
            revision_code=revision_code,
            as_of_date=effective_date,
            bom_version_id=root_bom.bom_version_id,
            bom_code=root_bom.bom_code,
            bom_statuses=statuses,
            max_depth=max_depth,
            rows=rows,
            totals=totals,
        )

    def where_used(
        self,
        part_number: str,
        revision_code: str,
        max_depth: int = DEFAULT_MAX_DEPTH,
        as_of_date: date | None = None,
        statuses: Sequence[str] | None = DEFAULT_BOM_STATUSES,
    ) -> WhereUsedResult:
        """Return every ancestor revision that uses the part.

        The searched part is level 0 and its direct parent assembly is level 1.
        Only BOM versions that are effective on ``as_of_date`` are traversed, so
        a BOM that has expired never counts as current usage.
        """
        part_number = _validate_identifier(part_number, "part_number")
        revision_code = _validate_identifier(revision_code, "revision_code")
        max_depth = _validate_max_depth(max_depth)
        effective_date = self._resolve_as_of_date(as_of_date)
        statuses = _normalise_statuses(statuses)

        self._require_part_revision(part_number, revision_code)
        facts = self._repository.find_where_used(
            part_number, revision_code, max_depth + 1, effective_date, statuses
        )
        _guard_depth(facts, max_depth, part_number, revision_code)
        facts = [fact for fact in facts if fact.bom_level <= max_depth]
        self._guard_unique_effective_boms(
            [
                (fact.ancestor_part_number, fact.ancestor_revision_code)
                for fact in facts
            ],
            effective_date,
            statuses,
        )

        rows = [
            WhereUsedRow(
                bom_level=fact.bom_level,
                ancestor_part_number=fact.ancestor_part_number,
                ancestor_revision_code=fact.ancestor_revision_code,
                ancestor_part_type=fact.ancestor_part_type,
                bom_version_id=fact.bom_version_id,
                bom_code=fact.bom_code,
                path=list(fact.path),
            )
            for fact in facts
        ]
        rows.sort(key=lambda row: (row.bom_level, row.ancestor_part_number))
        return WhereUsedResult(
            part_number=part_number,
            revision_code=revision_code,
            as_of_date=effective_date,
            bom_statuses=statuses,
            max_depth=max_depth,
            rows=rows,
            ancestors=sorted({row.ancestor_part_number for row in rows}),
            products=sorted(
                {
                    row.ancestor_part_number
                    for row in rows
                    if row.ancestor_part_type == "FINISHED_PRODUCT"
                }
            ),
        )

    def find_alternatives(
        self, part_number: str, revision_code: str
    ) -> AlternativeResult:
        """Return the alternatives of a part revision as plain facts.

        No alternative is selected here: qualification decides later, in the
        planner, not in a lookup.
        """
        part_number = _validate_identifier(part_number, "part_number")
        revision_code = _validate_identifier(revision_code, "revision_code")
        self._require_part_revision(part_number, revision_code)
        facts = self._repository.find_alternatives(part_number, revision_code)
        return AlternativeResult(
            part_number=part_number,
            revision_code=revision_code,
            rows=[_alternative_row(fact) for fact in facts],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _require_part_revision(self, part_number: str, revision_code: str) -> None:
        """Raise when the part revision does not exist."""
        if self._repository.get_part_revision(part_number, revision_code) is None:
            raise PartRevisionNotFoundError(
                f"part revision not found: ({part_number}, {revision_code})"
            )

    def _resolve_as_of_date(self, as_of_date: date | None) -> date:
        """Return the business date to evaluate effectivity against."""
        if as_of_date is None:
            return self._today()
        if isinstance(as_of_date, datetime):
            raise DomainValidationError(
                "as_of_date must be a date, not a datetime: "
                f"{as_of_date.isoformat()}"
            )
        if not isinstance(as_of_date, date):
            raise DomainValidationError(
                f"as_of_date must be a date, got {type(as_of_date).__name__}"
            )
        return as_of_date

    def _require_unique_effective_bom(
        self,
        key: tuple[str, str],
        as_of_date: date,
        statuses: tuple[str, ...],
    ):
        """Return the single effective BOM version of one part revision."""
        part_number, revision_code = key
        versions = self._repository.find_effective_bom_versions(
            [key], as_of_date, statuses
        ).get(key, [])
        if not versions:
            raise NoEffectiveBOMError(
                f"no effective BOM for ({part_number}, {revision_code}) "
                f"on {as_of_date.isoformat()} in states {list(statuses)}"
            )
        if len(versions) > 1:
            raise AmbiguousEffectiveBOMError(
                f"{len(versions)} effective BOM versions for "
                f"({part_number}, {revision_code}) on {as_of_date.isoformat()}: "
                f"{sorted(version.bom_code for version in versions)}"
            )
        return versions[0]

    def _guard_unique_effective_boms(
        self,
        keys: Sequence[tuple[str, str]],
        as_of_date: date,
        statuses: tuple[str, ...],
    ) -> None:
        """Apply the "exactly one effective BOM" rule to every revision used.

        Nested assemblies are checked as well, so a duplicated effective BOM deep
        in the structure is reported instead of silently fanning out.
        """
        checked = sorted(set(keys))
        if not checked:
            return
        found = self._repository.find_effective_bom_versions(
            checked, as_of_date, statuses
        )
        for key in checked:
            versions = found.get(key, [])
            if len(versions) > 1:
                raise AmbiguousEffectiveBOMError(
                    f"{len(versions)} effective BOM versions for "
                    f"({key[0]}, {key[1]}) on {as_of_date.isoformat()}: "
                    f"{sorted(version.bom_code for version in versions)}"
                )
            if not versions:
                raise NoEffectiveBOMError(
                    f"no effective BOM for ({key[0]}, {key[1]}) "
                    f"on {as_of_date.isoformat()} in states {list(statuses)}"
                )


def _validate_identifier(value: str, field: str) -> str:
    """Return a trimmed identifier or raise a domain validation error."""
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _validate_max_depth(max_depth: int) -> int:
    """Return a valid ``max_depth`` or raise a domain validation error."""
    if isinstance(max_depth, bool) or not isinstance(max_depth, int):
        raise DomainValidationError(
            f"max_depth must be an integer, got {type(max_depth).__name__}"
        )
    if max_depth <= 0:
        raise DomainValidationError(
            f"max_depth must be greater than 0, got {max_depth}"
        )
    if max_depth > MAX_ALLOWED_DEPTH:
        raise DomainValidationError(
            f"max_depth {max_depth} exceeds the allowed limit {MAX_ALLOWED_DEPTH}"
        )
    return max_depth


def _normalise_statuses(statuses: Sequence[str] | None) -> tuple[str, ...]:
    """Return the BOM states to traverse as a tuple."""
    if statuses is None:
        return DEFAULT_BOM_STATUSES
    return tuple(statuses)


def _cumulative_quantity(fact: BomLineFact) -> Decimal:
    """Multiply the path quantities with ``Decimal``, never with ``float``."""
    return prod(fact.ancestor_quantities, start=Decimal(1)) * fact.quantity_per


def _guard_depth(
    facts: Sequence[BomLineFact] | Sequence[WhereUsedFact],
    max_depth: int,
    part_number: str,
    revision_code: str,
) -> None:
    """Raise when the graph is deeper than the requested ``max_depth``."""
    if any(fact.bom_level > max_depth for fact in facts):
        raise DepthLimitExceededError(
            f"BOM traversal for ({part_number}, {revision_code}) exceeded "
            f"max_depth={max_depth}"
        )


def _alternative_row(fact: AlternativeFact) -> AlternativeRow:
    """Convert one alternative fact into its DTO, mapping data errors."""
    try:
        return AlternativeRow(
            alternative_part_number=fact.alternative_part_number,
            alternative_revision_code=fact.alternative_revision_code,
            qualification_status=fact.qualification_status,  # type: ignore[arg-type]
            replacement_type=fact.replacement_type,  # type: ignore[arg-type]
            verified_at=fact.verified_at,
            verified_by=fact.verified_by,
            alternative_id=fact.alternative_id,
        )
    except ValidationError as exc:
        raise DomainValidationError(
            "alternative relationship has an unsupported qualification or "
            f"replacement type: {fact.qualification_status}/"
            f"{fact.replacement_type}"
        ) from exc
