"""LangChain adapters for the existing read-only application tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from app.tools.enterprise import (
    AffectedProductsQuery,
    OrderQuery,
    PartQuery,
    PartRevisionQuery,
    PurchaseQuery,
    SupplierPartsQuery,
    SupplierQuery,
    get_part_revisions,
    get_production_order_records,
    get_production_orders_for_part,
    get_purchase_order_records,
    get_sales_order_records,
    get_sales_orders_for_products,
    get_supplier_parts,
    get_suppliers,
)
from app.tools.erp_facts import get_inventory, get_production_requirements, get_purchase_orders
from app.tools.product_structure import (
    find_where_used,
    get_alternatives,
    get_bom_structure,
)
from app.tools.schemas import (
    FindWhereUsedInput,
    GetAlternativesInput,
    GetBOMStructureInput,
    GetInventoryInput,
    GetProductionRequirementsInput,
    GetPurchaseOrdersInput,
)


def _application_tool_adapter(
    input_model: type[BaseModel],
    application_tool: Callable[[Any], BaseModel],
) -> Callable[..., str]:
    """Validate LangChain arguments and serialize an application Tool result."""

    def invoke(**kwargs: object) -> str:
        request = input_model.model_validate(kwargs)
        result = application_tool(request)
        return result.model_dump_json()

    return invoke


def get_review_tools() -> list[BaseTool]:
    """Build the bounded read-only Tool set available to the Review Agent."""
    return [
        StructuredTool.from_function(
            func=_application_tool_adapter(FindWhereUsedInput, find_where_used),
            name="find_where_used",
            description=(
                "查询本企业指定零件版本被哪些真实产品/上级组件使用（Where-Used）。"
                "问‘BRG-6204-A 被哪些产品使用’必须调用；解释 Where-Used 概念无需调用。"
            ),
            args_schema=FindWhereUsedInput,
        ),
        StructuredTool.from_function(
            func=_application_tool_adapter(GetInventoryInput, get_inventory),
            name="get_inventory",
            description=("查询本企业指定零件版本的真实库存、预留和可用量。"
                         "问‘BRG-6204-A 当前库存多少’必须调用；解释安全库存概念无需调用。"),
            args_schema=GetInventoryInput,
        ),
        StructuredTool.from_function(
            func=_application_tool_adapter(GetPurchaseOrdersInput, get_purchase_orders),
            name="get_purchase_orders",
            description=("查询本企业指定零件版本关联的采购订单，可筛选未完成订单。"
                         "问某零件有哪些未完成采购订单必须调用；解释采购流程无需调用。"),
            args_schema=GetPurchaseOrdersInput,
        ),
        StructuredTool.from_function(
            func=_application_tool_adapter(GetAlternativesInput, get_alternatives),
            name="get_alternatives",
            description=(
                "查询本企业指定零件版本的替代料关系及认证资格。"
                "问某零件有哪些替代料或哪种已认证必须调用；解释替代料概念无需调用。"
            ),
            args_schema=GetAlternativesInput,
        ),
        StructuredTool.from_function(
            func=_application_tool_adapter(GetBOMStructureInput, get_bom_structure),
            name="get_bom_structure",
            description=("查询本企业指定产品/组件版本在业务日期有效的 BOM 零件和每件用量。"
                         "问‘ROB-P100 需要哪些零件’必须调用；解释什么是 BOM 无需调用。"),
            args_schema=GetBOMStructureInput,
        ),
    ]


def get_enterprise_tools() -> list[BaseTool]:
    """Employee assistant allowlist; every adapter delegates to an application Tool."""
    from pydantic import TypeAdapter

    def adapter(schema: type[BaseModel], application_tool: Callable[..., Any]) -> Callable[..., str]:
        def invoke(**kwargs: object) -> str:
            result = application_tool(schema.model_validate(kwargs))
            return TypeAdapter(Any).dump_json(result).decode("utf-8")
        return invoke

    additions = [
        ("get_suppliers", SupplierQuery, get_suppliers, "查询本企业供应商真实资料；问 SUP-001 是哪家或供应商状态必须调用，解释供应商概念无需调用。"),
        ("get_supplier_parts", SupplierPartsQuery, get_supplier_parts, "查询本企业供应商供应哪些零件、某零件由谁供应及资格状态；问 SUP-001 供应哪些零件必须调用，解释供应关系无需调用。"),
        ("get_part_revisions", PartRevisionQuery, get_part_revisions, "查询本企业零件/产品在当前或指定业务日期有效的版本；需要确定真实版本时必须调用，不得猜测；解释版本概念无需调用。"),
        ("get_purchase_order_records", PurchaseQuery, get_purchase_order_records, "查询本企业采购订单列表、未完成订单或指定 PO 详情；问 PO 编号或供应商未完成订单必须调用，解释采购订单概念无需调用。"),
        ("get_production_order_records", OrderQuery, get_production_order_records, "查询本企业生产订单列表、指定 MO 详情及物料需求；问真实生产订单必须调用，解释生产订单概念无需调用。"),
        ("get_production_orders_for_part", PartQuery, get_production_orders_for_part, "查询本企业某零件关联的生产订单及物料需求；问某零件关联哪些生产订单必须调用，解释生产排程无需调用。"),
        ("get_sales_order_records", OrderQuery, get_sales_order_records, "查询本企业销售订单列表或指定 SO 详情；问真实销售订单必须调用，解释销售订单概念无需调用。"),
        ("get_sales_orders_for_products", AffectedProductsQuery, get_sales_orders_for_products,
         "查询本企业已核验受影响成品版本对应的销售订单行；分析零件停产交付影响时必须先核验 Where-Used，不能查询全公司订单替代；解释销售概念无需调用。"),
    ]
    return get_review_tools() + [
        StructuredTool.from_function(
            func=_application_tool_adapter(GetProductionRequirementsInput, get_production_requirements),
            name="get_production_requirements",
            description=("查询本企业指定零件版本关联的生产订单及冻结物料需求。"
                         "问某零件的实际生产需求必须调用；解释需求计划概念无需调用。"),
            args_schema=GetProductionRequirementsInput,
        ),
    ] + [
        StructuredTool.from_function(func=adapter(schema, tool), name=name,
                                     description=description, args_schema=schema)
        for name, schema, tool, description in additions
    ]
