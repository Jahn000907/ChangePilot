import type { ExecutionResult, HumanApproval, ReviewResult, StrategyCandidate } from "./types";

export interface MaterialSubstitutionRequest {
  thread_id: string;
  part_number: string;
  revision_code: string;
  candidate_part_number: string;
  candidate_revision_code?: string;
  as_of_date: string;
  requested_by: string;
  priority: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
}

export interface MaterialSubstitutionResult {
  thread_id: string;
  status: "INTERRUPTED" | "COMPLETED";
  state: {
    run_id: string;
    case_number: string | null;
    ecr_number: string | null;
    impact: {
      candidate_part_number: string;
      candidate_revision_code: string;
      qualification_status: string;
      affected_products: string[];
      original_production: { rows: { order_number: string; required_qty: string }[] };
      original_inventory: { rows: { qty_on_hand: string }[] };
    } | null;
    strategies: StrategyCandidate[];
    review_result: ReviewResult | null;
    approval: HumanApproval | null;
    execution_result: ExecutionResult | null;
  };
  approval_request: unknown | null;
}
