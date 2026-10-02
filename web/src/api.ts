import type {
  HumanApproval,
  StartWorkflowRequest,
  WorkflowResult,
} from "./types";
import type {
  DataSummary, InventoryRow, ProductionOrderDetail, ProductionOrderRow,
  PurchaseOrderDetail, PurchaseOrderRow, SalesOrderDetail, SalesOrderRow,
  SupplierPartRow, SupplierRow,
} from "./dataTypes";
import type {
  AssistantTurnResult, ConversationDetail, ConversationSummary,
} from "./assistantTypes";
import type { MaterialSubstitutionRequest, MaterialSubstitutionResult } from "./materialTypes";
import type { AgentRunDetail, AgentRunSummary } from "./observabilityTypes";
import { supplierSearchValue } from "./supplierSearch";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");
const WORKFLOW_PATH = "/api/v1/workflows/supplier-eol";
const DATA_PATH = "/api/v1/data";
const ASSISTANT_PATH = "/api/v1/assistant/conversations";
const MATERIAL_PATH = "/api/v1/workflows/material-substitution";
const AGENT_RUNS_PATH = "/api/v1/agent-runs";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
  } catch {
    throw new Error("无法连接服务，请检查网络后重试。");
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message = response.status >= 500 && response.status !== 503
      ? "服务暂时不可用，请稍后重试。"
      : Array.isArray(detail)
      ? detail.map((item) => item.msg).join("; ")
      : detail || `请求失败（HTTP ${response.status}）`;
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function query(parameters: Record<string, string>): string {
  const values = Object.entries(parameters).filter(([, value]) => value.trim());
  return values.length ? `?${new URLSearchParams(values).toString()}` : "";
}

export const dataApi = {
  summary: () => request<DataSummary>(`${DATA_PATH}/summary`),
  suppliers: (search = "") =>
    request<SupplierRow[]>(`${DATA_PATH}/suppliers${query({ search })}`),
  supplierParts: (supplier = "", partNumber = "") =>
    request<SupplierPartRow[]>(
      `${DATA_PATH}/supplier-parts${query({ supplier: supplierSearchValue(supplier), part_number: partNumber })}`,
    ),
  inventory: (partNumber = "") =>
    request<InventoryRow[]>(`${DATA_PATH}/inventory${query({ part_number: partNumber })}`),
  purchaseOrders: () => request<PurchaseOrderRow[]>(`${DATA_PATH}/purchase-orders`),
  purchaseOrder: (number: string) =>
    request<PurchaseOrderDetail>(`${DATA_PATH}/purchase-orders/${encodeURIComponent(number)}`),
  productionOrders: () => request<ProductionOrderRow[]>(`${DATA_PATH}/production-orders`),
  productionOrder: (number: string) =>
    request<ProductionOrderDetail>(`${DATA_PATH}/production-orders/${encodeURIComponent(number)}`),
  salesOrders: () => request<SalesOrderRow[]>(`${DATA_PATH}/sales-orders`),
  salesOrder: (number: string) =>
    request<SalesOrderDetail>(`${DATA_PATH}/sales-orders/${encodeURIComponent(number)}`),
};

export const assistantApi = {
  create: (title = "新对话") => request<ConversationSummary>(ASSISTANT_PATH, {
    method: "POST", body: JSON.stringify({ title }),
  }),
  list: () => request<ConversationSummary[]>(ASSISTANT_PATH),
  get: (id: string) => request<ConversationDetail>(`${ASSISTANT_PATH}/${encodeURIComponent(id)}`),
  remove: (id: string) => request<void>(`${ASSISTANT_PATH}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  }),
  send: (id: string, content: string) => request<AssistantTurnResult>(
    `${ASSISTANT_PATH}/${encodeURIComponent(id)}/messages`,
    { method: "POST", body: JSON.stringify({ content }) },
  ),
};

export const materialApi = {
  start: (payload: MaterialSubstitutionRequest) => request<MaterialSubstitutionResult>(
    MATERIAL_PATH, { method: "POST", body: JSON.stringify(payload) },
  ),
  get: (id: string) => request<MaterialSubstitutionResult>(
    `${MATERIAL_PATH}/${encodeURIComponent(id)}`,
  ),
  approve: (id: string, approval: HumanApproval) => request<MaterialSubstitutionResult>(
    `${MATERIAL_PATH}/${encodeURIComponent(id)}/approval`,
    { method: "POST", body: JSON.stringify(approval) },
  ),
};

export const agentRunsApi = {
  list: () => request<AgentRunSummary[]>(AGENT_RUNS_PATH),
  get: (runId: string) => request<AgentRunDetail>(
    `${AGENT_RUNS_PATH}/${encodeURIComponent(runId)}`,
  ),
};

export function startSupplierEOLWorkflow(
  payload: StartWorkflowRequest,
): Promise<WorkflowResult> {
  return request<WorkflowResult>(WORKFLOW_PATH, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getSupplierEOLWorkflow(
  threadId: string,
): Promise<WorkflowResult> {
  return request<WorkflowResult>(
    `${WORKFLOW_PATH}/${encodeURIComponent(threadId)}`,
  );
}

export function submitSupplierEOLApproval(
  threadId: string,
  approval: HumanApproval,
): Promise<WorkflowResult> {
  return request<WorkflowResult>(
    `${WORKFLOW_PATH}/${encodeURIComponent(threadId)}/approval`,
    {
      method: "POST",
      body: JSON.stringify(approval),
    },
  );
}
