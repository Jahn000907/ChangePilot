"""Neo4j repository for the product structure (Part / BOM) graph.

This is the only layer that writes Cypher for the product structure, and it
returns plain frozen dataclasses — never a ``neo4j.Record``, ``neo4j.Node`` or
driver temporal type. Business decisions (quantity accumulation, depth rules,
error mapping, DTO assembly) belong to ``ProductStructureService``.

Traversals follow the BOM chain explicitly:

    PartRevision -[:HAS_BOM]-> BOMVersion -[:HAS_LINE]-> BOMLine
                 -[:COMPONENT]-> PartRevision

for explosion and the same chain in reverse for where-used. Every level is one
explicit branch of the query, so no wildcard ``[*1..N]`` traversal across
arbitrary relationship types is possible.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from neo4j import Driver

from app.core.config import get_settings
from app.db.neo4j.driver import get_driver

#: Default BOM state for production queries (v0.4 section 15, BOM-04).
DEFAULT_BOM_STATUSES: tuple[str, ...] = ("RELEASED",)


@dataclass(frozen=True)
class PartRevisionFact:
    """One part revision plus the identity of its part."""

    part_number: str
    revision_code: str
    part_type: str
    name: str
    category: str
    make_or_buy: str
    base_unit: str
    lifecycle_state: str
    effective_from: date | None
    effective_to: date | None


@dataclass(frozen=True)
class BomVersionFact:
    """One BOM version of a part revision."""

    bom_version_id: str
    bom_code: str
    status: str
    bom_revision_code: str
    effective_from: date | None
    effective_to: date | None


@dataclass(frozen=True)
class BomLineFact:
    """One exploded BOM line (parent revision -> component revision).

    ``ancestor_keys`` / ``ancestor_quantities`` describe the path that reached
    the parent, so the service can compute the cumulative quantity in
    ``Decimal`` without ever doing arithmetic on Cypher floats.
    """

    bom_level: int
    parent_part_number: str
    parent_revision_code: str
    component_part_number: str
    component_revision_code: str
    line_number: int
    quantity_per: Decimal
    unit: str
    bom_version_id: str
    bom_line_id: str
    ancestor_keys: tuple[str, ...]
    ancestor_quantities: tuple[Decimal, ...]


@dataclass(frozen=True)
class WhereUsedFact:
    """One upward usage of a part revision."""

    bom_level: int
    ancestor_part_number: str
    ancestor_revision_code: str
    ancestor_part_type: str
    bom_version_id: str
    bom_code: str
    path: tuple[str, ...]


@dataclass(frozen=True)
class AlternativeFact:
    """One ``ALTERNATIVE_TO`` relationship."""

    alternative_part_number: str
    alternative_revision_code: str
    qualification_status: str
    replacement_type: str
    verified_at: datetime | None
    verified_by: str | None
    alternative_id: str | None


def _as_decimal(value: object) -> Decimal:
    """Convert a Neo4j numeric to ``Decimal`` without binary float drift."""
    return Decimal(str(value))


def _as_date(value: object) -> date | None:
    """Convert a Neo4j temporal value to a native ``date``."""
    if value is None:
        return None
    to_native = getattr(value, "to_native", None)
    converted = to_native() if callable(to_native) else value
    # ``datetime`` is a subclass of ``date``: a timestamp must not be reported
    # as a plain calendar date.
    if isinstance(converted, datetime):
        return converted.date()
    return converted if isinstance(converted, date) else None


def _as_datetime(value: object) -> datetime | None:
    """Convert a Neo4j temporal value to a native ``datetime``."""
    if value is None:
        return None
    to_native = getattr(value, "to_native", None)
    converted = to_native() if callable(to_native) else value
    return converted if isinstance(converted, datetime) else None


def _part_key(alias: str) -> str:
    """Cypher expression building the stable ``PART|REV`` key of a revision."""
    return f"{alias}.part_number + '|' + {alias}.revision_code"


def effective_bom_condition(alias: str) -> str:
    """Build the "BOM version is effective on ``$as_of_date``" predicate.

    Boundaries are inclusive on both ends (``effective_from <= as_of_date`` and
    ``effective_to >= as_of_date``), which is the rule stated by the execution
    task; v0.3 section 11 and v0.4 section 20 define the fields but do not
    disambiguate the boundary themselves.

    Property access goes through the property map on purpose: the golden seed
    omits keys whose value is null, and referring to a non-existent key directly
    makes the server emit a ``property key does not exist`` warning on every
    call. A missing key therefore means "no limit on that side".
    """
    return (
        f"{alias}.status IN $statuses"
        f" AND (properties({alias})['effective_from'] IS NULL"
        f" OR properties({alias})['effective_from'] <= $as_of_date)"
        f" AND (properties({alias})['effective_to'] IS NULL"
        f" OR properties({alias})['effective_to'] >= $as_of_date)"
    )


def _explosion_branch(level: int) -> str:
    """Build one BOM level of the explosion query."""
    chain = [
        (
            "(root:PartRevision {part_number: $part_number, "
            "revision_code: $revision_code})"
        )
    ]
    for index in range(1, level + 1):
        chain.append(
            f"-[:HAS_BOM]->(b{index}:BOMVersion)"
            f"-[:HAS_LINE]->(l{index}:BOMLine)"
            f"-[:COMPONENT]->(r{index}:PartRevision)"
        )
    parent_alias = "root" if level == 1 else f"r{level - 1}"
    # Every level (including nested assemblies) filters on the same
    # ``$as_of_date``, so one explosion never mixes business dates.
    conditions = " AND ".join(
        effective_bom_condition(f"b{index}") for index in range(1, level + 1)
    )
    ancestor_keys = ", ".join(
        [_part_key("root")] + [_part_key(f"r{index}") for index in range(1, level)]
    )
    ancestor_quantities = ", ".join(
        f"l{index}.quantity" for index in range(1, level)
    )
    return (
        "MATCH "
        + "".join(chain)
        + f"\nWHERE {conditions}"
        + f"\nRETURN {level} AS bom_level"
        + f", {parent_alias}.part_number AS parent_part_number"
        + f", {parent_alias}.revision_code AS parent_revision_code"
        + f", r{level}.part_number AS component_part_number"
        + f", r{level}.revision_code AS component_revision_code"
        + f", l{level}.line_number AS line_number"
        + f", l{level}.quantity AS quantity"
        + f", l{level}.unit AS unit"
        + f", b{level}.bom_version_id AS bom_version_id"
        + f", l{level}.bom_line_id AS bom_line_id"
        + f", [{ancestor_keys}] AS ancestor_keys"
        + f", [{ancestor_quantities}] AS ancestor_quantities"
    )


def explosion_query(max_depth: int) -> str:
    """Build the level-by-level BOM explosion query."""
    branches = [_explosion_branch(level) for level in range(1, max_depth + 1)]
    return (
        "\nUNION\n".join(branches)
        + "\nORDER BY bom_level, parent_part_number, line_number"
    )


def _where_used_branch(level: int) -> str:
    """Build one BOM level of the where-used query (walking upwards)."""
    chain = (
        "(root:PartRevision {part_number: $part_number, "
        "revision_code: $revision_code})"
    )
    for index in range(1, level + 1):
        chain += (
            f"<-[:COMPONENT]-(l{index}:BOMLine)"
            f"<-[:HAS_LINE]-(b{index}:BOMVersion)"
            f"<-[:HAS_BOM]-(u{index}:PartRevision)"
        )
    conditions = " AND ".join(
        effective_bom_condition(f"b{index}") for index in range(1, level + 1)
    )
    path = ", ".join(
        ["root.part_number"] + [f"u{index}.part_number" for index in range(1, level + 1)]
    )
    return (
        f"MATCH {chain}"
        f"\nMATCH (u{level})<-[:HAS_REVISION]-(up{level}:Part)"
        f"\nWHERE {conditions}"
        f"\nRETURN {level} AS bom_level"
        f", u{level}.part_number AS ancestor_part_number"
        f", u{level}.revision_code AS ancestor_revision_code"
        f", up{level}.part_type AS ancestor_part_type"
        f", b{level}.bom_version_id AS bom_version_id"
        f", b{level}.bom_code AS bom_code"
        f", [{path}] AS path"
    )


def where_used_query(max_depth: int) -> str:
    """Build the level-by-level where-used query."""
    branches = [_where_used_branch(level) for level in range(1, max_depth + 1)]
    return (
        "\nUNION\n".join(branches)
        + "\nORDER BY bom_level, ancestor_part_number"
    )


class ProductStructureRepository:
    """Read-only access to the Part / BOM graph."""

    def __init__(
        self, driver: Driver | None = None, database: str | None = None
    ) -> None:
        self._driver = driver
        self._database = database

    @property
    def driver(self) -> Driver:
        """Return the injected driver or the process-wide shared driver."""
        return self._driver if self._driver is not None else get_driver()

    @property
    def database(self) -> str:
        """Return the Neo4j database to query."""
        if self._database is not None:
            return self._database
        return get_settings().neo4j.database

    def _run(self, query: str, **parameters: Any) -> list[dict[str, Any]]:
        """Execute one read-only query and return plain dictionaries."""
        with self.driver.session(database=self.database) as session:
            return [dict(record) for record in session.run(query, **parameters)]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_part_revision(
        self, part_number: str, revision_code: str
    ) -> PartRevisionFact | None:
        """Return one part revision, or ``None`` when it does not exist."""
        # Optional temporal properties are read through the property map: the
        # seed omits keys whose value is null, and referencing a non-existent
        # property key directly makes Neo4j warn on every call.
        rows = self._run(
            """
            MATCH (p:Part)-[:HAS_REVISION]->(r:PartRevision {
                part_number: $part_number, revision_code: $revision_code})
            RETURN properties(r)['part_number'] AS part_number,
                   r.revision_code AS revision_code,
                   p.part_type AS part_type,
                   p.name AS name,
                   p.category AS category,
                   p.make_or_buy AS make_or_buy,
                   p.base_unit AS base_unit,
                   r.lifecycle_state AS lifecycle_state,
                   properties(r)['effective_from'] AS effective_from,
                   properties(r)['effective_to'] AS effective_to
            """,
            part_number=part_number,
            revision_code=revision_code,
        )
        if not rows:
            return None
        row = rows[0]
        return PartRevisionFact(
            part_number=str(row["part_number"]),
            revision_code=str(row["revision_code"]),
            part_type=str(row["part_type"]),
            name=str(row["name"]),
            category=str(row["category"]),
            make_or_buy=str(row["make_or_buy"]),
            base_unit=str(row["base_unit"]),
            lifecycle_state=str(row["lifecycle_state"]),
            effective_from=_as_date(row["effective_from"]),
            effective_to=_as_date(row["effective_to"]),
        )

    def list_bom_versions(
        self,
        part_number: str,
        revision_code: str,
        statuses: Sequence[str] | None = None,
        as_of_date: date | None = None,
    ) -> list[BomVersionFact]:
        """Return the BOM versions of one part revision.

        ``statuses`` and ``as_of_date`` are optional filters; without them every
        version of the revision is returned, which is what the service needs to
        tell "no BOM at all" from "no effective BOM".
        """
        query = (
            "MATCH (r:PartRevision {part_number: $part_number,"
            " revision_code: $revision_code})-[:HAS_BOM]->(b:BOMVersion)"
        )
        parameters: dict[str, Any] = {
            "part_number": part_number,
            "revision_code": revision_code,
        }
        conditions = []
        if statuses:
            conditions.append("b.status IN $statuses")
            parameters["statuses"] = list(statuses)
        if as_of_date is not None:
            conditions.append(effective_bom_condition("b"))
            parameters["as_of_date"] = as_of_date
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += (
            " RETURN b.bom_version_id AS bom_version_id, b.bom_code AS bom_code,"
            " b.status AS status, b.bom_revision_code AS bom_revision_code,"
            " properties(b)['effective_from'] AS effective_from,"
            " properties(b)['effective_to'] AS effective_to"
            " ORDER BY b.bom_code"
        )
        return [
            BomVersionFact(
                bom_version_id=str(row["bom_version_id"]),
                bom_code=str(row["bom_code"]),
                status=str(row["status"]),
                bom_revision_code=str(row["bom_revision_code"]),
                effective_from=_as_date(row["effective_from"]),
                effective_to=_as_date(row["effective_to"]),
            )
            for row in self._run(query, **parameters)
        ]

    def find_effective_bom_versions(
        self,
        keys: Sequence[tuple[str, str]],
        as_of_date: date,
        statuses: Sequence[str] | None = DEFAULT_BOM_STATUSES,
    ) -> dict[tuple[str, str], list[BomVersionFact]]:
        """Return the effective BOM versions of several part revisions at once.

        The service uses this to enforce "exactly one effective RELEASED BOM"
        for the exploded revision and every nested parent, in a single query.
        """
        if not keys:
            return {}
        rows = self._run(
            "UNWIND $keys AS key "
            "MATCH (r:PartRevision {part_number: key.part_number,"
            " revision_code: key.revision_code})-[:HAS_BOM]->(b:BOMVersion) "
            f"WHERE {effective_bom_condition('b')} "
            "RETURN key.part_number AS part_number,"
            " key.revision_code AS revision_code,"
            " b.bom_version_id AS bom_version_id, b.bom_code AS bom_code,"
            " b.status AS status, b.bom_revision_code AS bom_revision_code,"
            " properties(b)['effective_from'] AS effective_from,"
            " properties(b)['effective_to'] AS effective_to "
            "ORDER BY part_number, revision_code, bom_code",
            keys=[
                {"part_number": part_number, "revision_code": revision_code}
                for part_number, revision_code in keys
            ],
            statuses=list(statuses) if statuses else [],
            as_of_date=as_of_date,
        )
        result: dict[tuple[str, str], list[BomVersionFact]] = {}
        for row in rows:
            fact = BomVersionFact(
                bom_version_id=str(row["bom_version_id"]),
                bom_code=str(row["bom_code"]),
                status=str(row["status"]),
                bom_revision_code=str(row["bom_revision_code"]),
                effective_from=_as_date(row["effective_from"]),
                effective_to=_as_date(row["effective_to"]),
            )
            key = (str(row["part_number"]), str(row["revision_code"]))
            result.setdefault(key, []).append(fact)
        return result

    def explode_bom(
        self,
        part_number: str,
        revision_code: str,
        max_depth: int,
        as_of_date: date,
        statuses: Sequence[str] | None = DEFAULT_BOM_STATUSES,
    ) -> list[BomLineFact]:
        """Return every effective BOM line of the product, level by level."""
        rows = self._run(
            explosion_query(max_depth),
            part_number=part_number,
            revision_code=revision_code,
            as_of_date=as_of_date,
            statuses=list(statuses) if statuses else [],
        )
        return [
            BomLineFact(
                bom_level=int(row["bom_level"]),
                parent_part_number=str(row["parent_part_number"]),
                parent_revision_code=str(row["parent_revision_code"]),
                component_part_number=str(row["component_part_number"]),
                component_revision_code=str(row["component_revision_code"]),
                line_number=int(row["line_number"]),
                quantity_per=_as_decimal(row["quantity"]),
                unit=str(row["unit"]),
                bom_version_id=str(row["bom_version_id"]),
                bom_line_id=str(row["bom_line_id"]),
                ancestor_keys=tuple(str(key) for key in row["ancestor_keys"]),
                ancestor_quantities=tuple(
                    _as_decimal(value) for value in row["ancestor_quantities"]
                ),
            )
            for row in rows
        ]

    def find_where_used(
        self,
        part_number: str,
        revision_code: str,
        max_depth: int,
        as_of_date: date,
        statuses: Sequence[str] | None = DEFAULT_BOM_STATUSES,
    ) -> list[WhereUsedFact]:
        """Return every ancestor that uses the part through an effective BOM."""
        rows = self._run(
            where_used_query(max_depth),
            part_number=part_number,
            revision_code=revision_code,
            as_of_date=as_of_date,
            statuses=list(statuses) if statuses else [],
        )
        return [
            WhereUsedFact(
                bom_level=int(row["bom_level"]),
                ancestor_part_number=str(row["ancestor_part_number"]),
                ancestor_revision_code=str(row["ancestor_revision_code"]),
                ancestor_part_type=str(row["ancestor_part_type"]),
                bom_version_id=str(row["bom_version_id"]),
                bom_code=str(row["bom_code"]),
                path=tuple(str(item) for item in row["path"]),
            )
            for row in rows
        ]

    def find_alternatives(
        self, part_number: str, revision_code: str
    ) -> list[AlternativeFact]:
        """Return the ``ALTERNATIVE_TO`` targets of one part revision."""
        rows = self._run(
            """
            MATCH (a:PartRevision {part_number: $part_number,
                                   revision_code: $revision_code})
                  -[alt:ALTERNATIVE_TO]->(b:PartRevision)
            RETURN b.part_number AS alternative_part_number,
                   b.revision_code AS alternative_revision_code,
                   alt.qualification_status AS qualification_status,
                   alt.replacement_type AS replacement_type,
                   alt.verified_at AS verified_at,
                   alt.verified_by AS verified_by,
                   alt.alternative_id AS alternative_id
            ORDER BY alternative_part_number
            """,
            part_number=part_number,
            revision_code=revision_code,
        )
        return [
            AlternativeFact(
                alternative_part_number=str(row["alternative_part_number"]),
                alternative_revision_code=str(row["alternative_revision_code"]),
                qualification_status=str(row["qualification_status"]),
                replacement_type=str(row["replacement_type"]),
                verified_at=_as_datetime(row["verified_at"]),
                verified_by=(
                    str(row["verified_by"]) if row["verified_by"] is not None else None
                ),
                alternative_id=(
                    str(row["alternative_id"])
                    if row["alternative_id"] is not None
                    else None
                ),
            )
            for row in rows
        ]
