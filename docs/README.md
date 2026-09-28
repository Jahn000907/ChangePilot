# ChangePilot 技术文档

本目录用于保存 ChangePilot 的需求分析、业务设计、技术架构、数据库设计、Agent 设计、评测设计以及 Codex 执行任务书。

V2 已实现架构与演示材料：

- [V2 架构说明](change_pilot_v2_architecture.md)：实际分层、流程、存储与评测边界。
- [面试项目速记](interview_project_overview.md)：一分钟介绍与常见设计问答。
- [Demo 前检查](demo_checklist.md)：演示前的最小核对清单。

历史数据库/业务设计与 `archive/` 内容用于背景参考；当前已实现能力以代码、测试和上述 V2 文档为准。

## 文档规则

业务概念尽量使用中文。

行业标准缩写第一次出现时使用：

中文名称（英文缩写）

例如：

物料清单（BOM）

工程变更申请（ECR）

工程变更单（ECO）

产品生命周期管理系统（PLM）

企业资源计划系统（ERP）

代码类名称、框架名称、API 函数名保留英文。

## archive

`archive/` 保存已经失效的历史设计文档。

历史设计不得覆盖当前有效设计。

## prompts

`prompts/` 保存不同开发阶段交给 Codex 执行的任务书和 Prompt。
