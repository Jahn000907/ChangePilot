# ChangePilot 模拟企业业务建模与 BOM 数据模型设计

**文档版本：v0.3**  
**文档状态：当前业务领域基线**  
**用途：定义模拟企业、产品结构、BOM 版本、工程变更业务对象以及 Neo4j/PostgreSQL 职责边界。**

---

## 1. 模拟企业

虚拟企业：

**智衡自动化设备有限公司**

项目内部代号：

```text
ZhiHeng Automation
```

企业主营：

- 工业机器人；
- 自动化输送设备；
- 运动控制模块；
- 驱动单元；
- 齿轮传动组件。

MVP 只模拟一个制造基地：

```text
华东制造基地
Plant Code: CN-E01
```

和一个主要仓库：

```text
中央物料仓
Warehouse Code: WH-01
```

---

## 2. 业务角色

### 产品工程师

负责：

- 产品设计；
- BOM；
- 零件选型；
- 替代件评估；
- 工程变更方案。

### 采购工程师

负责：

- 供应商；
- 采购订单；
- 停产通知；
- 价格和交期。

### 生产计划员

负责：

- 生产订单；
- 物料需求；
- 生产时间。

### 质量工程师

负责：

- 替代件认证；
- 零件质量状态。

### 工程变更负责人

负责最终人工审批。

---

## 3. MVP 最终产品

第一阶段定义四个最终产品：

```text
ROB-P100
六轴工业机器人

ROB-P200
重载工业机器人

CON-C100
模块化自动输送系统

PAL-P300
自动码垛设备
```

这些产品故意共享：

- 驱动单元；
- 齿轮箱；
- 电机；
- 轴承；
- 编码器；
- 传感器。

以制造复杂的多层影响关系。

---

## 4. 产品结构层级

```text
L0 最终产品
↓
L1 系统
↓
L2 组件
↓
L3 子组件
↓
L4 采购零件
```

示例：

```text
ROB-P100
│
├── ASM-ARM100
│   ├── ASM-JOINT100 × 3
│   │   ├── ASM-GEARBOX100
│   │   │   ├── BRG-6204-A × 2
│   │   │   ├── GEAR-G100 × 3
│   │   │   └── SHAFT-S100 × 1
│   │   ├── MOTOR-SM100 × 1
│   │   └── ENCODER-E100 × 1
│   └── FRAME-F100
│
└── ASM-CTRL100
    ├── PLC-C100
    ├── SENSOR-S100 × 4
    └── CABLE-C100
```

`BRG-6204-A` 还必须通过其他组件被：

```text
ROB-P200
CON-C100
PAL-P300
```

共同使用。

---

## 5. Part 与 PartRevision

必须区分：

```text
Part
零件主数据
```

和：

```text
PartRevision
零件工程版本
```

Part 表示：

> 这个零件是什么。

PartRevision 表示：

> 这个零件在某一工程状态下是什么样子。

生命周期：

```text
DRAFT
IN_REVIEW
RELEASED
OBSOLETE
```

已发布版本不得直接覆盖关键工程属性。

---

## 6. BOM 版本模型

工程变更不能直接修改旧 BOM。

核心结构：

```text
Part
↓
PartRevision
↓
BOMVersion
↓
BOMLine
↓
PartRevision
```

例如：

```text
ROB-P100 Rev B
│
├── BOM-B01
│   └── 使用 BRG-6204-A
│
└── BOM-B02
    └── 使用 BRG-6204-B
```

旧 BOM：

```text
BOM-B01
有效：2026-01-01 ~ 2026-11-30
```

新 BOM：

```text
BOM-B02
有效：2026-12-01 ~ 未来
```

---

## 7. BOMLine

每条 BOM 行至少包含：

- 行号；
- 数量；
- 单位；
- 损耗率；
- 可选状态；
- 生效日期；
- 失效日期；
- 工厂；
- 来源工程变更编号。

BOMLine 作为节点建模，便于后续表达：

- Redline；
- 新增；
- 删除；
- 替换；
- 行级 Effectivity。

---

## 8. Neo4j 核心图模型

节点：

```text
Part
PartRevision
BOMVersion
BOMLine
```

关系：

```text
Part
-[:HAS_REVISION]->
PartRevision
```

```text
PartRevision
-[:HAS_BOM]->
BOMVersion
```

```text
BOMVersion
-[:HAS_LINE]->
BOMLine
```

```text
BOMLine
-[:COMPONENT]->
PartRevision
```

替代关系：

```text
PartRevision
-[:ALTERNATIVE_TO]->
PartRevision
```

---

## 9. BOM 无环规则

正式 BOM 必须是：

**有向无环图（DAG）**。

非法结构：

```text
A
↓
B
↓
C
↓
A
```

数据生成器和正式 BOM 写入服务都必须执行循环检查。

---

## 10. 替代零件

MVP 至少定义：

```text
QUALIFIED
已认证

CONDITIONAL
有条件使用

UNQUALIFIED
未认证
```

只有 `QUALIFIED` 可以被自动纳入正式候选方案。

`CONDITIONAL` 必须人工审核。

`UNQUALIFIED` 不允许自动执行。

---

## 11. 生效性

MVP 只支持：

**日期生效。**

字段：

```text
effective_from
effective_to
```

第一版不做：

- 序列号生效；
- 客户生效；
- 参数化 Effectivity；
- 多工厂 Effectivity。

---

## 12. BOM Redline

正式 BOM 修改前先生成草案。

示例：

旧：

```text
BRG-6204-A × 2
```

拟变更：

```text
REMOVE BRG-6204-A
ADD BRG-6204-B
```

审批前不得修改正式 BOM。

---

## 13. Neo4j 与 PostgreSQL 分工

### Neo4j

负责：

- Part；
- PartRevision；
- BOMVersion；
- BOMLine；
- 替代关系；
- Where-Used；
- BOM 展开。

### PostgreSQL

负责：

- 供应商；
- SupplierPart；
- 库存；
- 采购订单；
- 生产订单；
- 生产物料需求；
- 销售订单；
- ECR；
- ECO；
- 审批；
- Agent Run；
- Tool Call；
- Audit。

跨库通过稳定业务标识：

```text
part_number
revision_code
```

和必要 UUID 关联。

---

## 14. 事务领域模型

主要 PostgreSQL 逻辑对象：

```text
suppliers
supplier_parts
inventory_balances

purchase_orders
purchase_order_lines

production_orders
production_material_requirements

sales_orders
sales_order_lines

engineering_change_requests
engineering_change_orders
change_impacts
approval_records

agent_runs
tool_calls
audit_events
```

数据库字段级详细设计以 v0.4 为准。

---

## 15. 生产订单历史物料需求

生产订单创建/释放后，需要将当时 BOM 展开结果固化到：

```text
production_material_requirements
```

以后即使产品 BOM 改变：

> 历史已释放生产订单仍以该表作为旧零件需求事实。

不能使用当前 BOM 反推历史订单。

---

## 16. 合成数据规模

### Golden Seed

第一阶段：

```text
4 个最终产品
10~15 个主要组件
30~50 个零件
5 个供应商
70~100 条 BOM Line
20 个采购订单
15 个生产订单
15 个销售订单
```

### Benchmark Seed

后续：

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

---

## 17. 数据生成顺序

必须：

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

禁止独立随机生成完全无关的业务数据。

---

## 18. Ground Truth

Benchmark 的真实答案由确定性程序生成：

```text
Neo4j 图查询
+
PostgreSQL 查询
+
规则引擎
```

不允许使用另一个大模型生成 Ground Truth。

例如：

```text
BRG-6204-A 停产
```

Ground Truth 应包括：

- 受影响组件；
- 受影响最终产品；
- 库存；
- 相关采购订单；
- 相关生产订单；
- 相关销售订单；
- 已认证替代件。

---

## 19. 标准案例 CASE-EOL-001

供应商：

```text
SUP-001
MotionWorks
```

目标零件：

```text
BRG-6204-A
```

最后采购日期：

```text
2026-11-30
```

停产日期：

```text
2027-01-31
```

替代件：

```text
BRG-6204-B
QUALIFIED
```

和：

```text
BRG-6204-C
UNQUALIFIED
```

`BRG-6204-A` 至少影响：

- 2 种齿轮箱；
- 4 个最终产品；
- 至少一条 3 层以上 Where-Used 路径。

同时存在：

- 库存；
- 3 个未完成采购订单；
- 7 个未完成生产订单；
- 5 个相关销售订单。

---

## 20. 核心业务不变量

1. `part_number` 全局唯一；
2. 一个 Part 可以有多个 PartRevision；
3. RELEASED PartRevision 不允许直接覆盖关键工程属性；
4. BOMVersion 必须属于一个 PartRevision；
5. BOMLine 数量必须大于 0；
6. 正式 BOM 不允许循环；
7. 正式 BOM 有效期不能非法重叠；
8. DRAFT BOM 不参与正式生产需求计算；
9. 审批前不能修改正式 BOM；
10. Agent 未经审批不能调用正式写工具；
11. 所有正式写操作必须生成审计记录；
12. 工程变更写操作必须支持幂等。

---

## 21. MVP 暂不建模

第一版不做：

- 制造物料清单（MBOM）；
- 工艺路线；
- 多工厂；
- 产品变型；
- 150% BOM；
- 序列号生效；
- CAD；
- 3D 模型；
- 复杂材料替代；
- 真实 PLM / ERP 对接。

---

## 22. 当前文档与 v0.4 的关系

本文件负责回答：

> 业务世界是什么？

> 产品怎么组成？

> 工程变更如何影响产品结构？

v0.4 负责回答：

> 这些对象在 Neo4j 和 PostgreSQL 中具体怎么存？

包括：

- 字段类型；
- 主键；
- 外键；
- 索引；
- 唯一约束；
- 幂等；
- 跨库一致性；
- Audit；
- Agent Trace。

因此开发实现阶段必须同时遵守 v0.3 与 v0.4。
