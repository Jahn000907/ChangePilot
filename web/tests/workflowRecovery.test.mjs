import assert from "node:assert/strict";
import test from "node:test";

import {
  canApproveWorkflow,
  clearWorkflowThread,
  readActiveWorkflowKind,
  readWorkflowThread,
  recoverWorkflow,
  saveWorkflowThread,
  saveActiveWorkflowKind,
  workflowDisplayStatus,
} from "../src/workflowRecovery.ts";

function storage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
    values,
  };
}

function snapshot(status, { decision = null, exhausted = false, execution = null } = {}) {
  return {
    status,
    approval_request: status === "INTERRUPTED" ? { case_number: "CASE-1" } : null,
    state: {
      review_exhausted: exhausted,
      approval: decision ? { decision } : null,
      execution_result: execution,
    },
  };
}

test("two formal workflow pointers remain isolated and new workflow clears only its own pointer", () => {
  const local = storage();
  saveWorkflowThread("supplier_eol", "eol-1", local);
  saveWorkflowThread("material_substitution", "sub-1", local);
  assert.equal(readWorkflowThread("supplier_eol", local), "eol-1");
  assert.equal(readWorkflowThread("material_substitution", local), "sub-1");
  assert.equal(local.values.size, 2);
  saveActiveWorkflowKind("material_substitution", local);
  assert.equal(readActiveWorkflowKind(local), "material_substitution");
  clearWorkflowThread("supplier_eol", local);
  assert.equal(readWorkflowThread("supplier_eol", local), null);
  assert.equal(readWorkflowThread("material_substitution", local), "sub-1");
  assert.equal(readActiveWorkflowKind(local), "material_substitution");
});

for (const kind of ["supplier_eol", "material_substitution"]) {
  test(`${kind} remount restores each server state and approval controls`, async () => {
    const local = storage();
    saveWorkflowThread(kind, "saved-1", local);
    const seen = [];
    for (const expected of [
      snapshot("RUNNING"), snapshot("INTERRUPTED", { exhausted: true }),
      snapshot("COMPLETED", { decision: "APPROVE", execution: { eco_id: "ECO-1" } }),
      snapshot("COMPLETED", { decision: "REJECT" }), snapshot("FAILED"),
    ]) {
      const recovered = await recoverWorkflow(kind, readWorkflowThread(kind, local),
        async (id) => { seen.push(id); return expected; }, local);
      assert.equal(recovered.kind, "found");
      assert.deepEqual(recovered.result, expected);
      assert.equal(canApproveWorkflow(recovered.result), expected.status === "INTERRUPTED");
    }
    assert.deepEqual(seen, Array(5).fill("saved-1"));
    assert.equal(workflowDisplayStatus(snapshot("RUNNING")), "正在执行");
    assert.equal(workflowDisplayStatus(snapshot("INTERRUPTED", { exhausted: true })), "等待人工处理");
    assert.equal(workflowDisplayStatus(snapshot("COMPLETED", { decision: "APPROVE", execution: {} })), "执行记录已创建");
    assert.equal(workflowDisplayStatus(snapshot("COMPLETED", { decision: "REJECT" })), "已驳回");
    assert.equal(workflowDisplayStatus(snapshot("FAILED")), "执行失败");
  });

  test(`${kind} clears only a confirmed 404, but retains pointer on network failure`, async () => {
    const local = storage();
    saveWorkflowThread(kind, "saved-2", local);
    await assert.rejects(
      recoverWorkflow(kind, "saved-2", async () => { throw new Error("network"); }, local),
      /network/,
    );
    assert.equal(readWorkflowThread(kind, local), "saved-2");
    const missing = await recoverWorkflow(kind, "saved-2", async () => {
      throw Object.assign(new Error("missing"), { status: 404 });
    }, local);
    assert.equal(missing.kind, "missing");
    assert.equal(readWorkflowThread(kind, local), null);
  });

  test(`${kind} manual recovery switches pointer; an early 404 can recover on retry`, async () => {
    const local = storage();
    saveWorkflowThread(kind, "old-thread", local);
    const restored = await recoverWorkflow(kind, "manual-thread",
      async (id) => { assert.equal(id, "manual-thread"); return snapshot("INTERRUPTED"); }, local);
    assert.equal(restored.kind, "found");
    assert.equal(readWorkflowThread(kind, local), "manual-thread");
    let calls = 0;
    const retried = await recoverWorkflow(kind, "manual-thread", async () => {
      calls += 1;
      if (calls === 1) throw Object.assign(new Error("not yet checkpointed"), { status: 404 });
      return snapshot("RUNNING");
    }, local, 1);
    assert.equal(retried.kind, "found");
    assert.equal(calls, 2);
    assert.equal(readWorkflowThread(kind, local), "manual-thread");
  });
}
