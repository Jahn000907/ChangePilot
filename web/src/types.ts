export interface StartWorkflowRequest {
  thread_id: string;
  part_number: string;
  revision: string;
  supplier_code: string;
  supplier_name: string;
  last_time_buy_date: string;
  eol_date: string;
  as_of_date: string;
  priority: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  requested_by: string;
  source_type: string;
}

export interface StrategyCandidate {
  strategy_type: string;
  title: string;
  summary: string;
  rationale: string;
  actions: string[];
  risks: string[];
}

export interface ReviewResult {
  decision: "PASS" | "REVISE";
  summary: string;
  issues: string[];
  recommendations: string[];
}

export interface AlternativeAssessment {
  alternative_part_number: string;
  alternative_revision_code: string;
  qualification_status: string;
  replacement_type: string;
  classification: string;
}

export interface SupplierEOLImpact {
  part_number: string;
  revision_code: string;
  as_of_date: string;
  product: {
    affected_finished_products: string[];
    affected_assemblies: string[];
  };
  bom_quantity: {
    requirement_per_product: Record<string, string | number>;
  };
  inventory: {
    total_on_hand: string;
    total_reserved: string;
    available_qty: string;
    locations: string[];
  };
  purchase: {
    committed_open_qty: string;
    potential_qty: string;
    blocked_qty: string;
    orders: unknown[];
  };
  production: {
    current_frozen_demand_qty: string;
    current_orders: string[];
    historical_orders: string[];
  };
  sales: {
    current_exposure_orders: number;
    current_exposure_qty: string;
    potential_exposure_orders: number;
    potential_exposure_qty: string;
    material_equivalent: {
      current_material_equivalent_qty: string;
      potential_material_equivalent_qty: string;
    };
  };
  alternatives: {
    assessments: AlternativeAssessment[];
    eligible_count: number;
    requires_review_count: number;
    ineligible_count: number;
  };
  coverage: {
    inventory_coverage_delta: string;
    projected_coverage_delta: string;
  };
}

export interface ExecutionResult {
  strategy_id: string;
  eco_id: string;
  execution_job_ids: string[];
  status: string;
  summary: string;
}

export interface HumanApproval {
  decision: "APPROVE" | "REJECT";
  comment: string;
  reviewer?: string;
  selected_strategy_index: number;
}

export interface ApprovalRequest {
  case_id: string;
  case_number: string;
  ecr_id: string;
  ecr_number: string;
  impact_summary: Record<string, unknown>;
  strategies: StrategyCandidate[];
  review_result: ReviewResult;
}

export interface WorkflowState {
  run_id: string | null;
  case_id: string | null;
  case_number: string | null;
  case_status: string | null;
  ecr_id: string | null;
  ecr_number: string | null;
  ecr_status: string | null;
  impact: SupplierEOLImpact | null;
  strategies: StrategyCandidate[];
  review_result: ReviewResult | null;
  revision_count: number;
  approval: HumanApproval | null;
  approval_status: string;
  execution_result: ExecutionResult | null;
  execution_status: string;
  status: string;
  error: string | null;
}

export interface WorkflowResult {
  thread_id: string;
  status: "INTERRUPTED" | "COMPLETED";
  state: WorkflowState;
  approval_request: ApprovalRequest | null;
  interrupt_id: string | null;
}
