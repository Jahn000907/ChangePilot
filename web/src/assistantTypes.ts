export interface AssistantContext {
  current_product: string | null;
  current_part: string | null;
  current_revision: string | null;
  current_supplier_code: string | null;
  current_purchase_order: string | null;
  current_production_order: string | null;
  current_sales_order: string | null;
  current_focus: "product" | "part" | "supplier" | "purchase_order" | "production_order" | "sales_order" | null;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  status: "ACTIVE" | "ARCHIVED";
  context: AssistantContext;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[];
}

export interface WorkflowSuggestion {
  workflow: "supplier_eol" | "material_substitution";
  label: string;
  prefill: Record<string, string>;
}

export interface AssistantTurnResult {
  conversation_id: string;
  assistant_message: ConversationMessage;
  context: AssistantContext;
  workflow_suggestion: WorkflowSuggestion | null;
  answer_status: "SUCCESS" | "NO_DATA" | "MISSING_INPUT" | "TOOL_ERROR" | "LLM_ERROR";
}
