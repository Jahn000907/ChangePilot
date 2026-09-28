"""Read-only, deterministic evidence gathering for material substitution."""

from __future__ import annotations

from app.domain.dto.material_substitution import (
    MaterialSubstitutionImpact,
    MaterialSubstitutionInput,
)
from app.services.product_structure import ProductStructureService
from app.tools.erp_facts import get_inventory, get_production_requirements, get_purchase_orders
from app.tools.product_structure import find_where_used, get_alternatives
from app.tools.schemas import (
    FindWhereUsedInput,
    GetAlternativesInput,
    GetInventoryInput,
    GetProductionRequirementsInput,
    GetPurchaseOrdersInput,
)


class MaterialSubstitutionService:
    """Collect facts through existing read Tools; never ask an LLM to classify them."""

    def __init__(self, product_structure: ProductStructureService | None = None) -> None:
        self._structure = product_structure or ProductStructureService()

    def analyze(self, event: MaterialSubstitutionInput) -> MaterialSubstitutionImpact:
        candidate_revision = event.candidate_revision_code
        if candidate_revision is None:
            revisions = self._structure.list_revision_codes(event.candidate_part_number)
            if len(revisions) != 1:
                raise ValueError("候选替代料版本不明确，请指定 candidate_revision_code")
            candidate_revision = revisions[0]
        original = (event.part_number, event.revision_code)
        candidate = (event.candidate_part_number, candidate_revision)
        original_where = find_where_used(FindWhereUsedInput(
            part_number=original[0], revision_code=original[1], as_of_date=event.as_of_date
        ))
        candidate_where = find_where_used(FindWhereUsedInput(
            part_number=candidate[0], revision_code=candidate[1], as_of_date=event.as_of_date
        ))
        alternatives = get_alternatives(GetAlternativesInput(
            part_number=original[0], revision_code=original[1]
        ))
        match = next((row for row in alternatives.rows if (
            row.alternative_part_number, row.alternative_revision_code
        ) == candidate), None)
        original_inventory = get_inventory(GetInventoryInput(part_number=original[0], revision_code=original[1]))
        candidate_inventory = get_inventory(GetInventoryInput(part_number=candidate[0], revision_code=candidate[1]))
        original_purchase = get_purchase_orders(GetPurchaseOrdersInput(part_number=original[0], revision_code=original[1]))
        candidate_purchase = get_purchase_orders(GetPurchaseOrdersInput(part_number=candidate[0], revision_code=candidate[1]))
        original_production = get_production_requirements(GetProductionRequirementsInput(part_number=original[0], revision_code=original[1]))
        candidate_production = get_production_requirements(GetProductionRequirementsInput(part_number=candidate[0], revision_code=candidate[1]))
        return MaterialSubstitutionImpact(
            part_number=original[0], revision_code=original[1],
            candidate_part_number=candidate[0], candidate_revision_code=candidate[1],
            as_of_date=event.as_of_date,
            qualification_status=str(match.qualification_status) if match else "NOT_LISTED",
            replacement_type=str(match.replacement_type) if match else None,
            original_where_used=original_where, candidate_where_used=candidate_where,
            original_inventory=original_inventory, candidate_inventory=candidate_inventory,
            original_purchase=original_purchase, candidate_purchase=candidate_purchase,
            original_production=original_production, candidate_production=candidate_production,
            affected_products=original_where.products,
            caveats=[
                "资格状态来自现有替代关系；未列出的候选料不可直接认定为已认证。",
                "库存、采购与冻结生产需求是独立事实，不代表可直接切换 BOM。",
                "批准仅创建受控执行记录，不自动修改 ERP 或 Neo4j BOM。",
            ],
        )
