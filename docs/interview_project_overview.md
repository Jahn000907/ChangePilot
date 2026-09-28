# ChangePilot 面试项目速记

本页用于复习实际完成的 V2，不把规划中的功能说成已实现。架构细节见[技术说明](change_pilot_v2_architecture.md)。

## 一分钟项目介绍

“ChangePilot 是我做的制造业工程变更 Agent 应用。员工可以用自然语言查询 BOM、库存、采购、生产等企业事实；简单问题走只读 Tool，复杂跨域问题由 Supervisor 按需协调结构、供应、生产、交付四个领域 Agent。真正的 Supplier EOL 和物料替代变更则进入 LangGraph 流程：确定性影响分析、LLM 策略、Tool 辅助审查、人工审批，最后生成受控 ECO 和执行任务。PostgreSQL 存业务、会话、Trace 和持久化 Checkpoint，Neo4j 存产品结构。我还做了 pytest、本地 Benchmark 和 LangSmith 实验。当前执行只创建记录，不写回真实 ERP/BOM；真实模型调度仍有波动。”

## 为什么做这个项目？

我想从只检索文档的传统 RAG 转向有工具、有状态、有审批边界的 Agent Application。工程变更要跨产品结构、供应、库存、生产与交付，还要保留责任和审计，因此很适合把 Agent 的分析能力与确定性 Workflow 分开设计。

## 为什么 PostgreSQL + Neo4j？

PostgreSQL 适合订单、库存、ECM、审批、会话、审计这些需要约束和事务的记录，也承载 LangGraph Checkpoint。Neo4j 适合沿 BOM 层级追踪零件的 Where-Used 与替代关系。不是为了“双数据库”而双数据库：产品图查询与事务写入的形态不同；跨库没有分布式事务，图/ERP 查询保持只读，ECM 写入以 PostgreSQL 事务为边界。

## 为什么不是所有问题都用 Multi-Agent？

“某零件库存多少”是单事实查询，直接 Tool 更快、更可验证，也减少 LLM 调度误差。只有供应风险、停产影响这类需要跨领域证据的问题才交给 Supervisor。V2.8 真实 Case 曾因模型计划校验失败而未完成，说明按需调度是成本和稳定性的现实要求。

## 为什么 Supervisor + Domain Agents？

Supervisor 只规划与综合，Structure/Supply/Production/Delivery Agent 各自有 Tool 白名单和结构化证据。这样可以限制工具权限、看清每个领域查了什么，并把“已核验事实”和“未知项”留在输出里。它不是让四个 Agent 每次固定全上，也不能直接执行变更。

## Multi-Agent 和 Workflow 有什么区别？

Multi-Agent 是动态只读协作，解决“应查哪些领域、如何综合”；正式 Workflow 是状态明确、可恢复、可审批的业务流程，解决“何时持久化 Change Case、何时允许执行”。前者的结论不能替代 Impact、Review 或人工批准。

## 为什么 Human-in-the-loop 与持久 Checkpoint 重要？

工程变更可能影响采购、生产和客户承诺，LLM 无权批准。LangGraph 在 Human Approval 使用真正的 `interrupt`，APPROVE/REJECT 由人提交；PostgreSQL Checkpointer 让等待审批的线程在后端重启后仍可用原 `thread_id` 恢复，避免把审批状态绑在单个进程内存里。ECM 业务表仍是业务记录，Checkpoint 只管执行位置和状态。

## 如何减少幻觉？

企业事实须经只读 Tool；实体、版本与日期按确定性规则补全，不让模型猜；Tool 失败、无数据和参数不足分开处理。Assistant 对模型分析中的无证据编号/数值做拦截，Review Agent 可再次查询 Tool，正式执行还有人工审批。它们降低风险但不意味着“零幻觉”；真实模型的 Tool/Agent 计划仍要持续评测。

## 如何做 Evaluation？

pytest 断言库存、Tool、恢复、审批和幂等等确定性行为；本地 13 Case Benchmark 默认 Fake LLM、真实只读 Tool，逐 Case 记录工具与 Agent 选择、路由、事实支撑、建议、完成率和延迟；LangSmith 用于 Trace、Dataset、Experiment 与可选的主观 Judge。Judge 不判客观库存数字。当前 Fake 12/13、最近真实 DeepSeek 7/8，通过率与失败 Case 都应如实展示。

## 最大不足是什么？

目前 Dataset 小，不能外推到真实工厂；LLM 调度有随机性，综合停产/供应风险 Case 已出现部分完成或计划校验失败；没有 RBAC 和生产级部署；没有真实 ERP/PLM 写回，Execution 只创建受控记录；BOM Redline 只是准备任务，没有实际草案或图谱改写。下一步应先深入理解源码与失败路径，再扩数据集、加强调度和安全控制，而不是宣称已能全自动执行工程变更。
