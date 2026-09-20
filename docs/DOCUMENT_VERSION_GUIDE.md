# ChangePilot 文档版本说明

## 当前有效基线

### v0.3

`changepilot_business_domain_bom_model_v0.3.md`

负责：

- 模拟企业；
- 产品体系；
- BOM 领域模型；
- 版本；
- 生效性；
- 业务对象；
- Neo4j / PostgreSQL 职责边界；
- 合成数据逻辑。

状态：

**ACTIVE BASELINE**

### v0.4

`changepilot_database_design_v0.4.md`

负责：

- Neo4j 节点、关系、约束与索引；
- PostgreSQL Schema；
- 字段类型；
- 主外键；
- 状态枚举；
- 索引；
- 跨库一致性；
- 幂等；
- 审计；
- Seed；
- Codex 实现边界。

状态：

**ACTIVE BASELINE / FROZEN FOR MVP**

---

## 历史版本

### v0.1

最初产品与总体技术设计。

状态：

**ARCHIVED**

不得作为数据库或领域模型实现依据。

### v0.2

中文化后的总体项目设计。

状态：

**ARCHIVED**

其中很多概念已经由 v0.3 / v0.4 进一步细化。

---

## Codex 阅读优先级

Codex 执行当前开发任务时：

```text
当前阶段执行任务书
>
v0.4 数据库详细设计
>
v0.3 业务领域与 BOM 模型
>
其他当前有效专题设计
>
历史 v0.1 / v0.2
```

如果文档发生冲突：

1. 停止擅自决定；
2. 将冲突交给 GPT 分析；
3. 人确认；
4. 更新设计文档；
5. Codex 再修改代码。
