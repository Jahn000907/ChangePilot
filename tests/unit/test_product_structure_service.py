"""Unit tests for :class:`ProductStructureService` (no database involved)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.db.neo4j.repositories.product_structure import AlternativeFact
from app.domain.errors import (
    AmbiguousEffectiveBOMError,
    BomNotFoundError,
    DepthLimitExceededError,
    DomainValidationError,
    NoEffectiveBOMError,
    PartRevisionNotFoundError,
)
from app.services.product_structure import MAX_ALLOWED_DEPTH, ProductStructureService
from tests.fixtures.product_structure_fakes import (
    FakeProductStructureRepository,
    bom_line_fact,
    fake_version,
    part_revision_fact,
    where_used_fact,
)

AS_OF = date(2026, 6, 1)


def build_service(repository: FakeProductStructureRepository) -> ProductStructureService:
    """Return a service whose default business date is fixed."""
    return ProductStructureService(repository, today=lambda: AS_OF)


def test_explosion_supports_multiple_levels_with_decimal_quantities():
    """A two-level explosion multiplies cumulative quantities exactly."""
    repository = FakeProductStructureRepository(
        revisions={("ROB-TEST", "A"): part_revision_fact("ROB-TEST")},
        versions={("ROB-TEST", "A"): [fake_version()]},
        explosion=[
            bom_line_fact(level=1, parent="ROB-TEST", component="ASM-TEST", quantity="2"),
            bom_line_fact(
                level=2,
                parent="ASM-TEST",
                component="PART-TEST",
                quantity="3",
                ancestor_quantities=("2",),
            ),
        ],
    )
    repository.versions[("ASM-TEST", "A")] = [fake_version("bv-asm")]

    result = build_service(repository).explode_bom("ROB-TEST", "A")

    assert [row.bom_level for row in result.rows] == [1, 2]
    assert result.quantity_of("ASM-TEST") == Decimal(2)
    assert result.quantity_of("PART-TEST") == Decimal(6)  # 2 x 3
    assert isinstance(result.quantity_of("PART-TEST"), Decimal)
    assert all(isinstance(row.quantity_per, Decimal) for row in result.rows)
    assert all(isinstance(row.cumulative_quantity, Decimal) for row in result.rows)
    assert result.as_of_date == AS_OF
    assert result.bom_code == "BOM-TEST-01"


def test_explosion_totals_sum_all_paths():
    """The same component reached through two parents is summed per product unit."""
    repository = FakeProductStructureRepository(
        revisions={("ROB-TEST", "A"): part_revision_fact("ROB-TEST")},
        versions={
            ("ROB-TEST", "A"): [fake_version()],
            ("ASM-A", "A"): [fake_version("bv-a")],
            ("ASM-B", "A"): [fake_version("bv-b")],
        },
        explosion=[
            bom_line_fact(level=1, parent="ROB-TEST", component="ASM-A", quantity="1"),
            bom_line_fact(level=1, parent="ROB-TEST", component="ASM-B", quantity="2"),
            bom_line_fact(
                level=2,
                parent="ASM-A",
                component="PART-TEST",
                quantity="4",
                ancestor_quantities=("1",),
            ),
            bom_line_fact(
                level=2,
                parent="ASM-B",
                component="PART-TEST",
                quantity="4",
                ancestor_quantities=("2",),
            ),
        ],
    )

    result = build_service(repository).explode_bom("ROB-TEST", "A")

    assert result.quantity_of("PART-TEST") == Decimal(12)  # 4 + 8


def test_explosion_asks_one_level_deeper_for_depth_guard():
    """The service probes ``max_depth + 1`` so a truncated BOM is detected."""
    repository = FakeProductStructureRepository(
        revisions={("ROB-TEST", "A"): part_revision_fact("ROB-TEST")},
        versions={("ROB-TEST", "A"): [fake_version()]},
        explosion=[
            bom_line_fact(level=1, parent="ROB-TEST", component="ASM-TEST", quantity="1")
        ],
    )

    build_service(repository).explode_bom("ROB-TEST", "A", max_depth=3)

    assert repository.explosion_calls[0][2] == 4
    assert repository.explosion_calls[0][3] == AS_OF
    assert repository.explosion_calls[0][4] == ("RELEASED",)


def test_explosion_raises_when_depth_limit_is_exceeded():
    """A BOM deeper than ``max_depth`` is reported, not silently truncated."""
    repository = FakeProductStructureRepository(
        revisions={("ROB-TEST", "A"): part_revision_fact("ROB-TEST")},
        versions={
            ("ROB-TEST", "A"): [fake_version()],
            ("ASM-TEST", "A"): [fake_version("bv-asm")],
        },
        explosion=[
            bom_line_fact(level=1, parent="ROB-TEST", component="ASM-TEST", quantity="1"),
            bom_line_fact(
                level=2,
                parent="ASM-TEST",
                component="PART-TEST",
                quantity="1",
                ancestor_quantities=("1",),
            ),
        ],
    )

    with pytest.raises(DepthLimitExceededError):
        build_service(repository).explode_bom("ROB-TEST", "A", max_depth=1)


@pytest.mark.parametrize("max_depth", [0, -1, MAX_ALLOWED_DEPTH + 1])
def test_invalid_max_depth_is_rejected(max_depth):
    """``max_depth`` must be positive and within the allowed ceiling."""
    service = build_service(FakeProductStructureRepository())

    with pytest.raises(DomainValidationError):
        service.explode_bom("ROB-TEST", "A", max_depth=max_depth)


def test_missing_part_revision_raises_domain_error():
    """An unknown part revision is a domain error, not an empty result."""
    service = build_service(FakeProductStructureRepository())

    with pytest.raises(PartRevisionNotFoundError):
        service.explode_bom("UNKNOWN", "A")


def test_revision_without_any_bom_raises_bom_not_found():
    """A known revision that owns no BOM version cannot be exploded."""
    repository = FakeProductStructureRepository(
        revisions={
            ("PART-TEST", "A"): part_revision_fact("PART-TEST", "A", "PURCHASED_PART")
        }
    )

    with pytest.raises(BomNotFoundError):
        build_service(repository).explode_bom("PART-TEST", "A")


def test_blank_identifier_is_rejected():
    """Blank identifiers fail validation before touching the repository."""
    service = build_service(FakeProductStructureRepository())

    with pytest.raises(DomainValidationError):
        service.where_used("   ", "A")


def test_where_used_levels_and_products():
    """Where-used reports levels, ancestors and finished products."""
    repository = FakeProductStructureRepository(
        revisions={("BRG-TEST", "A"): part_revision_fact("BRG-TEST")},
        versions={
            ("ASM-TEST", "A"): [fake_version("bv-1")],
            ("ASM-ARM", "A"): [fake_version("bv-2")],
            ("ROB-TEST", "A"): [fake_version("bv-3")],
        },
        upstream=[
            where_used_fact(1, "ASM-TEST", "ASSEMBLY"),
            where_used_fact(2, "ASM-ARM", "ASSEMBLY", ("BRG-TEST", "ASM-TEST", "ASM-ARM")),
            where_used_fact(
                3,
                "ROB-TEST",
                "FINISHED_PRODUCT",
                ("BRG-TEST", "ASM-TEST", "ASM-ARM", "ROB-TEST"),
            ),
        ],
    )

    result = build_service(repository).where_used("BRG-TEST", "A")

    assert [row.bom_level for row in result.rows] == [1, 2, 3]
    assert result.ancestors == ["ASM-ARM", "ASM-TEST", "ROB-TEST"]
    assert result.products == ["ROB-TEST"]
    assert result.rows[-1].path[-1] == "ROB-TEST"
    assert result.as_of_date == AS_OF
    assert result.rows[0].bom_code == "BOM-TEST-01"


def test_where_used_raises_on_depth_limit():
    """Where-used obeys the same depth protection as the explosion."""
    repository = FakeProductStructureRepository(
        revisions={("BRG-TEST", "A"): part_revision_fact("BRG-TEST")},
        versions={("ASM-ARM", "A"): [fake_version()]},
        upstream=[where_used_fact(2, "ASM-ARM", "ASSEMBLY")],
    )

    with pytest.raises(DepthLimitExceededError):
        build_service(repository).where_used("BRG-TEST", "A", max_depth=1)


def test_alternatives_are_returned_without_selection():
    """Alternatives are plain facts; the service never picks one."""
    repository = FakeProductStructureRepository(
        revisions={("BRG-TEST", "A"): part_revision_fact("BRG-TEST")},
        alternatives=[
            AlternativeFact(
                alternative_part_number="BRG-B",
                alternative_revision_code="A",
                qualification_status="QUALIFIED",
                replacement_type="DIRECT",
                verified_at=None,
                verified_by="quality",
                alternative_id="alt-1",
            ),
            AlternativeFact(
                alternative_part_number="BRG-C",
                alternative_revision_code="A",
                qualification_status="UNQUALIFIED",
                replacement_type="CONDITIONAL",
                verified_at=None,
                verified_by="quality",
                alternative_id="alt-2",
            ),
        ],
    )

    result = build_service(repository).find_alternatives("BRG-TEST", "A")

    assert [row.qualification_status for row in result.rows] == [
        "QUALIFIED",
        "UNQUALIFIED",
    ]
    assert not hasattr(result, "selected")


def test_unsupported_qualification_becomes_domain_error():
    """An unknown qualification value is reported as a domain error."""
    repository = FakeProductStructureRepository(
        revisions={("BRG-TEST", "A"): part_revision_fact("BRG-TEST")},
        alternatives=[
            AlternativeFact(
                alternative_part_number="BRG-X",
                alternative_revision_code="A",
                qualification_status="MAYBE",
                replacement_type="DIRECT",
                verified_at=None,
                verified_by=None,
                alternative_id=None,
            )
        ],
    )

    with pytest.raises(DomainValidationError):
        build_service(repository).find_alternatives("BRG-TEST", "A")


def test_dto_boundary_has_no_driver_types():
    """Facts are plain dataclasses and DTOs only carry python types."""
    repository = FakeProductStructureRepository(
        revisions={("ROB-TEST", "A"): part_revision_fact("ROB-TEST")},
        versions={("ROB-TEST", "A"): [fake_version()]},
        explosion=[
            bom_line_fact(level=1, parent="ROB-TEST", component="ASM-TEST", quantity="1")
        ],
    )
    service = build_service(repository)

    revision = service.get_part_revision("ROB-TEST", "A")
    result = service.explode_bom("ROB-TEST", "A")

    assert isinstance(result.model_dump(), dict)
    assert type(revision).__module__.startswith("app.")
    assert type(result.rows[0]).__module__.startswith("app.")
    assert "neo4j" not in repr(result.model_dump())


# ---------------------------------------------------------------------------
# Effectivity (as_of_date)
# ---------------------------------------------------------------------------
def test_default_as_of_date_comes_from_the_injected_today():
    """The default business date is resolved at the service boundary."""
    repository = FakeProductStructureRepository(
        revisions={("ROB-TEST", "A"): part_revision_fact("ROB-TEST")},
        versions={("ROB-TEST", "A"): [fake_version()]},
        explosion=[
            bom_line_fact(level=1, parent="ROB-TEST", component="ASM-TEST", quantity="1")
        ],
    )

    result = ProductStructureService(
        repository, today=lambda: date(2026, 7, 15)
    ).explode_bom("ROB-TEST", "A")

    assert result.as_of_date == date(2026, 7, 15)


def test_datetime_as_of_date_is_rejected():
    """A timestamp is not a business date."""
    service = build_service(FakeProductStructureRepository())

    with pytest.raises(DomainValidationError):
        service.explode_bom(
            "ROB-TEST", "A", as_of_date=datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        )


def test_bom_not_yet_effective_on_the_requested_date():
    """A version whose window starts later is not effective yet."""
    repository = FakeProductStructureRepository(
        revisions={("ROB-TEST", "A"): part_revision_fact("ROB-TEST")},
        versions={
            ("ROB-TEST", "A"): [fake_version(effective_from=date(2026, 9, 1))]
        },
    )

    with pytest.raises(NoEffectiveBOMError) as excinfo:
        build_service(repository).explode_bom("ROB-TEST", "A", as_of_date=AS_OF)

    message = str(excinfo.value)
    assert "ROB-TEST" in message
    assert "2026-06-01" in message


def test_bom_expired_before_the_requested_date():
    """A version whose window ended earlier is no longer effective."""
    repository = FakeProductStructureRepository(
        revisions={("ROB-TEST", "A"): part_revision_fact("ROB-TEST")},
        versions={
            ("ROB-TEST", "A"): [
                fake_version(effective_from=date(2025, 1, 1), effective_to=date(2026, 5, 31))
            ]
        },
    )

    with pytest.raises(NoEffectiveBOMError):
        build_service(repository).explode_bom("ROB-TEST", "A", as_of_date=AS_OF)


def test_open_ended_window_includes_later_dates():
    """A missing ``effective_to`` means "valid until further notice"."""
    repository = FakeProductStructureRepository(
        revisions={("ROB-TEST", "A"): part_revision_fact("ROB-TEST")},
        versions={
            ("ROB-TEST", "A"): [fake_version(effective_from=date(2026, 1, 1))]
        },
        explosion=[
            bom_line_fact(level=1, parent="ROB-TEST", component="ASM-TEST", quantity="1")
        ],
    )

    result = build_service(repository).explode_bom(
        "ROB-TEST", "A", as_of_date=date(2030, 1, 1)
    )

    assert len(result.rows) == 1


def test_two_effective_boms_are_reported_not_silently_selected():
    """Overlapping RELEASED windows are a data conflict (v0.4 BOM-03)."""
    repository = FakeProductStructureRepository(
        revisions={("ROB-TEST", "A"): part_revision_fact("ROB-TEST")},
        versions={
            ("ROB-TEST", "A"): [
                fake_version("bv-1", "BOM-TEST-01", effective_from=date(2026, 1, 1)),
                fake_version("bv-2", "BOM-TEST-02", effective_from=date(2026, 5, 1)),
            ]
        },
    )

    with pytest.raises(AmbiguousEffectiveBOMError) as excinfo:
        build_service(repository).explode_bom("ROB-TEST", "A", as_of_date=AS_OF)

    assert "BOM-TEST-01" in str(excinfo.value)
    assert "BOM-TEST-02" in str(excinfo.value)


def test_nested_level_uses_the_same_as_of_date():
    """A nested assembly that is not effective on the date is not expanded."""
    repository = FakeProductStructureRepository(
        revisions={("ROB-TEST", "A"): part_revision_fact("ROB-TEST")},
        versions={
            ("ROB-TEST", "A"): [fake_version(effective_from=date(2026, 1, 1))],
            ("ASM-TEST", "A"): [fake_version("bv-asm", effective_from=date(2026, 9, 1))],
        },
        explosion=[
            bom_line_fact(level=1, parent="ROB-TEST", component="ASM-TEST", quantity="1"),
            bom_line_fact(
                level=2,
                parent="ASM-TEST",
                component="PART-TEST",
                quantity="2",
                ancestor_quantities=("1",),
            ),
        ],
    )
    service = build_service(repository)

    before = service.explode_bom("ROB-TEST", "A", as_of_date=AS_OF)
    after = service.explode_bom("ROB-TEST", "A", as_of_date=date(2026, 9, 15))

    assert [row.component_part_number for row in before.rows] == ["ASM-TEST"]
    assert [row.component_part_number for row in after.rows] == [
        "ASM-TEST",
        "PART-TEST",
    ]


def test_where_used_excludes_expired_bom():
    """Usage through an expired BOM is not reported for the requested date."""
    repository = FakeProductStructureRepository(
        revisions={("BRG-TEST", "A"): part_revision_fact("BRG-TEST")},
        versions={
            ("ASM-OLD", "A"): [
                fake_version("bv-old", "BOM-OLD-01", effective_to=date(2026, 5, 31))
            ],
            ("ASM-NEW", "A"): [fake_version("bv-new", "BOM-NEW-01")],
        },
        upstream=[
            where_used_fact(1, "ASM-OLD", "ASSEMBLY", bom_code="BOM-OLD-01"),
            where_used_fact(1, "ASM-NEW", "ASSEMBLY", bom_code="BOM-NEW-01"),
        ],
    )

    result = build_service(repository).where_used("BRG-TEST", "A", as_of_date=AS_OF)

    assert result.ancestors == ["ASM-NEW"]
    assert result.rows[0].bom_code == "BOM-NEW-01"
