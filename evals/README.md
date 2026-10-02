# ChangePilot 评测

当前提供 `CASE-EOL-001` 的确定性 Supplier EOL Benchmark：

```powershell
uv run --extra dev python -m evals.run_supplier_eol
```

默认使用 Fake LLM，真实执行 Impact、Review Tool Calling、Human Approval 与
Execution，并在评分后清理本次生成的 ECM/Trace 数据。可选 `--llm deepseek` 使用
当前环境配置的真实模型，`--json` 输出完整结构化结果。

V2.8 企业智能助手评测分为：定向 `pytest`（确定性事实与安全边界）、
本地固定 Case Benchmark（默认可控 Fake LLM，真实只读 Tool）和可选 LangSmith 开发实验。
本地 Case 位于 `evals/benchmarks/assistant_core_v28.json`，每次报告写入
`evals/results/assistant_v28.json` 与 `.md`。报告保留逐 Case 指标、问题、延迟和版本信息。

```powershell
uv run python -m evals.run
```

本地 Benchmark 默认不调用真实模型、不上传数据；可显式加 `--real-llm` 使用 DeepSeek。
LangSmith Dataset 入口仅准备或同步 Case，不运行评测：

```powershell
uv run python -m evals.langsmith_dataset
```

LangSmith Experiment / Judge 入口运行可选的真实模型实验和主观评分：

```powershell
uv run python -m evals.langsmith_experiment --limit 2 --real-llm --judge
```

`--judge` 是可选的主观分析/完整性/清晰度评分；客观企业事实仍由确定性指标判定。
真实模型与 LangSmith 需分别显式配置。关闭 `LANGSMITH_TRACING` 或不配置 Key 时，
正常产品运行和本地 Benchmark 不依赖 LangSmith 服务。
