import { FormEvent, useRef, useState } from "react";

import { materialApi } from "./api";
import type { MaterialSubstitutionRequest, MaterialSubstitutionResult } from "./materialTypes";
import { businessDateShanghai } from "./display";

interface Props {
  prefill?: Record<string, string>;
}

const qualificationLabels: Record<string, string> = {
  QUALIFIED: "已认证", CONDITIONAL: "有条件认证",
  UNQUALIFIED: "未认证", NOT_LISTED: "未发现替代关系",
};

function initialForm(prefill?: Record<string, string>): MaterialSubstitutionRequest {
  const fromChat = prefill !== undefined;
  return {
    thread_id: `sub-${Date.now().toString(36)}`,
    part_number: prefill?.part_number || (fromChat ? "" : "BRG-6204-A"),
    revision_code: prefill?.revision || (fromChat ? "" : "A"),
    candidate_part_number: prefill?.candidate_part_number || (fromChat ? "" : "BRG-6204-B"),
    candidate_revision_code: prefill?.candidate_revision_code || (fromChat ? "" : "A"),
    as_of_date: fromChat ? businessDateShanghai() : "2026-09-20",
    requested_by: "web.user",
    priority: "HIGH",
  };
}

export default function MaterialSubstitutionPanel({ prefill }: Props) {
  const [form, setForm] = useState<MaterialSubstitutionRequest>(() => initialForm(prefill));
  const [result, setResult] = useState<MaterialSubstitutionResult | null>(null);
  const [selected, setSelected] = useState(0);
  const [reviewer, setReviewer] = useState("change.manager");
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  function update(key: keyof MaterialSubstitutionRequest, value: string) {
    setForm((previous) => ({ ...previous, [key]: value }));
  }

  async function start(event: FormEvent) {
    event.preventDefault();
    if (busyRef.current) return;
    busyRef.current = true;
    setLoading(true);
    setError(null);
    try {
      setResult(await materialApi.start({
        ...form,
        candidate_revision_code: form.candidate_revision_code?.trim() || undefined,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "替代评估启动失败");
    } finally {
      busyRef.current = false;
      setLoading(false);
    }
  }

  async function decide(decision: "APPROVE" | "REJECT") {
    if (!result || busyRef.current) return;
    busyRef.current = true;
    setLoading(true);
    setError(null);
    try {
      setResult(await materialApi.approve(result.thread_id, {
        decision, comment, reviewer: reviewer || undefined, selected_strategy_index: selected,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审批提交失败");
    } finally {
      busyRef.current = false;
      setLoading(false);
    }
  }

  const impact = result?.state.impact;
  return (
    <section className="panel material-panel">
      <div className="panel-heading">
        <div>
          <span className="section-number">02</span>
          <h3>物料替代评估</h3>
          <p>核对产品使用、资格、库存、采购及生产事实，经策略评审和人工审批后创建执行记录。</p>
        </div>
        {result && <button type="button" className="button button-secondary" onClick={() => {
          setForm(initialForm(prefill)); setResult(null); setError(null);
        }}>新建评估</button>}
      </div>
      {error && <p role="alert" className="assistant-error">{error}</p>}
      <form onSubmit={start}>
        <fieldset disabled={loading || result !== null}>
          <div className="form-grid">
            <label><span>原零件号</span><input value={form.part_number} required onChange={(e) => update("part_number", e.target.value)} /></label>
            <label><span>原零件版本</span><input value={form.revision_code} required onChange={(e) => update("revision_code", e.target.value)} /></label>
            <label><span>候选替代零件</span><input value={form.candidate_part_number} required onChange={(e) => update("candidate_part_number", e.target.value)} /></label>
            <label><span>候选版本（可留空以核对唯一版本）</span><input value={form.candidate_revision_code || ""} onChange={(e) => update("candidate_revision_code", e.target.value)} /></label>
            <label><span>分析日期</span><input type="date" value={form.as_of_date} required onChange={(e) => update("as_of_date", e.target.value)} /></label>
            <label><span>工作流线程 ID</span><input value={form.thread_id} required onChange={(e) => update("thread_id", e.target.value)} /></label>
          </div>
          <div className="form-actions"><button className="button button-primary" type="submit">{loading ? "评估中…" : "启动替代评估"}</button></div>
        </fieldset>
      </form>
      {result && <div className="material-results">
        <div className="identity-grid">
          <div className="identity"><span>变更案例</span><strong>{result.state.case_number}</strong></div>
          <div className="identity"><span>工程变更请求</span><strong>{result.state.ecr_number}</strong></div>
          <div className="identity"><span>状态</span><strong>{result.status === "INTERRUPTED" ? "待人工审批" : "已完成"}</strong></div>
        </div>
        {impact && <div className="metric-grid">
          <div className="metric"><span>候选料</span><strong>{impact.candidate_part_number}/{impact.candidate_revision_code}</strong></div>
          <div className="metric"><span>资格状态</span><strong>{qualificationLabels[impact.qualification_status] || impact.qualification_status}</strong></div>
          <div className="metric"><span>受影响成品</span><strong>{impact.affected_products.length}</strong></div>
          <div className="metric"><span>关联生产需求</span><strong>{impact.original_production.rows.length}</strong></div>
        </div>}
        {impact && <p>受影响产品：{impact.affected_products.join("、") || "暂无"}</p>}
        {result.state.strategies.map((strategy, index) => <div className="material-strategy" key={`${strategy.title}-${index}`}>
          <strong>{index + 1}. {strategy.title}</strong><p>{strategy.summary}</p>
          <small>依据：{strategy.rationale}</small>
        </div>)}
        {result.state.review_result && <p>策略评审：{result.state.review_result.decision === "PASS" ? "通过" : "需要修订"} · {result.state.review_result.summary}</p>}
        {result.status === "COMPLETED" && result.state.review_result?.decision === "REVISE" && !result.state.approval &&
          <p>策略修订次数已达上限，未进入人工审批或执行。</p>}
        {result.status === "INTERRUPTED" && <div className="material-approval">
          <h4>人工审批</h4>
          <div className="form-grid">
            <label><span>审批人</span><input value={reviewer} onChange={(e) => setReviewer(e.target.value)} /></label>
            <label><span>所选策略</span><select value={selected} onChange={(e) => setSelected(Number(e.target.value))}>
              {result.state.strategies.map((strategy, index) => <option value={index} key={index}>{strategy.title}</option>)}
            </select></label>
            <label className="span-two"><span>审批意见</span><textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
          </div>
          <div className="approval-actions">
            <button type="button" className="button button-danger" disabled={loading} onClick={() => void decide("REJECT")}>驳回</button>
            <button type="button" className="button button-primary" disabled={loading} onClick={() => void decide("APPROVE")}>批准所选策略</button>
          </div>
        </div>}
        {result.state.execution_result && <p>已创建 ECO {result.state.execution_result.eco_id} 和 {result.state.execution_result.execution_job_ids.length} 项待执行记录；尚未修改 ERP 或 BOM。</p>}
        {result.state.approval?.decision === "REJECT" && <p>评估已驳回，未创建执行记录。</p>}
      </div>}
    </section>
  );
}
