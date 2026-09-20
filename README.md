# ChangePilot

ChangePilot 是一个面向制造业工程变更管理场景的智能体应用项目。

当前项目处于基础架构设计与数据基础设施建设阶段。

## 当前阶段

项目骨架初始化。

当前尚未实现：

- 数据库（PostgreSQL 与 Neo4j 的 Schema 已建立，业务数据仅有 Golden Seed）
- Agent
- MCP
- 前端
- 工程变更业务流程

## 数据基础设施命令

以下命令在项目根目录执行（需先 `docker compose up -d` 并激活 `changepilot` 环境）：

```powershell
python -m alembic upgrade head
python scripts/init_neo4j_schema.py
python scripts/seed_golden.py
python scripts/check_data_consistency.py
```

`scripts/seed_golden.py` 是幂等的：确定性 ID + upsert / MERGE，重复执行不会产生重复数据，
且只允许在 `APP_ENV=development` 或 `test` 下运行。

`scripts/check_data_consistency.py` 为只读一致性检查：全部通过退出码为 0，任一失败为非 0。

详细技术设计位于 `docs/`。

## 技术规划

后续预计使用：

- Python
- FastAPI
- PostgreSQL
- Neo4j
- LangGraph
- MCP
- React
- Docker

具体技术方案以 `docs/` 中当前有效设计文档为准。
