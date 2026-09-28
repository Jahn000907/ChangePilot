import { useEffect, useState } from "react";

import { agentRunsApi } from "./api";
import { formatShanghaiTime } from "./display";
import type { AgentRunDetail, AgentRunSummary } from "./observabilityTypes";

const domainNames = ["StructureAgent", "SupplyAgent", "ProductionAgent", "DeliveryAgent"];
const names: Record<string, string> = {
  enterprise_assistant: "企业智能助手", supplier_eol: "供应商停产流程",
  material_substitution: "物料替代流程",
  supervisor_plan: "Supervisor 规划", supervisor_summary: "Supervisor 汇总",
  assistant_response: "企业助手回答", StructureAgent: "产品结构 Agent",
  SupplyAgent: "供应 Agent", ProductionAgent: "生产 Agent",
  DeliveryAgent: "交付 Agent", impact_analysis: "影响分析",
  strategy_generation: "策略生成", review: "策略评审",
  human_approval: "人工审批", execution: "工程变更执行",
};
const statuses: Record<string, string> = {
  RUNNING: "运行中", WAITING_HUMAN: "等待人工审批", SUCCEEDED: "成功",
  FAILED: "失败", CANCELLED: "已取消", STARTED: "已开始", PENDING: "待执行",
};
const jobTypes: Record<string, string> = {
  PURCHASE_ACTION: "采购调整", PRODUCTION_ACTION: "生产计划",
  SUBSTITUTION_VALIDATION: "替代料验证", BOM_REDLINE_DRAFT: "BOM 草案准备",
  SUPPLIER_COMMUNICATION: "供应商沟通", DELIVERY_REVIEW: "交付复核",
};
const auditNames: Record<string, string> = {
  CHANGE_CASE_CREATED: "创建变更案例", HUMAN_APPROVE: "人工批准",
  HUMAN_REJECT: "人工驳回", STRATEGY_SELECTED: "选定策略",
  ECO_CREATED: "创建 ECO", EXECUTION_JOB_CREATED: "创建执行任务",
};

function elapsed(ms: number | null): string {
  if (ms === null) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export default function AgentRunCenter() {
  const [runs, setRuns] = useState<AgentRunSummary[]>([]);
  const [detail, setDetail] = useState<AgentRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      setRuns(await agentRunsApi.list());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "运行记录加载失败");
    } finally {
      setLoading(false);
    }
  }

  async function open(runId: string) {
    setDetailLoading(true);
    setError(null);
    try {
      setDetail(await agentRunsApi.get(runId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "运行详情加载失败");
    } finally {
      setDetailLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  return <div className="run-center">
    <div className="data-intro">
      <div>
        <p className="eyebrow">只读可观测性</p>
        <h2>Agent 运行中心</h2>
        <p>查看企业助手、多智能体协作和正式流程的执行链路。</p>
      </div>
      <button className="button button-secondary" type="button" onClick={() => void refresh()}
        disabled={loading}>刷新记录</button>
    </div>
    {error && <div className="error-banner" role="alert">{error}</div>}
    <div className="run-layout">
      <section className="panel run-list">
        <h3>最近运行</h3>
        {loading && <p className="muted">正在加载运行记录…</p>}
        {!loading && runs.length === 0 && <p className="muted">暂无运行记录。</p>}
        {runs.map((run) => <button key={run.run_id} type="button"
          className={`run-list-item ${detail?.run_id === run.run_id ? "active" : ""}`}
          onClick={() => void open(run.run_id)}>
          <span className="run-list-title">{names[run.workflow_name] || run.workflow_name}</span>
          <span className={`run-status run-status-${run.status.toLowerCase()}`}>
            {statuses[run.status] || run.status}</span>
          <small>{formatShanghaiTime(run.started_at)} · {elapsed(run.duration_ms)}</small>
          <small>{run.has_supervisor ? "包含 Supervisor" : "无 Supervisor"} ·
            {run.called_tools.length} 个 Tool</small>
        </button>)}
      </section>

      <section className="panel run-detail">
        {detailLoading && <p className="muted">正在加载详情…</p>}
        {!detailLoading && !detail && <p className="muted">请选择一条运行记录。</p>}
        {!detailLoading && detail && <>
          <div className="panel-heading compact">
            <div><h3>{names[detail.workflow_name] || detail.workflow_name}</h3>
              <p>{statuses[detail.status] || detail.status}</p></div>
            <span className="count-badge">{elapsed(detail.duration_ms)}</span>
          </div>
          <div className="run-metadata">
            <div><span>Run ID</span><code>{detail.run_id}</code></div>
            {detail.thread_id && <div><span>线程 ID</span><code>{detail.thread_id}</code></div>}
            <div><span>开始</span><strong>{formatShanghaiTime(detail.started_at)}</strong></div>
            <div><span>结束</span><strong>{detail.finished_at ? formatShanghaiTime(detail.finished_at) : "—"}</strong></div>
          </div>
          {detail.error_summary && <p className="run-warning">{detail.error_summary}</p>}

          {detail.has_supervisor && <div className="run-domains">
            <h4>领域 Agent 选择</h4>
            <div className="run-domain-grid">{domainNames.map((name) => {
              const selected = detail.selected_agents.includes(name);
              const step = detail.steps.find((item) => item.node_name === name);
              return <div className="run-domain" key={name}>
                <strong>{names[name]}</strong>
                <span>{!selected ? "未选择" : !step ? "已选择，未执行" :
                  statuses[step.status] || step.status}</span>
              </div>;
            })}</div>
          </div>}

          <h4>Agent 执行链</h4>
          <ol className="run-timeline">{detail.steps.map((step) => <li key={step.step_id}>
            <div className="run-step-header">
              <strong>{names[step.node_name] || step.agent_name || step.node_name}</strong>
              <span>{statuses[step.status] || step.status} · {elapsed(step.duration_ms)}</span>
            </div>
            <small>{formatShanghaiTime(step.started_at)}</small>
            <p>{step.summary}</p>
            {step.tool_calls.map((call) => <div className="run-tool" key={call.tool_call_id}>
              <strong>{call.tool_name}</strong>
              <span>{statuses[call.status] || call.status} · {elapsed(call.duration_ms)}</span>
              <p>参数：{Object.entries(call.arguments).map(([key, value]) =>
                `${key}=${String(value)}`).join("，") || "无"}</p>
              <p>{call.result_summary}</p>
            </div>)}
          </li>)}</ol>

          {detail.execution_jobs.length > 0 && <div className="run-section">
            <h4>受控执行任务</h4>
            {detail.execution_jobs.map((job) => <div className="run-job" key={job.execution_job_id}>
              <strong>{job.title}</strong><span>{jobTypes[job.action_type] || job.action_type} ·
                {statuses[job.status] || job.status}</span>
              <p>{job.description}</p>
              <small>{job.owner_department || "待分派"} · {job.related_part_number || "—"} ·
                {formatShanghaiTime(job.created_at)}</small>
            </div>)}
          </div>}
          {detail.audit_events.length > 0 && <div className="run-section">
            <h4>关键审计事件</h4>
            <ul>{detail.audit_events.map((event) => <li key={event.audit_id}>
              {auditNames[event.action] || event.action} · {formatShanghaiTime(event.created_at)}
            </li>)}</ul>
          </div>}
        </>}
      </section>
    </div>
  </div>;
}
