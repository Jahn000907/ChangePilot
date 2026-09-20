"""Deterministic definitions of the ChangePilot Golden Seed.

This module holds the hand-maintained business data of the simulated company
智衡自动化设备有限公司 (ZhiHeng Automation). It contains no database access: the
loaders in ``neo4j.py`` / ``postgres.py`` only read these definitions.

Design references:

- docs/changepilot_business_domain_bom_model_v0.3.md: simulated company, product
  structure, BOM levels, CASE-EOL-001;
- docs/changepilot_database_design_v0.4.md sections 62.1 / 63 / 64 / 73-76:
  Golden Seed scale, generation order and the CASE-EOL-001 constraints.

Everything is deterministic: ids come from ``uuid5`` over a fixed namespace and
every timestamp is a constant, so re-running the seed produces identical rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

# --------------------------------------------------------------------------
# Deterministic identifiers and fixed timestamps
# --------------------------------------------------------------------------
GOLDEN_NAMESPACE: uuid.UUID = uuid.uuid5(uuid.NAMESPACE_DNS, "changepilot.golden")

#: One fixed instant for every ``created_at`` / ``released_at`` written by the seed.
SEED_TIMESTAMP: datetime = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
BOM_EFFECTIVE_FROM: date = date(2026, 1, 1)
DEFAULT_REVISION_CODE = "A"
BOM_REVISION_CODE = "01"
PLANT_CODE = "CN-E01"
WAREHOUSE_CODE = "WH-01"
CURRENCY = "CNY"


def golden_id(kind: str, key: str) -> uuid.UUID:
    """Return the deterministic UUID of one golden seed object."""
    return uuid.uuid5(GOLDEN_NAMESPACE, f"{kind}:{key}")


def golden_id_str(kind: str, key: str) -> str:
    """Return the deterministic UUID as the canonical string form (Neo4j uses it)."""
    return str(golden_id(kind, key))


# --------------------------------------------------------------------------
# Parts (v0.3 section 3 / 4, v0.4 section 11)
# --------------------------------------------------------------------------
#: (part_number, name, category)
PRODUCTS: tuple[tuple[str, str, str], ...] = (
    ("ROB-P100", "六轴工业机器人", "机器人整机"),
    ("ROB-P200", "重载工业机器人", "机器人整机"),
    ("CON-C100", "模块化自动输送系统", "输送系统"),
    ("PAL-P300", "自动码垛设备", "码垛设备"),
)

#: (part_number, name, category)
ASSEMBLIES: tuple[tuple[str, str, str], ...] = (
    ("ASM-ARM100", "六轴机械臂总成", "机械臂系统"),
    ("ASM-ARM200", "重载机械臂总成", "机械臂系统"),
    ("ASM-JOINT100", "关节模组", "传动组件"),
    ("ASM-JOINT200", "重载关节模组", "传动组件"),
    ("ASM-GEARBOX100", "关节齿轮箱", "传动组件"),
    ("ASM-GEARBOX200", "重载关节齿轮箱", "传动组件"),
    ("ASM-GEARBOX300", "输送驱动齿轮箱", "传动组件"),
    ("ASM-GEARBOX400", "码垛回转齿轮箱", "传动组件"),
    ("ASM-CTRL100", "标准控制柜总成", "控制系统"),
    ("ASM-CTRL200", "重载控制柜总成", "控制系统"),
    ("ASM-CONV100", "输送主线总成", "输送系统"),
    ("ASM-CONV200", "输送支线总成", "输送系统"),
    ("ASM-PAL100", "码垛主机总成", "码垛系统"),
    ("ASM-PAL200", "码垛夹具总成", "码垛系统"),
)

#: (part_number, name, category, supplier_code) for purchased parts.
PURCHASED_PARTS: tuple[tuple[str, str, str, str], ...] = (
    ("BRG-6204-A", "深沟球轴承 6204 A 版", "轴承", "SUP-001"),
    ("BRG-6204-B", "深沟球轴承 6204 B 版", "轴承", "SUP-001"),
    ("BRG-6204-C", "深沟球轴承 6204 C 版", "轴承", "SUP-001"),
    ("SEAL-O100", "骨架油封 Ø25", "密封件", "SUP-001"),
    ("SEAL-O200", "骨架油封 Ø35", "密封件", "SUP-001"),
    ("GEAR-G100", "精密齿轮 模数2", "齿轮", "SUP-002"),
    ("GEAR-G200", "重载齿轮 模数3", "齿轮", "SUP-002"),
    ("SHAFT-S100", "传动轴 Ø25", "轴类", "SUP-002"),
    ("SHAFT-S200", "重载传动轴 Ø35", "轴类", "SUP-002"),
    ("MOTOR-SM100", "400W 伺服电机", "电机", "SUP-003"),
    ("MOTOR-SM200", "1.5kW 伺服电机", "电机", "SUP-003"),
    ("ENCODER-E100", "增量式编码器", "编码器", "SUP-003"),
    ("ENCODER-E200", "多圈绝对值编码器", "编码器", "SUP-003"),
    ("PLC-C100", "标准型可编程控制器", "控制器", "SUP-004"),
    ("PLC-C200", "重载型可编程控制器", "控制器", "SUP-004"),
    ("SENSOR-S100", "光电传感器", "传感器", "SUP-004"),
    ("SENSOR-S200", "接近传感器", "传感器", "SUP-004"),
    ("CABLE-C100", "动力电缆 4x2.5", "线缆", "SUP-004"),
    ("CABLE-C200", "控制电缆 8x0.75", "线缆", "SUP-004"),
    ("ENCLOSURE-EN100", "标准控制柜外壳", "机柜附件", "SUP-004"),
    ("ENCLOSURE-EN200", "重载控制柜外壳", "机柜附件", "SUP-004"),
    ("FAN-FAN100", "控制柜冷却风扇", "冷却", "SUP-004"),
    ("FILTER-FL100", "控制柜滤芯", "过滤", "SUP-004"),
    ("ROLLER-R100", "输送辊筒 Ø50", "辊筒", "SUP-005"),
    ("ROLLER-R200", "重载输送辊筒 Ø76", "辊筒", "SUP-005"),
    ("BELT-B100", "标准输送带", "输送带", "SUP-005"),
    ("BELT-B200", "加宽输送带", "输送带", "SUP-005"),
    ("GRIPPER-GR100", "气动码垛夹具", "夹具", "SUP-005"),
    ("VALVE-V100", "气动电磁阀", "气动", "SUP-005"),
    ("SCREW-SC100", "高强度紧固件组", "紧固件", "SUP-005"),
)

#: (part_number, name, category) for parts manufactured in house (MAKE, no supplier).
MANUFACTURED_PARTS: tuple[tuple[str, str, str], ...] = (
    ("FRAME-F100", "机械臂框架", "结构件"),
    ("FRAME-F200", "重载机械臂框架", "结构件"),
)


@dataclass(frozen=True)
class PartDef:
    """One ``Part`` node / stable material identity (v0.4 section 11.1)."""

    part_number: str
    name: str
    part_type: str
    category: str
    make_or_buy: str
    base_unit: str = "EA"


def all_parts() -> tuple[PartDef, ...]:
    """Return every part of the golden seed in a stable order."""
    parts = [
        PartDef(number, name, "FINISHED_PRODUCT", category, "MAKE")
        for number, name, category in PRODUCTS
    ]
    parts += [
        PartDef(number, name, "ASSEMBLY", category, "MAKE")
        for number, name, category in ASSEMBLIES
    ]
    parts += [
        PartDef(number, name, "PURCHASED_PART", category, "BUY")
        for number, name, category, _supplier in PURCHASED_PARTS
    ]
    parts += [
        PartDef(number, name, "MANUFACTURED_PART", category, "MAKE")
        for number, name, category in MANUFACTURED_PARTS
    ]
    return tuple(parts)


#: part_number -> supplier_code for purchased parts.
SUPPLIER_OF_PART: dict[str, str] = {
    number: supplier for number, _name, _category, supplier in PURCHASED_PARTS
}

#: Optional JSON-string specification of a part revision (v0.4 section 12.1).
#: The three bearing variants differ in clearance, precision class and rated
#: dynamic load, which is the "engineering attribute" difference required by
#: v0.4 section 74 for CASE-EOL-001.
PART_SPECIFICATIONS: dict[str, str] = {
    "BRG-6204-A": (
        '{"bearing_type": "deep_groove", "bore_mm": 20, "outer_mm": 47, '
        '"width_mm": 14, "clearance": "CN", "precision": "P6", '
        '"dynamic_load_kn": 12.8}'
    ),
    "BRG-6204-B": (
        '{"bearing_type": "deep_groove", "bore_mm": 20, "outer_mm": 47, '
        '"width_mm": 14, "clearance": "C3", "precision": "P5", '
        '"dynamic_load_kn": 14.2}'
    ),
    "BRG-6204-C": (
        '{"bearing_type": "deep_groove", "bore_mm": 20, "outer_mm": 47, '
        '"width_mm": 14, "clearance": "CN", "precision": "P0", '
        '"dynamic_load_kn": 11.5}'
    ),
}

#: part_number -> commercial data of its supply relationship.
SUPPLIER_PART_BY_PART: dict[str, SupplierPartDef] = {}


# --------------------------------------------------------------------------
# BOM structure (v0.3 section 4, v0.4 sections 14-18)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BomLineDef:
    """One BOM line of a parent part (v0.4 section 16.1)."""

    parent_part_number: str
    line_number: int
    component_part_number: str
    quantity: Decimal
    unit: str = "EA"
    scrap_rate: Decimal = Decimal(0)
    is_optional: bool = False
    change_number: str | None = None


def _bom(parent: str, *components: tuple[str, str]) -> list[BomLineDef]:
    """Build the BOM lines of one parent from (component, quantity) pairs."""
    return [
        BomLineDef(parent, index, component, Decimal(quantity))
        for index, (component, quantity) in enumerate(components, start=1)
    ]


BOM_LINES: tuple[BomLineDef, ...] = tuple(
    line
    for lines in (
        # L0 -> L1: finished products
        _bom(
            "ROB-P100",
            ("ASM-ARM100", "1"),
            ("ASM-CTRL100", "1"),
            ("FRAME-F100", "1"),
            ("CABLE-C100", "2"),
        ),
        _bom(
            "ROB-P200",
            ("ASM-ARM200", "1"),
            ("ASM-CTRL200", "1"),
            ("FRAME-F200", "1"),
            ("CABLE-C100", "2"),
        ),
        _bom(
            "CON-C100",
            ("ASM-CONV100", "2"),
            ("ASM-CONV200", "1"),
            ("ASM-CTRL100", "1"),
            ("FRAME-F100", "2"),
        ),
        _bom(
            "PAL-P300",
            ("ASM-PAL100", "1"),
            ("ASM-PAL200", "1"),
            ("ASM-CTRL200", "1"),
            ("FRAME-F200", "1"),
            ("CABLE-C200", "2"),
        ),
        # L1 systems
        _bom(
            "ASM-ARM100",
            ("ASM-JOINT100", "3"),
            ("FRAME-F100", "1"),
            ("CABLE-C100", "2"),
            ("SENSOR-S100", "2"),
        ),
        _bom(
            "ASM-ARM200",
            ("ASM-JOINT200", "3"),
            ("FRAME-F200", "1"),
            ("CABLE-C100", "2"),
            ("SENSOR-S200", "2"),
        ),
        _bom(
            "ASM-CONV100",
            ("BELT-B100", "1"),
            ("ROLLER-R100", "4"),
            ("ASM-GEARBOX300", "1"),
            ("MOTOR-SM100", "1"),
            ("FRAME-F100", "1"),
            ("SCREW-SC100", "12"),
        ),
        _bom(
            "ASM-CONV200",
            ("BELT-B200", "1"),
            ("ROLLER-R200", "2"),
            ("CABLE-C200", "1"),
            ("FRAME-F100", "1"),
        ),
        _bom(
            "ASM-PAL100",
            ("ASM-GEARBOX400", "1"),
            ("MOTOR-SM200", "1"),
            ("ROLLER-R200", "2"),
            ("FRAME-F200", "1"),
        ),
        _bom(
            "ASM-PAL200",
            ("GRIPPER-GR100", "1"),
            ("SENSOR-S100", "2"),
            ("CABLE-C100", "1"),
            ("VALVE-V100", "1"),
        ),
        _bom(
            "ASM-CTRL100",
            ("PLC-C100", "1"),
            ("SENSOR-S100", "4"),
            ("CABLE-C200", "1"),
            ("ENCLOSURE-EN100", "1"),
            ("FAN-FAN100", "1"),
            ("FILTER-FL100", "1"),
        ),
        _bom(
            "ASM-CTRL200",
            ("PLC-C200", "1"),
            ("SENSOR-S200", "6"),
            ("CABLE-C200", "2"),
            ("ENCLOSURE-EN200", "1"),
            ("FAN-FAN100", "2"),
            ("FILTER-FL100", "1"),
        ),
        # L2 / L3 transmission groups: four gearboxes use BRG-6204-A
        _bom(
            "ASM-JOINT100",
            ("ASM-GEARBOX100", "1"),
            ("MOTOR-SM100", "1"),
            ("ENCODER-E100", "1"),
            ("SHAFT-S100", "1"),
        ),
        _bom(
            "ASM-JOINT200",
            ("ASM-GEARBOX200", "1"),
            ("MOTOR-SM200", "1"),
            ("ENCODER-E200", "1"),
            ("SHAFT-S200", "1"),
        ),
        _bom(
            "ASM-GEARBOX100",
            ("BRG-6204-A", "2"),
            ("GEAR-G100", "3"),
            ("SHAFT-S100", "1"),
            ("SEAL-O100", "2"),
            ("SCREW-SC100", "8"),
        ),
        _bom(
            "ASM-GEARBOX200",
            ("BRG-6204-A", "4"),
            ("GEAR-G200", "3"),
            ("SHAFT-S200", "1"),
            ("SEAL-O200", "2"),
        ),
        _bom(
            "ASM-GEARBOX300",
            ("BRG-6204-A", "2"),
            ("GEAR-G100", "2"),
            ("SHAFT-S100", "1"),
            ("SEAL-O100", "2"),
        ),
        _bom(
            "ASM-GEARBOX400",
            ("BRG-6204-A", "2"),
            ("GEAR-G200", "2"),
            ("SHAFT-S200", "1"),
            ("SEAL-O200", "2"),
        ),
    )
    for line in lines
)


def bom_children(part_number: str) -> tuple[BomLineDef, ...]:
    """Return the BOM lines of one parent part, in line order."""
    return tuple(
        sorted(
            (line for line in BOM_LINES if line.parent_part_number == part_number),
            key=lambda line: line.line_number,
        )
    )


def parts_with_bom() -> tuple[str, ...]:
    """Return every part number that owns a BOM version, in a stable order."""
    parents = {line.parent_part_number for line in BOM_LINES}
    return tuple(
        part.part_number for part in all_parts() if part.part_number in parents
    )


def explode_leaf_requirements(
    part_number: str, quantity: Decimal
) -> dict[tuple[str, str], Decimal]:
    """Expand a BOM into leaf (purchased / manufactured) requirements.

    This is the deterministic expansion used to freeze the material requirements
    of a released production order (v0.4 section 64). It only walks the BOM data
    above, so historical requirements never depend on the current Neo4j graph.
    Scrap rates are ignored: the MVP does not do scrap planning.

    Returns a mapping of ``(part_number, revision_code) -> required quantity``.
    """
    requirements: dict[tuple[str, str], Decimal] = {}
    for line in bom_children(part_number):
        child_quantity = quantity * line.quantity
        if bom_children(line.component_part_number):
            nested = explode_leaf_requirements(
                line.component_part_number, child_quantity
            )
            for key, value in nested.items():
                requirements[key] = requirements.get(key, Decimal(0)) + value
        else:
            key = (line.component_part_number, DEFAULT_REVISION_CODE)
            requirements[key] = requirements.get(key, Decimal(0)) + child_quantity
    return requirements


# --------------------------------------------------------------------------
# Alternative parts (v0.4 section 21)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class AlternativeDef:
    """One ``ALTERNATIVE_TO`` relationship between two part revisions."""

    from_part_number: str
    from_revision_code: str
    to_part_number: str
    to_revision_code: str
    qualification_status: str
    replacement_type: str
    verified_by: str


ALTERNATIVES: tuple[AlternativeDef, ...] = (
    AlternativeDef(
        "BRG-6204-A",
        DEFAULT_REVISION_CODE,
        "BRG-6204-B",
        DEFAULT_REVISION_CODE,
        "QUALIFIED",
        "DIRECT",
        "quality.engineer",
    ),
    AlternativeDef(
        "BRG-6204-A",
        DEFAULT_REVISION_CODE,
        "BRG-6204-C",
        DEFAULT_REVISION_CODE,
        "UNQUALIFIED",
        "CONDITIONAL",
        "quality.engineer",
    ),
)


# --------------------------------------------------------------------------
# Suppliers (v0.4 sections 26 / 27)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SupplierDef:
    """One supplier of the simulated company (v0.4 section 26)."""

    supplier_code: str
    supplier_name: str
    status: str
    quality_rating: Decimal
    delivery_rating: Decimal


SUPPLIERS: tuple[SupplierDef, ...] = (
    SupplierDef("SUP-001", "MotionWorks", "ACTIVE", Decimal("95.50"), Decimal("92.00")),
    SupplierDef("SUP-002", "GearTech", "ACTIVE", Decimal("91.00"), Decimal("88.50")),
    SupplierDef("SUP-003", "ServoDrive", "ACTIVE", Decimal("93.20"), Decimal("90.10")),
    SupplierDef("SUP-004", "ControlLine", "ACTIVE", Decimal("89.40"), Decimal("94.30")),
    SupplierDef("SUP-005", "MechWorks", "PHASE_OUT", Decimal("85.10"), Decimal("80.20")),
)


@dataclass(frozen=True)
class SupplierPartDef:
    """Supply relationship between a supplier and a part (v0.4 section 27)."""

    supplier_code: str
    part_number: str
    manufacturer_part_number: str
    qualification_status: str
    unit_price: Decimal
    lead_time_days: int
    minimum_order_qty: Decimal
    status: str = "ACTIVE"
    last_time_buy_date: date | None = None
    eol_date: date | None = None


def _supplier_part(
    supplier_code: str,
    part_number: str,
    manufacturer_part_number: str,
    unit_price: str,
    lead_time_days: int,
    minimum_order_qty: str,
    qualification_status: str = "QUALIFIED",
    status: str = "ACTIVE",
    last_time_buy_date: date | None = None,
    eol_date: date | None = None,
) -> SupplierPartDef:
    return SupplierPartDef(
        supplier_code=supplier_code,
        part_number=part_number,
        manufacturer_part_number=manufacturer_part_number,
        qualification_status=qualification_status,
        unit_price=Decimal(unit_price),
        lead_time_days=lead_time_days,
        minimum_order_qty=Decimal(minimum_order_qty),
        status=status,
        last_time_buy_date=last_time_buy_date,
        eol_date=eol_date,
    )


SUPPLIER_PARTS: tuple[SupplierPartDef, ...] = (
    # SUP-001 MotionWorks — CASE-EOL-001 (v0.4 sections 73 / 74)
    _supplier_part(
        "SUP-001",
        "BRG-6204-A",
        "MW-6204-A",
        "12.5000",
        30,
        "50",
        status="LAST_TIME_BUY",
        last_time_buy_date=date(2026, 11, 30),
        eol_date=date(2027, 1, 31),
    ),
    _supplier_part("SUP-001", "BRG-6204-B", "MW-6204-B", "15.8000", 45, "50"),
    _supplier_part(
        "SUP-001",
        "BRG-6204-C",
        "MW-6204-C",
        "9.9000",
        20,
        "100",
        qualification_status="UNQUALIFIED",
    ),
    _supplier_part("SUP-001", "SEAL-O100", "MW-SEAL-25", "3.2000", 15, "200"),
    _supplier_part("SUP-001", "SEAL-O200", "MW-SEAL-35", "4.1000", 15, "200"),
    # SUP-002 GearTech
    _supplier_part("SUP-002", "GEAR-G100", "GT-M2-100", "86.0000", 40, "20"),
    _supplier_part("SUP-002", "GEAR-G200", "GT-M3-200", "142.0000", 55, "10"),
    _supplier_part("SUP-002", "SHAFT-S100", "GT-S25-100", "58.0000", 35, "20"),
    _supplier_part("SUP-002", "SHAFT-S200", "GT-S35-200", "96.0000", 50, "10"),
    # SUP-003 ServoDrive
    _supplier_part("SUP-003", "MOTOR-SM100", "SD-400W-A", "1280.0000", 21, "5"),
    _supplier_part("SUP-003", "MOTOR-SM200", "SD-1500W-B", "3260.0000", 28, "2"),
    _supplier_part("SUP-003", "ENCODER-E100", "SD-ENC-17", "420.0000", 18, "10"),
    _supplier_part("SUP-003", "ENCODER-E200", "SD-ENC-23", "880.0000", 25, "5"),
    # SUP-004 ControlLine
    _supplier_part("SUP-004", "PLC-C100", "CL-PLC-100", "2450.0000", 30, "2"),
    _supplier_part("SUP-004", "PLC-C200", "CL-PLC-200", "4380.0000", 35, "1"),
    _supplier_part("SUP-004", "SENSOR-S100", "CL-PS-100", "78.0000", 12, "50"),
    _supplier_part("SUP-004", "SENSOR-S200", "CL-PX-200", "112.0000", 14, "50"),
    _supplier_part("SUP-004", "CABLE-C100", "CL-CB-425", "36.0000", 10, "100"),
    _supplier_part("SUP-004", "CABLE-C200", "CL-CB-8075", "28.0000", 10, "100"),
    _supplier_part(
        "SUP-004", "ENCLOSURE-EN100", "CL-EN-100", "680.0000", 20, "5"
    ),
    _supplier_part(
        "SUP-004", "ENCLOSURE-EN200", "CL-EN-200", "1180.0000", 25, "3"
    ),
    _supplier_part("SUP-004", "FAN-FAN100", "CL-FAN-100", "46.0000", 8, "100"),
    _supplier_part("SUP-004", "FILTER-FL100", "CL-FLT-100", "22.0000", 8, "200"),
    # SUP-005 MechWorks
    _supplier_part("SUP-005", "ROLLER-R100", "MW-R50-100", "64.0000", 16, "50"),
    _supplier_part("SUP-005", "ROLLER-R200", "MW-R76-200", "108.0000", 20, "30"),
    _supplier_part("SUP-005", "BELT-B100", "MW-BELT-100", "210.0000", 24, "20"),
    _supplier_part("SUP-005", "BELT-B200", "MW-BELT-200", "345.0000", 28, "10"),
    _supplier_part("SUP-005", "GRIPPER-GR100", "MW-GR-100", "1560.0000", 32, "5"),
    _supplier_part("SUP-005", "VALVE-V100", "MW-VLV-100", "96.0000", 12, "50"),
    _supplier_part("SUP-005", "SCREW-SC100", "MW-SCR-100", "0.8000", 6, "1000"),
)

SUPPLIER_PART_BY_PART = {item.part_number: item for item in SUPPLIER_PARTS}


# --------------------------------------------------------------------------
# Inventory (v0.4 section 28)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class InventoryDef:
    """One inventory balance (v0.4 section 28)."""

    part_number: str
    revision_code: str
    qty_on_hand: Decimal
    qty_reserved: Decimal
    unit_cost: Decimal


def _inventory(
    part_number: str, qty_on_hand: str, qty_reserved: str, unit_cost: str
) -> InventoryDef:
    return InventoryDef(
        part_number=part_number,
        revision_code=DEFAULT_REVISION_CODE,
        qty_on_hand=Decimal(qty_on_hand),
        qty_reserved=Decimal(qty_reserved),
        unit_cost=Decimal(unit_cost),
    )


INVENTORY: tuple[InventoryDef, ...] = (
    _inventory("BRG-6204-A", "820", "120", "12.5000"),
    _inventory("BRG-6204-B", "150", "0", "15.8000"),
    _inventory("BRG-6204-C", "60", "0", "9.9000"),
    _inventory("SEAL-O100", "2400", "300", "3.2000"),
    _inventory("SEAL-O200", "1600", "200", "4.1000"),
    _inventory("GEAR-G100", "640", "80", "86.0000"),
    _inventory("GEAR-G200", "280", "40", "142.0000"),
    _inventory("SHAFT-S100", "520", "60", "58.0000"),
    _inventory("SHAFT-S200", "240", "20", "96.0000"),
    _inventory("MOTOR-SM100", "96", "12", "1280.0000"),
    _inventory("MOTOR-SM200", "38", "6", "3260.0000"),
    _inventory("ENCODER-E100", "180", "20", "420.0000"),
    _inventory("ENCODER-E200", "72", "8", "880.0000"),
    _inventory("PLC-C100", "54", "6", "2450.0000"),
    _inventory("PLC-C200", "22", "4", "4380.0000"),
    _inventory("SENSOR-S100", "1260", "180", "78.0000"),
    _inventory("SENSOR-S200", "860", "90", "112.0000"),
    _inventory("CABLE-C100", "3400", "400", "36.0000"),
    _inventory("CABLE-C200", "2800", "350", "28.0000"),
    _inventory("ENCLOSURE-EN100", "120", "16", "680.0000"),
    _inventory("ENCLOSURE-EN200", "58", "8", "1180.0000"),
    _inventory("FAN-FAN100", "1500", "150", "46.0000"),
    _inventory("FILTER-FL100", "2600", "200", "22.0000"),
    _inventory("ROLLER-R100", "880", "100", "64.0000"),
    _inventory("ROLLER-R200", "420", "50", "108.0000"),
    _inventory("BELT-B100", "140", "20", "210.0000"),
    _inventory("BELT-B200", "76", "10", "345.0000"),
    _inventory("GRIPPER-GR100", "34", "4", "1560.0000"),
    _inventory("VALVE-V100", "620", "60", "96.0000"),
    _inventory("SCREW-SC100", "18000", "2000", "0.8000"),
    _inventory("FRAME-F100", "86", "10", "1680.0000"),
    _inventory("FRAME-F200", "42", "6", "2360.0000"),
)


# --------------------------------------------------------------------------
# Sales orders (v0.4 sections 33 / 34)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SalesOrderDef:
    """One customer sales order; ``lines`` are (product, quantity, delivered)."""

    order_number: str
    customer_code: str
    status: str
    order_date: date
    requested_delivery_date: date | None
    lines: tuple[tuple[str, str, str], ...]


SALES_ORDERS: tuple[SalesOrderDef, ...] = (
    SalesOrderDef(
        "SO-2026-000001",
        "CUST-001",
        "OPEN",
        date(2026, 8, 3),
        date(2026, 11, 15),
        (("ROB-P100", "6", "0"),),
    ),
    SalesOrderDef(
        "SO-2026-000002",
        "CUST-002",
        "CONFIRMED",
        date(2026, 8, 5),
        date(2026, 11, 30),
        (("ROB-P200", "3", "0"),),
    ),
    SalesOrderDef(
        "SO-2026-000003",
        "CUST-003",
        "OPEN",
        date(2026, 8, 6),
        date(2026, 12, 10),
        (("CON-C100", "2", "0"),),
    ),
    SalesOrderDef(
        "SO-2026-000004",
        "CUST-004",
        "PARTIALLY_DELIVERED",
        date(2026, 8, 8),
        date(2026, 10, 20),
        (("PAL-P300", "4", "1"),),
    ),
    SalesOrderDef(
        "SO-2026-000005",
        "CUST-001",
        "OPEN",
        date(2026, 8, 10),
        date(2026, 12, 5),
        (("ROB-P100", "4", "0"), ("ASM-CTRL100", "2", "0")),
    ),
    SalesOrderDef(
        "SO-2026-000006",
        "CUST-005",
        "CONFIRMED",
        date(2026, 8, 12),
        date(2026, 11, 25),
        (("ROB-P200", "2", "0"),),
    ),
    SalesOrderDef(
        "SO-2026-000007",
        "CUST-006",
        "COMPLETED",
        date(2026, 7, 20),
        date(2026, 9, 30),
        (("ROB-P100", "3", "3"),),
    ),
    SalesOrderDef(
        "SO-2026-000008",
        "CUST-003",
        "OPEN",
        date(2026, 8, 15),
        date(2026, 12, 20),
        (("CON-C100", "3", "0"),),
    ),
    SalesOrderDef(
        "SO-2026-000009",
        "CUST-002",
        "PARTIALLY_DELIVERED",
        date(2026, 8, 18),
        date(2026, 11, 10),
        (("ROB-P200", "4", "2"),),
    ),
    SalesOrderDef(
        "SO-2026-000010",
        "CUST-004",
        "CONFIRMED",
        date(2026, 8, 20),
        date(2026, 12, 15),
        (("PAL-P300", "2", "0"),),
    ),
    SalesOrderDef(
        "SO-2026-000011",
        "CUST-005",
        "COMPLETED",
        date(2026, 7, 28),
        date(2026, 10, 10),
        (("ROB-P100", "5", "5"),),
    ),
    SalesOrderDef(
        "SO-2026-000012",
        "CUST-006",
        "OPEN",
        date(2026, 8, 22),
        date(2026, 12, 28),
        (("CON-C100", "1", "0"), ("ASM-CONV200", "4", "0")),
    ),
    SalesOrderDef(
        "SO-2026-000013",
        "CUST-001",
        "CONFIRMED",
        date(2026, 8, 25),
        date(2026, 11, 28),
        (("PAL-P300", "3", "0"),),
    ),
    SalesOrderDef(
        "SO-2026-000014",
        "CUST-003",
        "DRAFT",
        date(2026, 8, 28),
        date(2027, 1, 15),
        (("ROB-P200", "1", "0"),),
    ),
    SalesOrderDef(
        "SO-2026-000015",
        "CUST-004",
        "CANCELLED",
        date(2026, 7, 15),
        date(2026, 9, 15),
        (("ROB-P100", "2", "0"),),
    ),
)


# --------------------------------------------------------------------------
# Purchase orders (v0.4 sections 29 / 30)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PurchaseOrderLineDef:
    """One purchase order line; ``received`` may be partially received."""

    part_number: str
    revision_code: str
    ordered_qty: Decimal
    received_qty: Decimal
    unit_price: Decimal
    expected_date: date | None
    status: str


@dataclass(frozen=True)
class PurchaseOrderDef:
    """One purchase order at one supplier."""

    po_number: str
    supplier_code: str
    status: str
    order_date: date
    expected_date: date | None
    lines: tuple[PurchaseOrderLineDef, ...]


def _po_line(
    part_number: str,
    ordered_qty: str,
    received_qty: str,
    unit_price: str,
    expected_date: date | None,
    status: str,
) -> PurchaseOrderLineDef:
    return PurchaseOrderLineDef(
        part_number=part_number,
        revision_code=DEFAULT_REVISION_CODE,
        ordered_qty=Decimal(ordered_qty),
        received_qty=Decimal(received_qty),
        unit_price=Decimal(unit_price),
        expected_date=expected_date,
        status=status,
    )


PURCHASE_ORDERS: tuple[PurchaseOrderDef, ...] = (
    # Three unfinished orders still expecting BRG-6204-A (v0.4 section 76)
    PurchaseOrderDef(
        "PO-2026-000001",
        "SUP-001",
        "OPEN",
        date(2026, 8, 4),
        date(2026, 10, 15),
        (
            _po_line(
                "BRG-6204-A", "500", "0", "12.5000", date(2026, 10, 15), "OPEN"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000002",
        "SUP-004",
        "COMPLETED",
        date(2026, 7, 10),
        date(2026, 8, 10),
        (
            _po_line(
                "PLC-C100", "20", "20", "2450.0000", date(2026, 8, 10), "COMPLETED"
            ),
            _po_line(
                "SENSOR-S100",
                "400",
                "400",
                "78.0000",
                date(2026, 8, 10),
                "COMPLETED",
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000003",
        "SUP-003",
        "PARTIALLY_RECEIVED",
        date(2026, 8, 6),
        date(2026, 9, 20),
        (
            _po_line(
                "MOTOR-SM100",
                "60",
                "30",
                "1280.0000",
                date(2026, 9, 20),
                "PARTIALLY_RECEIVED",
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000004",
        "SUP-001",
        "PARTIALLY_RECEIVED",
        date(2026, 8, 8),
        date(2026, 10, 5),
        (
            _po_line(
                "BRG-6204-A",
                "300",
                "100",
                "12.5000",
                date(2026, 10, 5),
                "PARTIALLY_RECEIVED",
            ),
            _po_line(
                "SEAL-O100",
                "600",
                "600",
                "3.2000",
                date(2026, 9, 25),
                "COMPLETED",
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000005",
        "SUP-002",
        "COMPLETED",
        date(2026, 7, 18),
        date(2026, 8, 28),
        (
            _po_line(
                "GEAR-G100", "200", "200", "86.0000", date(2026, 8, 28), "COMPLETED"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000006",
        "SUP-005",
        "OPEN",
        date(2026, 8, 12),
        date(2026, 10, 20),
        (
            _po_line(
                "ROLLER-R100",
                "300",
                "0",
                "64.0000",
                date(2026, 10, 20),
                "OPEN",
            ),
            _po_line(
                "BELT-B100", "40", "0", "210.0000", date(2026, 10, 20), "OPEN"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000007",
        "SUP-001",
        "OPEN",
        date(2026, 8, 14),
        date(2026, 10, 25),
        (
            _po_line(
                "BRG-6204-A", "200", "0", "12.5000", date(2026, 10, 25), "OPEN"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000008",
        "SUP-004",
        "COMPLETED",
        date(2026, 7, 22),
        date(2026, 9, 1),
        (
            _po_line(
                "CABLE-C100", "800", "800", "36.0000", date(2026, 9, 1), "COMPLETED"
            ),
            _po_line(
                "CABLE-C200", "600", "600", "28.0000", date(2026, 9, 1), "COMPLETED"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000009",
        "SUP-002",
        "PARTIALLY_RECEIVED",
        date(2026, 8, 16),
        date(2026, 10, 10),
        (
            _po_line(
                "SHAFT-S100",
                "150",
                "80",
                "58.0000",
                date(2026, 10, 10),
                "PARTIALLY_RECEIVED",
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000010",
        "SUP-003",
        "COMPLETED",
        date(2026, 7, 25),
        date(2026, 9, 5),
        (
            _po_line(
                "ENCODER-E100",
                "100",
                "100",
                "420.0000",
                date(2026, 9, 5),
                "COMPLETED",
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000011",
        "SUP-004",
        "OPEN",
        date(2026, 8, 18),
        date(2026, 10, 30),
        (
            _po_line(
                "ENCLOSURE-EN100", "30", "0", "680.0000", date(2026, 10, 30), "OPEN"
            ),
            _po_line(
                "FILTER-FL100",
                "800",
                "0",
                "22.0000",
                date(2026, 10, 30),
                "OPEN",
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000012",
        "SUP-005",
        "COMPLETED",
        date(2026, 7, 30),
        date(2026, 9, 10),
        (
            _po_line(
                "GRIPPER-GR100", "10", "10", "1560.0000", date(2026, 9, 10), "COMPLETED"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000013",
        "SUP-001",
        "COMPLETED",
        date(2026, 7, 12),
        date(2026, 8, 15),
        (
            _po_line(
                "SEAL-O200", "500", "500", "4.1000", date(2026, 8, 15), "COMPLETED"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000014",
        "SUP-002",
        "OPEN",
        date(2026, 8, 20),
        date(2026, 11, 5),
        (
            _po_line(
                "GEAR-G200", "80", "0", "142.0000", date(2026, 11, 5), "OPEN"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000015",
        "SUP-003",
        "PARTIALLY_RECEIVED",
        date(2026, 8, 22),
        date(2026, 11, 1),
        (
            _po_line(
                "MOTOR-SM200",
                "12",
                "5",
                "3260.0000",
                date(2026, 11, 1),
                "PARTIALLY_RECEIVED",
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000016",
        "SUP-004",
        "BLOCKED",
        date(2026, 8, 24),
        date(2026, 11, 8),
        (
            _po_line(
                "PLC-C200", "8", "0", "4380.0000", date(2026, 11, 8), "OPEN"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000017",
        "SUP-005",
        "OPEN",
        date(2026, 8, 26),
        date(2026, 11, 12),
        (
            _po_line(
                "ROLLER-R200", "120", "0", "108.0000", date(2026, 11, 12), "OPEN"
            ),
            _po_line(
                "VALVE-V100", "200", "0", "96.0000", date(2026, 11, 12), "OPEN"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000018",
        "SUP-002",
        "COMPLETED",
        date(2026, 7, 28),
        date(2026, 9, 6),
        (
            _po_line(
                "SHAFT-S200", "60", "60", "96.0000", date(2026, 9, 6), "COMPLETED"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000019",
        "SUP-004",
        "COMPLETED",
        date(2026, 8, 1),
        date(2026, 9, 12),
        (
            _po_line(
                "SENSOR-S200", "300", "300", "112.0000", date(2026, 9, 12), "COMPLETED"
            ),
            _po_line(
                "FAN-FAN100", "400", "400", "46.0000", date(2026, 9, 12), "COMPLETED"
            ),
        ),
    ),
    PurchaseOrderDef(
        "PO-2026-000020",
        "SUP-005",
        "DRAFT",
        date(2026, 8, 30),
        date(2026, 11, 20),
        (
            _po_line(
                "SCREW-SC100", "6000", "0", "0.8000", date(2026, 11, 20), "OPEN"
            ),
            _po_line(
                "BELT-B200", "20", "0", "345.0000", date(2026, 11, 20), "OPEN"
            ),
        ),
    ),
)


# --------------------------------------------------------------------------
# Production orders (v0.4 section 31)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ProductionOrderDef:
    """One production order; requirements are frozen from ``product_part_number``."""

    order_number: str
    product_part_number: str
    product_revision: str
    planned_qty: Decimal
    completed_qty: Decimal
    planned_start: datetime
    planned_end: datetime
    status: str


def _production(
    order_number: str,
    product: str,
    planned_qty: str,
    completed_qty: str,
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    status: str,
) -> ProductionOrderDef:
    return ProductionOrderDef(
        order_number=order_number,
        product_part_number=product,
        product_revision=DEFAULT_REVISION_CODE,
        planned_qty=Decimal(planned_qty),
        completed_qty=Decimal(completed_qty),
        planned_start=datetime(*start, 8, 0, tzinfo=UTC),
        planned_end=datetime(*end, 17, 0, tzinfo=UTC),
        status=status,
    )


PRODUCTION_ORDERS: tuple[ProductionOrderDef, ...] = (
    _production(
        "MO-2026-000001", "ROB-P100", "10", "0", (2026, 9, 7), (2026, 9, 25), "RELEASED"
    ),
    _production(
        "MO-2026-000002",
        "ROB-P100",
        "8",
        "3",
        (2026, 8, 24),
        (2026, 9, 18),
        "IN_PROGRESS",
    ),
    _production(
        "MO-2026-000003",
        "ROB-P100",
        "6",
        "6",
        (2026, 7, 6),
        (2026, 7, 31),
        "COMPLETED",
    ),
    _production(
        "MO-2026-000004", "ROB-P200", "5", "0", (2026, 9, 14), (2026, 10, 9), "RELEASED"
    ),
    _production(
        "MO-2026-000005",
        "ROB-P200",
        "4",
        "1",
        (2026, 8, 31),
        (2026, 9, 28),
        "IN_PROGRESS",
    ),
    _production(
        "MO-2026-000006", "ROB-P100", "12", "0", (2026, 9, 21), (2026, 10, 16), "RELEASED"
    ),
    _production(
        "MO-2026-000007", "CON-C100", "3", "0", (2026, 9, 10), (2026, 10, 2), "RELEASED"
    ),
    _production(
        "MO-2026-000008",
        "CON-C100",
        "2",
        "1",
        (2026, 8, 27),
        (2026, 9, 22),
        "IN_PROGRESS",
    ),
    _production(
        "MO-2026-000009", "PAL-P300", "4", "0", (2026, 9, 17), (2026, 10, 13), "RELEASED"
    ),
    _production(
        "MO-2026-000010",
        "PAL-P300",
        "3",
        "1",
        (2026, 9, 3),
        (2026, 9, 30),
        "IN_PROGRESS",
    ),
    _production(
        "MO-2026-000011", "ROB-P200", "6", "0", (2026, 10, 5), (2026, 10, 30), "PLANNED"
    ),
    _production(
        "MO-2026-000012",
        "CON-C100",
        "4",
        "4",
        (2026, 7, 13),
        (2026, 8, 7),
        "COMPLETED",
    ),
    # Control group: these sub-assemblies do not contain BRG-6204-A.
    _production(
        "MO-2026-000013",
        "ASM-CTRL100",
        "20",
        "0",
        (2026, 9, 8),
        (2026, 9, 29),
        "RELEASED",
    ),
    _production(
        "MO-2026-000014",
        "ASM-CTRL200",
        "15",
        "4",
        (2026, 8, 25),
        (2026, 9, 19),
        "IN_PROGRESS",
    ),
    _production(
        "MO-2026-000015",
        "ASM-PAL200",
        "25",
        "0",
        (2026, 9, 15),
        (2026, 10, 6),
        "RELEASED",
    ),
)


#: Part numbers whose BOM does not contain BRG-6204-A (control group).
CONTROL_PART_NUMBERS: tuple[str, ...] = ("ASM-CTRL100", "ASM-CTRL200", "ASM-PAL200")

#: Production order states that already carry frozen material requirements.
#: ``PLANNED`` means the order is not released yet, so no BOM explosion has been
#: frozen for it (v0.4 section 64).
FROZEN_REQUIREMENT_STATUSES: tuple[str, ...] = (
    "RELEASED",
    "IN_PROGRESS",
    "COMPLETED",
)


def production_orders_with_frozen_requirements() -> tuple[ProductionOrderDef, ...]:
    """Return the orders that must have frozen material requirements."""
    return tuple(
        order
        for order in PRODUCTION_ORDERS
        if order.status in FROZEN_REQUIREMENT_STATUSES
    )


def production_orders_without_frozen_requirements() -> tuple[ProductionOrderDef, ...]:
    """Return the orders that must not have frozen material requirements."""
    return tuple(
        order
        for order in PRODUCTION_ORDERS
        if order.status not in FROZEN_REQUIREMENT_STATUSES
    )
