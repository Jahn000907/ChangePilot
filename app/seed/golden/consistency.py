"""Read-only cross-database consistency checks for the loaded data world.

This module never writes to PostgreSQL or Neo4j. It reuses the golden seed
verification of ``validation.py`` and adds the checks that the seed loader does
not cover:

- PostgreSQL data presence per ERP table;
- Neo4j graph invariants (1:1 ownership, matching business keys, no duplicate
  line numbers, acyclic BOM);
- alternatives that must not be used by a released BOM yet;
- PostgreSQL -> Neo4j reference integrity for every product / part identity;
- frozen material requirements of released orders;
- readiness of the golden EOL scenario file.

Where-used traversal follows the BOM chain explicitly:
``PartRevision <- COMPONENT - BOMLine <- HAS_LINE - BOMVersion <- HAS_BOM - PartRevision``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.db.neo4j.driver import get_driver
from app.db.postgres.session import create_session
from app.seed.golden import data as seed
from app.seed.golden.validation import (
    EOL_PART_NUMBER,
    ERP_TABLES,
    CheckResult,
    case_eol_checks,
    empty_schema_counts,
)

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
SCENARIO_FILE: Path = PROJECT_ROOT / "data" / "scenarios" / "supplier_eol_brg_6204_a.json"

#: PostgreSQL tables that reference a Neo4j part / product identity, with the
#: columns that carry the business key and a human readable label.
REFERENCE_SOURCES: tuple[tuple[str, str, str, str], ...] = (
    ("erp.supplier_parts", "part_number", "revision_code", "供应商零件关系"),
    ("erp.inventory_balances", "part_number", "revision_code", "库存余额"),
    ("erp.purchase_order_lines", "part_number", "revision_code", "采购订单行"),
    ("erp.production_orders", "product_part_number", "product_revision", "生产订单产品"),
    (
        "erp.production_material_requirements",
        "part_number",
        "revision_code",
        "冻结物料需求",
    ),
    ("erp.sales_order_lines", "product_part_number", "product_revision", "销售订单行"),
)


def _neo4j(query: str, **params: Any) -> list[dict[str, Any]]:
    """Run a read-only Cypher query and return plain dictionaries."""
    database = get_settings().neo4j.database
    with get_driver().session(database=database) as session:
        return [dict(record) for record in session.run(query, **params)]


def _sql(sql: str, **params: Any) -> list[Any]:
    """Run a read-only SQL query and return the rows."""
    with create_session() as session:
        return list(session.execute(text(sql), params).all())


def _sql_scalar(sql: str, **params: Any) -> Any:
    """Run a read-only SQL query and return a single scalar value."""
    with create_session() as session:
        return session.execute(text(sql), params).scalar_one()


# --------------------------------------------------------------------------
# PostgreSQL presence
# --------------------------------------------------------------------------
def postgres_presence_checks() -> list[CheckResult]:
    """Every golden ERP table must still hold business data."""
    counts = {}
    with create_session() as session:
        for table in ERP_TABLES:
            counts[table] = session.execute(
                text(f"SELECT count(*) FROM erp.{table}")
            ).scalar_one()
    return [
        CheckResult(
            f"erp.{table} 存在业务数据",
            counts[table] > 0,
            f"实际 {counts[table]} 行，期望 > 0",
        )
        for table in ERP_TABLES
    ]


# --------------------------------------------------------------------------
# Neo4j graph invariants
# --------------------------------------------------------------------------
def graph_invariant_checks() -> list[CheckResult]:
    """Ownership, key consistency and BOM line integrity of the golden graph."""
    results: list[CheckResult] = []

    orphan_revisions = _neo4j(
        "MATCH (r:PartRevision) "
        "OPTIONAL MATCH (r)<-[hr:HAS_REVISION]-(:Part) "
        "WITH r, count(hr) AS owners "
        "WHERE owners <> 1 "
        "RETURN count(r) AS bad"
    )[0]["bad"]
    results.append(
        CheckResult(
            "每个 PartRevision 恰好归属一个 Part",
            orphan_revisions == 0,
            f"违规节点 {orphan_revisions}，期望 0",
        )
    )

    mismatched_owners = _neo4j(
        "MATCH (p:Part)-[:HAS_REVISION]->(r:PartRevision) "
        "WHERE p.part_number <> r.part_number "
        "RETURN count(*) AS bad"
    )[0]["bad"]
    results.append(
        CheckResult(
            "Part.part_number 与所属 PartRevision.part_number 一致",
            mismatched_owners == 0,
            f"不一致关系 {mismatched_owners}，期望 0",
        )
    )

    orphan_versions = _neo4j(
        "MATCH (b:BOMVersion) "
        "OPTIONAL MATCH (b)<-[hb:HAS_BOM]-(:PartRevision) "
        "WITH b, count(hb) AS owners "
        "WHERE owners <> 1 "
        "RETURN count(b) AS bad"
    )[0]["bad"]
    results.append(
        CheckResult(
            "每个 BOMVersion 恰好归属一个 PartRevision",
            orphan_versions == 0,
            f"违规节点 {orphan_versions}，期望 0",
        )
    )

    mismatched_versions = _neo4j(
        "MATCH (r:PartRevision)-[:HAS_BOM]->(b:BOMVersion) "
        "WHERE b.parent_part_number <> r.part_number "
        "   OR b.parent_revision_code <> r.revision_code "
        "RETURN count(*) AS bad"
    )[0]["bad"]
    results.append(
        CheckResult(
            "BOMVersion 的 parent 键与所属 PartRevision 一致",
            mismatched_versions == 0,
            f"不一致关系 {mismatched_versions}，期望 0",
        )
    )

    bad_has_line = _neo4j(
        "MATCH (l:BOMLine) "
        "OPTIONAL MATCH (l)<-[hl:HAS_LINE]-(:BOMVersion) "
        "WITH l, count(hl) AS owners WHERE owners <> 1 "
        "RETURN count(l) AS bad"
    )[0]["bad"]
    results.append(
        CheckResult(
            "每个 BOMLine 恰好有一个入向 HAS_LINE",
            bad_has_line == 0,
            f"违规节点 {bad_has_line}，期望 0",
        )
    )

    bad_component = _neo4j(
        "MATCH (l:BOMLine) "
        "OPTIONAL MATCH (l)-[c:COMPONENT]->(:PartRevision) "
        "WITH l, count(c) AS components WHERE components <> 1 "
        "RETURN count(l) AS bad"
    )[0]["bad"]
    results.append(
        CheckResult(
            "每个 BOMLine 恰好有一个出向 COMPONENT",
            bad_component == 0,
            f"违规节点 {bad_component}，期望 0",
        )
    )

    duplicate_lines = _neo4j(
        "MATCH (b:BOMVersion)-[:HAS_LINE]->(l:BOMLine) "
        "WITH b, l.line_number AS line_number, count(*) AS c "
        "WHERE c > 1 "
        "RETURN count(*) AS bad"
    )[0]["bad"]
    results.append(
        CheckResult(
            "同一 BOMVersion 内 line_number 不重复",
            duplicate_lines == 0,
            f"重复组 {duplicate_lines}，期望 0",
        )
    )

    cycle = find_bom_cycle()
    results.append(
        CheckResult(
            "正式 BOM 无环（DAG）",
            cycle is None,
            "未发现循环" if cycle is None else "发现循环: " + " -> ".join(cycle),
        )
    )
    return results


def bom_edges() -> list[tuple[str, str]]:
    """Return every ``parent revision -> child revision`` BOM edge."""
    rows = _neo4j(
        "MATCH (parent:PartRevision)-[:HAS_BOM]->(:BOMVersion)"
        "-[:HAS_LINE]->(:BOMLine)-[:COMPONENT]->(child:PartRevision) "
        "RETURN DISTINCT parent.part_number AS parent, child.part_number AS child"
    )
    return [(str(row["parent"]), str(row["child"])) for row in rows]


def find_bom_cycle(edges: list[tuple[str, str]] | None = None) -> list[str] | None:
    """Return one BOM cycle as a path, or ``None`` when the BOM is a DAG.

    The edges come from a graph query; the traversal itself is a depth-first
    search over those real edges, so a cycle that spans several assemblies is
    detected rather than inferred from node counts.
    """
    graph: dict[str, list[str]] = {}
    for parent, child in edges if edges is not None else bom_edges():
        graph.setdefault(parent, []).append(child)

    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {node: WHITE for node in graph}
    for node in list(graph):
        for child in graph[node]:
            colour.setdefault(child, WHITE)

    def walk(node: str, stack: list[str]) -> list[str] | None:
        colour[node] = GREY
        stack.append(node)
        for child in graph.get(node, []):
            if colour.get(child, WHITE) == GREY:
                return stack[stack.index(child) :] + [child]
            if colour.get(child, WHITE) == WHITE:
                found = walk(child, stack)
                if found is not None:
                    return found
        stack.pop()
        colour[node] = BLACK
        return None

    for node in list(graph):
        if colour.get(node, WHITE) == WHITE:
            found = walk(node, [])
            if found is not None:
                return found
    return None


# --------------------------------------------------------------------------
# Alternatives
# --------------------------------------------------------------------------
def alternative_usage_checks() -> list[CheckResult]:
    """The candidate replacements must not be used by a released BOM yet."""
    results: list[CheckResult] = []
    for part_number in ("BRG-6204-B", "BRG-6204-C"):
        rows = _neo4j(
            "MATCH (b:BOMVersion)-[:HAS_LINE]->(:BOMLine)-[:COMPONENT]->"
            "(r:PartRevision {part_number: $part_number}) "
            "WHERE b.status = 'RELEASED' "
            "RETURN count(*) AS used",
            part_number=part_number,
        )
        used = rows[0]["used"]
        results.append(
            CheckResult(
                f"{part_number} 未被正式 Released BOM 使用",
                used == 0,
                f"被引用 {used} 次，期望 0",
            )
        )
    return results


# --------------------------------------------------------------------------
# Cross database references
# --------------------------------------------------------------------------
def neo4j_part_revisions() -> set[tuple[str, str]]:
    """Return every ``(part_number, revision_code)`` pair known to Neo4j."""
    rows = _neo4j(
        "MATCH (r:PartRevision) "
        "RETURN r.part_number AS part_number, r.revision_code AS revision_code"
    )
    return {
        (str(row["part_number"]), str(row["revision_code"])) for row in rows
    }


def cross_database_checks() -> list[CheckResult]:
    """Every PostgreSQL product / part identity must resolve in Neo4j."""
    known = neo4j_part_revisions()
    results: list[CheckResult] = []
    for table, part_column, revision_column, label in REFERENCE_SOURCES:
        rows = _sql(
            f"SELECT DISTINCT {part_column} AS part_number, "
            f"{revision_column} AS revision_code FROM {table}"
        )
        dangling = sorted(
            {
                (str(row.part_number), str(row.revision_code))
                for row in rows
                if (str(row.part_number), str(row.revision_code)) not in known
            }
        )
        results.append(
            CheckResult(
                f"{label}（{table}）引用可在 Neo4j 定位",
                not dangling,
                f"共 {len(rows)} 个业务标识，悬空 {len(dangling)} 个"
                + (f": {dangling[:5]}" if dangling else ""),
            )
        )
    return results


# --------------------------------------------------------------------------
# Frozen material requirements
# --------------------------------------------------------------------------
def frozen_requirement_checks() -> list[CheckResult]:
    """Released / in-progress orders must already carry frozen requirements."""
    missing = _sql_scalar(
        """
        SELECT count(*)
        FROM erp.production_orders po
        WHERE po.status IN ('RELEASED', 'IN_PROGRESS')
          AND NOT EXISTS (
              SELECT 1 FROM erp.production_material_requirements pmr
              WHERE pmr.production_order_id = po.production_order_id
          )
        """
    )
    results = [
        CheckResult(
            "已释放 / 进行中的生产订单都有冻结需求",
            missing == 0,
            f"缺少冻结需求的订单 {missing} 个，期望 0",
        )
    ]
    frozen_rows = _sql_scalar(
        "SELECT count(*) FROM erp.production_material_requirements"
    )
    results.append(
        CheckResult(
            "冻结需求表可独立读取历史事实",
            frozen_rows > 0,
            f"共 {frozen_rows} 行冻结需求（检查过程未访问 Neo4j BOM）",
        )
    )

    planned_with_requirements = _sql(
        """
        SELECT po.order_number, count(pmr.requirement_id) AS requirement_count
        FROM erp.production_orders po
        LEFT JOIN erp.production_material_requirements pmr
          ON pmr.production_order_id = po.production_order_id
        WHERE po.status = 'PLANNED'
        GROUP BY po.order_number
        ORDER BY po.order_number
        """
    )
    unexpected = [
        f"{row.order_number}={row.requirement_count}"
        for row in planned_with_requirements
        if row.requirement_count
    ]
    results.append(
        CheckResult(
            "PLANNED 生产订单没有冻结需求（未释放即未展开）",
            not unexpected,
            (
                "PLANNED 订单: "
                + ", ".join(
                    f"{row.order_number}={row.requirement_count}"
                    for row in planned_with_requirements
                )
                if planned_with_requirements
                else "无 PLANNED 订单"
            )
            + (f"，异常: {unexpected}" if unexpected else ""),
        )
    )
    return results


# --------------------------------------------------------------------------
# Golden EOL scenario readiness
# --------------------------------------------------------------------------
def scenario_checks() -> list[CheckResult]:
    """The scenario file must be fully supported by the loaded data world."""
    results: list[CheckResult] = []
    try:
        scenario = json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            CheckResult(
                "EOL 场景文件可解析",
                False,
                f"{SCENARIO_FILE.name}: {exc}",
            )
        ]

    required_keys = (
        "supplier",
        "part_number",
        "revision_code",
        "last_time_buy_date",
        "eol_date",
        "suggested_replacement",
    )
    missing_keys = [key for key in required_keys if key not in scenario]
    results.append(
        CheckResult(
            "EOL 场景文件字段完整",
            not missing_keys,
            f"缺失字段 {missing_keys}" if missing_keys else "字段齐全",
        )
    )

    supplier_rows = _sql(
        """
        SELECT s.supplier_name, sp.status, sp.last_time_buy_date, sp.eol_date
        FROM erp.supplier_parts sp
        JOIN erp.suppliers s ON s.supplier_id = sp.supplier_id
        WHERE s.supplier_code = :supplier_code AND sp.part_number = :part
        """,
        supplier_code=scenario.get("supplier_code"),
        part=scenario.get("part_number"),
    )
    supplier_ok = bool(supplier_rows)
    results.append(
        CheckResult(
            "场景供应商与零件在 PostgreSQL 有供应关系",
            supplier_ok,
            (
                f"{supplier_rows[0].supplier_name} / {supplier_rows[0].status} "
                f"/ {supplier_rows[0].last_time_buy_date} / {supplier_rows[0].eol_date}"
                if supplier_ok
                else "未找到供应关系"
            ),
        )
    )
    if supplier_ok:
        row = supplier_rows[0]
        dates_ok = (
            str(row.last_time_buy_date) == scenario["last_time_buy_date"]
            and str(row.eol_date) == scenario["eol_date"]
        )
        results.append(
            CheckResult(
                "场景最后采购日期 / 停产日期与数据库一致",
                dates_ok,
                (
                    f"DB {row.last_time_buy_date} / {row.eol_date}，"
                    f"场景 {scenario['last_time_buy_date']} / {scenario['eol_date']}"
                ),
            )
        )

    revision_known = (
        str(scenario.get("part_number")),
        str(scenario.get("revision_code")),
    ) in neo4j_part_revisions()
    results.append(
        CheckResult(
            "场景零件版本在 Neo4j 中存在",
            revision_known,
            f"({scenario.get('part_number')}, {scenario.get('revision_code')})"
            + (" 已定位" if revision_known else " 未找到"),
        )
    )

    replacement = scenario.get("suggested_replacement", {})
    replacement_known = (
        str(replacement.get("part_number")),
        str(replacement.get("revision_code")),
    ) in neo4j_part_revisions()
    results.append(
        CheckResult(
            "建议替代件在 Neo4j 中存在",
            replacement_known,
            f"({replacement.get('part_number')}, {replacement.get('revision_code')})"
            + (" 已定位" if replacement_known else " 未找到"),
        )
    )
    return results


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------
def all_checks() -> list[tuple[str, list[CheckResult]]]:
    """Return every consistency check grouped by section."""
    return [
        ("PostgreSQL 数据存在性", postgres_presence_checks()),
        ("ECM / Agent / Audit 仍为空", _empty_runtime_checks()),
        ("Neo4j 图结构不变量", graph_invariant_checks()),
        ("替代料关系", alternative_usage_checks()),
        ("PostgreSQL → Neo4j 跨库引用", cross_database_checks()),
        ("冻结生产需求", frozen_requirement_checks()),
        ("Golden EOL 场景就绪", scenario_checks()),
        ("Golden Seed 验收（复用 seed validation）", case_eol_checks()),
    ]


def _empty_runtime_checks() -> list[CheckResult]:
    """Runtime schemas must still be empty."""
    counts = empty_schema_counts()
    dirty = {name: count for name, count in counts.items() if count}
    return [
        CheckResult(
            "ecm / agent / audit 无运行时业务数据",
            not dirty,
            f"{len(counts)} 张表全部 0 行" if not dirty else f"非空: {dirty}",
        )
    ]


def count_checks(grouped: list[tuple[str, list[CheckResult]]]) -> int:
    """Return the total number of checks."""
    return sum(len(checks) for _section, checks in grouped)


def all_passed(grouped: list[tuple[str, list[CheckResult]]]) -> bool:
    """Return whether every check passed."""
    return all(check.passed for _section, checks in grouped for check in checks)


#: Kept for callers that only need the headline facts.
EOL_SCENARIO_FILE = SCENARIO_FILE
EOL_PART = EOL_PART_NUMBER
SEED_PRODUCTS = tuple(number for number, _name, _category in seed.PRODUCTS)
