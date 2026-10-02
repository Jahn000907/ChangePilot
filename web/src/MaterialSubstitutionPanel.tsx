import { FormEvent, useEffect, useRef, useState } from "react";

import { materialApi } from "./api";
import type { MaterialSubstitutionRequest, MaterialSubstitutionResult } from "./materialTypes";
import { businessDateShanghai } from "./display";
import {
  canApproveWorkflow, clearWorkflowThread, readWorkflowThread, recoverWorkflow,
  saveWorkflowThread, workflowDisplayStatus,
} from "./workflowRecovery";

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
  const [activeThread, setActiveThread] = useState<string | null>(() => readWorkflowThread("material_substitution"));
  const [manualThread, setManualThread] = useState("");
  const [recovering, setRecovering] = useState(false);
  const [selected, setSelected] = useState(0);
  const [reviewer, setReviewer] = useState("change.manager");
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const threadId = readWorkflowThread("material_substitution");
    if (!threadId) return;
    let active = true;
    setRecovering(true);
    void recoverWorkflow("material_substitution", threadId, materialApi.get, undefined, 2)
      .then((recovered) => {
        if (!active) return;
        if (recovered.kind === "missing") {
          setActiveThread(null);
          setError("已保存的物料替代流程不存在，已清除恢复入口。可新建或输入其他线程 ID。");
        } else {
          setResult(recovered.result);
          setActiveThread(recovered.result.thread_id);
          setForm((previous) => ({ ...previous, thread_id: recovered.result.thread_id }));
          setSelected(recovered.result.state.approval?.selected_strategy_index ?? 0);
        }
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? `流程恢复失败：${reason.message}。可重试，恢复入口仍已保留。` : "流程恢复失败，可重试。");
      })
      .finally(() => { if (active) setRecovering(false); });
    return () => { active = false; };
  }, []);

  function update(key: keyof MaterialSubstitutionRequest, value: string) {
    setForm((previous) => ({ ...previous, [key]: value }));
  }

  async function start(event: FormEvent) {
    event.preventDefault();
    if (busyRef.current) return;
    busyRef.current = true;
    saveWorkflowThread("material_substitution", form.thread_id);
    setActiveThread(form.thread_id);
    setLoading(true);
    setError(null);
    try {
      const started = await materialApi.start({
        ...form,
        candidate_revision_code: form.candidate_revision_code?.trim() || undefined,
      });
      setResult(started);
      saveWorkflowThread("material_substitution", started.thread_id);
      setActiveThread(started.thread_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "替代评估启动失败");
    } finally {
      busyRef.current = false;
      setLoading(false);
    }
  }

  async function restore(threadId: string) {
    if (!threadId.trim() || busyRef.current) return;
    busyRef.current = true;
    setRecovering(true);
    setError(null);
    try {
      const recovered = await recoverWorkflow("material_substitution", threadId, materialApi.get);
      if (recovered.kind === "missing") {
        if (activeThread === threadId) {
          setActiveThread(null);
          setResult(null);
        }
        setError("未找到该物料替代流程，请核对线程 ID。");
      } else {
        setResult(recovered.result);
        setActiveThread(recovered.result.thread_id);
        setForm((previous) => ({ ...previous, thread_id: recovered.result.thread_id }));
        setSelected(recovered.result.state.approval?.selected_strategy_index ?? 0);
        setManualThread("");
      }
    } catch (reason) {
      setError(reason instanceof Error ? `流程恢复失败：${reason.message}。可重试。` : "流程恢复失败，可重试。");
    } finally {
      busyRef.current = false;
      setRecovering(false);
    }
  }

  function newWorkflow() {
    clearWorkflowThread("material_substitution");
    setActiveThread(null);
    setForm(initialForm(prefill));
    setResult(null);
    setSelected(0);
    setManualThread("");
    setError(null);
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
        {activeThread && <button type="button" className="button button-secondary" disabled={loading || recovering} onClick={newWorkflow}>新建工作流</button>}
      </div>
      {error && <p role="alert" className="assistant-error">{error}</p>}
      <form onSubmit={(event) => { event.preventDefault(); void restore(manualThread); }} className="form-actions" aria-label="恢复已有物料替代流程">
        <label><span>已有线程 ID</span><input value={manualThread} onChange={(event) => setManualThread(event.target.value)} placeholder="输入已有 thread_id" required disabled={loading || recovering} /></label>
        <button type="submit" className="button button-secondary" disabled={loading || recovering}>恢复流程</button>
      </form>
      <form onSubmit={start}>
        <fieldset disabled={loading || recovering || activeThread !== null || result !== null}>
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
      {activeThread && <div className="form-actions">
        <span>当前线程：{activeThread}{!result && " · 流程可能仍在执行，可刷新状态"}</span>
        <button type="button" className="button button-secondary" disabled={loading || recovering} onClick={() => void restore(activeThread)}>刷新状态</button>
      </div>}
      {result?.status === "RUNNING" && <p className="material-results">当前流程已启动，正在执行；可刷新状态。</p>}
      {result?.status === "FAILED" && <p className="assistant-error" role="alert">流程执行失败。可核对运行记录，或新建工作流；不会自动重试。</p>}
      {result && <div className="material-results">
        <div className="identity-grid">
          <div className="identity"><span>变更案例</span><strong>{result.state.case_number}</strong></div>
          <div className="identity"><span>工程变更请求</span><strong>{result.state.ecr_number}</strong></div>
          <div className="identity"><span>状态</span><strong>{workflowDisplayStatus(result)}</strong></div>
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
          {strategy.risks.length > 0 && <ul>{strategy.risks.map((risk, riskIndex) => <li key={riskIndex}>{risk}</li>)}</ul>}
        </div>)}
        {result.state.review_result && <p>策略评审：{result.state.review_result.decision === "PASS" ? "通过" : "需要修订"} · {result.state.review_result.summary}</p>}
        {canApproveWorkflow(result) && <div className="material-approval">
          <h4>{result.state.review_exhausted ? "等待人工处理" : "人工审批"}</h4>
          {result.state.review_exhausted && <div role="alert" className="assistant-error">
            <p>{result.approval_request?.human_intervention_reason}</p>
            <p>当前评审仍为“需要修订”。批准表示人工接受评审风险；驳回则不创建执行记录。</p>
            <p>评审轮次：{result.state.review_count}</p>
            <ul>{result.state.review_result?.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>
            <ul>{result.state.review_result?.recommendations.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </div>}
          <div className="form-grid">
            <label><span>审批人</span><input value={reviewer} onChange={(e) => setReviewer(e.target.value)} /></label>
            <label><span>所选策略</span><select value={selected} onChange={(e) => setSelected(Number(e.target.value))}>
              {result.state.strategies.map((strategy, index) => <option value={index} key={index}>{strategy.title}</option>)}
            </select></label>
            <label className="span-two"><span>审批意见</span><textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
          </div>
          <div className="approval-actions">
            <button type="button" className="button button-danger" disabled={loading} onClick={() => void decide("REJECT")}>驳回</button>
            <button type="button" className="button button-primary" disabled={loading} onClick={() => void decide("APPROVE")}>{result.state.review_exhausted ? "知悉风险并批准所选策略" : "批准所选策略"}</button>
          </div>
        </div>}
        {result.state.execution_result && <p>已创建 ECO {result.state.execution_result.eco_id} 和 {result.state.execution_result.execution_job_ids.length} 项待执行记录；尚未修改 ERP 或 BOM。</p>}
        {result.state.approval?.decision === "REJECT" && <p>评估已驳回，未创建执行记录。</p>}
      </div>}
    </section>
  );
}
