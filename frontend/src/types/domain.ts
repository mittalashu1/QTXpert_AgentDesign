export type UserRole =
  | "admin"
  | "qa_lead"
  | "qa_engineer"
  | "business_analyst"
  | "automation_engineer"
  | "viewer";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface UploadedAsset {
  id: string;
  project_id: string | null;
  filename: string;
  extension: string;
  content_type: string | null;
  category: "apk" | "ipa" | "document" | "test_data" | "media" | "other" | string;
  source_module: string;
  storage_backend: string;
  size_bytes: number;
  sha256: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export type DocumentProfile = "general" | "banking" | "retail" | "saas" | "government";
export type DocumentFindingStatus = "open" | "accepted" | "rejected" | "resolved" | "needs_clarification";

export interface DocumentInventoryItem {
  asset_id: string;
  filename: string;
  document_type: string;
  classification_confidence: number;
  quality_score: number;
  testability_score: number;
  issue_count: number;
  status: "good" | "attention" | "critical" | string;
}

export interface DocumentFinding {
  id: string;
  run_id: string;
  asset_id: string | null;
  finding_key: string;
  category: string;
  severity: "critical" | "high" | "medium" | "low" | string;
  confidence: number;
  title: string;
  description: string;
  testing_impact: string | null;
  original_text: string | null;
  suggested_refinement: string | null;
  evidence: Array<{
    asset_id?: string | null;
    filename?: string;
    excerpt?: string;
    reason?: string;
  }> | null;
  status: DocumentFindingStatus | string;
  resolution_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentAnalysisRun {
  id: string;
  project_id: string;
  requested_by_id: string;
  status: "queued" | "extracting" | "analyzing" | "completed" | "failed" | string;
  profile: DocumentProfile | string;
  asset_ids: string[];
  document_inventory: DocumentInventoryItem[] | null;
  knowledge_model: Record<string, string[]> | null;
  scores: Record<string, number> | null;
  missing_documents: Array<{ document_type: string; priority: string; reason: string }> | null;
  recommendations: string[] | null;
  readiness_score: number;
  readiness_status: string;
  summary: string | null;
  error_message: string | null;
  published_requirement_id: string | null;
  findings: DocumentFinding[];
  created_at: string;
  updated_at: string;
}

export type RequirementSource =
  | "brd_upload"
  | "jira_export"
  | "jira_live"
  | "confluence"
  | "direct_prompt";

export type RequirementStatus = "received" | "normalized" | "failed";

export interface Requirement {
  id: string;
  project_id: string;
  title: string;
  source: RequirementSource;
  status: RequirementStatus;
  extracted_metadata: Record<string, unknown> | null;
  created_at: string;
}

export type RunStatus =
  | "pending"
  | "normalizing"
  | "analyzing"
  | "generating_scenarios"
  | "generating_test_cases"
  | "risk_analysis"
  | "completed"
  | "failed";

export type Priority = "critical" | "high" | "medium" | "low";
export type Severity = "blocker" | "critical" | "major" | "minor" | "trivial";
export type RiskLevel = "high" | "medium" | "low";

export interface TestCase {
  id: string;
  test_case_key: string;
  requirement_traceability: string | null;
  test_type: string;
  scenario: string;
  objective: string;
  priority: Priority;
  severity: Severity;
  preconditions: string | null;
  test_data: Record<string, unknown> | null;
  steps: string[];
  expected_result: string;
  post_conditions: string | null;
  is_automation_candidate: boolean;
  automation_type: string | null;
  risk_level: RiskLevel;
}

export interface GenerationRun {
  id: string;
  project_id: string;
  status: RunStatus;
  llm_provider: string;
  llm_model: string;
  generation_profile: "smoke" | "feature" | "regression" | "deep_regression";
  title?: string | null;
  requirement_summary: string | null;
  business_rules: string[] | null;
  functional_breakdown: Record<string, unknown>[] | null;
  test_scenarios: Record<string, unknown>[] | null;
  risk_analysis: Record<string, unknown> | null;
  processing_time_seconds: number | null;
  error_message: string | null;
  created_at: string;
  test_cases: TestCase[];
}

export interface GenerationRunSummary {
  id: string;
  project_id: string;
  status: RunStatus;
  llm_provider: string;
  llm_model: string;
  generation_profile: "smoke" | "feature" | "regression" | "deep_regression" | string;
  title?: string | null;
  requirement_summary: string | null;
  first_scenario: string | null;
  test_case_count: number;
  created_at: string;
}

export type ExecutionStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ExecutionResultStatus = "pending" | "passed" | "failed" | "blocked" | "skipped";

export interface Defect {
  id: string;
  defect_key: string;
  title: string;
  severity: string;
  status: string;
}

export interface ExecutionResult {
  id: string;
  test_case_id: string;
  execution_plan_case_id: string | null;
  test_case_key: string;
  scenario: string;
  status: ExecutionResultStatus;
  duration_ms: number | null;
  error_message: string | null;
  evidence: Record<string, unknown> | null;
  defects: Defect[];
}

export interface ExecutionRun {
  id: string;
  project_id: string;
  execution_plan_id: string | null;
  name: string;
  status: ExecutionStatus;
  browser: string;
  base_url: string;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  blocked_tests: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  results: ExecutionResult[];
}

export type ExecutionSuiteType = "smoke" | "feature" | "regression" | "deep_regression";
export type ExecutionPlanStatus = "draft" | "ready" | "blocked" | "queued" | "running" | "completed" | "failed" | string;
export type ExecutionPlanReadiness = "pending" | "not_selected" | "manual_review" | "ready" | "blocked" | "approval_required" | string;

export interface ExecutionPlanCase {
  id: string;
  source_test_case_id: string | null;
  selection_order: number;
  selected: boolean;
  execution_mode: "automated" | "manual";
  readiness: ExecutionPlanReadiness;
  blocker_reason: string | null;
  test_case_key: string;
  requirement_traceability: string | null;
  test_type: string;
  scenario: string;
  objective: string;
  priority: string;
  severity: string;
  preconditions: string | null;
  test_data: Record<string, unknown> | null;
  steps: string[];
  expected_result: string;
  post_conditions: string | null;
  is_automation_candidate: boolean;
  automation_type: string | null;
  risk_level: string;
}

export interface ExecutionPlan {
  id: string;
  project_id: string;
  source_generation_run_id: string | null;
  name: string;
  suite_type: ExecutionSuiteType;
  status: ExecutionPlanStatus;
  source_title: string | null;
  source_created_at: string | null;
  created_at: string;
  updated_at: string;
  total_cases: number;
  selected_cases: number;
  selected_automated_cases: number;
  ready_cases: number;
  blocked_cases: number;
  cases: ExecutionPlanCase[];
}

export interface DashboardSummary {
  requirements: number;
  test_cases: number;
  execution_runs: number;
  pass_rate: number;
  open_defects: number;
  automation_candidates: number;
  recent_runs: ExecutionRun[];
}

export interface AICostBreakdown {
  provider: string;
  model: string;
  tier: string;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  unpriced_requests: number;
}

export interface AzureActualCost {
  configured: boolean;
  connected: boolean;
  actual_cost: number | null;
  currency: string | null;
  last_synced_at: string | null;
  scope: string | null;
  resource_name: string | null;
  error: string | null;
}

export interface AICostSummary {
  period_days: number;
  since: string;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  unpriced_requests: number;
  by_model: AICostBreakdown[];
  azure: AzureActualCost;
  variance_usd: number | null;
}

export const EXPORT_FORMATS = [
  { value: "json", label: "JSON" },
  { value: "csv", label: "CSV" },
  { value: "excel", label: "Excel (.xlsx)" },
  { value: "markdown", label: "Markdown" },
  { value: "testrail", label: "TestRail" },
  { value: "zephyr", label: "Zephyr" },
  { value: "xray", label: "Xray" },
  { value: "azure_devops", label: "Azure DevOps Test Plans" },
] as const;

