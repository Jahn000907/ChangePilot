"""In-memory fakes and sample facts for the product structure tests.

The fake implements the repository interface with hand-written facts and can
model BOM effectivity windows, so the service's ``as_of_date`` behaviour
(including nested levels) is testable without touching the real database. It
records the calls it receives, which lets tests verify the depth guard, the
status filter and the business date that was used.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.db.neo4j.repositories.product_structure import (
    AlternativeFact,
    BomLineFact,
    BomVersionFact,
    PartRevisionFact,
    WhereUsedFact,
)


def part_revision_fact(
    part_number: str,
    revision_code: str = "A",
    part_type: str = "ASSEMBLY",
) -> PartRevisionFact:
    """Build one part revision fact."""
    return PartRevisionFact(
        part_number=part_number,
        revision_code=revision_code,
        part_type=part_type,
        name=f"{part_number} name",
        category="test",
        make_or_buy="MAKE",
        base_unit="EA",
        lifecycle_state="RELEASED",
        effective_from=date(2026, 1, 1),
        effective_to=None,
    )


def bom_version_fact(
    bom_version_id: str = "bv-1",
    bom_code: str = "BOM-TEST-01",
    status: str = "RELEASED",
) -> BomVersionFact:
    """Build one BOM version fact."""
    return BomVersionFact(
        bom_version_id=bom_version_id,
        bom_code=bom_code,
        status=status,
        bom_revision_code="01",
        effective_from=date(2026, 1, 1),
        effective_to=None,
    )


@dataclass(frozen=True)
class FakeBomVersion:
    """A BOM version plus the effectivity window the fake applies."""

    version: BomVersionFact
    effective_from: date | None = None
    effective_to: date | None = None

    def effective_on(self, day: date) -> bool:
        """Return whether the version is effective on ``day`` (inclusive)."""
        if self.effective_from is not None and self.effective_from > day:
            return False
        return self.effective_to is None or self.effective_to >= day


def fake_version(
    bom_version_id: str = "bv-1",
    bom_code: str = "BOM-TEST-01",
    effective_from: date | None = None,
    effective_to: date | None = None,
    status: str = "RELEASED",
) -> FakeBomVersion:
    """Build one BOM version with an effectivity window."""
    return FakeBomVersion(
        version=bom_version_fact(bom_version_id, bom_code, status),
        effective_from=effective_from,
        effective_to=effective_to,
    )


def bom_line_fact(
    *,
    level: int,
    parent: str,
    component: str,
    quantity: str,
    ancestor_quantities: tuple[str, ...] = (),
    line_number: int = 1,
) -> BomLineFact:
    """Build one exploded BOM line fact."""
    return BomLineFact(
        bom_level=level,
        parent_part_number=parent,
        parent_revision_code="A",
        component_part_number=component,
        component_revision_code="A",
        line_number=line_number,
        quantity_per=Decimal(quantity),
        unit="EA",
        bom_version_id=f"bv-{level}",
        bom_line_id=f"bl-{level}-{line_number}",
        ancestor_keys=(f"{parent}|A",),
        ancestor_quantities=tuple(Decimal(value) for value in ancestor_quantities),
    )


def where_used_fact(
    level: int,
    ancestor: str,
    part_type: str = "ASSEMBLY",
    path: tuple[str, ...] = (),
    bom_code: str = "BOM-TEST-01",
) -> WhereUsedFact:
    """Build one where-used fact."""
    return WhereUsedFact(
        bom_level=level,
        ancestor_part_number=ancestor,
        ancestor_revision_code="A",
        ancestor_part_type=part_type,
        bom_version_id=f"bv-{level}",
        bom_code=bom_code,
        path=path or ("PART-TEST", ancestor),
    )


def _selected(
    item: FakeBomVersion, statuses: Sequence[str] | None, as_of_date: date | None
) -> bool:
    """Return whether one version passes the status and effectivity filters."""
    if statuses and item.version.status not in statuses:
        return False
    return as_of_date is None or item.effective_on(as_of_date)


@dataclass
class FakeProductStructureRepository:
    """Repository stand-in returning prepared facts."""

    revisions: dict[tuple[str, str], PartRevisionFact] = field(default_factory=dict)
    versions: dict[tuple[str, str], list[FakeBomVersion]] = field(default_factory=dict)
    explosion: list[BomLineFact] = field(default_factory=list)
    upstream: list[WhereUsedFact] = field(default_factory=list)
    alternatives: list[AlternativeFact] = field(default_factory=list)
    explosion_calls: list[tuple] = field(default_factory=list)
    where_used_calls: list[tuple] = field(default_factory=list)
    effective_bom_calls: list[tuple[tuple[str, str], ...]] = field(
        default_factory=list
    )

    def get_part_revision(
        self, part_number: str, revision_code: str
    ) -> PartRevisionFact | None:
        return self.revisions.get((part_number, revision_code))

    def list_bom_versions(
        self,
        part_number: str,
        revision_code: str,
        statuses: Sequence[str] | None = None,
        as_of_date: date | None = None,
    ) -> list[BomVersionFact]:
        return [
            item.version
            for item in self.versions.get((part_number, revision_code), [])
            if _selected(item, statuses, as_of_date)
        ]

    def find_effective_bom_versions(
        self,
        keys: Sequence[tuple[str, str]],
        as_of_date: date,
        statuses: Sequence[str] | None = None,
    ) -> dict[tuple[str, str], list[BomVersionFact]]:
        key_tuple = tuple(keys)
        self.effective_bom_calls.append(key_tuple)
        found: dict[tuple[str, str], list[BomVersionFact]] = {}
        for key in key_tuple:
            versions = [
                item.version
                for item in self.versions.get(key, [])
                if _selected(item, statuses, as_of_date)
            ]
            if versions:
                found[key] = versions
        return found

    def explode_bom(
        self,
        part_number: str,
        revision_code: str,
        max_depth: int,
        as_of_date: date,
        statuses: Sequence[str] | None = None,
    ) -> list[BomLineFact]:
        self.explosion_calls.append(
            (
                part_number,
                revision_code,
                max_depth,
                as_of_date,
                tuple(statuses) if statuses else None,
            )
        )
        return [
            fact
            for fact in self.explosion
            if fact.bom_level <= max_depth
            and self._parent_has_effective_bom(fact, as_of_date, statuses)
        ]

    def find_where_used(
        self,
        part_number: str,
        revision_code: str,
        max_depth: int,
        as_of_date: date,
        statuses: Sequence[str] | None = None,
    ) -> list[WhereUsedFact]:
        self.where_used_calls.append(
            (
                part_number,
                revision_code,
                max_depth,
                as_of_date,
                tuple(statuses) if statuses else None,
            )
        )
        return [
            fact
            for fact in self.upstream
            if fact.bom_level <= max_depth
            and self._parent_has_effective_bom(fact, as_of_date, statuses)
        ]

    def find_alternatives(
        self, part_number: str, revision_code: str
    ) -> list[AlternativeFact]:
        return list(self.alternatives)

    def _parent_has_effective_bom(
        self,
        fact: BomLineFact | WhereUsedFact,
        as_of_date: date,
        statuses: Sequence[str] | None,
    ) -> bool:
        """Mimic the per-level effectivity filter of the real Cypher query."""
        if isinstance(fact, BomLineFact):
            key = (fact.parent_part_number, fact.parent_revision_code)
        else:
            key = (fact.ancestor_part_number, fact.ancestor_revision_code)
        return any(
            _selected(item, statuses, as_of_date)
            for item in self.versions.get(key, [])
        )
