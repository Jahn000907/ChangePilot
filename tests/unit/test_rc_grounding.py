"""Grounded analysis may reason qualitatively without fabricating facts."""

from app.agents.enterprise_assistant import EnterpriseAssistant, ToolFact
from app.core.business_display import business_value


def test_grounded_analysis_accepts_qualitative_reasoning_only() -> None:
    facts = [ToolFact("get_inventory", {"part_number": "BRG-6204-A"}, {
        "rows": [{"part_number": "BRG-6204-A", "qty_on_hand": "700"}],
    })]
    question = "分析 BRG-6204-A 的库存风险"
    assert EnterpriseAssistant._grounded_analysis(
        "当前库存提供一定短期缓冲，但后续补货连续性仍需核验。", facts, question,
    )
    assert not EnterpriseAssistant._grounded_analysis(
        "库存只剩 70，PO-FAKE-99 已确认延期。", facts, question,
    )
    assert not EnterpriseAssistant._grounded_analysis("库存70。", facts, question)
    assert EnterpriseAssistant._grounded_analysis(
        "已核验可用量 650，仍需核验后续补货。", facts, question,
        "根据已查库存记录计算的可用量 650。",
    )
    assert not EnterpriseAssistant._grounded_analysis(
        "已核验可用量 600。", facts, question,
        "根据已查库存记录计算的可用量 650。",
    )


def test_business_statuses_are_chinese_in_assistant_output() -> None:
    assert business_value("PARTIALLY_RECEIVED") == "部分收货"
    assert business_value("BLOCKED") == "已冻结"
    fact = ToolFact("get_purchase_orders", {"part_number": "PART-X"}, {
        "rows": [{"po_number": "PO-X", "po_status": "PARTIALLY_RECEIVED",
                  "supplier_name": "供应商", "ordered_qty": "6.0000", "received_qty": "2.0000"}],
    })
    text = EnterpriseAssistant._format_fact(fact)
    assert "部分收货" in text and "PARTIALLY_RECEIVED" not in text
    assert "6.0000" not in text and "6" in text
