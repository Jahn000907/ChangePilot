export interface AgentRunSummary {
  run_id: string;
  thread_id: string | null;
  workflow_name: string;
  status: string;
  analysis_status: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  error_summary: string | null;
  has_supervisor: boolean;
  agent_count: number;
  selected_agents: string[];
  called_tools: string[];
}

export interface ToolCallView {
  tool_call_id: string;
  step_id: string | null;
  tool_name: string;
  agent_name: string;
  status: string;
  duration_ms: number | null;
  created_at: string;
  arguments: Record<string, string | number | boolean | null>;
  result_summary: string;
}

export interface AgentStepView {
  step_id: string;
  node_name: string;
  agent_name: string | null;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  summary: string;
  tool_calls: ToolCallView[];
}

export interface AuditEventView {
  audit_id: string;
  action: string;
  actor_type: string;
  object_type: string;
  object_id: string;
  created_at: string;
}

export interface ExecutionJobView {
  execution_job_id: string;
  eco_id: string;
  action_type: string;
  title: string;
  description: string;
  owner_department: string | null;
  status: string;
  related_part_number: string | null;
  created_at: string;
}

export interface AgentRunDetail extends AgentRunSummary {
  steps: AgentStepView[];
  audit_events: AuditEventView[];
  execution_jobs: ExecutionJobView[];
}
