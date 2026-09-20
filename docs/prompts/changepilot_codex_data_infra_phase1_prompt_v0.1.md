# ChangePilot 数据基础设施第一阶段 Codex 执行任务书 / Prompt

**文档版本：v0.1**  
**文档状态：ACTIVE EXECUTION PROMPT**  
**适用阶段：数据基础设施第一阶段**  
**执行主体：Codex**  
**设计与约束来源：ChangePilot v0.3 / v0.4 技术文档**  

---

# 1. 任务目的

本任务用于指导 Codex 在 ChangePilot 项目中完成第一阶段数据基础设施建设。

本阶段目标不是实现智能体，而是先建立一个：

> **能够独立启动、结构稳定、数据可验证、规则可测试的模拟制造企业数据环境。**

完成后，项目应具备：

```text
Docker Compose
↓
PostgreSQL
+
Neo4j
↓
PostgreSQL Migration
+
Neo4j Schema
↓
领域模型
↓
Golden Seed
↓
数据完整性检查
↓
自动测试
```

只有这一阶段通过验收后，后续才能继续开发：

```text
Domain Service
↓
Tool
↓
MCP
↓
LangGraph
↓
Agent
```

---

# 2. Codex 的角色

你是 ChangePilot 项目的**代码执行与落地工程师**。

你的职责是：

- 阅读现有项目设计文档；
- 根据设计创建代码；
- 创建配置文件；
- 创建数据库迁移；
- 创建 Neo4j Schema；
- 创建数据模型；
- 创建 Golden Seed；
- 创建一致性检查脚本；
- 编写自动测试；
- 修复你在执行过程中引入的问题；
- 更新必要的运行说明。

你不是：

- 产品经理；
- 架构设计决策者；
- 业务规则设计者。

如果实现中发现核心设计存在冲突：

> **不要自行改变业务模型。**

应停止相关实现，并在执行结果中明确报告冲突。

---

# 3. 必须优先阅读的项目文档

开始修改代码之前，必须先阅读：

```text
docs/DOCUMENT_VERSION_GUIDE.md
```

然后按以下顺序阅读：

```text
docs/changepilot_database_design_v0.4.md
```

```text
docs/changepilot_business_domain_bom_model_v0.3.md
```

历史文件：

```text
docs/archive/changepilot_overall_design_v0.1.md
docs/archive/changepilot_overall_design_v0.2.md
```

只用于理解项目演进。

**不得使用 v0.1 / v0.2 覆盖 v0.3 / v0.4 的当前设计。**

---

# 4. 文档优先级

发生冲突时：

```text
本次 Codex 执行任务书
>
v0.4 数据库详细设计
>
v0.3 业务领域与 BOM 模型
>
其他当前 ACTIVE 文档
>
archive 历史文档
```

如果两个 ACTIVE 文档出现无法自行解释的核心冲突：

```text
停止该部分实现
↓
记录问题
↓
等待 GPT 分析
↓
等待人确认
```

不要擅自选择其中一种设计。

---

# 5. 本阶段硬性禁止事项

本阶段**不要实现**：

```text
LangGraph
Agent
Multi-Agent
MCP Server
RAG
Embedding
Vector Database
Web Search
LLM API
Prompt
Chat UI
React Frontend
用户登录
权限管理 UI
真实 SAP 集成
真实 Teamcenter 集成
真实 MES 集成
MBOM
Routing
Quality NCR
Customer Change
复杂 Approval Workflow
```

也不要添加：

```text
pgvector
Milvus
Qdrant
Chroma
```

ChangePilot 第一阶段不是 RAG 项目。

---

# 6. 不得擅自改变的架构决策

以下内容已经冻结。

## D-01

产品结构使用：

```text
Neo4j
```

## D-02

企业事务、工程变更、Agent Trace、Audit 使用：

```text
PostgreSQL
```

## D-03

必须区分：

```text
Part
```

和：

```text
PartRevision
```

## D-04

BOM 必须采用：

```text
PartRevision
→ BOMVersion
→ BOMLine
→ PartRevision
```

## D-05

正式 BOM 不允许原地覆盖。

## D-06

工程变更通过新的 BOMVersion 表达。

## D-07

正式发布数据不允许被 Agent 或任意上层模块直接修改。

## D-08

后续所有正式写操作必须经过 Domain Service。

## D-09

具有副作用的写操作必须支持幂等。

## D-10

高风险正式写操作前必须存在人工审批。

## D-11

Neo4j 与 PostgreSQL 不实现虚假的跨数据库原子事务。

## D-12

跨数据库正式执行后续使用：

```text
execution_jobs
```

管理。

## D-13

正式写操作必须记录：

```text
audit.audit_events
```

## D-14

未来 Agent 不允许执行任意 SQL / Cypher。

## D-15

历史生产订单的物料需求以：

```text
erp.production_material_requirements
```

为事实。

## D-16

Benchmark Ground Truth 必须由确定性程序生成。

---

# 7. 技术基线

除非仓库已有明确技术选择，否则采用：

## Python

```text
Python 3.12+
```

## Web / Application Framework

本阶段可以创建 FastAPI 项目骨架，但：

> 不需要实现业务 API。

如果当前仓库尚未需要 FastAPI，可以只创建应用配置和数据库基础模块。

## PostgreSQL

目标：

```text
PostgreSQL 18
```

本地使用 PostgreSQL 17 也允许，只要当前 SQL 特性兼容。

## Neo4j

目标：

```text
Neo4j 2026.x Community Edition
```

不要使用只有 Enterprise Edition 才支持的 Schema Constraint。

## ORM

```text
SQLAlchemy 2.x
```

使用现代 typed declarative style。

## Migration

```text
Alembic
```

## Validation

```text
Pydantic v2
```

## PostgreSQL Driver

优先：

```text
psycopg 3
```

## Neo4j Driver

使用官方：

```text
neo4j
```

Python Driver。

## Testing

```text
pytest
```

---

# 8. 开发质量要求

所有代码必须：

- 有清晰模块边界；
- 有类型标注；
- 避免重复逻辑；
- 不在 Router / Script 中硬编码业务规则；
- 不让 ORM Model 承担所有业务逻辑；
- 不让数据库 Repository 承担领域决策；
- 不创建巨大单文件；
- 不将密码提交到仓库；
- 不把 LLM 或 Agent 作为任何数据库逻辑依赖。

优先保持：

> **简单、可读、可测试。**

不要为了展示架构能力过度设计。

---

# 9. 目标目录结构

如果仓库已有结构，优先在现有结构中合理合并。

如果仓库为空，可以建立：

```text
changepilot/
│
├── app/
│   ├── __init__.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   └── logging.py
│   │
│   ├── domain/
│   │   ├── enums.py
│   │   ├── errors.py
│   │   └── dto/
│   │
│   ├── db/
│   │   ├── postgres/
│   │   │   ├── base.py
│   │   │   ├── session.py
│   │   │   └── models/
│   │   │
│   │   └── neo4j/
│   │       ├── driver.py
│   │       └── schema.py
│   │
│   └── seed/
│       ├── golden/
│       └── generators/
│
├── alembic/
│
├── infra/
│   ├── neo4j/
│   │   └── schema.cypher
│   │
│   └── docker/
│
├── scripts/
│   ├── seed_golden_data.py
│   └── check_data_integrity.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── docs/
│   └── ...
│
├── alembic.ini
├── docker-compose.yml
├── .env.example
├── pyproject.toml
└── README.md
```

目录可以根据现有仓库调整，但职责边界必须保持清晰。

---

# 10. 阶段 0：仓库检查

开始写代码前：

1. 查看当前目录结构；
2. 查看现有 `pyproject.toml` / requirements；
3. 查看 Python 版本；
4. 查看是否已有 Docker Compose；
5. 查看是否已有 PostgreSQL / Neo4j 配置；
6. 查看是否已有 Alembic；
7. 查看测试结构；
8. 阅读 v0.3 / v0.4 文档。

输出一个简短内部实施计划，然后开始执行。

**不要因为已有部分代码就全部重写。**

优先：

> 增量修改。

---

# 11. 阶段 1：基础项目与环境配置

## 11.1 `.env.example`

至少包含：

```text
POSTGRES_HOST
POSTGRES_PORT
POSTGRES_DB
POSTGRES_USER
POSTGRES_PASSWORD

NEO4J_URI
NEO4J_USER
NEO4J_PASSWORD
NEO4J_DATABASE
```

可以额外加入：

```text
APP_ENV
LOG_LEVEL
```

不得：

- 写真实密码；
- 提交 `.env`。

确保 `.gitignore` 忽略：

```text
.env
```

---

## 11.2 配置模块

创建统一配置：

```text
app/core/config.py
```

使用：

```text
pydantic-settings
```

或现有等价方案。

业务代码不得到处直接调用：

```python
os.getenv(...)
```

所有环境配置通过统一 Settings 对象访问。

---

# 12. 阶段 2：Docker Compose

创建或更新：

```text
docker-compose.yml
```

至少包含：

```text
postgres
neo4j
```

## PostgreSQL

必须：

- 有持久化 volume；
- 有 healthcheck；
- 从环境变量读取密码；
- 暴露本地开发端口。

## Neo4j

必须：

- 使用 Community Edition；
- 有持久化 data volume；
- 有 healthcheck 或等价 readiness；
- 开放 Bolt / HTTP 所需端口；
- 从环境变量读取认证配置。

不要添加当前阶段不需要的：

```text
Redis
Kafka
MinIO
RabbitMQ
Elasticsearch
```

---

# 13. 阶段 3：PostgreSQL Schema

根据：

```text
docs/changepilot_database_design_v0.4.md
```

创建：

```text
erp
ecm
agent
audit
```

四个 PostgreSQL Schema。

必须由 Alembic Migration 创建。

不要依赖应用启动时：

```text
Base.metadata.create_all()
```

自动建立正式数据库。

---

# 14. 阶段 4：PostgreSQL ORM Model

按照 v0.4 创建至少以下模型。

## ERP Schema

```text
erp.suppliers
erp.supplier_parts
erp.inventory_balances

erp.purchase_orders
erp.purchase_order_lines

erp.production_orders
erp.production_material_requirements

erp.sales_orders
erp.sales_order_lines
```

## ECM Schema

```text
ecm.change_cases
ecm.engineering_change_requests
ecm.change_impacts
ecm.change_strategies
ecm.change_strategy_actions
ecm.change_reviews
ecm.engineering_change_orders
ecm.approval_records
ecm.bom_redlines
ecm.bom_redline_lines
ecm.execution_jobs
```

## Agent Schema

```text
agent.agent_runs
agent.agent_steps
agent.tool_calls
```

## Audit Schema

```text
audit.audit_events
```

字段类型、唯一约束、CHECK、FK、索引：

> 严格以 v0.4 为准。

不要因为实现方便删除字段。

如果发现数据库层无法正确表达某个约束：

- 不擅自删掉；
- 在领域层增加 Validator；
- 在执行报告中说明。

---

# 15. PostgreSQL Enum 策略

第一阶段不强制使用 PostgreSQL 原生 ENUM。

优先：

```text
varchar
+
Python Enum
+
CHECK Constraint
```

或者项目当前已有统一 Enum 策略。

目标：

- Migration 易维护；
- 业务值受控；
- 后续增加状态不至于过度困难。

所有枚举值必须集中定义。

建议：

```text
app/domain/enums.py
```

不得在多个文件重复声明：

```text
RELEASED
APPROVED
SUPPLIER_EOL
```

等字符串。

---

# 16. 阶段 5：PostgreSQL Migration

建立：

```text
Alembic
```

如果已有 Alembic，则在现有 Migration 体系中继续。

第一版 Migration 应能够从空数据库一次性：

```text
alembic upgrade head
```

创建全部：

```text
Schema
Table
Constraint
Index
```

并且：

```text
alembic downgrade base
```

至少在开发数据库能够正常回滚。

不要把 Seed Data 写入 Schema Migration。

Schema 与 Seed 必须分离。

---

# 17. 阶段 6：Neo4j 连接层

创建统一 Neo4j Driver 管理模块。

例如：

```text
app/db/neo4j/driver.py
```

要求：

- Driver 生命周期集中管理；
- 不在业务模块反复创建 Driver；
- 支持连接检测；
- 参数化查询；
- 不通过字符串拼接 Cypher。

---

# 18. 阶段 7：Neo4j Schema

创建：

```text
infra/neo4j/schema.cypher
```

包含 v0.4 中规定的：

## 唯一约束

### Part

```text
part_id
part_number
```

### PartRevision

```text
revision_id
(part_number, revision_code)
```

### BOMVersion

```text
bom_version_id
bom_code
(parent_part_number, parent_revision_code, bom_revision_code)
```

### BOMLine

```text
bom_line_id
```

以及必要普通索引。

禁止添加：

> 只有 Neo4j Enterprise 才能使用的约束。

---

# 19. Neo4j Schema 初始化脚本

提供 Python 或 Shell 入口用于执行：

```text
infra/neo4j/schema.cypher
```

例如：

```text
python scripts/init_neo4j_schema.py
```

要求：

- 可重复执行；
- 使用 `IF NOT EXISTS`；
- 已存在 Schema 时不失败。

---

# 20. 阶段 8：领域枚举

根据 v0.3 / v0.4 创建统一 Enum。

至少包括：

```text
PartType
MakeOrBuy
LifecycleState
BomStatus
QualificationStatus
SupplierStatus
SupplierPartStatus
PurchaseOrderStatus
ProductionOrderStatus
SalesOrderStatus
ChangeCaseType
ChangeCaseStatus
EcrStatus
Priority
ImpactObjectType
ImpactSeverity
StrategyType
StrategyStatus
ReviewDecision
EcoStatus
ApprovalDecision
RedlineStatus
RedlineActionType
ExecutionJobStatus
AgentRunStatus
ToolMode
ToolCallStatus
ActorType
```

代码 Enum 名称可使用英文。

用户显示文本不在本阶段实现。

---

# 21. 阶段 9：领域异常

创建统一领域异常：

```text
DomainValidationError
EntityNotFoundError
ConflictError
PermissionDeniedError
ApprovalRequiredError
IdempotencyConflictError
ExternalToolError
ExecutionFailedError
```

本阶段只建立类型。

暂不需要实现完整异常到 HTTP 的映射。

---

# 22. 阶段 10：Neo4j 基础 DTO

创建 Pydantic DTO。

至少：

```text
PartDTO
PartRevisionDTO
BOMVersionDTO
BOMLineDTO
AlternativePartDTO
```

DTO 与 Neo4j Driver 的底层 Record 解耦。

后续 Tool 不得直接返回：

```text
neo4j.Record
```

---

# 23. 阶段 11：Golden Seed

创建：

```text
scripts/seed_golden_data.py
```

或者等价入口。

Golden Seed 必须是：

> **可阅读、可重复、可验证的固定演示数据。**

不能全部通过无意义随机生成。

---

# 24. Golden Seed 企业基础数据

企业：

```text
智衡自动化设备有限公司
```

制造基地：

```text
CN-E01
```

仓库：

```text
WH-01
```

最终产品至少：

```text
ROB-P100
ROB-P200
CON-C100
PAL-P300
```

---

# 25. Golden Seed 产品结构

必须构造：

```text
BRG-6204-A
```

并满足：

- 被至少 2 个不同 Gearbox 使用；
- 间接影响 4 个最终产品；
- 至少存在一条 3 层以上 Where-Used 路径。

例如：

```text
BRG-6204-A
↑
ASM-GEARBOX100
↑
ASM-JOINT100
↑
ROB-P100
```

数据应与 v0.3 描述保持一致。

---

# 26. Golden Seed 替代件

必须存在：

```text
BRG-6204-B
```

状态：

```text
QUALIFIED
```

以及：

```text
BRG-6204-C
```

状态：

```text
UNQUALIFIED
```

两者至少在以下某些方面存在差异：

- 单价；
- 交期；
- 工程规格；
- 供应商。

目标是后续能够形成：

> 成本低但未认证

与：

> 成本稍高但已认证

的业务冲突。

---

# 27. Golden Seed 供应商

必须包含：

```text
SUP-001
MotionWorks
```

并让：

```text
BRG-6204-A
```

满足：

```text
status = LAST_TIME_BUY
last_time_buy_date = 2026-11-30
eol_date = 2027-01-31
```

注意：

当前日期不影响 Seed 中的业务案例日期。

Seed 数据用于固定演示与测试。

---

# 28. Golden Seed 业务事务

必须至少生成：

```text
20 个采购订单
15 个生产订单
15 个销售订单
```

其中与：

```text
BRG-6204-A
```

相关的业务事实至少包括：

```text
3 个未完成采购订单
7 个未完成生产订单
5 个相关销售订单
```

并存在：

```text
inventory_balances
```

记录。

事务数据必须与产品结构和生产物料需求逻辑一致。

---

# 29. Seed 数据可重复执行

`seed_golden_data.py` 必须支持重复运行。

推荐两种方式之一：

## 方式 A

开发环境明确：

```text
--reset
```

清空 Golden Seed 再重新生成。

## 方式 B

基于稳定业务键：

```text
upsert / idempotent insert
```

不要让第二次执行产生：

```text
ROB-P100
ROB-P100
```

两个重复产品。

---

# 30. Seed UUID 策略

为了方便自动测试，Golden Seed 推荐使用：

```text
固定 UUID
```

或由固定 namespace + 业务编号生成稳定 UUID。

不要每次随机产生完全不同 UUID，导致：

- 测试不稳定；
- 快照困难；
- 调试困难。

Benchmark Seed 后续另行设计。

---

# 31. 生产物料需求生成

生产订单对应的：

```text
production_material_requirements
```

不能独立随机生成。

必须根据：

```text
产品
+
产品版本
+
当时有效 BOM
+
生产数量
```

执行确定性 BOM Explosion。

例如：

```text
ROB-P100 × 10

ROB-P100
→ ASM-JOINT100 × 3

ASM-JOINT100
→ ASM-GEARBOX100 × 1

ASM-GEARBOX100
→ BRG-6204-A × 2
```

则理论需求：

```text
10 × 3 × 1 × 2 = 60
```

必须正确写入：

```text
production_material_requirements
```

---

# 32. BOM Explosion 实现要求

本阶段可以实现一个确定性基础服务：

```text
BomExplosionService
```

或等价模块。

职责：

```text
输入：
product_part_number
product_revision
quantity
effective_date

输出：
展开后的采购件 / 自制件需求
```

MVP 不需要做复杂：

- scrap planning；
- alternate selection；
- variant configuration。

但需要：

- 正确递归；
- 防止循环；
- 数量累乘；
- 使用正确有效 BOM。

---

# 33. 阶段 12：数据一致性检查

创建：

```text
scripts/check_data_integrity.py
```

执行后输出清晰结果。

至少检查：

## 跨数据库

1. PostgreSQL `part_number` 是否都存在于 Neo4j；
2. `revision_code` 是否存在；
3. SupplierPart 是否指向存在的 Part；
4. Redline 引用的 BOM 是否存在。

## Neo4j

5. BOM 是否存在循环；
6. PartRevision 是否正确归属于 Part；
7. BOMVersion 是否正确归属于 PartRevision；
8. BOMLine 是否只有一个组件；
9. RELEASED BOM 是否存在有效期非法重叠。

## PostgreSQL

10. `qty_reserved <= qty_on_hand`；
11. `received_qty <= ordered_qty`；
12. `completed_qty <= planned_qty`；
13. `issued_qty <= required_qty`；
14. 外键完整；
15. 关键业务编号唯一。

## Golden Seed

16. BRG-6204-A 是否影响 4 个最终产品；
17. 是否存在已认证和未认证替代件；
18. 是否存在规定数量的相关采购 / 生产 / 销售订单。

---

# 34. 数据一致性检查输出

成功：

```text
ChangePilot Data Integrity Check

[PASS] PostgreSQL references
[PASS] BOM cycle validation
[PASS] BOM effectivity
[PASS] Inventory constraints
[PASS] Production requirements
[PASS] CASE-EOL-001 golden scenario

RESULT: PASS
```

失败：

必须指出：

```text
检查项
对象
原因
```

并：

```text
exit code != 0
```

方便 CI 使用。

---

# 35. 阶段 13：基础数据库测试

使用：

```text
pytest
```

至少覆盖：

---

## 35.1 PostgreSQL Tests

### 唯一性

- supplier_code 唯一；
- po_number 唯一；
- order_number 唯一；
- case idempotency_key 唯一。

### 数量 CHECK

拒绝：

```text
qty_reserved > qty_on_hand
```

拒绝：

```text
received_qty > ordered_qty
```

拒绝：

```text
completed_qty > planned_qty
```

### FK

不存在 Supplier 时不能建立 Purchase Order。

---

## 35.2 Neo4j Tests

验证：

- `part_number` 唯一；
- `(part_number, revision_code)` 唯一；
- Where-Used 返回正确对象；
- BOM 展开正确；
- 多层 BOM 正确；
- 循环 BOM 被应用层拒绝。

---

## 35.3 Golden Seed Tests

必须验证：

```text
BRG-6204-A
```

可以反向找到：

```text
ROB-P100
ROB-P200
CON-C100
PAL-P300
```

至少四个最终产品。

同时验证：

```text
BRG-6204-B
```

为已认证替代件。

```text
BRG-6204-C
```

为未认证替代件。

---

# 36. 测试数据库原则

自动测试不得依赖开发数据库中已有的人工作业数据。

优先：

```text
Testcontainers
```

如果当前执行环境不适合 Testcontainers，可以使用：

- Docker Compose test profile；
- 独立测试数据库；
- pytest fixture 初始化。

但必须保证：

> 测试可重复。

不要要求测试必须按照固定人工操作顺序运行。

---

# 37. 阶段 14：README 更新

README 只补充本阶段真正实现的内容。

至少说明：

## 环境

```text
Python
Docker
PostgreSQL
Neo4j
```

## 启动

```bash
docker compose up -d
```

## Migration

```bash
alembic upgrade head
```

## 初始化 Neo4j Schema

提供真实命令。

## Golden Seed

```bash
python scripts/seed_golden_data.py
```

## 数据检查

```bash
python scripts/check_data_integrity.py
```

## 测试

```bash
pytest
```

不要在 README 中宣称：

```text
Agent 已实现
MCP 已实现
Multi-Agent 已实现
```

如果本阶段没有实现。

---

# 38. 建议依赖

根据实际需要最小化依赖。

可能包括：

```text
sqlalchemy
alembic
psycopg[binary]
neo4j
pydantic
pydantic-settings
pytest
```

如果使用：

```text
FastAPI
```

项目骨架，可加入：

```text
fastapi
uvicorn
```

但不要为了未来需求一次安装几十个 Agent / AI 包。

第一阶段不要加入：

```text
langchain
langgraph
openai
anthropic
mcp
```

---

# 39. Logging

建立基本日志配置。

脚本和应用使用：

```text
logging
```

不得大量使用：

```python
print()
```

但：

```text
scripts/check_data_integrity.py
```

最终面向人的 PASS / FAIL 汇总可以打印。

日志不得包含：

- PostgreSQL 密码；
- Neo4j 密码；
- 完整连接字符串中的敏感字段。

---

# 40. Repository / Service 实现边界

本阶段可以建立数据库访问基础 Repository。

但不要提前实现所有未来业务服务。

允许：

```text
PartRepository
BomRepository
SupplierRepository
InventoryRepository
OrderRepository
```

如果 Seed / Integrity Check 有实际需要。

允许最小：

```text
BomExplosionService
BomCycleValidator
```

因为 Seed 与一致性检查需要。

暂时不要实现：

```text
EngineeringChangePlanner
ReviewerAgent
ExecutionAgent
MCPToolRegistry
```

---

# 41. Agent 相关表虽然创建，但不实现 Agent

v0.4 已要求创建：

```text
agent.agent_runs
agent.agent_steps
agent.tool_calls
```

本阶段要：

> 创建表。

但不要：

> 编写 Agent。

这些表先作为未来运行基础设施。

---

# 42. Audit 表虽然创建，但暂不实现所有审计场景

创建：

```text
audit.audit_events
```

可以为 Seed / 数据初始化写最少必要的系统事件，也可以暂不写 Seed Audit。

关键是：

- 表结构存在；
- Repository/Model 正确；
- 后续可用。

不要为了测试 Audit 而提前实现完整工程变更执行流程。

---

# 43. 代码风格

如果项目已有：

```text
ruff
black
mypy
pyright
```

等配置，遵循现有配置。

如果没有：

优先增加：

```text
ruff
```

作为 lint / format 工具即可。

不要一次引入过多工具链。

所有新增代码执行至少：

```text
ruff check .
pytest
```

如果启用了 formatter：

```text
ruff format --check .
```

---

# 44. 本阶段最终验收命令

目标是让人在本地能够按照顺序执行：

```bash
docker compose up -d
```

确认：

```text
PostgreSQL healthy
Neo4j healthy
```

然后：

```bash
alembic upgrade head
```

成功。

然后：

```bash
python scripts/init_neo4j_schema.py
```

成功。

然后：

```bash
python scripts/seed_golden_data.py
```

成功。

然后：

```bash
python scripts/check_data_integrity.py
```

返回：

```text
RESULT: PASS
```

然后：

```bash
pytest
```

测试通过。

最后：

```bash
ruff check .
```

通过。

---

# 45. 完成定义

只有以下全部满足，本阶段才算完成。

## 基础设施

- [ ] PostgreSQL 可以启动
- [ ] Neo4j 可以启动
- [ ] 都具有持久化 Volume
- [ ] 都具有健康检查

## PostgreSQL

- [ ] 四个 Schema 已创建
- [ ] v0.4 所有 MVP 表已创建
- [ ] FK / UNIQUE / CHECK 正确
- [ ] 索引正确
- [ ] Alembic Migration 可用

## Neo4j

- [ ] 核心节点约束已创建
- [ ] 核心索引已创建
- [ ] schema 初始化可重复运行

## 领域模型

- [ ] Enum 集中定义
- [ ] DTO 存在
- [ ] 基础领域异常存在

## Seed

- [ ] 四个最终产品存在
- [ ] BRG-6204-A 多层共享
- [ ] 替代件 B / C 存在
- [ ] Supplier EOL 数据存在
- [ ] 采购 / 生产 / 销售数据存在
- [ ] 生产需求由 BOM 展开产生

## Integrity

- [ ] 跨库引用验证
- [ ] BOM DAG 验证
- [ ] 数量约束验证
- [ ] CASE-EOL-001 验证

## Test

- [ ] pytest 通过
- [ ] 核心数据库规则有测试
- [ ] Golden Seed 关键 Ground Truth 有测试

## 文档

- [ ] README 启动命令与代码一致
- [ ] `.env.example` 完整
- [ ] 无真实秘密信息提交

---

# 46. Codex 执行过程中的冲突处理

如果遇到：

> v0.4 中字段和实际 SQLAlchemy 不兼容

先寻找符合原意的实现方式。

不要直接删除字段。

如果遇到：

> Neo4j Community 不支持某约束

将该规则下沉到：

```text
Domain Validator
```

并测试。

如果遇到：

> 两个设计文档在核心业务上冲突

停止修改相关模块。

报告：

```text
冲突文档
冲突位置
你的理解
可能的方案
```

等待下一轮设计决策。

---

# 47. Codex 禁止自行做出的决定

以下问题不得自行扩展：

```text
是否增加 Redis
是否增加 Kafka
是否增加向量数据库
是否改用 MongoDB
是否去掉 Neo4j
是否把全部数据放 PostgreSQL
是否引入真实 Agent
是否引入 MCP
是否增加 MBOM
是否增加工艺路线
是否增加真实 SAP / Teamcenter
是否修改审批架构
```

如果觉得有必要：

> 在最终执行报告中提出建议。

不要直接实施。

---

# 48. Codex 可以自行决定的内容

在不改变设计语义的情况下，可以自行决定：

- Python 文件如何拆分；
- SQLAlchemy mixin；
- 测试 fixture 结构；
- helper 命名；
- Repository 具体实现方式；
- 日志封装方式；
- UUID helper；
- Seed helper；
- Docker volume 名；
- pyproject 依赖版本兼容细节；
- import 组织。

原则：

> 技术实现自由，领域模型不自由。

---

# 49. 执行报告格式

完成后不要只回复：

> Done.

必须提供：

## 1. 完成内容

列出真正实现的模块。

## 2. 新建 / 修改文件

例如：

```text
docker-compose.yml
app/core/config.py
...
```

## 3. 数据库实现

说明：

- PostgreSQL Schema；
- 表；
- Migration；
- Neo4j Constraint / Index。

## 4. Seed 数据

说明：

- 产品数量；
- BOM 规模；
- Supplier；
- CASE-EOL-001。

## 5. 自动测试

列出执行的命令与结果。

## 6. 数据完整性检查

给出 PASS / FAIL。

## 7. 已知问题

必须明确写：

```text
None
```

或者具体问题。

## 8. 与设计文档存在的差异

如果完全一致：

```text
None
```

如果做了任何合理技术调整：

明确说明。

## 9. 后续建议

只提出建议。

不要继续实现下一阶段。

---

# 50. 本阶段结束后必须停止

完成：

```text
Data Infrastructure Phase 1
```

以后：

> **停止开发。**

不要主动继续：

```text
MCP
Agent
LangGraph
Frontend
```

等待 GPT 与人进行阶段验收，并生成下一阶段 Codex Prompt。

---

# 51. 给 Codex 的直接执行提示词

下面内容可以直接作为 Codex 的主提示词使用。

---

## Codex Prompt

你现在负责 ChangePilot 项目的“数据基础设施第一阶段”。

在修改任何代码之前，请先阅读：

1. `docs/DOCUMENT_VERSION_GUIDE.md`
2. `docs/changepilot_database_design_v0.4.md`
3. `docs/changepilot_business_domain_bom_model_v0.3.md`

其中 v0.4 是数据库实现的主要技术基线，v0.3 是业务领域和 BOM 模型基线。`docs/archive/` 下的 v0.1、v0.2 只用于了解历史，不得覆盖当前设计。

你的目标是建立一个可独立运行、可验证、可测试的模拟制造企业数据环境。第一阶段只实现数据基础设施，不实现 Agent、LangGraph、MCP、RAG、前端或真实企业系统集成。

请按本任务书逐阶段完成：

1. 检查现有仓库，优先增量修改，不要无理由重写。
2. 建立统一 `.env.example` 和应用配置。
3. 建立 PostgreSQL + Neo4j Community 的 Docker Compose。
4. 使用 SQLAlchemy 2.x + Alembic 创建 v0.4 要求的 `erp / ecm / agent / audit` PostgreSQL Schema、表、约束、索引和外键。
5. 建立 Neo4j Driver 和 `infra/neo4j/schema.cypher`，实现 v0.4 定义的 Part / PartRevision / BOMVersion / BOMLine 约束与索引。
6. 创建集中式领域 Enum、基础领域异常和 Neo4j DTO。
7. 创建固定、可重复执行的 Golden Seed，包含 ROB-P100、ROB-P200、CON-C100、PAL-P300，以及共享零件 BRG-6204-A。
8. BRG-6204-A 必须被至少两个不同 Gearbox 使用、间接影响四个最终产品，并至少存在一条 3 层以上 Where-Used 路径。
9. 创建已认证替代件 BRG-6204-B 和未认证替代件 BRG-6204-C。
10. 创建 SUP-001 / MotionWorks 的 Supplier EOL 场景，BRG-6204-A 的最后采购日期为 2026-11-30，停产日期为 2027-01-31。
11. Golden Seed 至少包含 20 个采购订单、15 个生产订单、15 个销售订单；其中 BRG-6204-A 至少关联 3 个未完成采购订单、7 个未完成生产订单和 5 个相关销售订单。
12. 生产订单的 `production_material_requirements` 必须由当时有效 BOM 进行确定性 BOM Explosion 生成，不能独立随机生成。
13. 建立 `scripts/check_data_integrity.py`，检查跨库引用、BOM DAG、BOM Effectivity、库存和订单数量约束以及 CASE-EOL-001。
14. 编写 pytest，覆盖 PostgreSQL 核心约束、Neo4j 多层 BOM / Where-Used、循环检测、Golden Seed Ground Truth。
15. 更新 README，确保启动、Migration、Neo4j Schema、Seed、Integrity Check、pytest 命令与实际代码一致。
16. 执行测试与静态检查，修复你引入的问题。

必须遵守以下硬性规则：

- 产品结构只放 Neo4j。
- 企业事务、工程变更、Agent Trace 和 Audit 放 PostgreSQL。
- Part 和 PartRevision 分离。
- BOM 使用 `PartRevision → BOMVersion → BOMLine → PartRevision`。
- 正式 BOM 不原地覆盖。
- Agent 层未来不能直接访问数据库。
- 不实现任意 SQL/Cypher Agent 工具。
- 不使用 Neo4j Enterprise-only 约束。
- 不添加向量数据库。
- 不添加 Redis/Kafka 等无关基础设施。
- 不实现 Agent、LangGraph、MCP 或前端。
- 不修改 v0.3 / v0.4 的核心领域设计。
- 如果核心文档发生冲突，停止相关部分并报告，不得自行改变架构。
- 不要使用 LLM 生成 Ground Truth。
- 数据库密码不得提交到仓库。

本阶段期望最终可以由人执行：

```bash
docker compose up -d
alembic upgrade head
python scripts/init_neo4j_schema.py
python scripts/seed_golden_data.py
python scripts/check_data_integrity.py
pytest
ruff check .
```

其中数据完整性检查必须最终输出：

```text
RESULT: PASS
```

完成本阶段后请停止，不要继续实现 Agent / MCP / LangGraph。

最终请按照任务书“执行报告格式”汇报：
完成内容、修改文件、数据库实现、Seed、测试结果、完整性检查、已知问题、与设计差异和后续建议。

---

# 52. 人工验收说明

Codex 完成以后，人负责：

1. 安装 Docker；
2. 准备 Python 环境；
3. 填写本地 `.env`；
4. 启动 Docker Compose；
5. 执行 Migration；
6. 执行 Seed；
7. 执行 Integrity Check；
8. 执行 pytest；
9. 打开 Neo4j Browser 简单查看产品关系；
10. 检查 PostgreSQL 数据是否存在。

如果出现环境问题：

> 人负责环境修复。

如果出现代码问题：

> 交 Codex 修复。

如果出现设计问题：

> GPT 分析 → 人确认 → 更新文档 → Codex 修改。

---

# 53. GPT / Codex / 人协作边界

本阶段遵循：

## GPT

负责：

- 架构；
- 业务规则；
- 数据模型；
- 技术约束；
- 任务拆解；
- Codex Prompt；
- 设计冲突分析。

## Codex

负责：

- 实际文件创建；
- 实际代码编写；
- Migration；
- Seed；
- Test；
- Bug Fix；
- README 落地。

## 人

负责：

- 环境安装；
- Docker 启动；
- 命令执行；
- 人工验收；
- 关键设计确认。

---

# 54. 文档状态

本任务书在第一阶段数据基础设施开发期间状态为：

```text
ACTIVE EXECUTION PROMPT
```

当第一阶段验收通过后：

```text
ARCHIVED AS COMPLETED
```

下一阶段重新生成新的 Codex 执行任务书。

不要不断修改同一个 Prompt 来覆盖历史开发过程。

每个阶段保留独立版本，形成项目开发轨迹。
