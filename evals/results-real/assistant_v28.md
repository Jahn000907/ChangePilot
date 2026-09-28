# ChangePilot V2.8 Assistant Benchmark

模式：real；Case：8；通过：7；失败：1

| 指标 | 得分 |
| --- | ---: |
| tool_selection_accuracy | 0.875 |
| agent_selection_precision | 0.875 |
| agent_selection_recall | 0.875 |
| agent_selection_exact | 0.875 |
| supervisor_routing_accuracy | 1.000 |
| fact_grounding_rate | 1.000 |
| unsupported_fact_rate | 0.000 |
| workflow_suggestion_accuracy | 1.000 |
| task_completion_rate | 0.875 |
| average_latency_ms | 907.5 |

| Case | 结果 | 问题 |
| --- | --- | --- |
| general_bom | PASS |  |
| general_eco | PASS |  |
| inventory | PASS |  |
| alternatives | PASS |  |
| where_used | PASS |  |
| bom | PASS |  |
| purchase | PASS |  |
| supply_risk | FAIL | 缺少 Tool: find_where_used；缺少 Tool: get_inventory；缺少 Tool: get_purchase_orders；缺少 Agent: StructureAgent；缺少 Agent: SupplyAgent；任务未完成: LLM_ERROR |
