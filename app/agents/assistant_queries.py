"""Deterministic entities and intent for employee read queries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.domain.dto.assistant import AssistantContext

ENTITY = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", re.IGNORECASE)
REVISION = re.compile(r"(?:版本|Revision|Rev)[：:\s]*([A-Z0-9]+)", re.IGNORECASE)
ISO_DATE = re.compile(r"(?<!\d)(\d{4}-\d{1,2}-\d{1,2})(?!\d)")
CN_DATE = re.compile(r"(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})日")
PRODUCT_PREFIXES = {"ASM", "CON", "PAL", "ROB"}
MATERIAL_PREFIXES = {
    "BELT", "BRG", "CABLE", "ENCLOSURE", "ENCODER", "FAN", "FILTER",
    "FRAME", "GEAR", "GRIPPER", "MOTOR", "PLC", "ROLLER", "SCREW",
    "SEAL", "SENSOR", "SHAFT", "VALVE",
}


@dataclass(frozen=True)
class QueryEntities:
    products: tuple[str, ...] = ()
    parts: tuple[str, ...] = ()
    supplier_code: str | None = None
    purchase_order: str | None = None
    production_order: str | None = None
    sales_order: str | None = None
    revision: str | None = None
    as_of_date: date | None = None


def extract_entities(question: str) -> QueryEntities:
    products: list[str] = []
    parts: list[str] = []
    supplier = purchase = production = sales = None
    for match in ENTITY.finditer(question.upper()):
        value = match.group()
        prefix = value.split("-", 1)[0]
        if prefix in PRODUCT_PREFIXES:
            products.append(value)
        elif prefix in MATERIAL_PREFIXES:
            parts.append(value)
        elif prefix == "SUP":
            supplier = value
        elif prefix == "PO":
            purchase = value
        elif prefix == "MO":
            production = value
        elif prefix == "SO":
            sales = value
    revision_match = REVISION.search(question)
    iso_match = ISO_DATE.search(question)
    cn_match = CN_DATE.search(question)
    business_date = None
    if iso_match:
        business_date = date.fromisoformat(iso_match.group(1))
    elif cn_match:
        business_date = date(*map(int, cn_match.groups()))
    return QueryEntities(
        products=tuple(dict.fromkeys(products)),
        parts=tuple(dict.fromkeys(parts)),
        supplier_code=supplier,
        purchase_order=purchase,
        production_order=production,
        sales_order=sales,
        revision=revision_match.group(1).upper() if revision_match else None,
        as_of_date=business_date,
    )


def clear_intent(question: str, entities: QueryEntities, context: AssistantContext) -> str | None:
    """Route only unmistakable single-fact questions; LLM handles the rest."""
    if any(word in question for word in ("综合分析", "供应风险", "无法供应", "结合库存", "结合采购")):
        return None
    if any(word in question for word in ("什么是", "通常", "一般", "改写", "翻译")) and not (
        entities.parts or entities.products or entities.supplier_code
        or entities.purchase_order or entities.production_order or entities.sales_order
    ) and not any(word in question for word in ("它", "这个产品", "这个零件", "其中")):
        return None
    if any(word in question for word in ("结合", "根据", "分析", "解释", "说明", "对比")) and any(
        word in question for word in ("库存", "采购", "替代料", "BOM", "Where-Used", "被哪些产品使用")
    ):
        return None
    if entities.purchase_order or (context.current_purchase_order and "采购订单" in question):
        return "get_purchase_order_records"
    if entities.production_order or (context.current_production_order and "生产订单" in question):
        return "get_production_order_records"
    if entities.sales_order or (context.current_sales_order and "销售订单" in question):
        return "get_sales_order_records"
    if (entities.supplier_code or context.current_supplier_code) and any(
        word in question for word in ("供应哪些零件", "供应的零件", "供应物料")
    ):
        return "get_supplier_parts"
    if entities.supplier_code and any(word in question for word in ("供应商", "是谁", "信息")):
        return "get_suppliers"
    if (entities.supplier_code or context.current_focus == "supplier") and "采购订单" in question:
        return "get_purchase_order_records"
    if (entities.parts or context.current_part) and "采购订单" in question:
        return "get_purchase_orders"
    if substitution_pair(question):
        return "get_alternatives"
    if (entities.parts or context.current_part) and any(
        word in question.upper() for word in ("停产", "EOL", "断供", "LAST TIME BUY")
    ):
        return "get_supplier_parts"
    if "替代料" in question and not any(word in question for word in ("评估", "切换", "替换为")):
        return "get_alternatives"
    if "已认证" in question and (entities.parts or context.current_part):
        return "get_alternatives"
    if "库存" in question and not any(word in question for word in ("影响", "评估")):
        return "get_inventory"
    if any(word in question for word in ("被哪些产品使用", "被哪些上级", "哪里使用", "Where-Used")):
        return "find_where_used"
    if (entities.products or context.current_product) and any(
        word in question for word in ("哪些零件", "哪些物料", "BOM", "组成")
    ):
        return "get_bom_structure"
    if "其中" in question and context.current_product and any(
        word in question for word in ("需要多少", "用量", "数量")
    ):
        return "get_bom_structure"
    return None


def substitution_pair(question: str) -> tuple[str, str] | None:
    """Return (original, candidate) only for unambiguous replacement phrasing."""
    part = r"([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)"
    patterns = (
        (rf"用\s*{part}\s*替代\s*{part}", True),
        (rf"将\s*{part}\s*替换为\s*{part}", False),
        (rf"把\s*{part}\s*替换成\s*{part}", False),
    )
    for pattern, candidate_first in patterns:
        match = re.search(pattern, question.upper())
        if match:
            first, second = match.groups()
            if first != second:
                return (second, first) if candidate_first else (first, second)
    return None
