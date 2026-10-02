# ChangePilot V2.8 Assistant Benchmark

模式：real；Case：8；通过：7；失败：1

| 指标 | 得分 |
| --- | ---: |
| tool_selection_accuracy | 0.938 |
| agent_selection_precision | 1.000 |
| agent_selection_recall | 0.938 |
| agent_selection_exact | 0.875 |
| supervisor_routing_accuracy | 1.000 |
| fact_grounding_rate | 0.975 |
| unsupported_fact_rate | 0.025 |
| workflow_suggestion_accuracy | 1.000 |
| task_completion_rate | 0.875 |
| average_latency_ms | 1300.8 |

| Case | 结果 | 问题 |
| --- | --- | --- |
| general_bom | PASS |  |
| general_eco | PASS |  |
| inventory | PASS |  |
| alternatives | PASS |  |
| where_used | PASS |  |
| bom | PASS |  |
| purchase | PASS |  |
| supply_risk | FAIL | 缺少 Tool: find_where_used；误调用 Tool: get_supplier_parts；缺少 Agent: StructureAgent；无证据事实: 1000；无证据事实: 3；无证据事实: 900；任务未完成: SUCCESS |
