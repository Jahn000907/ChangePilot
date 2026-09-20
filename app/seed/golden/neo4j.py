"""Load the Golden Seed product / BOM graph into Neo4j.

Every write is a ``MERGE`` keyed on the stable business identifiers that the
schema constraints already protect, so running the loader twice refreshes
properties instead of duplicating nodes, relationships or alternative links.

The graph written here is exactly the model of design doc v0.4 sections 10-21:
``Part`` / ``PartRevision`` / ``BOMVersion`` / ``BOMLine`` plus the
``HAS_REVISION``, ``HAS_BOM``, ``HAS_LINE``, ``COMPONENT`` and
``ALTERNATIVE_TO`` relationships.
"""

from __future__ import annotations

from typing import Any

from neo4j import Driver

from app.core.config import get_settings
from app.db.neo4j.driver import get_driver
from app.seed.golden import data as seed


def _run(driver: Driver, query: str, rows: list[dict[str, Any]]) -> int:
    """Run one batched write statement and return how many rows were sent."""
    if not rows:
        return 0
    database = get_settings().neo4j.database
    with driver.session(database=database) as session:
        session.run(query, rows=rows).consume()
    return len(rows)


def part_rows() -> list[dict[str, Any]]:
    """Rows for the ``Part`` nodes (v0.4 section 11.1)."""
    return [
        {
            "part_id": seed.golden_id_str("part", part.part_number),
            "part_number": part.part_number,
            "name": part.name,
            "part_type": part.part_type,
            "category": part.category,
            "make_or_buy": part.make_or_buy,
            "base_unit": part.base_unit,
            "created_at": seed.SEED_TIMESTAMP,
        }
        for part in seed.all_parts()
    ]


def part_revision_rows() -> list[dict[str, Any]]:
    """Rows for the ``PartRevision`` nodes (v0.4 section 12.1).

    The golden seed only contains released engineering data, so neither
    ``DRAFT`` nor ``IN_REVIEW`` revisions are produced.
    """
    return [
        {
            "revision_id": seed.golden_id_str("part_revision", part.part_number),
            "part_number": part.part_number,
            "revision_code": seed.DEFAULT_REVISION_CODE,
            "lifecycle_state": "RELEASED",
            "effective_from": seed.BOM_EFFECTIVE_FROM,
            "effective_to": None,
            "specification_json": seed.PART_SPECIFICATIONS.get(part.part_number),
            "created_by": "seed.golden",
            "created_at": seed.SEED_TIMESTAMP,
            "released_at": seed.SEED_TIMESTAMP,
        }
        for part in seed.all_parts()
    ]


def bom_version_rows() -> list[dict[str, Any]]:
    """Rows for the ``BOMVersion`` nodes (v0.4 section 14.1)."""
    return [
        {
            "bom_version_id": seed.golden_id_str("bom_version", parent),
            "bom_code": f"BOM-{parent}-{seed.BOM_REVISION_CODE}",
            "parent_part_number": parent,
            "parent_revision_code": seed.DEFAULT_REVISION_CODE,
            "bom_revision_code": seed.BOM_REVISION_CODE,
            "status": "RELEASED",
            "source_bom_version_id": None,
            "effective_from": seed.BOM_EFFECTIVE_FROM,
            "effective_to": None,
            "change_case_id": None,
            "created_at": seed.SEED_TIMESTAMP,
            "released_at": seed.SEED_TIMESTAMP,
        }
        for parent in seed.parts_with_bom()
    ]


def bom_line_rows() -> list[dict[str, Any]]:
    """Rows for the ``BOMLine`` nodes and their parent / component wiring."""
    rows = []
    for line in seed.BOM_LINES:
        rows.append(
            {
                "bom_line_id": seed.golden_id_str(
                    "bom_line", f"{line.parent_part_number}:{line.line_number}"
                ),
                "bom_version_id": seed.golden_id_str(
                    "bom_version", line.parent_part_number
                ),
                "parent_part_number": line.parent_part_number,
                "line_number": line.line_number,
                # Neo4j stores native numbers here (v0.4 section 16.1); business
                # calculations must convert with Decimal(str(value)) later.
                "quantity": float(line.quantity),
                "unit": line.unit,
                "scrap_rate": float(line.scrap_rate),
                "is_optional": line.is_optional,
                "plant_code": seed.PLANT_CODE,
                # Line level effectivity stays empty in the MVP so the line
                # inherits the BOMVersion window (v0.4 section 20).
                "effective_from": None,
                "effective_to": None,
                "change_number": line.change_number,
                "component_part_number": line.component_part_number,
                "component_revision_code": seed.DEFAULT_REVISION_CODE,
            }
        )
    return rows


def alternative_rows() -> list[dict[str, Any]]:
    """Rows for the ``ALTERNATIVE_TO`` relationships (v0.4 section 21)."""
    return [
        {
            "alternative_id": seed.golden_id_str(
                "alternative",
                f"{alt.from_part_number}->{alt.to_part_number}",
            ),
            "from_part_number": alt.from_part_number,
            "from_revision_code": alt.from_revision_code,
            "to_part_number": alt.to_part_number,
            "to_revision_code": alt.to_revision_code,
            "qualification_status": alt.qualification_status,
            "replacement_type": alt.replacement_type,
            "verified_at": seed.SEED_TIMESTAMP,
            "verified_by": alt.verified_by,
        }
        for alt in seed.ALTERNATIVES
    ]


_MERGE_PARTS = """
UNWIND $rows AS row
MERGE (p:Part {part_number: row.part_number})
SET p += row
"""

_MERGE_PART_REVISIONS = """
UNWIND $rows AS row
MERGE (r:PartRevision {part_number: row.part_number, revision_code: row.revision_code})
SET r += row
"""

_MERGE_HAS_REVISION = """
UNWIND $rows AS row
MATCH (p:Part {part_number: row.part_number})
MATCH (r:PartRevision {part_number: row.part_number, revision_code: row.revision_code})
MERGE (p)-[:HAS_REVISION]->(r)
"""

_MERGE_BOM_VERSIONS = """
UNWIND $rows AS row
MERGE (b:BOMVersion {bom_version_id: row.bom_version_id})
SET b += row
"""

_MERGE_HAS_BOM = """
UNWIND $rows AS row
MATCH (r:PartRevision {part_number: row.parent_part_number,
                       revision_code: row.parent_revision_code})
MATCH (b:BOMVersion {bom_version_id: row.bom_version_id})
MERGE (r)-[:HAS_BOM]->(b)
"""

_MERGE_BOM_LINES = """
UNWIND $rows AS row
MERGE (l:BOMLine {bom_line_id: row.bom_line_id})
SET l += row
"""

_MERGE_HAS_LINE = """
UNWIND $rows AS row
MATCH (b:BOMVersion {bom_version_id: row.bom_version_id})
MATCH (l:BOMLine {bom_line_id: row.bom_line_id})
MERGE (b)-[:HAS_LINE]->(l)
"""

_MERGE_COMPONENT = """
UNWIND $rows AS row
MATCH (l:BOMLine {bom_line_id: row.bom_line_id})
MATCH (c:PartRevision {part_number: row.component_part_number,
                       revision_code: row.component_revision_code})
MERGE (l)-[:COMPONENT]->(c)
"""

_MERGE_ALTERNATIVES = """
UNWIND $rows AS row
MATCH (a:PartRevision {part_number: row.from_part_number,
                       revision_code: row.from_revision_code})
MATCH (b:PartRevision {part_number: row.to_part_number,
                       revision_code: row.to_revision_code})
MERGE (a)-[alt:ALTERNATIVE_TO]->(b)
SET alt.alternative_id = row.alternative_id,
    alt.qualification_status = row.qualification_status,
    alt.replacement_type = row.replacement_type,
    alt.verified_at = row.verified_at,
    alt.verified_by = row.verified_by
"""


def load_golden_graph(driver: Driver | None = None) -> dict[str, int]:
    """Write the whole golden graph and return the number of rows per step."""
    active_driver = driver if driver is not None else get_driver()
    parts = part_rows()
    revisions = part_revision_rows()
    versions = bom_version_rows()
    lines = bom_line_rows()
    alternatives = alternative_rows()

    counts = {
        "part": _run(active_driver, _MERGE_PARTS, parts),
        "part_revision": _run(active_driver, _MERGE_PART_REVISIONS, revisions),
        # Revisions must exist before the HAS_REVISION relationship is merged,
        # otherwise the MATCH finds nothing and silently writes no relationship.
        "has_revision": _run(active_driver, _MERGE_HAS_REVISION, revisions),
        "bom_version": _run(active_driver, _MERGE_BOM_VERSIONS, versions),
        "has_bom": _run(active_driver, _MERGE_HAS_BOM, versions),
        "bom_line": _run(active_driver, _MERGE_BOM_LINES, lines),
        "has_line": _run(active_driver, _MERGE_HAS_LINE, lines),
        "component": _run(active_driver, _MERGE_COMPONENT, lines),
        "alternative": _run(active_driver, _MERGE_ALTERNATIVES, alternatives),
    }
    return counts
