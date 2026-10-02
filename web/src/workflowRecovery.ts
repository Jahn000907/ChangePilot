/** Persist only the current formal workflow identity; the server owns its state. */
export type WorkflowKind = "supplier_eol" | "material_substitution";
type PointerStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const keys: Record<WorkflowKind, string> = {
  supplier_eol: "changepilot.workflow.supplier_eol.thread_id",
  material_substitution: "changepilot.workflow.material_substitution.thread_id",
};
const activeKindKey = "changepilot.workflow.active_type";

function storageOrNull(storage?: PointerStorage): PointerStorage | null {
  try {
    return storage ?? window.localStorage;
  } catch {
    return null;
  }
}

export function readWorkflowThread(kind: WorkflowKind, storage?: PointerStorage): string | null {
  try {
    return storageOrNull(storage)?.getItem(keys[kind])?.trim() || null;
  } catch {
    return null;
  }
}

export function saveWorkflowThread(kind: WorkflowKind, threadId: string, storage?: PointerStorage): void {
  try {
    storageOrNull(storage)?.setItem(keys[kind], threadId.trim());
  } catch {
    // Disabled storage must not prevent the workflow itself from running.
  }
}

export function clearWorkflowThread(kind: WorkflowKind, storage?: PointerStorage): void {
  try {
    storageOrNull(storage)?.removeItem(keys[kind]);
  } catch {
    // The UI can still start a new workflow without persistent storage.
  }
}

export function readActiveWorkflowKind(storage?: PointerStorage): WorkflowKind {
  try {
    return storageOrNull(storage)?.getItem(activeKindKey) === "material_substitution"
      ? "material_substitution" : "supplier_eol";
  } catch {
    return "supplier_eol";
  }
}

export function saveActiveWorkflowKind(kind: WorkflowKind, storage?: PointerStorage): void {
  try {
    storageOrNull(storage)?.setItem(activeKindKey, kind);
  } catch {
    // The selected tab remains usable when browser storage is unavailable.
  }
}

function isNotFound(error: unknown): boolean {
  return typeof error === "object" && error !== null && "status" in error && error.status === 404;
}

export type RecoveryResult<T> = { kind: "found"; result: T } | { kind: "missing" };

type WorkflowSnapshot = {
  status: "RUNNING" | "INTERRUPTED" | "COMPLETED" | "FAILED";
  approval_request: unknown | null;
  state: {
    review_exhausted: boolean;
    approval: { decision: "APPROVE" | "REJECT" } | null;
    execution_result: unknown | null;
  };
};

export function canApproveWorkflow(result: WorkflowSnapshot): boolean {
  return result.status === "INTERRUPTED" && result.approval_request !== null;
}

export function workflowDisplayStatus(result: WorkflowSnapshot): string {
  if (result.status === "RUNNING") return "正在执行";
  if (result.status === "FAILED") return "执行失败";
  if (result.status === "INTERRUPTED") {
    return result.state.review_exhausted ? "等待人工处理" : "待人工审批";
  }
  if (result.state.approval?.decision === "REJECT") return "已驳回";
  if (result.state.execution_result) return "执行记录已创建";
  return "已结束（未执行）";
}

export async function recoverWorkflow<T>(
  kind: WorkflowKind,
  threadId: string,
  getWorkflow: (id: string) => Promise<T>,
  storage?: PointerStorage,
  notFoundRetries = 0,
): Promise<RecoveryResult<T>> {
  const id = threadId.trim();
  if (!id) return { kind: "missing" };
  for (let attempt = 0; ; attempt += 1) {
    try {
      const result = await getWorkflow(id);
      saveWorkflowThread(kind, id, storage);
      return { kind: "found", result };
    } catch (error) {
      if (!isNotFound(error)) throw error;
      if (attempt < notFoundRetries) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        continue;
      }
      if (readWorkflowThread(kind, storage) === id) clearWorkflowThread(kind, storage);
      return { kind: "missing" };
    }
  }
}
