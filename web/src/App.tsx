import { FormEvent, useMemo, useRef, useState } from "react";

import {
  getSupplierEOLWorkflow,
  startSupplierEOLWorkflow,
  submitSupplierEOLApproval,
} from "./api";
import type {
  ExecutionResult,
  ReviewResult,
  StartWorkflowRequest,
  StrategyCandidate,
  SupplierEOLImpact,
  WorkflowResult,
} from "./types";
import DataCenter from "./DataCenter";
import AssistantPanel from "./AssistantPanel";
import MaterialSubstitutionPanel from "./MaterialSubstitutionPanel";
import AgentRunCenter from "./AgentRunCenter";
import type { WorkflowSuggestion } from "./assistantTypes";
import { businessDateShanghai, formatQuantity } from "./display";

const strategyNames: Record<string, string> = {
  LAST_TIME_BUY: "最后采购", QUALIFIED_ALTERNATIVE: "已认证替代料",
  QUALIFICATION_REQUIRED: "替代料待认证", REDESIGN: "重新设计",
  SUPPLY_MITIGATION: "供应保障",
};
const qualificationNames: Record<string, string> = {
  QUALIFIED: "已认证", UNQUALIFIED: "未认证", CONDITIONAL: "有条件认证",
  ELIGIBLE: "可采用", INELIGIBLE: "不可直接采用", REQUIRES_REVIEW: "需要评审",
  DIRECT: "直接替代", CONDITIONAL_REPLACEMENT: "有条件替代",
};
const priorityNames: Record<string, string> = {
  LOW: "低", MEDIUM: "中", HIGH: "高", CRITICAL: "紧急",
};

function newThreadId(): string {
  return `eol-demo-${Date.now().toString(36)}`;
}

const goldenRequest = (): StartWorkflowRequest => ({
  thread_id: newThreadId(),
  part_number: "BRG-6204-A",
  revision: "A",
  supplier_code: "SUP-001",
  supplier_name: "MotionWorks",
  last_time_buy_date: "2026-11-30",
  eol_date: "2027-01-31",
  as_of_date: "2026-09-20",
  priority: "HIGH",
  requested_by: "demo.user",
  source_type: "SUPPLIER_NOTICE",
});

export default function App() {
  const [view, setView] = useState<"workbench" | "data" | "runs">(
    () => window.location.hash === "#runs" ? "runs" :
      window.location.hash === "#data" ? "data" : "workbench",
  );
  const [formalFlow, setFormalFlow] = useState<"supplier_eol" | "material_substitution">("supplier_eol");
  const [materialPrefill, setMaterialPrefill] = useState<Record<string, string> | undefined>();
  const [form, setForm] = useState<StartWorkflowRequest>(goldenRequest);
  const [result, setResult] = useState<WorkflowResult | null>(null);
  const [selectedStrategy, setSelectedStrategy] = useState(0);
  const [reviewer, setReviewer] = useState("change.manager");
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  const displayStatus = useMemo(() => {
    if (!result) return "准备就绪";
    if (result.status === "INTERRUPTED") return "待人工审批";
    if (result.state.approval?.decision === "REJECT") return "已驳回";
    if (result.state.execution_result) return "执行记录已创建";
    return "已完成";
  }, [result]);

  function updateField<K extends keyof StartWorkflowRequest>(
    key: K,
    value: StartWorkflowRequest[K],
  ) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function runAction(action: () => Promise<WorkflowResult>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setLoading(true);
    setError(null);
    try {
      setResult(await action());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "请求出现未知错误");
    } finally {
      busyRef.current = false;
      setLoading(false);
    }
  }

  async function handleStart(event: FormEvent) {
    event.preventDefault();
    setSelectedStrategy(0);
    setComment("");
    await runAction(() => startSupplierEOLWorkflow(form));
  }

  async function handleApproval(decision: "APPROVE" | "REJECT") {
    if (!result) return;
    await runAction(() =>
      submitSupplierEOLApproval(result.thread_id, {
        decision,
        comment,
        reviewer: reviewer || undefined,
        selected_strategy_index: selectedStrategy,
      }),
    );
  }

  function resetDemo() {
    setForm(goldenRequest());
    setResult(null);
    setSelectedStrategy(0);
    setComment("");
    setError(null);
  }

  function changeView(next: "workbench" | "data" | "runs") {
    window.location.hash = next;
    setView(next);
  }

  function followSuggestion(suggestion: WorkflowSuggestion) {
    setView("workbench");
    setFormalFlow(suggestion.workflow);
    if (suggestion.workflow === "supplier_eol") {
      setForm((previous) => ({
        ...previous,
        part_number: suggestion.prefill.part_number || "",
        revision: suggestion.prefill.revision || "",
        supplier_code: suggestion.prefill.supplier_code || "",
        supplier_name: "",
        last_time_buy_date: "",
        eol_date: "",
        as_of_date: businessDateShanghai(),
        thread_id: newThreadId(),
      }));
      setResult(null);
    } else {
      setMaterialPrefill({ ...suggestion.prefill });
    }
    window.setTimeout(() => document.getElementById("formal-workflow")?.scrollIntoView({ behavior: "smooth" }), 100);
  }

  const state = result?.state;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark">CP</div>
        <div>
          <p className="eyebrow">工程变更智能管理</p>
          <h1>ChangePilot</h1>
        </div>
        <nav className="primary-nav" aria-label="主导航">
          <button type="button" className={view === "workbench" ? "active" : ""}
            onClick={() => changeView("workbench")}>智能工作台</button>
          <button type="button" className={view === "data" ? "active" : ""}
            onClick={() => changeView("data")}>企业数据中心</button>
          <button type="button" className={view === "runs" ? "active" : ""}
            onClick={() => changeView("runs")}>Agent 运行中心</button>
        </nav>
        <div className={`status-pill status-${displayStatus.toLowerCase().replaceAll(" ", "-")}`}>
          <span className="status-dot" />
          {view === "workbench" ? displayStatus : "只读查看"}
        </div>
      </header>

      <main>
        {view === "data" ? <DataCenter /> : view === "runs" ? <AgentRunCenter /> : <>
        <AssistantPanel onSuggestion={followSuggestion} />
        <div id="formal-workflow" className="formal-flow-tabs" aria-label="正式业务流程">
          <span>正式业务流程</span>
          <button type="button" className={formalFlow === "supplier_eol" ? "active" : ""}
            onClick={() => setFormalFlow("supplier_eol")}>供应商停产分析</button>
          <button type="button" className={formalFlow === "material_substitution" ? "active" : ""}
            onClick={() => setFormalFlow("material_substitution")}>物料替代评估</button>
        </div>
        {formalFlow === "supplier_eol" ? <>
        <section className="hero">
          <div>
            <p className="eyebrow">供应商停产事件</p>
            <h2>从供应风险识别到受控的工程变更执行</h2>
            <p className="hero-copy">
              基于产品结构和 ERP 事实分析影响，生成并评审处置策略，经人工审批后建立执行记录。
            </p>
          </div>
          <div className="stage-strip" aria-label="工作流阶段">
            {["影响分析", "处置策略", "策略评审", "人工审批", "变更执行"].map(
              (stage, index) => (
                <div className="stage" key={stage}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  {stage}
                </div>
              ),
            )}
          </div>
        </section>

        {error && (
          <div className="error-banner" role="alert">
            <strong>请求失败</strong>
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)} aria-label="关闭错误提示">
              ×
            </button>
          </div>
        )}

        <section className="panel event-panel">
          <div className="panel-heading">
            <div>
              <span className="section-number">01</span>
              <h3>供应商停产事件</h3>
              <p>已预填 Golden Scenario 示例数据，可直接启动演示。</p>
            </div>
            {result && (
              <button className="button button-secondary" type="button" onClick={resetDemo}>
                新建工作流
              </button>
            )}
          </div>

          <form onSubmit={handleStart}>
            <fieldset disabled={loading || result !== null}>
              <div className="form-grid">
                <label>
                  <span>供应商</span>
                  <input
                    value={form.supplier_name}
                    onChange={(event) => updateField("supplier_name", event.target.value)}
                    required
                  />
                </label>
                <label>
                  <span>供应商编号</span>
                  <input
                    value={form.supplier_code}
                    onChange={(event) => updateField("supplier_code", event.target.value)}
                    required
                  />
                </label>
                <label>
                  <span>零件号</span>
                  <input
                    value={form.part_number}
                    onChange={(event) => updateField("part_number", event.target.value)}
                    required
                  />
                </label>
                <label>
                  <span>版本号</span>
                  <input
                    value={form.revision}
                    onChange={(event) => updateField("revision", event.target.value)}
                    required
                  />
                </label>
                <label>
                  <span>最后采购日期</span>
                  <input
                    type="date"
                    value={form.last_time_buy_date}
                    onChange={(event) => updateField("last_time_buy_date", event.target.value)}
                    required
                  />
                </label>
                <label>
                  <span>停产日期</span>
                  <input
                    type="date"
                    value={form.eol_date}
                    onChange={(event) => updateField("eol_date", event.target.value)}
                    required
                  />
                </label>
                <label>
                  <span>分析日期</span>
                  <input
                    type="date"
                    value={form.as_of_date}
                    onChange={(event) => updateField("as_of_date", event.target.value)}
                    required
                  />
                </label>
                <label>
                  <span>优先级</span>
                  <select
                    value={form.priority}
                    onChange={(event) =>
                      updateField(
                        "priority",
                        event.target.value as StartWorkflowRequest["priority"],
                      )
                    }
                  >
                    {(["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const).map((value) => (
                      <option value={value} key={value}>{priorityNames[value]}</option>
                    ))}
                  </select>
                </label>
                <label className="span-two">
                  <span>工作流线程 ID</span>
                  <input
                    value={form.thread_id}
                    onChange={(event) => updateField("thread_id", event.target.value)}
                    required
                  />
                </label>
              </div>
              <div className="form-actions">
                <button className="button button-primary" type="submit">
                  {loading ? "正在分析…" : "启动智能分析"}
                </button>
                <span>创建变更案例，并在执行前等待人工审批。</span>
              </div>
            </fieldset>
          </form>
        </section>

        {result && state && (
          <>
            <section className="panel status-panel">
              <div className="panel-heading compact">
                <div>
                  <span className="section-number">02</span>
                  <h3>工作流状态</h3>
                </div>
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={loading}
                  onClick={() => runAction(() => getSupplierEOLWorkflow(result.thread_id))}
                >
                  刷新状态
                </button>
              </div>
              <div className="identity-grid">
                <Identity label="状态" value={displayStatus} accent />
                <Identity label="线程 ID" value={result.thread_id} />
                <Identity label="运行 ID" value={state.run_id} />
                <Identity label="变更案例" value={state.case_number || state.case_id} />
                <Identity label="工程变更请求 ECR" value={state.ecr_number || state.ecr_id} />
                <Identity label="修订轮次" value={String(state.revision_count)} />
              </div>
            </section>

            {state.impact && <ImpactPanel impact={state.impact} />}

            {state.strategies.length > 0 && (
              <StrategyPanel
                strategies={state.strategies}
                selected={selectedStrategy}
                onSelect={setSelectedStrategy}
                disabled={result.status !== "INTERRUPTED" || loading}
              />
            )}

            {state.review_result && <ReviewPanel review={state.review_result} />}

            {result.status === "INTERRUPTED" && result.approval_request && (
              <section className="panel approval-panel">
                <div className="panel-heading">
                  <div>
                    <span className="section-number">06</span>
                    <h3>人工审批</h3>
                    <p>审批完成前不会创建执行记录。</p>
                  </div>
                  <span className="approval-badge">待处理</span>
                </div>
                <div className="approval-grid">
                  <label>
                    <span>审批人</span>
                    <input
                      value={reviewer}
                      onChange={(event) => setReviewer(event.target.value)}
                      disabled={loading}
                    />
                  </label>
                  <label>
                    <span>选择处置策略</span>
                    <select
                      value={selectedStrategy}
                      onChange={(event) => setSelectedStrategy(Number(event.target.value))}
                      disabled={loading}
                    >
                      {state.strategies.map((strategy, index) => (
                        <option value={index} key={`${strategy.strategy_type}-${index}`}>
                          {index + 1}. {strategy.title}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="span-two">
                    <span>审批意见</span>
                    <textarea
                      value={comment}
                      onChange={(event) => setComment(event.target.value)}
                      placeholder="记录本次审批意见…"
                      rows={3}
                      disabled={loading}
                    />
                  </label>
                </div>
                <div className="approval-actions">
                  <button
                    className="button button-danger"
                    type="button"
                    disabled={loading}
                    onClick={() => handleApproval("REJECT")}
                  >
                    驳回
                  </button>
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={loading}
                    onClick={() => handleApproval("APPROVE")}
                  >
                    {loading ? "正在提交…" : "批准所选策略"}
                  </button>
                </div>
              </section>
            )}

            {state.execution_result && <ExecutionPanel execution={state.execution_result} />}

            {state.approval?.decision === "REJECT" && !state.execution_result && (
              <section className="panel rejected-panel">
                <span className="result-icon">×</span>
                <div>
                  <p className="eyebrow">审批结果已记录</p>
                  <h3>工作流已驳回，未执行工程变更。</h3>
                  {state.approval.comment && <p>{state.approval.comment}</p>}
                </div>
              </section>
            )}

            <details className="raw-panel">
              <summary>查看原始工作流响应</summary>
              <pre>{JSON.stringify(result, null, 2)}</pre>
            </details>
          </>
        )}
        </> : <MaterialSubstitutionPanel key={JSON.stringify(materialPrefill)} prefill={materialPrefill} />}
        </>}
      </main>

      <footer>
        <span>ChangePilot V2</span>
        <span>事实分析 · 智能策略 · 人工把关</span>
      </footer>
    </div>
  );
}

function Identity({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string | null;
  accent?: boolean;
}) {
  return (
    <div className={`identity ${accent ? "identity-accent" : ""}`}>
      <span>{label}</span>
      <strong title={value || "暂无数据"}>{value || "—"}</strong>
    </div>
  );
}

function ImpactPanel({ impact }: { impact: SupplierEOLImpact }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <span className="section-number">03</span>
          <h3>影响分析</h3>
          <p>依据 {impact.as_of_date} 的产品结构与 ERP 事实。</p>
        </div>
        <span className="fact-badge">已核验事实</span>
      </div>

      <div className="metric-grid">
        <Metric label="受影响成品" value={impact.product.affected_finished_products.length} />
        <Metric label="可用库存" value={impact.inventory.available_qty} unit="件" />
        <Metric label="已确认开放采购量" value={impact.purchase.committed_open_qty} unit="件" />
        <Metric label="冻结生产需求" value={impact.production.current_frozen_demand_qty} unit="件" />
        <Metric label="受影响销售订单" value={impact.sales.current_exposure_orders} />
        <Metric label="预计供给结余" value={impact.coverage.projected_coverage_delta} unit="件" />
      </div>

      <div className="impact-columns">
        <div className="impact-block">
          <h4>受影响成品</h4>
          <div className="tag-list">
            {impact.product.affected_finished_products.map((product) => (
              <span className="tag" key={product}>{product}</span>
            ))}
          </div>
          <h4>单位成品 BOM 用量</h4>
          <div className="data-list">
            {Object.entries(impact.bom_quantity.requirement_per_product).map(
              ([product, quantity]) => (
                <div key={product}><span>{product}</span><strong>{formatQuantity(quantity)}</strong></div>
              ),
            )}
          </div>
        </div>
        <div className="impact-block">
          <h4>业务影响</h4>
          <div className="data-list">
            <div><span>采购订单</span><strong>{impact.purchase.orders.length}</strong></div>
            <div><span>生产订单</span><strong>{impact.production.current_orders.length}</strong></div>
            <div><span>当前销售暴露数量</span><strong>{formatQuantity(impact.sales.current_exposure_qty)}</strong></div>
            <div><span>对应物料需求量</span><strong>{formatQuantity(impact.sales.material_equivalent.current_material_equivalent_qty)}</strong></div>
          </div>
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>替代料</th><th>版本</th><th>认证状态</th><th>适用性</th><th>替代类型</th></tr>
          </thead>
          <tbody>
            {impact.alternatives.assessments.map((alternative) => (
              <tr key={`${alternative.alternative_part_number}-${alternative.alternative_revision_code}`}>
                <td><strong>{alternative.alternative_part_number}</strong></td>
                <td>{alternative.alternative_revision_code}</td>
                <td><span className={`qualification qualification-${alternative.qualification_status.toLowerCase()}`}>{qualificationNames[alternative.qualification_status] || alternative.qualification_status}</span></td>
                <td>{qualificationNames[alternative.classification] || alternative.classification}</td>
                <td>{qualificationNames[alternative.replacement_type] || alternative.replacement_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Metric({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{formatQuantity(value)}</strong>
      {unit && <small>{unit}</small>}
    </div>
  );
}

function StrategyPanel({
  strategies,
  selected,
  onSelect,
  disabled,
}: {
  strategies: StrategyCandidate[];
  selected: number;
  onSelect: (index: number) => void;
  disabled: boolean;
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <span className="section-number">04</span>
          <h3>候选处置策略</h3>
          <p>选择一项策略提交人工审批。</p>
        </div>
        <span className="count-badge">共 {strategies.length} 项</span>
      </div>
      <div className="strategy-list">
        {strategies.map((strategy, index) => (
          <label className={`strategy-card ${selected === index ? "selected" : ""}`} key={`${strategy.strategy_type}-${index}`}>
            <input
              type="radio"
              name="strategy"
              checked={selected === index}
              onChange={() => onSelect(index)}
              disabled={disabled}
            />
            <div className="strategy-content">
              <div className="strategy-title-row">
                <span className="strategy-type">{strategyNames[strategy.strategy_type] || strategy.strategy_type}</span>
                <span>方案 {index + 1}</span>
              </div>
              <h4>{strategy.title}</h4>
              <p>{strategy.summary}</p>
              <div className="strategy-detail"><strong>依据</strong><span>{strategy.rationale}</span></div>
              <div className="strategy-columns">
                <BulletList title="建议行动" items={strategy.actions} />
                <BulletList title="风险" items={strategy.risks} empty="未列出风险" />
              </div>
            </div>
          </label>
        ))}
      </div>
    </section>
  );
}

function ReviewPanel({ review }: { review: ReviewResult }) {
  return (
    <section className="panel review-panel">
      <div className="panel-heading compact">
        <div>
          <span className="section-number">05</span>
          <h3>策略评审</h3>
        </div>
        <span className={`review-decision review-${review.decision.toLowerCase()}`}>
          {review.decision === "PASS" ? "通过" : "需要修订"}
        </span>
      </div>
      <p className="review-summary">{review.summary}</p>
      <div className="strategy-columns">
        <BulletList title="发现的问题" items={review.issues} empty="未发现阻断问题" />
        <BulletList title="评审建议" items={review.recommendations} empty="暂无建议" />
      </div>
    </section>
  );
}

function BulletList({ title, items, empty }: { title: string; items: string[]; empty?: string }) {
  return (
    <div className="bullet-block">
      <strong>{title}</strong>
      {items.length ? (
        <ul>{items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>
      ) : (
        <p className="muted">{empty}</p>
      )}
    </div>
  );
}

function ExecutionPanel({ execution }: { execution: ExecutionResult }) {
  return (
    <section className="panel execution-panel">
      <div className="execution-heading">
        <span className="result-icon">✓</span>
        <div>
          <p className="eyebrow">已批准并记录</p>
          <h3>工程变更执行记录已创建</h3>
          <p>{execution.summary}</p>
        </div>
        <span className="execution-status">{execution.status === "PENDING" ? "待执行" : execution.status}</span>
      </div>
      <div className="identity-grid">
        <Identity label="策略 ID" value={execution.strategy_id} />
        <Identity label="工程变更单 ECO" value={execution.eco_id} />
        <Identity label="执行任务" value={String(execution.execution_job_ids.length)} />
      </div>
      <div className="job-list">
        {execution.execution_job_ids.map((job) => <code key={job}>{job}</code>)}
      </div>
    </section>
  );
}
