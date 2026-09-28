# ChangePilot V2.8 Assistant Benchmark

模式：fake；Case：13；通过：12；失败：1

| 指标 | 得分 |
| --- | ---: |
| tool_selection_accuracy | 1.000 |
| agent_selection_precision | 1.000 |
| agent_selection_recall | 1.000 |
| agent_selection_exact | 1.000 |
| supervisor_routing_accuracy | 1.000 |
| fact_grounding_rate | 1.000 |
| unsupported_fact_rate | 0.000 |
| workflow_suggestion_accuracy | 1.000 |
| task_completion_rate | 0.923 |
| average_latency_ms | 73.9 |

| Case | 结果 | 问题 |
| --- | --- | --- |
| general_bom | PASS |  |
| general_eco | PASS |  |
| inventory | PASS |  |
| alternatives | PASS |  |
| where_used | PASS |  |
| bom | PASS |  |
| purchase | PASS |  |
| supply_risk | PASS |  |
| eol_impact | FAIL | 任务未完成: TOOL_ERROR |
| eol_suggestion | PASS |  |
| substitution_suggestion | PASS |  |
| no_data | PASS |  |
| tool_failure | PASS |  |
