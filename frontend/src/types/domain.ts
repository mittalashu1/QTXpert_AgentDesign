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
