# ChangePilot —— Neo4j + PostgreSQL 数据库详细设计

**文档版本：v0.4**  
**项目：ChangePilot——制造业工程变更影响分析与执行智能体平台**  
**当前阶段：数据库详细设计 / 数据约束冻结**  
**目标：作为后续 Codex 创建数据库、迁移脚本、领域模型与合成数据生成器时的强约束文档**

---

## 1. 文档目标

本文件将 v0.3 中的业务领域模型进一步转换为可实现的数据库设计，明确：

1. Neo4j 中存储哪些产品结构对象；
2. PostgreSQL 中存储哪些企业事务、工程变更和 Agent 运行数据；
3. 每个对象的字段、类型、约束和索引；
4. 两个数据库之间如何建立稳定引用；
5. 工程变更过程中如何保证版本、生效性、审批、审计与幂等；
6. 后续 Codex 编码时哪些规则不得自行修改。

本文档冻结之后，如果需要修改核心数据模型，应先修改本文档，再修改代码。

---

# 2. 总体数据架构

ChangePilot 将数据划分为三类。

## 2.1 产品结构事实

回答：

- 某零件是什么；
- 某零件有哪些版本；
- 某产品使用哪个 BOM；
- 某 BOM 包含哪些组件；
- 某零件被哪些组件、产品使用；
- 某零件有哪些候选替代零件。

由：

**Neo4j**

负责。

---

## 2.2 企业事务事实

回答：

- 当前库存是多少；
- 哪些采购订单尚未完成；
- 哪些生产订单仍需旧零件；
- 哪些销售订单可能受到影响；
- 哪个供应商正在供货；
- 工程变更处于什么状态；
- 谁进行了审批。

由：

**PostgreSQL**

负责。

---

## 2.3 智能体运行与治理事实

回答：

- 哪次 Agent 工作流处理了某个案例；
- 哪个智能体调用了哪个工具；
- 工具参数是什么；
- 执行耗时和 Token 使用量是多少；
- 哪些正式数据发生过修改；
- 修改前后分别是什么状态。

同样由：

**PostgreSQL**

负责。

---

# 3. 数据库职责边界

## 3.1 Neo4j

Neo4j 是产品结构关系的主要数据源。

存储：

- `Part`
- `PartRevision`
- `BOMVersion`
- `BOMLine`
- 零件版本之间的替代关系

不存储：

- 库存余额
- 采购订单
- 生产订单
- 销售订单
- 审批记录
- Agent Trace
- Audit Log

---

## 3.2 PostgreSQL

PostgreSQL 是企业事务、工程变更、Agent 运行及审计数据的数据源。

不复制完整 BOM 结构。

PostgreSQL 中引用产品结构对象时，只保存稳定业务标识，例如：

```text
part_number
revision_code
bom_version_id
bom_line_id
```

其中 Neo4j UUID 使用字符串形式写入 PostgreSQL 时，字段类型统一使用 `uuid`；业务编号继续使用字符串。

---

# 4. 数据库版本与兼容原则

## 4.1 PostgreSQL

目标：

```text
PostgreSQL 18
```

允许本地开发时使用 PostgreSQL 17，只要本项目实际使用的 SQL 特性兼容。

---

## 4.2 Neo4j

目标：

```text
Neo4j 2026.x
```

MVP 必须兼容 Neo4j Community Edition。

因此第一版：

- 使用唯一约束；
- 使用普通范围索引；
- 不强依赖 Enterprise Edition 才提供的属性存在约束、类型约束和节点键约束；
- 必填字段和复杂业务规则由 Python 领域服务负责校验。

---

# 5. 通用命名规范

## 5.1 PostgreSQL

表名、字段名：

```text
snake_case
```

例如：

```text
engineering_change_requests
production_material_requirements
created_at
```

PostgreSQL Schema：

```text
erp
ecm
agent
audit
```

---

## 5.2 Neo4j

节点 Label：

```text
PascalCase
```

例如：

```text
Part
PartRevision
BOMVersion
BOMLine
```

关系名称：

```text
UPPER_SNAKE_CASE
```

例如：

```text
HAS_REVISION
HAS_BOM
HAS_LINE
COMPONENT
ALTERNATIVE_TO
```

---

## 5.3 枚举值

数据库中统一：

```text
UPPER_SNAKE_CASE
```

例如：

```text
RELEASED
IN_PROGRESS
SUPPLIER_EOL
```

前端负责将其显示为中文。

---

# 6. ID 与业务编号规范

所有数据库实体同时区分：

1. 内部 ID；
2. 业务编号。

## 6.1 内部 ID

统一：

```text
UUID
```

MVP 使用 UUID v4。

例如：

```text
part_id
revision_id
po_id
eco_id
```

由应用层生成。

---

## 6.2 业务编号

用于用户识别。

例如：

```text
BRG-6204-A
PO-2026-000001
ECR-2026-000001
ECO-2026-000001
```

业务编号不得作为数据库主键。

---

# 7. 时间规范

所有带时区的时间：

```text
timestamptz
```

数据库统一保存 UTC。

前端根据用户时区转换显示。

只表示自然日期、不表示具体时刻的字段使用：

```text
date
```

例如：

```text
eol_date
effective_from
expected_date
```

禁止使用无时区：

```text
timestamp without time zone
```

作为业务事件时间。

---

# 8. 数值规范

数量：

```text
numeric(18, 4)
```

金额：

```text
numeric(18, 4)
```

比例：

```text
numeric(9, 6)
```

货币：

```text
char(3)
```

例如：

```text
CNY
USD
EUR
```

禁止使用 `float` 保存：

- 金额；
- 库存；
- BOM 数量；
- 单价。

---

# 9. JSON 使用原则

`jsonb` 只用于：

- Agent Tool 参数；
- Tool 返回摘要；
- 原始事件；
- 结构化证据；
- Before / After 审计快照；
- 不稳定的扩展元数据。

不得使用 JSONB 代替正常关系建模。

错误示例：

```text
purchase_order jsonb
```

正确方式：

```text
purchase_orders
purchase_order_lines
```

---

# 10. Neo4j 总体图模型

核心结构：

```text
Part
 │
 │ HAS_REVISION
 ▼
PartRevision
 │
 │ HAS_BOM
 ▼
BOMVersion
 │
 │ HAS_LINE
 ▼
BOMLine
 │
 │ COMPONENT
 ▼
PartRevision
```

递归以后形成：

```text
最终产品
  ↓
系统
  ↓
组件
  ↓
子组件
  ↓
采购零件
```

---

# 11. Neo4j：Part 节点

表示：

**零件或产品的稳定身份。**

Label：

```text
Part
```

## 11.1 属性

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `part_id` | String(UUID) | 是 | 内部唯一 ID |
| `part_number` | String | 是 | 全局业务编号 |
| `name` | String | 是 | 中文名称 |
| `part_type` | String | 是 | 零件类型 |
| `category` | String | 是 | 分类 |
| `make_or_buy` | String | 是 | 自制/采购 |
| `base_unit` | String | 是 | 基础单位 |
| `created_at` | DateTime | 是 | 创建时间 |

## 11.2 part_type

第一版允许：

```text
FINISHED_PRODUCT
ASSEMBLY
PURCHASED_PART
MANUFACTURED_PART
```

## 11.3 make_or_buy

允许：

```text
MAKE
BUY
```

## 11.4 约束

```cypher
CREATE CONSTRAINT part_id_unique IF NOT EXISTS
FOR (p:Part)
REQUIRE p.part_id IS UNIQUE;
```

```cypher
CREATE CONSTRAINT part_number_unique IF NOT EXISTS
FOR (p:Part)
REQUIRE p.part_number IS UNIQUE;
```

不重复为 `part_id` 和 `part_number` 创建相同范围索引。

---

# 12. Neo4j：PartRevision 节点

表示：

**某个 Part 的具体工程版本。**

Label：

```text
PartRevision
```

## 12.1 属性

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `revision_id` | String(UUID) | 是 | 内部唯一 ID |
| `part_number` | String | 是 | 冗余业务编号，方便查询 |
| `revision_code` | String | 是 | 版本代码 |
| `lifecycle_state` | String | 是 | 生命周期状态 |
| `effective_from` | Date | 否 | 生效日期 |
| `effective_to` | Date | 否 | 失效日期 |
| `specification_json` | String | 否 | JSON 字符串形式工程规格 |
| `created_by` | String | 是 | 创建人 |
| `created_at` | DateTime | 是 | 创建时间 |
| `released_at` | DateTime | 否 | 发布时间 |

## 12.2 生命周期状态

```text
DRAFT
IN_REVIEW
RELEASED
OBSOLETE
```

## 12.3 唯一规则

业务唯一键：

```text
(part_number, revision_code)
```

约束：

```cypher
CREATE CONSTRAINT part_revision_id_unique IF NOT EXISTS
FOR (r:PartRevision)
REQUIRE r.revision_id IS UNIQUE;
```

```cypher
CREATE CONSTRAINT part_revision_business_key_unique IF NOT EXISTS
FOR (r:PartRevision)
REQUIRE (r.part_number, r.revision_code) IS UNIQUE;
```

## 12.4 生命周期规则

### PR-01

`RELEASED` 后不能直接修改关键工程属性。

需要修改时必须：

- 创建新的 `PartRevision`；
- 或通过新的 `BOMVersion` 修改结构。

### PR-02

如果：

```text
effective_from IS NOT NULL
effective_to IS NOT NULL
```

必须满足：

```text
effective_from <= effective_to
```

该规则由 Python 领域服务验证。

---

# 13. Part 与 PartRevision 关系

关系：

```text
HAS_REVISION
```

结构：

```text
(:Part)-[:HAS_REVISION]->(:PartRevision)
```

规则：

1. 一个 Part 可以拥有多个 PartRevision；
2. 一个 PartRevision 必须只属于一个 Part；
3. `Part.part_number` 必须与 `PartRevision.part_number` 一致。

Neo4j Community 无法依赖数据库约束完整表达这些规则，因此由领域服务校验。

---

# 14. Neo4j：BOMVersion 节点

表示：

**某个 PartRevision 的一个物料清单版本。**

Label：

```text
BOMVersion
```

## 14.1 属性

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `bom_version_id` | String(UUID) | 是 | 内部 ID |
| `bom_code` | String | 是 | BOM 业务编号 |
| `parent_part_number` | String | 是 | 父件编号 |
| `parent_revision_code` | String | 是 | 父件版本 |
| `bom_revision_code` | String | 是 | BOM 版本 |
| `status` | String | 是 | 状态 |
| `source_bom_version_id` | String(UUID) | 否 | 来源 BOM |
| `effective_from` | Date | 否 | 生效日期 |
| `effective_to` | Date | 否 | 失效日期 |
| `change_case_id` | String(UUID) | 否 | 来源工程变更案例 |
| `created_at` | DateTime | 是 | 创建时间 |
| `released_at` | DateTime | 否 | 发布时间 |

## 14.2 状态

```text
DRAFT
IN_REVIEW
RELEASED
OBSOLETE
```

## 14.3 约束

```cypher
CREATE CONSTRAINT bom_version_id_unique IF NOT EXISTS
FOR (b:BOMVersion)
REQUIRE b.bom_version_id IS UNIQUE;
```

```cypher
CREATE CONSTRAINT bom_code_unique IF NOT EXISTS
FOR (b:BOMVersion)
REQUIRE b.bom_code IS UNIQUE;
```

业务组合必须唯一：

```text
(parent_part_number, parent_revision_code, bom_revision_code)
```

```cypher
CREATE CONSTRAINT bom_version_business_key_unique IF NOT EXISTS
FOR (b:BOMVersion)
REQUIRE (
  b.parent_part_number,
  b.parent_revision_code,
  b.bom_revision_code
) IS UNIQUE;
```

---

# 15. PartRevision 与 BOMVersion

关系：

```text
HAS_BOM
```

```text
(:PartRevision)-[:HAS_BOM]->(:BOMVersion)
```

规则：

### BOM-01

一个 BOMVersion 只能属于一个父 PartRevision。

### BOM-02

一个 PartRevision 可以拥有多个历史 BOMVersion。

### BOM-03

同一 PartRevision 在任意自然日期上最多只能存在一个：

```text
status = RELEASED
```

且处于有效期内的 BOMVersion。

### BOM-04

正式生产只允许读取：

```text
RELEASED
```

版本。

### BOM-05

`DRAFT` BOMVersion 不进入正式生产需求计算。

### BOM-06

同一 BOM 血缘中有效日期不得非法重叠。

该规则无法仅靠普通唯一约束实现，由 `BomVersionService` 校验。

---

# 16. Neo4j：BOMLine 节点

表示：

**BOM 中的一条物料明细。**

Label：

```text
BOMLine
```

## 16.1 属性

| 属性 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `bom_line_id` | String(UUID) | 是 | 内部 ID |
| `line_number` | Integer | 是 | 行号 |
| `quantity` | Float | 是 | Neo4j 内图展示用数量 |
| `unit` | String | 是 | 单位 |
| `scrap_rate` | Float | 是 | 损耗率 |
| `is_optional` | Boolean | 是 | 是否可选件 |
| `plant_code` | String | 否 | 工厂代码 |
| `effective_from` | Date | 否 | 行级生效日期 |
| `effective_to` | Date | 否 | 行级失效日期 |
| `change_number` | String | 否 | 来源工程变更编号 |

说明：

Neo4j 数字属性使用其原生数值类型。正式数量计算时，应由应用层转换为 `Decimal`，禁止直接使用二进制浮点结果进行金额或正式物料需求结算。

## 16.2 约束

```cypher
CREATE CONSTRAINT bom_line_id_unique IF NOT EXISTS
FOR (l:BOMLine)
REQUIRE l.bom_line_id IS UNIQUE;
```

同一个 BOMVersion 下：

```text
line_number
```

必须唯一。

由于该唯一性跨越 `BOMVersion -> BOMLine` 关系，第一版由领域服务负责检查。

## 16.3 数量约束

```text
quantity > 0
```

```text
0 <= scrap_rate < 1
```

由领域服务校验。

---

# 17. BOMVersion 与 BOMLine

关系：

```text
HAS_LINE
```

```text
(:BOMVersion)-[:HAS_LINE]->(:BOMLine)
```

规则：

- 一个 BOMLine 只能属于一个 BOMVersion；
- 一个 BOMVersion 可以包含多个 BOMLine；
- 删除正式 BOMLine 不执行物理删除，而通过新的 BOMVersion 表达。

---

# 18. BOMLine 与组件 PartRevision

关系：

```text
COMPONENT
```

```text
(:BOMLine)-[:COMPONENT]->(:PartRevision)
```

规则：

- 每条 BOMLine 必须连接一个且仅一个 PartRevision；
- 被引用组件必须存在；
- RELEASED BOM 所引用的组件版本原则上应为已发布版本；
- DRAFT BOM 允许暂时引用 IN_REVIEW 版本，但正式 Release 前必须完成校验。

---

# 19. BOM 无环约束

BOM 不允许出现：

```text
A → B → C → A
```

即正式 BOM 必须构成：

**有向无环图（DAG）**。

Neo4j Schema Constraint 无法直接表达全图无环。

因此新增或替换 BOMLine 前：

```text
parent_revision
child_revision
```

必须执行循环检测。

逻辑：

> 如果 child_revision 当前已经能够通过 BOM 展开到达 parent_revision，则禁止建立 parent → child。

领域服务：

```text
BomCycleValidator
```

必须在所有正式 BOM 写操作前执行。

Seed Data Generator 同样必须保证 DAG。

---

# 20. BOM 行生效日期规则

MVP 的主要生效控制位于：

```text
BOMVersion
```

BOMLine 的：

```text
effective_from
effective_to
```

第一版允许为空。

为空时表示：

> 继承 BOMVersion 的有效期。

第一版不主动创建大量行级 Effectivity，仅为后续扩展保留字段。

---

# 21. 替代零件关系

关系：

```text
ALTERNATIVE_TO
```

结构：

```text
(:PartRevision)-[:ALTERNATIVE_TO]->(:PartRevision)
```

关系属性：

| 属性 | 类型 | 说明 |
|---|---|---|
| `alternative_id` | String(UUID) | 替代关系 ID |
| `qualification_status` | String | 认证状态 |
| `replacement_type` | String | 替代类型 |
| `verified_at` | DateTime | 认证时间 |
| `verified_by` | String | 认证人 |

认证状态：

```text
QUALIFIED
CONDITIONAL
UNQUALIFIED
```

替代类型：

```text
DIRECT
CONDITIONAL
TEMPORARY
```

MVP 中：

只有：

```text
QUALIFIED
```

可以被 Planner 自动作为正式候选方案。

`CONDITIONAL` 必须进入人工审核。

`UNQUALIFIED` 不允许进入正式执行方案。

---

# 22. Neo4j 索引设计

唯一约束已经自带用于唯一性检查的索引，因此禁止重复建立相同索引。

额外建立：

```cypher
CREATE INDEX part_category_idx IF NOT EXISTS
FOR (p:Part)
ON (p.category);
```

```cypher
CREATE INDEX part_type_idx IF NOT EXISTS
FOR (p:Part)
ON (p.part_type);
```

```cypher
CREATE INDEX part_revision_state_idx IF NOT EXISTS
FOR (r:PartRevision)
ON (r.lifecycle_state);
```

```cypher
CREATE INDEX bom_version_status_idx IF NOT EXISTS
FOR (b:BOMVersion)
ON (b.status);
```

MVP 暂不创建大量全文、向量或关系属性索引。

索引必须由真实 Query Profile 决定，禁止为了“看起来完整”而无节制增加。

---

# 23. Neo4j 查询边界

Agent 不直接生成任意 Cypher 并连接数据库执行。

所有图查询通过受控 Tool：

```text
get_part
get_part_revision
get_bom
get_bom_subgraph
where_used
get_alternatives
```

进行。

原因：

1. 限制查询范围；
2. 避免 Agent 执行写 Cypher；
3. 方便记录审计；
4. 方便评测工具选择；
5. 方便未来将 Neo4j 替换成真正 PLM 接口。

---

# 24. PostgreSQL Schema 划分

PostgreSQL 使用：

```text
erp
ecm
agent
audit
```

四个逻辑 Schema。

职责：

```text
erp
企业事务
```

```text
ecm
工程变更管理
```

```text
agent
Agent 工作流运行信息
```

```text
audit
不可变审计事件
```

LangGraph Checkpoint 使用独立运行时表，不与上述领域表混用。

---

# 25. PostgreSQL 通用字段规则

所有主要表至少拥有：

```text
created_at timestamptz NOT NULL
```

需要业务更新的表增加：

```text
updated_at timestamptz NOT NULL
```

不允许依赖应用代码手工填写时间。

迁移中统一设置：

```sql
DEFAULT now()
```

---

# 26. ERP：suppliers

表：

```text
erp.suppliers
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `supplier_id` | uuid | PK |
| `supplier_code` | varchar(32) | UNIQUE NOT NULL |
| `supplier_name` | varchar(200) | NOT NULL |
| `status` | varchar(20) | NOT NULL |
| `quality_rating` | numeric(5,2) | NOT NULL |
| `delivery_rating` | numeric(5,2) | NOT NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

status：

```text
ACTIVE
BLOCKED
PHASE_OUT
```

CHECK：

```text
0 <= quality_rating <= 100
0 <= delivery_rating <= 100
```

索引：

```text
supplier_code UNIQUE
status
```

---

# 27. ERP：supplier_parts

表：

```text
erp.supplier_parts
```

表示供应商与零件的供货关系。

| 字段 | 类型 | 约束 |
|---|---|---|
| `supplier_part_id` | uuid | PK |
| `supplier_id` | uuid | FK → suppliers |
| `part_number` | varchar(64) | NOT NULL |
| `revision_code` | varchar(16) | NULL |
| `manufacturer_part_number` | varchar(100) | NOT NULL |
| `qualification_status` | varchar(20) | NOT NULL |
| `unit_price` | numeric(18,4) | NOT NULL |
| `currency` | char(3) | NOT NULL |
| `lead_time_days` | integer | NOT NULL |
| `minimum_order_qty` | numeric(18,4) | NOT NULL |
| `last_time_buy_date` | date | NULL |
| `eol_date` | date | NULL |
| `status` | varchar(20) | NOT NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

qualification_status：

```text
QUALIFIED
CONDITIONAL
UNQUALIFIED
```

status：

```text
ACTIVE
LAST_TIME_BUY
EOL
BLOCKED
```

约束：

```text
unit_price >= 0
lead_time_days >= 0
minimum_order_qty > 0
```

日期：

如果两个日期均存在：

```text
last_time_buy_date <= eol_date
```

唯一：

```text
(supplier_id, manufacturer_part_number)
```

索引：

```text
part_number
(part_number, qualification_status)
supplier_id
eol_date
```

---

# 28. ERP：inventory_balances

表：

```text
erp.inventory_balances
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `inventory_id` | uuid | PK |
| `plant_code` | varchar(20) | NOT NULL |
| `warehouse_code` | varchar(20) | NOT NULL |
| `part_number` | varchar(64) | NOT NULL |
| `revision_code` | varchar(16) | NOT NULL |
| `qty_on_hand` | numeric(18,4) | NOT NULL |
| `qty_reserved` | numeric(18,4) | NOT NULL |
| `unit_cost` | numeric(18,4) | NOT NULL |
| `currency` | char(3) | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

不单独保存：

```text
qty_available
```

避免冗余不一致。

由查询计算：

```text
qty_available = qty_on_hand - qty_reserved
```

约束：

```text
qty_on_hand >= 0
qty_reserved >= 0
qty_reserved <= qty_on_hand
unit_cost >= 0
```

唯一：

```text
(plant_code, warehouse_code, part_number, revision_code)
```

索引：

```text
part_number
(part_number, revision_code)
plant_code
```

---

# 29. ERP：purchase_orders

表：

```text
erp.purchase_orders
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `po_id` | uuid | PK |
| `po_number` | varchar(40) | UNIQUE NOT NULL |
| `supplier_id` | uuid | FK |
| `status` | varchar(30) | NOT NULL |
| `order_date` | date | NOT NULL |
| `expected_date` | date | NULL |
| `currency` | char(3) | NOT NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

状态：

```text
DRAFT
OPEN
PARTIALLY_RECEIVED
COMPLETED
CANCELLED
BLOCKED
```

索引：

```text
supplier_id
status
expected_date
```

---

# 30. ERP：purchase_order_lines

表：

```text
erp.purchase_order_lines
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `po_line_id` | uuid | PK |
| `po_id` | uuid | FK |
| `line_number` | integer | NOT NULL |
| `part_number` | varchar(64) | NOT NULL |
| `revision_code` | varchar(16) | NOT NULL |
| `ordered_qty` | numeric(18,4) | NOT NULL |
| `received_qty` | numeric(18,4) | NOT NULL |
| `unit_price` | numeric(18,4) | NOT NULL |
| `expected_date` | date | NULL |
| `status` | varchar(30) | NOT NULL |
| `created_at` | timestamptz | NOT NULL |

约束：

```text
line_number > 0
ordered_qty > 0
received_qty >= 0
received_qty <= ordered_qty
unit_price >= 0
```

唯一：

```text
(po_id, line_number)
```

索引：

```text
part_number
(part_number, revision_code)
status
expected_date
```

---

# 31. ERP：production_orders

表：

```text
erp.production_orders
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `production_order_id` | uuid | PK |
| `order_number` | varchar(40) | UNIQUE NOT NULL |
| `product_part_number` | varchar(64) | NOT NULL |
| `product_revision` | varchar(16) | NOT NULL |
| `planned_qty` | numeric(18,4) | NOT NULL |
| `completed_qty` | numeric(18,4) | NOT NULL |
| `planned_start` | timestamptz | NOT NULL |
| `planned_end` | timestamptz | NOT NULL |
| `status` | varchar(30) | NOT NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

状态：

```text
PLANNED
RELEASED
IN_PROGRESS
COMPLETED
BLOCKED
CANCELLED
```

约束：

```text
planned_qty > 0
completed_qty >= 0
completed_qty <= planned_qty
planned_start <= planned_end
```

索引：

```text
(product_part_number, product_revision)
status
planned_start
planned_end
```

---

# 32. ERP：production_material_requirements

表：

```text
erp.production_material_requirements
```

表示生产订单已经展开后的物料需求。

| 字段 | 类型 | 约束 |
|---|---|---|
| `requirement_id` | uuid | PK |
| `production_order_id` | uuid | FK |
| `line_number` | integer | NOT NULL |
| `part_number` | varchar(64) | NOT NULL |
| `revision_code` | varchar(16) | NOT NULL |
| `required_qty` | numeric(18,4) | NOT NULL |
| `reserved_qty` | numeric(18,4) | NOT NULL |
| `issued_qty` | numeric(18,4) | NOT NULL |
| `created_at` | timestamptz | NOT NULL |

约束：

```text
line_number > 0
required_qty > 0
reserved_qty >= 0
issued_qty >= 0
reserved_qty <= required_qty
issued_qty <= required_qty
```

唯一：

```text
(production_order_id, line_number)
```

索引：

```text
(part_number, revision_code)
production_order_id
```

工程变更分析：

**以该表为准判断已释放生产订单是否真正需要旧零件。**

不得让 Agent 根据当前 BOM 反推历史已释放订单需求。

---

# 33. ERP：sales_orders

表：

```text
erp.sales_orders
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `sales_order_id` | uuid | PK |
| `order_number` | varchar(40) | UNIQUE NOT NULL |
| `customer_code` | varchar(40) | NOT NULL |
| `status` | varchar(30) | NOT NULL |
| `order_date` | date | NOT NULL |
| `requested_delivery_date` | date | NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

状态：

```text
DRAFT
OPEN
CONFIRMED
PARTIALLY_DELIVERED
COMPLETED
CANCELLED
```

索引：

```text
customer_code
status
requested_delivery_date
```

---

# 34. ERP：sales_order_lines

表：

```text
erp.sales_order_lines
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `sales_order_line_id` | uuid | PK |
| `sales_order_id` | uuid | FK |
| `line_number` | integer | NOT NULL |
| `product_part_number` | varchar(64) | NOT NULL |
| `product_revision` | varchar(16) | NOT NULL |
| `ordered_qty` | numeric(18,4) | NOT NULL |
| `delivered_qty` | numeric(18,4) | NOT NULL |
| `requested_delivery_date` | date | NULL |
| `created_at` | timestamptz | NOT NULL |

约束：

```text
line_number > 0
ordered_qty > 0
delivered_qty >= 0
delivered_qty <= ordered_qty
```

唯一：

```text
(sales_order_id, line_number)
```

索引：

```text
(product_part_number, product_revision)
requested_delivery_date
```

---

# 35. 工程变更平台技术案例：change_cases

表：

```text
ecm.change_cases
```

这是 ChangePilot 自己的技术案例容器。

它不是 ECR，而是：

> 一次从原始业务事件到最终关闭的 Agent 工作流实例。

| 字段 | 类型 | 约束 |
|---|---|---|
| `case_id` | uuid | PK |
| `case_number` | varchar(40) | UNIQUE NOT NULL |
| `case_type` | varchar(40) | NOT NULL |
| `status` | varchar(30) | NOT NULL |
| `source_type` | varchar(30) | NOT NULL |
| `raw_event` | jsonb | NOT NULL |
| `idempotency_key` | varchar(100) | UNIQUE NOT NULL |
| `created_by` | varchar(100) | NOT NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |
| `closed_at` | timestamptz | NULL |

case_type：

```text
SUPPLIER_EOL
QUALITY_ISSUE
CUSTOMER_CHANGE
COST_REDUCTION
REGULATORY_CHANGE
```

MVP 实际启用：

```text
SUPPLIER_EOL
```

status：

```text
RECEIVED
ANALYZING
PLANNING
WAITING_APPROVAL
APPROVED
EXECUTING
COMPLETED
REJECTED
FAILED
CANCELLED
```

`idempotency_key` 用于防止同一上游事件重复创建案例。

索引：

```text
status
case_type
created_at
```

---

# 36. 工程变更申请：engineering_change_requests

表：

```text
ecm.engineering_change_requests
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `ecr_id` | uuid | PK |
| `ecr_number` | varchar(40) | UNIQUE NOT NULL |
| `case_id` | uuid | FK UNIQUE NOT NULL |
| `change_type` | varchar(40) | NOT NULL |
| `source_type` | varchar(30) | NOT NULL |
| `subject_part_number` | varchar(64) | NOT NULL |
| `subject_revision_code` | varchar(16) | NULL |
| `title` | varchar(300) | NOT NULL |
| `description` | text | NOT NULL |
| `priority` | varchar(20) | NOT NULL |
| `status` | varchar(30) | NOT NULL |
| `requested_by` | varchar(100) | NOT NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

priority：

```text
LOW
MEDIUM
HIGH
CRITICAL
```

status：

```text
DRAFT
OPEN
ANALYZING
PLANNING
WAITING_APPROVAL
APPROVED
REJECTED
CLOSED
```

索引：

```text
subject_part_number
status
priority
created_at
```

---

# 37. 影响分析：change_impacts

表：

```text
ecm.change_impacts
```

用于保存一次影响分析发现的具体对象。

| 字段 | 类型 | 约束 |
|---|---|---|
| `impact_id` | uuid | PK |
| `ecr_id` | uuid | FK NOT NULL |
| `analysis_run_id` | uuid | NOT NULL |
| `object_type` | varchar(40) | NOT NULL |
| `object_key` | varchar(150) | NOT NULL |
| `impact_type` | varchar(40) | NOT NULL |
| `severity` | varchar(20) | NOT NULL |
| `reason` | text | NOT NULL |
| `evidence` | jsonb | NOT NULL |
| `created_at` | timestamptz | NOT NULL |

object_type：

```text
PART
PART_REVISION
ASSEMBLY
PRODUCT
BOM_VERSION
INVENTORY
PURCHASE_ORDER
PRODUCTION_ORDER
SALES_ORDER
```

severity：

```text
INFO
LOW
MEDIUM
HIGH
CRITICAL
```

同一次分析中避免重复：

```text
UNIQUE(
  analysis_run_id,
  object_type,
  object_key,
  impact_type
)
```

索引：

```text
ecr_id
analysis_run_id
(object_type, object_key)
severity
```

注意：

重新执行影响分析时：

- 不覆盖旧结果；
- 创建新的 `analysis_run_id`；
- 前端默认展示最新成功运行；
- 历史结果保留用于审计和 Eval。

---

# 38. 候选变更方案：change_strategies

表：

```text
ecm.change_strategies
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `strategy_id` | uuid | PK |
| `ecr_id` | uuid | FK NOT NULL |
| `strategy_code` | varchar(30) | NOT NULL |
| `strategy_type` | varchar(40) | NOT NULL |
| `title` | varchar(200) | NOT NULL |
| `summary` | text | NOT NULL |
| `effective_from` | date | NULL |
| `replacement_part_number` | varchar(64) | NULL |
| `replacement_revision_code` | varchar(16) | NULL |
| `risk_level` | varchar(20) | NOT NULL |
| `cost_delta` | numeric(18,4) | NOT NULL |
| `inventory_writeoff_cost` | numeric(18,4) | NOT NULL |
| `currency` | char(3) | NOT NULL |
| `details` | jsonb | NOT NULL |
| `status` | varchar(30) | NOT NULL |
| `created_at` | timestamptz | NOT NULL |

strategy_type：

```text
IMMEDIATE_REPLACEMENT
INVENTORY_RUN_OUT
SPLIT_EFFECTIVITY
LAST_TIME_BUY
```

status：

```text
CANDIDATE
RECOMMENDED
SELECTED
REJECTED
SUPERSEDED
```

约束：

```text
cost_delta 可以为负数
inventory_writeoff_cost >= 0
```

唯一：

```text
(ecr_id, strategy_code)
```

说明：

LLM 可以参与生成方案，但：

- 成本；
- 库存损失；
- 生效日期可行性；
- 订单数量；

必须来自确定性 Tool 的结果。

---

# 39. 变更方案动作：change_strategy_actions

表：

```text
ecm.change_strategy_actions
```

将自然语言方案拆成可执行的结构化动作。

| 字段 | 类型 | 约束 |
|---|---|---|
| `action_id` | uuid | PK |
| `strategy_id` | uuid | FK NOT NULL |
| `sequence_no` | integer | NOT NULL |
| `action_type` | varchar(40) | NOT NULL |
| `target_type` | varchar(40) | NOT NULL |
| `target_key` | varchar(150) | NOT NULL |
| `payload` | jsonb | NOT NULL |
| `requires_approval` | boolean | NOT NULL |
| `created_at` | timestamptz | NOT NULL |

action_type：

```text
CREATE_BOM_REDLINE
SET_EFFECTIVITY
BLOCK_PRODUCTION_ORDER
NOTIFY_OWNER
CREATE_ECO_DRAFT
```

MVP 不允许 Planner 自由创造未注册的 action_type。

唯一：

```text
(strategy_id, sequence_no)
```

---

# 40. 风险审查结果：change_reviews

表：

```text
ecm.change_reviews
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `review_id` | uuid | PK |
| `strategy_id` | uuid | FK NOT NULL |
| `review_run_id` | uuid | NOT NULL |
| `decision` | varchar(30) | NOT NULL |
| `risk_level` | varchar(20) | NOT NULL |
| `evidence_complete` | boolean | NOT NULL |
| `issues` | jsonb | NOT NULL |
| `created_at` | timestamptz | NOT NULL |

decision：

```text
PASS
REWORK
HUMAN_REVIEW
BLOCK
```

历史审查记录不得覆盖。

---

# 41. 工程变更单：engineering_change_orders

表：

```text
ecm.engineering_change_orders
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `eco_id` | uuid | PK |
| `eco_number` | varchar(40) | UNIQUE NOT NULL |
| `ecr_id` | uuid | FK NOT NULL |
| `selected_strategy_id` | uuid | FK NOT NULL |
| `status` | varchar(30) | NOT NULL |
| `effective_from` | date | NOT NULL |
| `approved_by` | varchar(100) | NULL |
| `approved_at` | timestamptz | NULL |
| `executed_at` | timestamptz | NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

status：

```text
DRAFT
WAITING_APPROVAL
APPROVED
EXECUTING
EXECUTED
EXECUTION_FAILED
REJECTED
CANCELLED
```

业务规则：

只有：

```text
APPROVED
```

状态才允许进入：

```text
EXECUTING
```

只有真实人工审批记录存在时，才能从：

```text
WAITING_APPROVAL → APPROVED
```

---

# 42. 人工审批：approval_records

表：

```text
ecm.approval_records
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `approval_id` | uuid | PK |
| `eco_id` | uuid | FK NOT NULL |
| `approval_type` | varchar(40) | NOT NULL |
| `approver_id` | varchar(100) | NOT NULL |
| `decision` | varchar(20) | NOT NULL |
| `comment` | text | NULL |
| `decided_at` | timestamptz | NOT NULL |
| `created_at` | timestamptz | NOT NULL |

decision：

```text
APPROVED
REJECTED
REWORK
```

MVP：

一个 `ENGINEERING_CHANGE_APPROVAL` 即可。

V2 可增加：

```text
ENGINEERING
QUALITY
PROCUREMENT
PRODUCTION
```

多角色审批。

---

# 43. BOM 修改草案：bom_redlines

表：

```text
ecm.bom_redlines
```

表示 Agent / 工程师拟对某个 BOM 做什么修改。

| 字段 | 类型 | 约束 |
|---|---|---|
| `redline_id` | uuid | PK |
| `eco_id` | uuid | FK NOT NULL |
| `source_bom_version_id` | uuid | NOT NULL |
| `target_bom_version_id` | uuid | NULL |
| `status` | varchar(30) | NOT NULL |
| `created_at` | timestamptz | NOT NULL |
| `applied_at` | timestamptz | NULL |

status：

```text
DRAFT
APPROVED
APPLIED
REJECTED
FAILED
```

`source_bom_version_id` / `target_bom_version_id` 对应 Neo4j 中的 UUID。

PostgreSQL 无数据库外键。

由 PLM Tool 在创建时检查 Neo4j 对象是否存在。

---

# 44. BOM 修改明细：bom_redline_lines

表：

```text
ecm.bom_redline_lines
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `redline_line_id` | uuid | PK |
| `redline_id` | uuid | FK NOT NULL |
| `sequence_no` | integer | NOT NULL |
| `action_type` | varchar(30) | NOT NULL |
| `source_bom_line_id` | uuid | NULL |
| `old_part_number` | varchar(64) | NULL |
| `old_revision_code` | varchar(16) | NULL |
| `new_part_number` | varchar(64) | NULL |
| `new_revision_code` | varchar(16) | NULL |
| `old_quantity` | numeric(18,4) | NULL |
| `new_quantity` | numeric(18,4) | NULL |
| `reason` | text | NOT NULL |
| `created_at` | timestamptz | NOT NULL |

action_type：

```text
ADD
REMOVE
REPLACE
UPDATE_QUANTITY
```

REPLACE 必须同时拥有：

```text
old_part_number
new_part_number
```

ADD 必须拥有：

```text
new_part_number
```

REMOVE 必须拥有：

```text
old_part_number
```

这些跨字段条件第一版由 Pydantic + 领域服务验证。

---

# 45. 跨数据库执行：execution_jobs

由于 PostgreSQL 与 Neo4j 之间不存在单一 ACID 事务，禁止假装可以进行跨库原子提交。

增加：

```text
ecm.execution_jobs
```

用于实现受控、可重试、幂等的执行。

| 字段 | 类型 | 约束 |
|---|---|---|
| `execution_job_id` | uuid | PK |
| `eco_id` | uuid | FK NOT NULL |
| `action_type` | varchar(40) | NOT NULL |
| `idempotency_key` | varchar(120) | UNIQUE NOT NULL |
| `payload` | jsonb | NOT NULL |
| `status` | varchar(30) | NOT NULL |
| `attempt_count` | integer | NOT NULL |
| `last_error` | text | NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |
| `completed_at` | timestamptz | NULL |

status：

```text
PENDING
RUNNING
SUCCEEDED
FAILED
CANCELLED
```

流程：

```text
人工审批
↓
PostgreSQL 创建 execution_job
↓
Executor 获取任务
↓
调用受控 PLM Write Tool
↓
Neo4j 完成 BOM 新版本创建
↓
验证
↓
execution_job = SUCCEEDED
↓
ECO = EXECUTED
```

失败：

```text
execution_job = FAILED
ECO = EXECUTION_FAILED
```

允许在相同 `idempotency_key` 下安全重试。

---

# 46. Agent 工作流：agent_runs

表：

```text
agent.agent_runs
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `run_id` | uuid | PK |
| `case_id` | uuid | NOT NULL |
| `workflow_name` | varchar(100) | NOT NULL |
| `workflow_version` | varchar(40) | NOT NULL |
| `status` | varchar(30) | NOT NULL |
| `model_provider` | varchar(50) | NULL |
| `model_name` | varchar(100) | NULL |
| `started_at` | timestamptz | NOT NULL |
| `finished_at` | timestamptz | NULL |
| `input_tokens` | bigint | NOT NULL |
| `output_tokens` | bigint | NOT NULL |
| `total_cost` | numeric(18,8) | NULL |
| `latency_ms` | bigint | NULL |
| `error_message` | text | NULL |

status：

```text
RUNNING
WAITING_HUMAN
SUCCEEDED
FAILED
CANCELLED
```

索引：

```text
case_id
status
started_at
```

---

# 47. Agent 节点运行：agent_steps

表：

```text
agent.agent_steps
```

记录 LangGraph 业务节点，而不是保存模型隐含推理过程。

| 字段 | 类型 | 约束 |
|---|---|---|
| `step_id` | uuid | PK |
| `run_id` | uuid | FK NOT NULL |
| `node_name` | varchar(100) | NOT NULL |
| `agent_name` | varchar(100) | NULL |
| `status` | varchar(30) | NOT NULL |
| `input_summary` | jsonb | NULL |
| `output_summary` | jsonb | NULL |
| `started_at` | timestamptz | NOT NULL |
| `finished_at` | timestamptz | NULL |
| `latency_ms` | bigint | NULL |
| `error_message` | text | NULL |

重要：

本表只保存：

- 输入摘要；
- 输出摘要；
- Tool Trace；
- 状态。

不保存或试图暴露模型私有思维链。

---

# 48. 工具调用：tool_calls

表：

```text
agent.tool_calls
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `tool_call_id` | uuid | PK |
| `run_id` | uuid | FK NOT NULL |
| `step_id` | uuid | FK NULL |
| `agent_name` | varchar(100) | NOT NULL |
| `tool_name` | varchar(100) | NOT NULL |
| `tool_mode` | varchar(10) | NOT NULL |
| `arguments` | jsonb | NOT NULL |
| `result_summary` | jsonb | NULL |
| `status` | varchar(30) | NOT NULL |
| `latency_ms` | bigint | NULL |
| `created_at` | timestamptz | NOT NULL |

tool_mode：

```text
READ
WRITE
```

status：

```text
STARTED
SUCCEEDED
FAILED
BLOCKED
```

所有 WRITE Tool 必须额外产生 Audit Event。

索引：

```text
run_id
tool_name
agent_name
created_at
```

MVP 默认不为 JSONB 建 GIN 索引。

如果后续经真实查询证明需要按 JSON 内容检索，再添加。

---

# 49. LangGraph Checkpoint

LangGraph 的 Checkpoint 数据属于：

**运行时持久化数据**

而不是业务数据。

原则：

1. 使用官方 PostgreSQL Checkpointer；
2. 由 Checkpointer 自己维护表结构；
3. 不允许业务代码直接读写其内部表；
4. `agent_runs` 用于业务级可观测；
5. Checkpoint 用于暂停、恢复和 durable execution。

二者不能混为一谈。

---

# 50. 审计日志：audit_events

表：

```text
audit.audit_events
```

是 Append-Only 表。

| 字段 | 类型 | 约束 |
|---|---|---|
| `audit_id` | uuid | PK |
| `case_id` | uuid | NULL |
| `run_id` | uuid | NULL |
| `actor_type` | varchar(20) | NOT NULL |
| `actor_id` | varchar(100) | NOT NULL |
| `action` | varchar(100) | NOT NULL |
| `object_type` | varchar(60) | NOT NULL |
| `object_id` | varchar(150) | NOT NULL |
| `before_state` | jsonb | NULL |
| `after_state` | jsonb | NULL |
| `metadata` | jsonb | NULL |
| `created_at` | timestamptz | NOT NULL |

actor_type：

```text
HUMAN
AGENT
SYSTEM
```

规则：

- 不提供业务 DELETE API；
- 不允许 UPDATE 历史 Audit Event；
- 需要纠正时创建新的审计事件。

索引：

```text
case_id
run_id
(object_type, object_id)
actor_type
created_at
```

---

# 51. PostgreSQL 外键删除策略

企业业务记录原则上禁止级联物理删除。

因此业务表默认：

```text
ON DELETE RESTRICT
```

或：

```text
ON DELETE NO ACTION
```

只对纯运行时的从属 Trace 数据考虑：

```text
ON DELETE CASCADE
```

但 MVP 建议 Agent Trace 也保留。

因此第一阶段几乎不使用业务级物理删除。

---

# 52. 跨库引用规则

PostgreSQL 无法对 Neo4j 建立 Foreign Key。

因此所有以下字段：

```text
part_number
revision_code
bom_version_id
bom_line_id
```

写入 PostgreSQL 前必须经过对应 PLM Tool 校验。

例如：

```text
create_bom_redline()
```

内部必须：

1. 查询 `source_bom_version_id`；
2. 验证其存在；
3. 验证状态；
4. 再写 PostgreSQL Redline。

不得让上层 Agent 绕过 Tool 直接写数据库。

---

# 53. Neo4j 与 PostgreSQL 一致性原则

两个数据库之间采用：

**最终一致 + 可验证执行**

而不是两阶段提交。

正式写操作遵循：

```text
Prepare
↓
PostgreSQL 记录执行任务
↓
执行 Neo4j 写操作
↓
验证 Neo4j 结果
↓
更新 PostgreSQL 执行状态
↓
写 Audit Event
```

如果中途失败：

- 不伪造成功；
- 标记 `EXECUTION_FAILED`；
- 保存错误；
- 允许幂等重试。

---

# 54. 数据库访问权限

Agent 本身不得拥有数据库账号。

架构：

```text
Agent
↓
Tool / MCP Server
↓
Application Service
↓
Database
```

至少区分：

## Read Tool

只能：

```text
SELECT / MATCH
```

用于：

- Intake Agent
- Impact Agent
- Planner Agent
- Reviewer Agent

## Write Tool

可以执行有限写操作。

仅：

```text
Execution Agent
```

拥有访问能力。

并要求：

```text
approved == true
```

---

# 55. 数据库账号建议

本地开发至少概念上区分：

```text
changepilot_migration
changepilot_read
changepilot_write
```

`changepilot_migration`：

- 创建表；
- 执行 migration。

`changepilot_read`：

- 查询生产数据。

`changepilot_write`：

- 仅受控 Application Service 使用。

MVP 可以先通过不同配置模拟权限，V1 再真正建立数据库角色。

---

# 56. 工程变更执行幂等

所有具有副作用的 Tool 必须接收：

```text
idempotency_key
```

例如：

```text
create_eco_draft
create_bom_redline
release_bom_version
block_production_order
```

相同：

```text
idempotency_key
```

重复调用时：

- 返回原结果；
- 不重复创建对象。

不能产生：

```text
ECO-001
ECO-002
```

两个重复工程变更单。

---

# 57. 编号生成

业务编号统一由服务生成，不由 LLM 生成。

例如：

```text
CASE-2026-000001
ECR-2026-000001
ECO-2026-000001
PO-2026-000001
SO-2026-000001
MO-2026-000001
```

LLM 可以描述：

> 需要创建工程变更单。

但不能决定正式编号。

---

# 58. 数据状态转换原则

所有关键状态不得允许任意字符串跳转。

例如 ECO：

```text
DRAFT
↓
WAITING_APPROVAL
↓
APPROVED
↓
EXECUTING
↓
EXECUTED
```

失败：

```text
EXECUTING
↓
EXECUTION_FAILED
```

拒绝：

```text
WAITING_APPROVAL
↓
REJECTED
```

状态转换必须由：

```text
EngineeringChangeService
```

处理。

禁止 Repository 直接根据 Agent 输出设置任意 status。

---

# 59. BOM 正式发布事务

发布新 BOMVersion 时，逻辑上必须完成：

1. 新 BOM 为 DRAFT；
2. 校验 BOM DAG；
3. 校验所有组件存在；
4. 校验所引用组件状态；
5. 校验日期；
6. 校验没有有效期非法重叠；
7. 找到旧 RELEASED BOM；
8. 设置旧版本 `effective_to`；
9. 新版本设置 `RELEASED`；
10. 新版本设置 `effective_from`；
11. 写审计。

Neo4j 内部相关修改必须放在单个 Neo4j Transaction 中。

---

# 60. PostgreSQL 工程变更事务

以下操作必须在单个 PostgreSQL Transaction 中完成：

例如：

```text
创建 ECO
+
关联 Selected Strategy
+
创建 Approval Request
```

或者：

```text
审批通过
+
写 Approval Record
+
更新 ECO 状态
+
创建 execution_job
```

禁止一个步骤成功、另一个步骤失败后留下半套业务数据。

---

# 61. 软删除原则

MVP 不实现通用：

```text
is_deleted
deleted_at
```

原因：

大量软删除字段会增加每个查询的复杂度。

本项目主要业务对象采用：

- lifecycle state；
- status；
- obsolete；
- cancelled；

表达业务失效。

Audit 不删除。

测试数据需要清理时：

> 重建开发数据库。

---

# 62. Seed Data 生成原则

Seed Data 分两层。

## 62.1 Golden Seed

人工维护的小型固定数据集。

规模：

```text
4 个最终产品
10~15 个组件
30~50 个零件
5 个供应商
70~100 条 BOM Line
20 个采购订单
15 个生产订单
15 个销售订单
```

目的：

- 可读；
- 可人工检查；
- 用于演示；
- 用于端到端测试。

---

## 62.2 Benchmark Seed

程序生成的大型固定数据集。

规模：

```text
8 个最终产品
40 个组件
250 个零件
20 个供应商
500~800 条 BOM Line
500 个采购订单
300 个生产订单
300 个销售订单
```

必须使用固定随机种子：

```text
seed = 20260919
```

确保每次 Benchmark 可复现。

---

# 63. Seed Data 生成顺序

严格：

```text
Part
↓
PartRevision
↓
BOMVersion
↓
BOMLine
↓
Supplier
↓
SupplierPart
↓
Sales Demand
↓
Production Order
↓
BOM Explosion
↓
Production Material Requirement
↓
Inventory
↓
Purchase Order
```

禁止分别随机生成完全无关的数据。

---

# 64. BOM Explosion

生产订单创建时：

必须根据该订单使用的：

```text
product_part_number
product_revision
```

以及当时有效：

```text
BOMVersion
```

进行 BOM Explosion。

计算结果固化到：

```text
production_material_requirements
```

后续工程变更发生时：

历史已释放订单仍以这张表为事实。

这可以模拟真实企业中：

> 工程结构变化不应自动重写已释放生产订单。

---

# 65. Ground Truth 设计

Agent Benchmark 的真实答案由确定性程序产生。

例如：

```text
BRG-6204-A EOL
```

Ground Truth 包括：

```text
affected_part_revisions
affected_assemblies
affected_products
affected_purchase_orders
affected_production_orders
affected_sales_orders
inventory_balance
qualified_alternatives
```

生成过程：

```text
Neo4j deterministic query
+
PostgreSQL deterministic query
+
Rule Engine
```

禁止：

> 再调用另一个 LLM 作为 Ground Truth。

---

# 66. 影响分析版本化

每次重新分析生成：

```text
analysis_run_id
```

例如：

```text
RUN-A
RUN-B
RUN-C
```

不能：

```text
DELETE old impacts
INSERT new impacts
```

理由：

需要比较：

- Agent 是否在新数据下改变判断；
- 人工要求 Re-analysis 后发生了什么；
- Benchmark 是否退化。

---

# 67. Audit 与 Agent Trace 的区别

`agent.tool_calls`

回答：

> Agent 做了什么？

`audit.audit_events`

回答：

> 正式业务数据发生了什么变化？

不是一个东西。

例如：

```text
Agent 调用：
release_bom_version()
```

写：

```text
tool_calls
```

真正发布成功：

```text
BOM-B01 → OBSOLETE
BOM-B02 → RELEASED
```

写：

```text
audit_events
```

---

# 68. JSONB 索引原则

MVP 不默认对所有 JSONB 建 GIN。

只有真实查询模式出现，例如经常执行：

```sql
WHERE evidence @> ...
```

时，再为指定字段增加 GIN。

原因：

- GIN 有额外写入成本；
- JSONB 字段主要用于 Trace 与审计；
- 多数 MVP 查询按 case_id、run_id、object_type 等普通字段过滤。

---

# 69. PostgreSQL 核心索引汇总

必须存在：

```text
erp.suppliers.supplier_code UNIQUE

erp.supplier_parts.part_number
erp.supplier_parts.eol_date

erp.inventory_balances(part_number, revision_code)

erp.purchase_order_lines(part_number, revision_code)

erp.production_orders(product_part_number, product_revision)

erp.production_material_requirements(part_number, revision_code)

erp.sales_order_lines(product_part_number, product_revision)

ecm.change_cases.idempotency_key UNIQUE
ecm.change_cases.status

ecm.engineering_change_requests.subject_part_number

ecm.change_impacts.analysis_run_id
ecm.change_impacts(object_type, object_key)

ecm.engineering_change_orders.eco_number UNIQUE

ecm.execution_jobs.idempotency_key UNIQUE

agent.agent_runs.case_id
agent.tool_calls.run_id

audit.audit_events.case_id
audit.audit_events(object_type, object_id)
```

其他索引在 Query Profile 后追加。

---

# 70. 外键汇总

主要 PostgreSQL FK：

```text
supplier_parts.supplier_id
→ suppliers.supplier_id
```

```text
purchase_orders.supplier_id
→ suppliers.supplier_id
```

```text
purchase_order_lines.po_id
→ purchase_orders.po_id
```

```text
production_material_requirements.production_order_id
→ production_orders.production_order_id
```

```text
sales_order_lines.sales_order_id
→ sales_orders.sales_order_id
```

```text
engineering_change_requests.case_id
→ change_cases.case_id
```

```text
change_impacts.ecr_id
→ engineering_change_requests.ecr_id
```

```text
change_strategies.ecr_id
→ engineering_change_requests.ecr_id
```

```text
change_strategy_actions.strategy_id
→ change_strategies.strategy_id
```

```text
engineering_change_orders.ecr_id
→ engineering_change_requests.ecr_id
```

```text
engineering_change_orders.selected_strategy_id
→ change_strategies.strategy_id
```

```text
approval_records.eco_id
→ engineering_change_orders.eco_id
```

```text
bom_redlines.eco_id
→ engineering_change_orders.eco_id
```

```text
bom_redline_lines.redline_id
→ bom_redlines.redline_id
```

```text
execution_jobs.eco_id
→ engineering_change_orders.eco_id
```

```text
agent_steps.run_id
→ agent_runs.run_id
```

```text
tool_calls.run_id
→ agent_runs.run_id
```

```text
tool_calls.step_id
→ agent_steps.step_id
```

---

# 71. MVP 中明确不创建的数据库对象

暂不创建：

```text
MBOM
Routing
Work Center
CAD Document
Quality NCR
Customer Approval
Multi-Plant Effectivity
Serial Effectivity
Variant Configuration
Engineering Specification Attribute Table
Vector Database
Embedding Table
RAG Document Table
```

原因：

这些都不属于 Supplier EOL → ECO 第一条主线的必要条件。

---

# 72. 不引入向量数据库

ChangePilot 第一版不是 RAG 项目。

因此禁止为了“AI 项目看起来完整”加入：

```text
pgvector
Milvus
Qdrant
Chroma
```

只有后续真的需要：

> 从供应商 PDF、工程规范、认证文件中做语义检索

时，再作为 Tool 增加。

---

# 73. 初始案例 CASE-EOL-001 数据约束

必须存在：

```text
Part:
BRG-6204-A
```

供应商：

```text
SUP-001
MotionWorks
```

供应商状态：

```text
ACTIVE
```

SupplierPart：

```text
status = LAST_TIME_BUY

last_time_buy_date = 2026-11-30

eol_date = 2027-01-31
```

---

# 74. CASE-EOL-001 替代件

至少：

```text
BRG-6204-B
qualification_status = QUALIFIED
```

```text
BRG-6204-C
qualification_status = UNQUALIFIED
```

两个候选。

两者必须在：

- 单价；
- 交期；
- 工程属性；

上存在差异。

---

# 75. CASE-EOL-001 BOM 约束

`BRG-6204-A` 至少影响：

```text
2 个不同 Gearbox
```

并通过它们间接影响：

```text
4 个最终产品
```

至少有一条：

```text
3 层以上
```

的间接 Where-Used 路径。

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

用于验证多层图遍历。

---

# 76. CASE-EOL-001 事务约束

至少存在：

```text
1 条当前库存
3 个未完成采购订单
7 个未完成生产订单
5 个相关销售订单
```

但并不是所有订单都必须真正受到阻断。

Benchmark 应区分：

```text
找到相关对象
```

和：

```text
真正构成业务风险
```

---

# 77. 领域服务边界

Codex 后续必须创建明确领域服务。

建议：

```text
PartService

BomService

BomVersionService

BomImpactService

SupplierService

InventoryService

OrderImpactService

EngineeringChangeService

ApprovalService

ExecutionService

AuditService
```

Repository 只做持久化。

业务规则不能散落在：

- FastAPI Router；
- LangGraph Node；
- Prompt；
- Repository。

---

# 78. Agent 与领域服务关系

正确：

```text
Agent
↓
Tool
↓
Domain Service
↓
Repository
↓
Database
```

错误：

```text
Agent
↓
SQLAlchemy Session
```

也错误：

```text
Agent
↓
Neo4j Driver
```

Agent 不知道底层数据库结构。

---

# 79. Tool 返回值规范

Tool 不返回裸数据库对象。

例如：

```text
where_used()
```

返回稳定 Pydantic DTO：

```text
WhereUsedResult
```

而不是：

```text
neo4j.Record
```

`get_inventory()` 返回：

```text
InventoryResult
```

而不是 SQLAlchemy ORM 对象。

数据库层可以变化，Agent Contract 不变。

---

# 80. 错误类型

后续实现统一异常体系：

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

Agent 不直接处理数据库底层异常。

---

# 81. 数据库迁移原则

PostgreSQL 使用：

```text
Alembic
```

所有 Schema 变更必须通过 Migration。

禁止：

> 开发过程中手工连数据库改表，然后不留下迁移文件。

Neo4j Schema 变更：

保存独立：

```text
infra/neo4j/schema.cypher
```

或者对应版本化脚本。

---

# 82. 初始化顺序

项目第一次启动：

```text
1. 启动 PostgreSQL
2. 启动 Neo4j
3. 执行 PostgreSQL Alembic Migration
4. 执行 Neo4j schema.cypher
5. 执行 Golden Seed
6. 执行数据一致性检查
7. 启动 FastAPI
```

---

# 83. 数据一致性检查

提供：

```text
scripts/check_data_integrity.py
```

至少检查：

1. PostgreSQL 中引用的 part_number 在 Neo4j 是否存在；
2. revision_code 是否存在；
3. BOM 是否有循环；
4. RELEASED BOM 是否存在有效期冲突；
5. Production Material Requirement 是否引用存在的零件；
6. Supplier Part 是否引用存在的采购零件；
7. qty_reserved 是否超过 qty_on_hand；
8. 已完成数量是否超过计划数量；
9. 已收货数量是否超过采购数量；
10. Redline 是否引用真实 BOM。

---

# 84. 测试数据库

自动测试不得直接使用开发数据库。

建议：

```text
changepilot_test
```

Neo4j 可以使用独立 test database / test container。

集成测试优先使用：

```text
Testcontainers
```

或 Docker Compose 独立测试实例。

---

# 85. 核心数据库测试

必须覆盖：

## Neo4j

```text
Part 唯一性

PartRevision 业务键唯一

BOMVersion 唯一

Where-Used 正确

多层 BOM 展开正确

BOM 循环拒绝

非法 Effectivity 拒绝
```

## PostgreSQL

```text
库存约束

PO 数量约束

Production Order 数量约束

唯一业务编号

FK 约束

重复 idempotency_key 拒绝

审批状态转换
```

## 跨库

```text
不存在的 Part 不允许写 SupplierPart

不存在的 BOM 不允许创建 Redline

执行失败不会伪造 ECO Executed

重复执行不会重复创建新 BOM
```

---

# 86. 数据库可观测性

数据库慢查询和性能优化不是 MVP 核心卖点。

但必须保留：

- SQLAlchemy 查询日志开关；
- Neo4j Query 日志开发开关；
- Tool latency；
- database operation latency。

禁止默认在生产式日志中打印：

- 完整密码；
- Token；
- 敏感连接字符串。

---

# 87. 环境变量命名

建议：

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

任何密码不得：

- 写进 Git；
- 写入 Seed 文件；
- 写入技术文档示例真实值。

项目提供：

```text
.env.example
```

不提交：

```text
.env
```

---

# 88. 数据库层安全原则

Agent 项目特别强调：

**模型输出不是可信输入。**

所有 LLM 输出进入数据库前必须：

1. Pydantic 校验；
2. Enum 校验；
3. 领域规则校验；
4. Tool Permission 校验；
5. 参数化数据库查询。

禁止：

```text
LLM 输出字符串
↓
拼接 SQL/Cypher
↓
执行
```

---

# 89. SQL / Cypher 注入防护

SQLAlchemy：

使用参数绑定。

Neo4j Driver：

使用 Cypher Parameter。

禁止：

```python
query = f"MATCH (p:Part {{part_number: '{llm_output}'}})"
```

应该：

```text
MATCH (p:Part {part_number: $part_number})
```

LLM 永远不能提供完整可执行 Query 给数据库驱动。

---

# 90. 正式写操作白名单

Execution Agent 只允许调用注册工具，例如：

```text
create_eco_draft

create_bom_redline

approve_redline

release_bom_version

set_effectivity

block_production_order
```

不能拥有：

```text
execute_sql()

execute_cypher()
```

这种通用写工具。

---

# 91. 当前数据库 ER 逻辑关系

PostgreSQL 概念结构：

```text
suppliers
   │
   ├── supplier_parts
   │
   └── purchase_orders
           │
           └── purchase_order_lines


production_orders
   │
   └── production_material_requirements


sales_orders
   │
   └── sales_order_lines


change_cases
   │
   └── engineering_change_requests
           │
           ├── change_impacts
           │
           ├── change_strategies
           │       │
           │       ├── change_strategy_actions
           │       └── change_reviews
           │
           └── engineering_change_orders
                   │
                   ├── approval_records
                   ├── bom_redlines
                   │       │
                   │       └── bom_redline_lines
                   │
                   └── execution_jobs


agent_runs
   │
   ├── agent_steps
   └── tool_calls


audit_events
```

---

# 92. Neo4j 概念结构

```text
(:Part)
    │
    └──[:HAS_REVISION]
          │
          ▼
    (:PartRevision)
          │
          ├──[:HAS_BOM]
          │      │
          │      ▼
          │  (:BOMVersion)
          │      │
          │      └──[:HAS_LINE]
          │             │
          │             ▼
          │         (:BOMLine)
          │             │
          │             └──[:COMPONENT]
          │                    │
          │                    ▼
          │              (:PartRevision)
          │
          └──[:ALTERNATIVE_TO]
                 │
                 ▼
           (:PartRevision)
```

---

# 93. Codex 不得擅自修改的冻结决策

后续实现阶段，Codex 必须遵守：

### D-01

产品结构使用 Neo4j。

### D-02

企业事务、工程变更、Agent Trace 和 Audit 使用 PostgreSQL。

### D-03

Part 与 PartRevision 分离。

### D-04

BOM 使用：

```text
PartRevision
→ BOMVersion
→ BOMLine
→ PartRevision
```

### D-05

正式 BOM 不进行原地覆盖。

### D-06

工程变更通过新 BOMVersion 表达。

### D-07

RELEASED 数据禁止被 Agent 直接修改。

### D-08

所有 Write Tool 必须经过领域服务。

### D-09

Write Tool 必须支持幂等。

### D-10

正式高风险写操作前必须存在人工审批。

### D-11

跨 Neo4j / PostgreSQL 不使用伪原子事务。

### D-12

使用 execution_jobs + 状态验证处理跨库执行。

### D-13

所有正式写操作记录 Audit Event。

### D-14

Agent 不允许执行任意 SQL 或 Cypher。

### D-15

生产订单历史物料需求以 production_material_requirements 为事实。

### D-16

Benchmark Ground Truth 使用确定性程序生成，不使用 LLM 生成。

---

# 94. 允许后续调整但必须先更新文档的内容

以下属于可演进设计：

```text
表字段增加
索引优化
Benchmark 数据规模
新的 Change Type
新的 Impact Type
新的 Agent Tool
新的 Approval Role
新的 BOM Effectivity 类型
```

但如果改变：

```text
核心节点
核心关系
数据库职责边界
工程变更状态模型
跨库一致性方式
```

必须先升级本技术文档版本。

---

# 95. 下一阶段

数据库模型冻结以后，下一阶段不是立即实现全部业务。

Codex 第一阶段只负责建立：

```text
基础项目目录
Docker Compose
PostgreSQL
Neo4j
Alembic
SQLAlchemy Base
PostgreSQL Schema
Neo4j Schema
领域枚举
领域 DTO
Golden Seed
Data Integrity Check
基础数据库测试
```

此时：

**不要实现 Agent。**

数据库和模拟企业环境先能够独立运行、验证和测试。

---

# 96. 第一阶段完成标准

Codex 第一阶段完成后，人工应能够执行：

```text
docker compose up -d
```

完成数据库启动。

然后：

```text
alembic upgrade head
```

创建 PostgreSQL 数据结构。

再运行：

```text
python scripts/seed_golden_data.py
```

生成：

- Neo4j 产品结构；
- PostgreSQL 事务数据。

然后：

```text
python scripts/check_data_integrity.py
```

输出：

```text
PASS
```

最后自动测试：

```text
pytest
```

能够验证核心数据库规则。

---

# 97. 本版本结论

ChangePilot v0.4 正式确定以下数据架构：

```text
Neo4j
=
产品结构图
+
BOM 版本
+
BOM 行
+
替代关系
```

```text
PostgreSQL
=
ERP 模拟事务
+
工程变更
+
审批
+
执行任务
+
Agent Trace
+
Audit
```

Agent 层不能越过 Tool / Domain Service 直接访问数据库。

正式工程变更必须满足：

```text
事件
↓
分析
↓
方案
↓
风险审查
↓
人工审批
↓
幂等执行任务
↓
受控写操作
↓
结果验证
↓
审计
```

数据库设计的目的不是增加技术复杂度，而是为后续 Agent 提供一个：

> **结构清晰、结果可验证、动作可治理、失败可恢复的模拟企业环境。**

---

# 98. 文档状态

本文件在进入 Codex 数据库骨架实现前视为：

```text
BASELINE / FROZEN FOR MVP
```

如果开发过程中发现设计问题：

```text
先提出问题
↓
GPT 分析
↓
修改文档版本
↓
人确认
↓
Codex 修改代码
```

禁止：

```text
Codex 自行改变领域模型
↓
文档事后补写
```

这条规则适用于 ChangePilot 后续所有核心技术设计。
