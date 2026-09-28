# ChangePilot Demo 前 5 分钟检查

使用[根 README 的启动与 7 步路径](../README.md)；本清单只检查演示条件，不执行数据重置。

- [ ] `docker compose ps`：PostgreSQL 与 Neo4j 容器运行；`http://localhost:7474` 可访问。
- [ ] 根目录 `.env` 已按 `.env.example` 填好数据库连接；真实模型演示需 `DEEPSEEK_API_KEY`。不要在屏幕共享中打开密钥文件。
- [ ] `GET http://localhost:8000/health` 返回 `{"status":"ok"}`；`http://localhost:8000/docs` 可访问。
- [ ] `http://localhost:5173` 打开 Web；API 地址指向当前后端。
- [ ] Golden Seed 的 `BRG-6204-A`、`ROB-P100`、`SUP-001` 可在只读数据中心/Tool 中查到；不要为演示重复改写 Seed。
- [ ] Assistant 新建对话，先问“什么是 BOM？”，再问“BRG-6204-A 当前库存是多少？”；展示通用回答与有 Tool 支撑的事实。
- [ ] Multi-Agent 问“综合分析 BRG-6204-A 停产会对公司造成哪些影响？”；准备展示 Agent 运行中心与未核验项。真实模型若调度失败，展示 Trace，不临时编造结果。
- [ ] 启动 Supplier EOL 或 `BRG-6204-A → BRG-6204-B` 物料替代流程；按 API/Web 必填字段填写事件日期，确认 Review 后出现 Human Approval。
- [ ] 记录 `thread_id`；需演示重启恢复时，重启后端、查询原线程，再提交 APPROVE。另一个独立演示线程可测试 REJECT。
- [ ] APPROVE 后检查 ECO、Execution Jobs、Agent Run Center 与 Audit；说明只是受控记录，不是真实 ERP/BOM 写回。
- [ ] `uv run python -m evals.run` 可生成本地报告；若展示 LangSmith，先确认 tracing 已开启且项目 `ChangePilot-V2` 可见。LangSmith 不可用时仍可演示本地 Benchmark。
- [ ] 演示结束前可直接说明现有基准：13 Case、Fake 12/13、最近真实 DeepSeek 7/8，以及失败项和随机性。
