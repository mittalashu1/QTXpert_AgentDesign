import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Dialog, DialogActions,
  DialogContent, DialogTitle, Divider, FormControl, FormControlLabel, Grid, InputLabel,
  IconButton, MenuItem, Paper, Select, Stack, Switch, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Tab, Tabs, TextField, Tooltip, Typography,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import SecurityOutlinedIcon from "@mui/icons-material/SecurityOutlined";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import BugReportOutlinedIcon from "@mui/icons-material/BugReportOutlined";
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import TravelExploreOutlinedIcon from "@mui/icons-material/TravelExploreOutlined";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import CloseRoundedIcon from "@mui/icons-material/CloseRounded";
import { apiClient } from "@/services/apiClient";
import { documentIntelligenceApi, uploadsApi } from "@/services/api";
import { DocumentContext } from "@/types/domain";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import RepositoryDocumentsPicker from "@/components/RepositoryDocumentsPicker";
import RepositoryAssetPicker from "@/components/RepositoryAssetPicker";
import { repositoryAssetExtension, useRepositoryAssets } from "@/components/repositoryAssets";

type TestBucket =
  | "installation" | "page_level" | "functional" | "uat" | "ui" | "accessibility"
  | "integration" | "performance" | "security" | "compatibility" | "resilience"
  | "permissions" | "regression";
type TargetKind = "android" | "ios" | "web";
type Provider = "browserstack" | "appium" | "playwright";
type TestCase = {
  id: string; suite: string; title: string; priority: "critical" | "high" | "medium" | "low";
  objective: string; steps: string[]; expected: string[]; autonomous: boolean;
  destructive: boolean; source: "deterministic" | "ai"; bucket?: TestBucket;
  requires_auth?: boolean; requires_test_data?: boolean; dependency?: string | null;
  evidence_required?: string[];
};
type Analysis = {
  job_id: string; filename: string; status: string; platform?: TargetKind; target_kind?: TargetKind; target_url?: string | null; app_name?: string; package_name?: string;
  version_name?: string; version_code?: string; min_sdk?: string; target_sdk?: string;
  main_activity?: string; activities: string[]; services: string[]; receivers: string[];
  permissions: string[]; file_count: number; size_bytes: number; sha256: string;
  debuggable?: boolean; inferred_domain: string; app_summary: string; critical_journeys: string[];
  clarification_questions: string[]; tests: TestCase[]; release_risks: string[];
  warnings: string[]; capabilities: Record<string, boolean>;
  context_considered?: boolean; ai_enrichment_used?: boolean; analysis_basis?: string[];
  document_asset_ids?: string[]; document_analysis_run_id?: string | null;
  checkpoint_stage?: string; input_requests?: AutopilotInputRequest[];
};
type ProviderStatus = { browserstack_configured: boolean; custom_appium_available: boolean; playwright_available?: boolean; custom_appium_reason?: string | null; custom_appium_url?: string | null; recommended_provider: Provider };
type AnalysisJob = {
  job_id: string; filename: string; status: "uploaded" | "analyzing" | "waiting_for_input" | "analyzed" | "failed" | "superseded";
  target_kind?: TargetKind; target_url?: string | null; profile_id?: string; report_tab_key?: string; surface_key?: string; surface_identity?: string; surface_version?: number; repository_asset_id?: string | null; stage: string; progress: number; context?: string; document_asset_ids?: string[]; document_analysis_run_id?: string | null; artifact_available?: boolean; error?: string; analysis?: Analysis | null;
  checkpoint_stage?: string; checkpoint_message?: string | null; input_requests?: AutopilotInputRequest[];
};
type ReportCheckStatus = "pass" | "fail" | "warning" | "pending" | "not_assessed";
type ReportCheck = {
  key: string; title: string; status: ReportCheckStatus; summary: string;
  dependency?: string | null; evidence: string[]; recommendation?: string | null;
};
type ReportRisk = {
  risk_id: string; title: string; severity: "critical" | "high" | "medium" | "low";
  likelihood: "high" | "medium" | "low"; impact: "critical" | "high" | "medium" | "low";
  status: "open" | "mitigated" | "pending_validation" | "accepted";
  evidence: string; mitigation: string;
};
type AuditReport = {
  schema_version: string; generated_at: string; report_title: string; prepared_for: string; role: string;
  recommendation: "GO" | "GO_WITH_CONDITIONS" | "NO_GO" | "PENDING"; rationale: string; last_run_at: string | null; executive_findings: string[]; reported_issues: string[];
  application_overview: {
    name: string; publisher: string; platform: string; package_name: string; version: string;
    target_market: string; regulatory_bodies: string[]; core_features: string[];
  };
  metrics: {
    designed_test_cases: number; executed_test_cases: number | null; passed_count: number; failed_count: number;
    blocked_count: number; skipped_count: number; pass_rate: number | null; defect_count: number | null;
    environment: string[]; evidence_state: string;
  };
  functional_testing: ReportCheck[]; non_functional_testing: ReportCheck[]; compliance_verification: ReportCheck[];
  risk_matrix: ReportRisk[]; recommendations: string[]; evidence: string[];
};
type Execution = {
  execution_id?: string; job_id?: string; device_name?: string; started_at?: string; finished_at?: string;
  status: "passed" | "failed" | "blocked"; target_kind?: TargetKind; target_url?: string | null; provider: Provider;
  duration_seconds: number; current_package?: string; current_activity?: string;
  screenshot_asset_id?: string; page_source_asset_id?: string; error?: string; evidence: Record<string, unknown>;
};
type ExecutionRequest = {
  target_kind?: TargetKind; target_url?: string | null; provider: Provider; appium_url?: string | null; device_name: string;
  platform_version?: string | null; appium_app?: string | null; no_reset: boolean; auto_grant_permissions: boolean;
};
type ExecutionRecord = Execution & { execution_id: string; job_id: string; created_at: string; request: ExecutionRequest };
type Locator = { strategy: "accessibility_id" | "id" | "xpath" | "css"; value: string; confidence: number };
type DiscoveredControl = {
  control_id: string; semantic_label: string; class_name: string; text: string;
  content_description: string; resource_id: string; bounds: string; clickable: boolean;
  enabled: boolean; input_capable: boolean; input_kind?: string | null; risk: "safe" | "review" | "blocked";
  risk_reason?: string | null; locators: Locator[];
};
type DiscoveredScreen = {
  screen_id: string; fingerprint: string; package_name?: string; activity_name?: string;
  url?: string | null; title?: string | null;
  screenshot_path?: string; page_source_path?: string; screenshot_asset_id?: string | null;
  page_source_asset_id?: string | null; controls: DiscoveredControl[];
};
type Discovery = {
  job_id: string; status: "completed" | "partial" | "blocked" | "failed";
  target_kind?: TargetKind; target_url?: string | null; provider: Provider; duration_seconds: number; device_name: string;
  observe_only: boolean; screen_count: number; control_count: number; safe_control_count: number;
  blocked_control_count: number; actions_attempted: number; stop_reason: string;
  screens: DiscoveredScreen[]; transitions?: unknown[]; input_requests?: AutopilotInputRequest[]; warnings: string[]; error?: string | null;
};
type AutomationTest = {
  test_id: string; title: string; suite: string; priority: "critical" | "high" | "medium" | "low";
  readiness: "executable" | "discovery_required" | "approval_required";
  bucket?: TestBucket; requires_auth?: boolean; requires_test_data?: boolean;
  dependency?: string | null; promoted_by_discovery: boolean; readiness_reason?: string | null;
};
type AutomationBundle = {
  job_id: string; schema_version: string; discovery_used: boolean; promoted_count: number;
  executable_count: number; discovery_required_count: number; approval_required_count: number;
  bucket_counts?: Record<string, number>; setup_provided_count?: number;
  setup_missing_fields?: string[]; tests: AutomationTest[];
};
type SuiteTestResult = {
  test_id: string; title: string; status: "passed" | "failed" | "blocked" | "skipped";
  bucket?: TestBucket; readiness?: "executable" | "discovery_required" | "approval_required" | null;
  dependency?: string | null; duration_seconds: number; error?: string | null;
};
type SuiteResult = {
  job_id: string; status: "passed" | "failed" | "partial" | "blocked";
  target_kind?: TargetKind; target_url?: string | null; provider: Provider; duration_seconds: number; selected_count: number;
  executed_count: number; deferred_count?: number; passed_count: number; failed_count: number; skipped_count: number;
  promoted_count: number; bucket_counts?: Record<string, number>; error?: string | null; tests: SuiteTestResult[];
};

type ProfileOption = {
  id: string; name: string; description: string; brief_context: string;
};
type ContextResponse = { context: string; source: "default" | "ai" | "fallback"; profile_id?: string; warning?: string | null };
type ReportTab = {
  report_tab_key?: string; surface_key: string; surface_identity: string; profile_id: string; target_kind: TargetKind;
  target_url?: string | null; filename: string; latest_job_id: string; latest_status: string;
  surface_version?: number; version_count?: number; latest_created_at: string; latest_updated_at: string; is_current: boolean;
};
type AutopilotInputRequest = {
  key: string; label: string; category: "credential" | "environment" | "test_data" | "approval" | "acceptance" | "integration";
  reason: string; required_for: string[]; sensitive: boolean; status: "pending" | "provided" | "validated" | "skipped" | "saved" | "random"; reference_present: boolean;
  source?: "plan" | "runtime"; screen_id?: string | null; control_id?: string | null; field_type?: string | null; input_hint?: "username" | "password" | "otp" | "text" | null; locator?: string | null;
  question?: string | null; placeholder?: string | null; format_hint?: string | null; credential_bundle?: boolean;
};
type InputDecision = "provide" | "skip" | "reuse" | "random";
type RandomSpec = { kind: "number" | "digits" | "text" | "email" | "phone" | "date" | "amount"; length: number; minimum?: number; maximum?: number; seed?: string };
type InputDraft = { decision: InputDecision; value: string; username: string; password: string; save_for_reuse: boolean; random_spec: RandomSpec };
type SavedInput = { key: string; label: string; category: AutopilotInputRequest["category"]; decision: InputDecision; save_for_reuse: boolean; has_value: boolean; generator_kind?: RandomSpec["kind"] | null; source?: "plan" | "runtime" | "user"; created_at?: string | null; updated_at?: string | null; expires_at?: string | null };
type SetupProfile = {
  job_id: string; credential_reference: string; account_role: string; environment_name: string;
  environment_url: string; test_data_reference: string; reset_hook_reference: string;
  acceptance_criteria_reference: string; api_oracle_reference: string; navigation_notes: string;
  safe_authentication_approved: boolean; approved_test_ids: string[]; runtime_input_references: Record<string, string>; updated_at?: string | null;
  provided_fields: string[]; missing_fields: string[]; input_requests: AutopilotInputRequest[]; runtime_input_requests?: AutopilotInputRequest[];
  input_decisions?: Record<string, InputDecision>; saved_inputs?: SavedInput[]; skipped_input_keys?: string[]; random_input_keys?: string[];
  checkpoint_stage: string; checkpoint_message?: string | null; last_validated_at?: string | null;
};

function emptySetup(jobId = ""): SetupProfile {
  return {
    job_id: jobId, credential_reference: "", account_role: "", environment_name: "",
    environment_url: "", test_data_reference: "", reset_hook_reference: "",
    acceptance_criteria_reference: "", api_oracle_reference: "", navigation_notes: "",
    safe_authentication_approved: false, approved_test_ids: [], runtime_input_references: {}, input_decisions: {}, saved_inputs: [], skipped_input_keys: [], random_input_keys: [], provided_fields: [], missing_fields: [], input_requests: [], runtime_input_requests: [],
    checkpoint_stage: "input_collection", checkpoint_message: null, last_validated_at: null,
  };
}

const DEFAULT_RANDOM_SPEC: RandomSpec = { kind: "text", length: 12, minimum: 0, maximum: 100000, seed: "" };

function buildInputDrafts(profile: SetupProfile | null | undefined): Record<string, InputDraft> {
  const requests = [...(profile?.input_requests || []), ...(profile?.runtime_input_requests || [])];
  const decisions = profile?.input_decisions || {};
  const saved = new Map((profile?.saved_inputs || []).map((item) => [item.key, item]));
  return Object.fromEntries(requests.map((request) => {
    const prior = decisions[request.key];
    const savedRecord = saved.get(request.key);
    const decision: InputDecision = prior === "skip"
      ? "skip"
      : prior === "random"
        ? "random"
        : (prior === "reuse" || savedRecord?.save_for_reuse ? "reuse" : "provide");
    return [request.key, {
      decision,
      value: "",
      username: "",
      password: "",
      save_for_reuse: Boolean(savedRecord?.save_for_reuse),
      random_spec: { ...DEFAULT_RANDOM_SPEC, kind: savedRecord?.generator_kind || "text" },
    } satisfies InputDraft];
  }));
}

const DEFAULT_PROFILE_ID = "uae_fintech";
const DEFAULT_PROFILE_OPTIONS: ProfileOption[] = [
  {
    id: "uae_fintech", name: "UAE Digital Banking & Wealth",
    description: "UAE banking and wealth QA, regulated journeys and CBUAE/SCA evidence.",
    brief_context: "Act as a UAE Digital Banking and Wealth QA Lead and Compliance Auditor for the {platform} product. Validate applicable onboarding/eKYC, UAE PASS, authentication, risk profiling, accounts, portfolios, cards, payments and customer journeys. Assess CBUAE/SCA-aligned controls, auditability, security, resilience, performance and data residency. Use only non-production data; keep money movement, OTP and destructive actions approval-gated. Produce an evidence-led executive Test and Audit Report. Unknown features, metrics, defects and compliance claims remain pending until observed or evidenced.",
  },
  {
    id: "payments_cards", name: "Payments & Cards",
    description: "Wallets, cards, checkout, transaction integrity and fraud controls.",
    brief_context: "Act as a Payments QA Lead for the {platform} product. Validate wallet and card lifecycle, checkout, authentication, ledger/settlement consistency, refunds, limits, fraud and abuse controls. Use non-production data and keep money movement, OTP and irreversible actions approval-gated. Capture device, API, audit-log and transaction evidence for an executive release report. Unknown metrics, defects and security/compliance claims remain pending.",
  },
  {
    id: "healthcare_regulated", name: "Healthcare & Regulated Data",
    description: "Patient journeys, privacy, consent, access control and regulated data handling.",
    brief_context: "Act as a Healthcare QA and Privacy Auditor for the {platform} product. Validate identity, consent, patient/provider journeys, sensitive-data handling, access control, audit trails and retention/deletion safeguards. Use synthetic data only; keep clinical, payment and destructive actions approval-gated. Produce an evidence-led release report. Unknown metrics, defects, privacy and regulatory claims remain pending until evidenced.",
  },
  {
    id: "ecommerce_marketplace", name: "E-commerce & Marketplace",
    description: "Catalog, search, cart, checkout, orders, delivery and refunds.",
    brief_context: "Act as an E-commerce QA Lead for the {platform} product. Validate catalog/search, account, cart, checkout, payment hand-off, order state, delivery, returns and refunds across the approved device matrix. Use non-production products and payment data; keep purchases, refunds and destructive actions approval-gated. Report observed evidence only and mark missing metrics, defects and compliance controls as pending validation.",
  },
  {
    id: "general_mobile", name: "General Mobile Application",
    description: "A neutral profile for applications without a specialised industry scope.",
    brief_context: "Act as a Senior QA Lead for the {platform} product. Discover critical user journeys, navigation, permissions, resilience, accessibility, integrations and security guardrails. Use non-production data; keep authentication, payments and destructive actions approval-gated. Create an evidence-led executive release report. Unknown metrics, defects and compliance claims remain pending until supported by evidence.",
  },
  {
    id: "custom", name: "Custom profile",
    description: "Start with a short neutral brief and tailor it in the context editor.",
    brief_context: "Act as a Senior QA Lead for the {platform} product. Focus on critical journeys, risk controls, integrations, security, performance and release evidence. Use non-production data and keep authentication, money movement and irreversible actions approval-gated. Add product-specific details below; unknown metrics, defects and compliance claims remain pending until supported by evidence.",
  },
];
function contextForProfile(profile: ProfileOption, applicationName?: string | null, target: TargetKind = "android", targetUrl?: string | null) {
  const application = applicationName?.trim() || "[TO CONFIRM]";
  const label = target === "ios" ? "iOS" : target === "web" ? "Web" : "Android";
  const brief = profile.brief_context
    .replace(/\{platform\}/gi, label)
    .replace(/Android/gi, label)
    .replace(/mobile application/gi, `${label} application`)
    .replace(/APK/gi, target === "ios" ? "IPA" : target === "web" ? "website" : "APK");
  let safeTargetUrl = "";
  if (target === "web" && targetUrl?.trim()) {
    try {
      const parsed = new URL(targetUrl.trim());
      safeTargetUrl = `${parsed.origin}${parsed.pathname}`;
    } catch {
      safeTargetUrl = targetUrl.trim().split(/[?#]/, 1)[0];
    }
  }
  const targetUrlLine = target === "web" ? `\nTarget URL: ${safeTargetUrl || "[TO CONFIRM]"}` : "";
  return `Profile category: ${profile.name}\nApplication: ${application}\nTarget: ${label}${targetUrlLine}\n${brief}`;
}
function contextForTarget(profile: ProfileOption, target: TargetKind, applicationName?: string | null, targetUrl?: string | null) {
  return contextForProfile(profile, applicationName, target, targetUrl);
}

function profileIdFromContext(value: string, profiles: ProfileOption[]) {
  const marker = value.match(/^Profile category:\s*(.+)$/im)?.[1]?.trim().toLowerCase();
  if (marker) {
    const match = profiles.find((profile) => profile.name.toLowerCase() === marker);
    if (match) return match.id;
  }
  // Older jobs predate the profile marker. Recognise the original UAE
  // fintech context so the selector remains truthful after a page refresh.
  const lowered = value.toLowerCase();
  if (["cbuae", "sca", "uae pass", "investnation", "finance house"].some((term) => lowered.includes(term))) {
    return DEFAULT_PROFILE_ID;
  }
  return "custom";
}

const DEFAULT_AUTOPILOT_CONTEXT = contextForProfile(DEFAULT_PROFILE_OPTIONS[0]);

const priorityColor: Record<TestCase["priority"], "error" | "warning" | "info" | "default"> = {
  critical: "error", high: "warning", medium: "info", low: "default",
};
const TEST_BUCKETS: TestBucket[] = [
  "installation", "page_level", "functional", "uat", "ui", "accessibility",
  "integration", "performance", "security", "compatibility", "resilience",
  "permissions", "regression",
];
const testBucketLabel: Record<TestBucket, string> = {
  installation: "Installation", page_level: "Page-level", functional: "Functional",
  uat: "UAT", ui: "UI", accessibility: "Accessibility", integration: "Integration",
  performance: "Performance", security: "Security", compatibility: "Compatibility",
  resilience: "Resilience", permissions: "Permissions", regression: "Regression",
};
function normalizedBucket(test: Pick<TestCase, "bucket"> | Pick<AutomationTest, "bucket"> | Pick<SuiteTestResult, "bucket">): TestBucket {
  return test.bucket && TEST_BUCKETS.includes(test.bucket) ? test.bucket : "functional";
}
function testModeLabel(test: TestCase) {
  if (test.destructive) return "Approval required";
  if (test.requires_auth || test.requires_test_data || test.dependency) return "Setup required";
  return "Autonomous-safe";
}
const riskColor: Record<DiscoveredControl["risk"], "success" | "warning" | "error"> = {
  safe: "success", review: "warning", blocked: "error",
};
const readinessColor: Record<AutomationTest["readiness"], "success" | "warning" | "default"> = {
  executable: "success", discovery_required: "default", approval_required: "warning",
};
const reportStatusColor: Record<ReportCheckStatus, "success" | "error" | "warning" | "info" | "default"> = {
  pass: "success", fail: "error", warning: "warning", pending: "info", not_assessed: "default",
};
const reportRiskColor: Record<ReportRisk["severity"], "error" | "warning" | "info" | "default"> = {
  critical: "error", high: "error", medium: "warning", low: "info",
};

function reportStatusLabel(status: string) {
  return status.replaceAll("_", " ").toUpperCase();
}

function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, value / 1024).toFixed(0)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
function isLoopbackAppiumUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return true;
  try {
    const hostname = new URL(trimmed).hostname.toLowerCase();
    return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]" || hostname === "::1";
  } catch {
    return true;
  }
}

function readableError(error: unknown, fallback: string) {
  const candidate = error as { response?: { data?: { detail?: unknown } }; message?: unknown };
  if (typeof candidate?.response?.data?.detail === "string") return candidate.response.data.detail;
  if (candidate?.response?.data?.detail && typeof candidate.response.data.detail === "object") {
    const detail = candidate.response.data.detail as { message?: unknown };
    if (typeof detail.message === "string") return detail.message;
  }
  if (error instanceof Error && error.message) return error.message;
  if (typeof candidate?.message === "string") return candidate.message;
  return fallback;
}

function duplicateReportTabDetails(error: unknown) {
  const candidate = error as { response?: { status?: number; data?: { detail?: unknown } } };
  const detail = candidate?.response?.data?.detail;
  if (candidate?.response?.status !== 409 || !detail || typeof detail !== "object") return null;
  const value = detail as { code?: unknown; message?: unknown; existing_job_id?: unknown; existing_created_at?: unknown };
  if (value.code !== "duplicate_surface") return null;
  return {
    message: typeof value.message === "string" ? value.message : "This profile, target and build already have a result.",
    existingJobId: typeof value.existing_job_id === "string" ? value.existing_job_id : "",
    createdAt: typeof value.existing_created_at === "string" ? value.existing_created_at : "",
  };
}

function contextForEditor(value: string) {
  // The API stores a bounded effective context that may include selected
  // repository excerpts. Keep those excerpts out of the editable brief so a
  // rerun does not append the same documents twice or expose their full text
  // in the profile editor.
  return value.split("\n\nSelected repository documentation:")[0]?.trim() || value;
}

function inputCategoryLabel(category: AutopilotInputRequest["category"]) {
  return {
    credential: "Authentication",
    environment: "Environment",
    test_data: "Test data",
    approval: "Approval",
    acceptance: "UAT acceptance",
    integration: "Integration oracle",
  }[category];
}

function requestDependentTitles(request: AutopilotInputRequest, tests: TestCase[]) {
  return request.required_for.map((id) => {
    const test = tests.find((item) => item.id === id);
    return test ? `${test.title} (${test.id})` : id;
  });
}

class TerminalAutopilotJobError extends Error {
  readonly terminal = true;
}

function ReportChecksTable({ checks }: { checks: ReportCheck[] }) {
  return <TableContainer sx={{ mt: 1.5, maxHeight: 360 }}><Table stickyHeader size="small"><TableHead><TableRow><TableCell>Control area</TableCell><TableCell>Status</TableCell><TableCell>Evidence-led assessment</TableCell><TableCell>Next action</TableCell></TableRow></TableHead><TableBody>{checks.map((check) => { const pending = check.status === "pending"; return <TableRow key={check.key} hover><TableCell sx={{ minWidth: 210 }}><Typography variant="body2" fontWeight={700}>{check.title}</Typography></TableCell><TableCell><Chip size="small" label={reportStatusLabel(check.status)} color={reportStatusColor[check.status]} variant="outlined" /></TableCell><TableCell sx={{ minWidth: 300 }}><Typography variant="body2">{pending ? (check.dependency || "Execution is yet to be completed.") : check.summary}</Typography>{!pending && check.evidence.map((item) => <Typography key={item} variant="caption" color="text.secondary" display="block">• {item}</Typography>)}</TableCell><TableCell sx={{ minWidth: 280 }}><Typography variant="caption" color="text.secondary">{pending ? "Pending" : check.recommendation || "—"}</Typography></TableCell></TableRow>; })}</TableBody></Table></TableContainer>;
}

function ReportRiskTable({ risks }: { risks: ReportRisk[] }) {
  if (risks.length === 0) return <Alert severity="success" sx={{ mt: 1.5 }}>No open risks were derived from the available evidence.</Alert>;
  return <TableContainer sx={{ mt: 1.5, maxHeight: 360 }}><Table stickyHeader size="small"><TableHead><TableRow><TableCell>Risk</TableCell><TableCell>Severity</TableCell><TableCell>Likelihood / impact</TableCell><TableCell>Evidence and mitigation</TableCell></TableRow></TableHead><TableBody>{risks.map((risk) => <TableRow key={risk.risk_id} hover><TableCell sx={{ minWidth: 220 }}><Typography variant="body2" fontWeight={700}>{risk.title}</Typography><Typography variant="caption" color="text.secondary">{risk.risk_id} · {reportStatusLabel(risk.status)}</Typography></TableCell><TableCell><Chip size="small" label={risk.severity.toUpperCase()} color={reportRiskColor[risk.severity]} variant="outlined" /></TableCell><TableCell>{risk.likelihood.toUpperCase()} / {risk.impact.toUpperCase()}</TableCell><TableCell sx={{ minWidth: 340 }}><Typography variant="caption" display="block">{risk.evidence}</Typography><Typography variant="caption" color="text.secondary" display="block" sx={{ mt: .5 }}>Mitigation: {risk.mitigation}</Typography></TableCell></TableRow>)}</TableBody></Table></TableContainer>;
}

function reportTargetLabel(targetKind: TargetKind) {
  return targetKind === "web" ? "Web" : targetKind === "ios" ? "iOS" : "Android";
}

function reportIdentityLabel(surface: ReportTab) {
  if (surface.target_kind === "web") return surface.surface_identity || "Website";
  return surface.filename || `${reportTargetLabel(surface.target_kind)} build`;
}

function reportTabKey(surface: ReportTab) {
  return surface.report_tab_key || `${surface.surface_key}:${surface.surface_version || surface.version_count || 1}:${surface.latest_job_id}`;
}

function ReportTabs({ reportTabs, profiles, activeReportTabKey, loading, disabled, onSelect }: {
  reportTabs: ReportTab[];
  profiles: ProfileOption[];
  activeReportTabKey: string;
  loading: boolean;
  disabled: boolean;
  onSelect: (reportTab: ReportTab) => void;
}) {
  if (reportTabs.length === 0) return null;
  const activeReportTab = reportTabs.find((reportTab) => reportTabKey(reportTab) === activeReportTabKey)
    ?? reportTabs.find((reportTab) => reportTab.surface_key === activeReportTabKey)
    ?? reportTabs[0];
  const selectedReportTabKey = reportTabKey(activeReportTab);
  const activeProfileName = profiles.find((profile) => profile.id === activeReportTab.profile_id)?.name || activeReportTab.profile_id;
  return <Box sx={{ mb: 2 }}>
    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} justifyContent="space-between">
      <Box>
        <Typography variant="subtitle2" fontWeight={800}>Report tabs</Typography>
        <Typography variant="caption" color="text.secondary">Each tab is isolated by profile, application target and build or URL.</Typography>
      </Box>
      {loading && <CircularProgress size={16} aria-label="Loading report views" />}
    </Stack>
    <Tabs
      value={selectedReportTabKey}
      onChange={(_, value: string) => {
        const selected = reportTabs.find((reportTab) => reportTabKey(reportTab) === value);
        if (selected) onSelect(selected);
      }}
      variant="scrollable"
      scrollButtons="auto"
      allowScrollButtonsMobile
      aria-label="Test and Audit Report tabs"
      sx={{ mt: .75, minHeight: 48, "& .MuiTab-root": { minHeight: 48, alignItems: "flex-start", textAlign: "left", textTransform: "none", px: 1.5, py: 1 } }}
    >
      {reportTabs.map((reportTab) => {
        const targetLabel = reportTargetLabel(reportTab.target_kind);
        const identity = reportIdentityLabel(reportTab);
        const profileName = profiles.find((profile) => profile.id === reportTab.profile_id)?.name || reportTab.profile_id;
        return <Tab
          key={reportTabKey(reportTab)}
          value={reportTabKey(reportTab)}
          disabled={disabled}
          aria-label={`${profileName} · ${targetLabel} · ${identity}`}
          title={`${profileName} · ${targetLabel} · ${identity}`}
          label={<Stack spacing={.1} sx={{ minWidth: 0, maxWidth: { xs: 170, sm: 230 } }}>
            <Typography variant="body2" fontWeight={700} noWrap>{profileName}</Typography>
            <Typography variant="caption" color="text.secondary" noWrap>{targetLabel} · {identity}{(reportTab.surface_version ?? 0) > 1 ? ` · v${reportTab.surface_version}` : ""}</Typography>
          </Stack>}
        />;
      })}
    </Tabs>
    <Stack direction={{ xs: "column", sm: "row" }} spacing={{ xs: .25, sm: 1 }} sx={{ mt: .75, minWidth: 0 }}>
      <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0 }}>Active report</Typography>
      <Typography variant="caption" color="text.secondary" noWrap sx={{ overflow: "hidden", textOverflow: "ellipsis" }} title={`${activeProfileName} · ${reportTargetLabel(activeReportTab.target_kind)} · ${reportIdentityLabel(activeReportTab)}`}>
        {activeProfileName} · {reportTargetLabel(activeReportTab.target_kind)} · {reportIdentityLabel(activeReportTab)}{(activeReportTab.surface_version ?? 0) > 1 ? ` · v${activeReportTab.surface_version}` : ""}
      </Typography>
    </Stack>
  </Box>;
}

function RuntimeScreenPreview({ screen }: { screen: DiscoveredScreen }) {
  const [imageUrl, setImageUrl] = useState("");
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    if (!screen.screenshot_asset_id) { setImageUrl(""); return () => { active = false; }; }
    uploadsApi.download(screen.screenshot_asset_id).then((response) => {
      if (!active) return;
      objectUrl = URL.createObjectURL(response.data);
      setImageUrl(objectUrl);
    }).catch(() => { if (active) setImageUrl(""); });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [screen.screenshot_asset_id]);
  return <Card variant="outlined" sx={{ height: "100%" }}><CardContent>
    <Box sx={{ height: 220, display: "flex", alignItems: "center", justifyContent: "center", bgcolor: "action.hover", borderRadius: 2, overflow: "hidden" }}>
      {imageUrl ? <Box component="img" src={imageUrl} alt={screen.screen_id} sx={{ width: "100%", height: "100%", objectFit: "contain" }} /> : <Typography variant="caption" color="text.secondary">Screenshot evidence pending</Typography>}
    </Box>
    <Typography variant="subtitle2" fontWeight={800} sx={{ mt: 1 }}>{screen.title || screen.screen_id}</Typography>
    <Typography variant="caption" color="text.secondary" display="block">{screen.url || screen.package_name || "Target identity pending"}{screen.activity_name ? " · " + screen.activity_name : ""}</Typography>
    <Stack direction="row" spacing={.75} sx={{ mt: 1 }}><Chip size="small" label={screen.controls.length + " controls"} variant="outlined" />{screen.page_source_asset_id && <Chip size="small" label="UI hierarchy saved" color="success" variant="outlined" />}</Stack>
  </CardContent></Card>;
}

export default function AutopilotPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { selectedProjectId } = useSelectedProject();
  const [file, setFile] = useState<File | null>(null);
  const [selectedDocumentAssetIds, setSelectedDocumentAssetIds] = useState<string[]>([]);
  const [documentAnalysisRunId, setDocumentAnalysisRunId] = useState("");
  const [selectedUploadId, setSelectedUploadId] = useState("");
  const [targetKind, setTargetKind] = useState<TargetKind>("android");
  const [targetUrl, setTargetUrl] = useState("");
  const [profiles, setProfiles] = useState<ProfileOption[]>(DEFAULT_PROFILE_OPTIONS);
  const [profileId, setProfileId] = useState(DEFAULT_PROFILE_ID);
  const [context, setContext] = useState(DEFAULT_AUTOPILOT_CONTEXT);
  const [contextSource, setContextSource] = useState<"default" | "ai" | "fallback" | "custom">("default");
  const [contextBusy, setContextBusy] = useState(false);
  const [contextNotice, setContextNotice] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [report, setReport] = useState<AuditReport | null>(null);
  const [execution, setExecution] = useState<Execution | null>(null);
  const [executionHistory, setExecutionHistory] = useState<ExecutionRecord[]>([]);
  const [discovery, setDiscovery] = useState<Discovery | null>(null);
  const [automation, setAutomation] = useState<AutomationBundle | null>(null);
  const [suite, setSuite] = useState<SuiteResult | null>(null);
  const [setup, setSetup] = useState<SetupProfile | null>(null);
  const [setupDraft, setSetupDraft] = useState<SetupProfile>(emptySetup());
  const [inputDrafts, setInputDrafts] = useState<Record<string, InputDraft>>({});
  const [setupOpen, setSetupOpen] = useState(false);
  const [checkpointStep, setCheckpointStep] = useState(0);
  const [setupBusy, setSetupBusy] = useState(false);
  const [resumeBusy, setResumeBusy] = useState(false);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);
  const [reportTabs, setReportTabs] = useState<ReportTab[]>([]);
  const [reportTabsLoading, setReportTabsLoading] = useState(false);
  const [activeReportTabKey, setActiveReportTabKey] = useState("");
  const [duplicatePrompt, setDuplicatePrompt] = useState<{ message: string; existingJobId: string; createdAt: string } | null>(null);
  const [rerunSetupPrompt, setRerunSetupPrompt] = useState(false);
  const [deleteReportOpen, setDeleteReportOpen] = useState(false);
  const [deleteReportBusy, setDeleteReportBusy] = useState(false);
  const [provider, setProvider] = useState<Provider>("browserstack");
  const [busy, setBusy] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [analysisStage, setAnalysisStage] = useState("");
  const [artifactAvailable, setArtifactAvailable] = useState(true);
  const [smokeBusy, setSmokeBusy] = useState(false);
  const [discoveryBusy, setDiscoveryBusy] = useState(false);
  const [suiteBusy, setSuiteBusy] = useState(false);
  const [discoveryMode, setDiscoveryMode] = useState<"safe" | "observe">("safe");
  const [error, setError] = useState("");
  const [appiumUrl, setAppiumUrl] = useState("");
  const [deviceName, setDeviceName] = useState("Google Pixel 8");
  const [platformVersion, setPlatformVersion] = useState("14.0");
  const [appiumApp, setAppiumApp] = useState("");
  const [autoGrantPermissions, setAutoGrantPermissions] = useState(true);
  const [testBucketFilter, setTestBucketFilter] = useState<"all" | TestBucket>("all");
  const [suiteBucket, setSuiteBucket] = useState<"all" | TestBucket>("all");

  const clearRunState = useCallback((options: { clearSurface?: boolean } = {}) => {
    // A refresh or project/surface change must not keep rendering an analysis
    // that belongs to an earlier job. Clear every derived result together so
    // a partial network response cannot leave a mixed old/new dashboard.
    setAnalysis(null);
    setReport(null);
    setExecution(null);
    setExecutionHistory([]);
    setDiscovery(null);
    setAutomation(null);
    setSuite(null);
    setSetup(null);
    setSetupDraft(emptySetup());
    setInputDrafts({});
    setCheckpointStep(0);
    setArtifactAvailable(true);
    setAnalysisProgress(0);
    setAnalysisStage("");
    setContextNotice("");
    setError("");
    if (options.clearSurface) {
      setReportTabs([]);
      setActiveReportTabKey("");
    }
  }, []);

  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.id === profileId) ?? DEFAULT_PROFILE_OPTIONS[0],
    [profileId, profiles],
  );
  const mobileAssets = useRepositoryAssets({
    projectId: selectedProjectId,
    extensions: ["apk", "ipa"],
    excludeCategories: ["autopilot_evidence", "execution_evidence"],
    excludeSourceModules: ["autopilot_evidence", "execution_report"],
    cacheKey: "autopilot-mobile-assets",
  });
  const storedApks = mobileAssets.assets;
  const repositoryLoading = mobileAssets.isLoading || mobileAssets.isFetching;

  const refreshProfiles = useCallback(async () => {
    try {
      const response = await apiClient.get<ProfileOption[]>("/autopilot/profiles", { timeout: 15000 });
      if (response.data.length > 0) setProfiles(response.data);
    } catch {
      // The local catalog is intentionally kept as a safe fallback for older
      // deployments while the backend rolls forward.
    }
  }, []);

  const refreshReportTabs = useCallback(async (projectId: string) => {
    if (!projectId) { setReportTabs([]); setActiveReportTabKey(""); return false; }
    setReportTabsLoading(true);
    // Do not leave tabs from the previous project/surface visible while the
    // replacement list is in flight. A failed request therefore cannot make
    // stale reports look current after a browser refresh.
    setReportTabs([]);
    setActiveReportTabKey("");
    try {
      let response;
      try {
        response = await apiClient.get<ReportTab[]>("/autopilot/report-tabs", { timeout: 15000 });
      } catch (error) {
        // Keep compatibility with deployments that have not rolled out the
        // report-tab alias yet; the response shape remains compatible.
        if ((error as { response?: { status?: number } })?.response?.status !== 404) throw error;
        response = await apiClient.get<ReportTab[]>("/autopilot/surfaces", { timeout: 15000 });
      }
      setReportTabs(response.data);
      const keys = response.data.map(reportTabKey);
      setActiveReportTabKey((current) => current && keys.includes(current) ? current : (keys[0] || ""));
      return true;
    } catch {
      setReportTabs([]);
      setActiveReportTabKey("");
      return false;
    } finally { setReportTabsLoading(false); }
  }, []);

  const refreshAutomation = useCallback(async (jobId: string) => {
    try { setAutomation((await apiClient.get<AutomationBundle>(`/autopilot/${jobId}/automation`, { timeout: 15000 })).data); }
    catch { setAutomation(null); }
  }, []);

  const refreshReport = useCallback(async (jobId: string) => {
    if (!jobId) { setReport(null); return; }
    try {
      setReport((await apiClient.get<AuditReport>(`/autopilot/${jobId}/report`, { timeout: 20000 })).data);
    } catch {
      // A report is derived data; keep the analysis visible if an older
      // deployment cannot serve the new endpoint yet.
      setReport(null);
    }
  }, []);

  const refreshExecutionHistory = useCallback(async (jobId: string) => {
    if (!jobId) { setExecutionHistory([]); return; }
    try {
      const response = await apiClient.get<ExecutionRecord[]>(`/autopilot/${jobId}/executions`, { timeout: 15000 });
      setExecutionHistory(response.data);
      if (response.data.length > 0) setExecution(response.data[0]);
    } catch {
      // Keep the current result visible when an older deployment or transient
      // database outage cannot serve the history endpoint.
      setExecutionHistory([]);
    }
  }, []);

  useEffect(() => {
    void refreshProfiles();
  }, [refreshProfiles]);
  useEffect(() => {
    apiClient.get<ProviderStatus>("/autopilot/providers").then((response) => {
      setProviderStatus(response.data);
      const preferred = response.data.recommended_provider === "browserstack" && response.data.browserstack_configured
        ? "browserstack"
        : response.data.custom_appium_available
          ? "appium"
          : "browserstack";
      setProvider(preferred);
      if (preferred === "appium") {
        setDeviceName("Android Emulator");
        setAppiumUrl(response.data.custom_appium_url || "");
      }
    }).catch(() => setProviderStatus(null));
  }, []);
  useEffect(() => {
    setActiveReportTabKey("");
    void refreshReportTabs(selectedProjectId);
  }, [refreshReportTabs, selectedProjectId]);
  useEffect(() => {
    clearRunState({ clearSurface: true });
    setSelectedUploadId("");
    setSelectedDocumentAssetIds([]);
    setDocumentAnalysisRunId("");
  }, [clearRunState, selectedProjectId]);

  useEffect(() => {
    const runId = searchParams.get("document_run") || "";
    if (!selectedProjectId || !runId) return;
    let active = true;
    const attachBaseline = async () => {
      try {
        const response = await documentIntelligenceApi.context(runId);
        const baseline: DocumentContext = response.data;
        if (!active || baseline.project_id !== selectedProjectId) return;
        setDocumentAnalysisRunId(baseline.run_id);
        setSelectedDocumentAssetIds(baseline.asset_ids);
        // Keep the editable brief compact. The full, bounded baseline is
        // rebuilt server-side from document_analysis_run_id when analysis
        // starts, so shortening the preview never drops evidence.
        const contextPreview = baseline.context.length > 8000
          ? `${baseline.context.slice(0, 7999).trimEnd()}…`
          : baseline.context;
        setContext(contextPreview);
        const profileMap: Record<string, string> = {
          banking: "uae_fintech",
          retail: "ecommerce_marketplace",
          saas: "custom",
          government: "custom",
          general: "general_mobile",
        };
        setProfileId(profileMap[baseline.profile] || profileIdFromContext(baseline.context, profiles));
        setContextSource("custom");
        setContextNotice("Document Intelligence baseline attached. It will scope analysis and remain linked to the resulting evidence.");
      } catch (err) {
        if (active) setError(readableError(err, "Unable to attach the Document Intelligence baseline"));
      }
    };
    void attachBaseline();
    return () => { active = false; };
  }, [profiles, searchParams, selectedProjectId]);

  const applyJob = useCallback((job: AnalysisJob) => {
    setAnalysisProgress(job.progress); setAnalysisStage(job.stage);
    if (job.target_kind) setTargetKind(job.target_kind);
    if (job.target_url !== undefined) setTargetUrl(job.target_url || "");
    if (job.profile_id) setProfileId(job.profile_id);
    if (job.report_tab_key) setActiveReportTabKey(job.report_tab_key);
    else if (job.surface_key) setActiveReportTabKey(`${job.surface_key}:${job.surface_version || 1}:${job.job_id}`);
    if (job.repository_asset_id) setSelectedUploadId(job.repository_asset_id);
    if (job.context !== undefined && job.context.trim()) {
      const editableContext = contextForEditor(job.context);
      const contextPreview = editableContext.length > 8000
        ? `${editableContext.slice(0, 7999).trimEnd()}…`
        : editableContext;
      setContext(contextPreview);
      if (!job.profile_id) setProfileId(profileIdFromContext(contextPreview, profiles));
      setContextSource("custom");
    }
    if (job.document_asset_ids) setSelectedDocumentAssetIds(job.document_asset_ids);
    else if (job.analysis?.document_asset_ids) setSelectedDocumentAssetIds(job.analysis.document_asset_ids);
    if (job.document_analysis_run_id) setDocumentAnalysisRunId(job.document_analysis_run_id);
    else if (job.analysis?.document_analysis_run_id) setDocumentAnalysisRunId(job.analysis.document_analysis_run_id);
    setArtifactAvailable(job.artifact_available !== false);
    if (job.status === "failed") {
      // A failed/latest job has no valid report. Remove any prior completed
      // result before surfacing its actionable error so a refresh cannot make
      // old evidence appear to belong to this failure.
      setAnalysis(null);
      setReport(null);
      setExecution(null);
      setExecutionHistory([]);
      setDiscovery(null);
      setAutomation(null);
      setSuite(null);
      setSetup(null);
      setSetupDraft(emptySetup(job.job_id));
      setInputDrafts({});
      setSetupOpen(false);
      if (job.error) setError(job.error);
      return;
    }
    if (["analyzed", "waiting_for_input", "superseded"].includes(job.status) && job.analysis) {
      setAnalysis(job.analysis);
      // The job-status response already carries the checkpoint requests. Seed
      // the editable setup state immediately so a slow setup request cannot
      // leave the user looking at an empty checkpoint panel.
      if (job.status === "waiting_for_input") {
        const jobRequests = job.input_requests || [];
        const requests = jobRequests.length > 0 ? jobRequests : (job.analysis.input_requests || []);
        if (requests.length > 0) {
          const checkpointSetup = {
            ...emptySetup(job.job_id),
            checkpoint_stage: job.checkpoint_stage || "input_collection",
            checkpoint_message: job.checkpoint_message || "Analysis paused safely. Review the required inputs before continuing.",
            input_requests: requests,
          };
          setSetup((current) => current?.job_id === job.job_id && current.input_requests.length > 0 ? current : checkpointSetup);
          setSetupDraft((current) => current.job_id === job.job_id && current.input_requests.length > 0 ? current : checkpointSetup);
          // A rerun can arrive while the previous report's draft values are
          // still in memory. Replace them for this job instead of letting old
          // keys suppress or contaminate the new checkpoint form.
          setInputDrafts(buildInputDrafts(checkpointSetup));
        }
      }
      void refreshExecutionHistory(job.analysis.job_id);
      void refreshReport(job.analysis.job_id);
    }
  }, [profiles, refreshExecutionHistory, refreshReport]);
  const pollAnalysis = useCallback(async (jobId: string) => {
    const deadline = Date.now() + 20 * 60 * 1000;
    let transientFailures = 0;
    while (Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      try {
        const job = (await apiClient.get<AnalysisJob>(`/autopilot/jobs/${jobId}`, { timeout: 15000 })).data;
        transientFailures = 0;
        // Clear a temporary connection notice as soon as the saved job is
        // reachable again. A failed job still sets its own actionable error.
        setError("");
        applyJob(job);
        if (job.status === "failed") throw new TerminalAutopilotJobError(job.error || "Autopilot analysis failed");
        if (["analyzed", "waiting_for_input", "superseded"].includes(job.status) && job.analysis) return job.analysis;
      } catch (err) {
        if (err instanceof TerminalAutopilotJobError) throw err;
        const status = (err as { response?: { status?: number } })?.response?.status;
        const retryable = !status || status === 408 || status === 425 || status === 429 || status >= 500;
        if (!retryable) throw err;
        transientFailures += 1;
        // Render instance replacement, cold starts and short network blips
        // must not discard a job that is persisted in the database.
        setError(`Temporary connection interruption while checking analysis status. Retrying (${transientFailures})…`);
        await new Promise((resolve) => window.setTimeout(resolve, Math.min(10000, 2000 + transientFailures * 1000)));
      }
    }
    throw new Error("Analysis is still running after 20 minutes. The job is saved; retry status shortly.");
  }, [applyJob]);

  useEffect(() => {
    let active = true;
    const restore = async () => {
      if (!selectedProjectId) return;
      // Start every restore from an empty derived state. If the latest-job
      // request returns null (or Neon is temporarily unavailable), the user
      // sees a clean pending view instead of the previous job's report.
      clearRunState({ clearSurface: true });
      try {
        await refreshReportTabs(selectedProjectId);
        const job = (await apiClient.get<AnalysisJob | null>("/autopilot/jobs/latest", { timeout: 15000 })).data;
        if (!active) return;
        if (!job) {
          setBusy(false);
          return;
        }
        applyJob(job);
        if (job.status === "uploaded" || job.status === "analyzing") {
          setBusy(true);
          await pollAnalysis(job.job_id);
          if (active) setBusy(false);
        }
      } catch (err) {
        if (active) {
          clearRunState({ clearSurface: true });
          setBusy(false);
          setError(readableError(err, "Unable to restore the latest Autopilot analysis"));
        }
      }
    };
    void restore();
    return () => { active = false; };
  }, [selectedProjectId, applyJob, clearRunState, pollAnalysis, refreshReportTabs]);

  useEffect(() => {
    let active = true;
    if (!analysis?.job_id) { setDiscovery(null); setAutomation(null); setSuite(null); setSetup(null); setReport(null); return; }
    Promise.allSettled([
      apiClient.get<Discovery | null>(`/autopilot/${analysis.job_id}/discovery`, { timeout: 15000 }),
      apiClient.get<AutomationBundle>(`/autopilot/${analysis.job_id}/automation`, { timeout: 15000 }),
      apiClient.get<SuiteResult | null>(`/autopilot/${analysis.job_id}/suite`, { timeout: 15000 }),
      apiClient.get<SetupProfile>("/autopilot/" + analysis.job_id + "/setup", { timeout: 15000 }),
      apiClient.get<AuditReport>(`/autopilot/${analysis.job_id}/report`, { timeout: 20000 }),
    ]).then(([discoveryResult, automationResult, suiteResult, setupResult, reportResult]) => {
      if (!active) return;
      setDiscovery(discoveryResult.status === "fulfilled" ? discoveryResult.value.data : null);
      setAutomation(automationResult.status === "fulfilled" ? automationResult.value.data : null);
      setSuite(suiteResult.status === "fulfilled" ? suiteResult.value.data : null);
      const resolvedSetup = setupResult.status === "fulfilled"
        ? setupResult.value.data
        : {
            ...emptySetup(analysis.job_id),
            checkpoint_stage: analysis.checkpoint_stage || "input_collection",
            checkpoint_message: "Analysis paused safely. Review the required inputs before continuing.",
            input_requests: analysis.input_requests || [],
          };
      // Older jobs and a briefly unavailable setup read can return a valid
      // profile shell without copying the request list from the job manifest.
      // Keep the job's pending requests as a safe fallback so the banner and
      // dialog never disappear while the durable setup is being rehydrated.
      const resolvedWithFallback = resolvedSetup.input_requests.length > 0 || (resolvedSetup.runtime_input_requests || []).length > 0 || !(analysis.input_requests || []).length
        ? resolvedSetup
        : { ...resolvedSetup, input_requests: analysis.input_requests || [], missing_fields: (analysis.input_requests || []).map((item) => item.label) };
      setSetup(resolvedWithFallback);
      // setupDraft drives both the banner and the dialog. Keep it in sync with
      // the durable setup response instead of leaving the initial empty form in
      // place (which previously hid all required inputs).
      setSetupDraft(resolvedWithFallback);
      setInputDrafts(buildInputDrafts(resolvedWithFallback));
      const pending = [...(resolvedWithFallback.input_requests || []), ...(resolvedWithFallback.runtime_input_requests || [])]
        .filter((item) => item.status === "pending");
      // A checkpoint can be returned as a terminal/analyzed job after a
      // restart or an older deployment has normalized its stage. The pending
      // request itself is the source of truth, so do not hide the dialog just
      // because the stage label was not persisted on that response.
      if (pending.length > 0) {
        const firstPending = [...(resolvedWithFallback.input_requests || []), ...(resolvedWithFallback.runtime_input_requests || [])].findIndex((item) => item.status === "pending");
        setCheckpointStep(firstPending >= 0 ? firstPending : 0);
        setSetupOpen(true);
      }
      setReport(reportResult.status === "fulfilled" ? reportResult.value.data : null);
    });
    return () => { active = false; };
  }, [analysis?.job_id, analysis?.checkpoint_stage, analysis?.input_requests]);

  useEffect(() => {
    if (!analysis?.job_id) return;
    const candidate = setup?.job_id === analysis.job_id
      ? setup
      : setupDraft.job_id === analysis.job_id
        ? setupDraft
        : null;
    if (!candidate) return;
    const pending = [...(candidate.input_requests || []), ...(candidate.runtime_input_requests || [])]
      .some((item) => item.status === "pending");
    if (pending) {
      const firstPending = [...(candidate.input_requests || []), ...(candidate.runtime_input_requests || [])].findIndex((item) => item.status === "pending");
      setCheckpointStep(firstPending >= 0 ? firstPending : 0);
      setSetupOpen(true);
    }
  }, [analysis?.job_id, setup, setupDraft]);

  const stats = useMemo(() => analysis ? {
    tests: analysis.tests.length,
    suites: new Set(analysis.tests.map((test) => test.suite)).size,
    autonomous: analysis.tests.filter((test) => test.autonomous).length,
    critical: analysis.tests.filter((test) => ["critical", "high"].includes(test.priority)).length,
    buckets: new Set(analysis.tests.map((test) => normalizedBucket(test))).size,
  } : null, [analysis]);
  const bucketCounts = useMemo(() => {
    const counts: Partial<Record<TestBucket, number>> = {};
    for (const test of analysis?.tests ?? []) {
      const bucket = normalizedBucket(test);
      counts[bucket] = (counts[bucket] || 0) + 1;
    }
    return counts;
  }, [analysis]);
  const visibleTests = useMemo(
    () => analysis?.tests.filter((test) => testBucketFilter === "all" || normalizedBucket(test) === testBucketFilter) ?? [],
    [analysis, testBucketFilter],
  );
  const suiteExecutableCount = useMemo(
    () => automation?.tests.filter((test) => test.readiness === "executable" && (suiteBucket === "all" || normalizedBucket(test) === suiteBucket)).length ?? 0,
    [automation, suiteBucket],
  );
  const selectedStoredApk = useMemo(() => storedApks.find((asset) => asset.id === selectedUploadId) ?? null, [storedApks, selectedUploadId]);
  const selectedApplicationName = selectedStoredApk?.filename?.replace(/\.(apk|ipa)$/i, "")
    || file?.name?.replace(/\.(apk|ipa)$/i, "")
    || analysis?.app_name
    || null;
  const discoveredRows = useMemo(() => discovery?.screens.flatMap((screen) => screen.controls.map((control) => ({ screen: screen.screen_id, control }))) ?? [], [discovery]);

  const resetResult = () => { clearRunState(); setSetupOpen(false); };
  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    if (selected) {
      setSelectedUploadId("");
      const nextTarget = /\.ipa$/i.test(selected.name) ? "ios" : "android";
      setTargetKind(nextTarget);
      setTargetUrl("");
      // A newly selected build defines a new analysis surface. Rebuild the
      // brief immediately so an older job's application name/platform cannot
      // leak into the next run; the user can still edit it afterwards.
      setContext(contextForTarget(selectedProfile, nextTarget, selected.name.replace(/\.(apk|ipa)$/i, "")));
      setContextSource("default");
    }
    resetResult();
  };
  const selectProfile = (nextProfileId: string) => {
    const nextProfile = profiles.find((profile) => profile.id === nextProfileId) ?? DEFAULT_PROFILE_OPTIONS[0];
    // A report is evidence for the context used by its job. Clear an older
    // result when the governing profile changes so it cannot be mistaken for
    // an assessment of the newly selected scope.
    resetResult();
    setProfileId(nextProfile.id);
    setContext(contextForTarget(nextProfile, targetKind, selectedApplicationName, targetUrl));
    setContextSource("default");
    setContextNotice(`${nextProfile.name} brief applied. You can edit it before starting the run.`);
    setError("");
  };
  const generateContext = async (mode: "default" | "generate" | "improve") => {
    if (mode === "default") {
      resetResult();
      setContext(contextForTarget(selectedProfile, targetKind, selectedApplicationName, targetUrl));
      setContextSource("default");
      setContextNotice(`${selectedProfile.name} brief applied. Review it before running.`);
      return;
    }
    setContextBusy(true); setContextNotice(""); setError("");
    try {
      const response = await apiClient.post<ContextResponse>("/autopilot/context/generate", {
        mode,
        profile_id: profileId,
        current_context: context,
        application_name: selectedApplicationName,
        package_name: analysis?.package_name || null,
        platform: targetKind === "web" ? "Web" : targetKind === "ios" ? "iOS" : "Android",
        target_url: targetKind === "web" ? targetUrl.trim() || null : null,
        build_name: selectedStoredApk?.filename || file?.name || null,
        observed_metadata: {
          ...(selectedStoredApk ? {
            filename: selectedStoredApk.filename,
            size_bytes: selectedStoredApk.size_bytes,
            sha256: selectedStoredApk.sha256,
            extension: selectedStoredApk.extension,
          } : {}),
          ...(analysis ? {
            observed_app_name: analysis.app_name,
            observed_package_name: analysis.package_name,
            observed_summary: analysis.app_summary,
            permissions: analysis.permissions.slice(0, 80),
            activities: analysis.activities.slice(0, 80),
            critical_journeys: analysis.critical_journeys.slice(0, 20),
          } : {}),
        },
        focus: `${selectedProfile.name} release readiness, functional QA and evidence-led reporting`,
      }, { timeout: 90000 });
      resetResult();
      setContext(response.data.context);
      setProfileId(response.data.profile_id || profileId);
      setContextSource(response.data.source);
      setContextNotice(response.data.warning || (response.data.source === "ai" ? "AI-generated context applied. Review it before analysis." : "Safe fallback context applied."));
    } catch (err) {
      setError(readableError(err, "Context generation failed"));
    } finally { setContextBusy(false); }
  };
  const analyze = async (surfaceAction: "ask" | "new" | "override" = "ask") => {
    const isWebsite = targetKind === "web";
    if ((!isWebsite && !file && !selectedUploadId) || (isWebsite && !targetUrl.trim()) || !selectedProjectId) {
      setError(isWebsite ? "Enter a website URL before starting Autopilot." : "Select a project and APK/IPA before starting Autopilot.");
      return;
    }
    // Do not carry the previous completed progress into a new run. The old
    // value made a fresh analysis render as “complete · 100%” while the
    // background job was still being queued/read.
    setAnalysisProgress(3); setAnalysisStage("queued");
    setBusy(true); setError(""); setContextNotice(""); setSetupOpen(false); setExecution(null); setExecutionHistory([]); setDiscovery(null); setAutomation(null); setSuite(null); setReport(null);
    try {
      let response;
      if (selectedUploadId && !isWebsite) {
        response = await apiClient.post<AnalysisJob>("/autopilot/analyze-existing", { upload_id: selectedUploadId, context, profile_id: profileId, surface_action: surfaceAction, document_asset_ids: selectedDocumentAssetIds, document_analysis_run_id: documentAnalysisRunId || undefined }, { timeout: 300000 });
      } else {
        const form = new FormData();
        if (isWebsite) form.append("target_url", targetUrl.trim());
        else form.append("file", file as File);
        form.append("context", context); form.append("profile_id", profileId);
        form.append("surface_action", surfaceAction);
        form.append("document_asset_ids", JSON.stringify(selectedDocumentAssetIds));
        if (documentAnalysisRunId) form.append("document_analysis_run_id", documentAnalysisRunId);
        response = await apiClient.post<AnalysisJob>("/autopilot/analyze", form, { headers: { "Content-Type": "multipart/form-data" }, timeout: 300000 });
        if (!isWebsite) {
          // Repository refresh is convenience metadata; a successful analysis
          // must remain usable if the list endpoint has a transient failure.
          try { await mobileAssets.refetch(); } catch { /* keep the analysis result */ }
        }
      }
      applyJob(response.data); await pollAnalysis(response.data.job_id); await refreshAutomation(response.data.job_id); await refreshReport(response.data.job_id); await refreshReportTabs(selectedProjectId);
    } catch (err) {
      const duplicate = duplicateReportTabDetails(err);
      if (duplicate && surfaceAction === "ask") {
        setDuplicatePrompt(duplicate);
      } else {
        setError(readableError(err, "Autopilot analysis failed"));
      }
    }
    finally { setBusy(false); }
  };

  const selectReportTab = async (reportTab: ReportTab) => {
    if (busy || !selectedProjectId || reportTab.latest_job_id === analysis?.job_id) return;
    setBusy(true); setError(""); resetResult(); setActiveReportTabKey(reportTabKey(reportTab));
    try {
      const job = (await apiClient.get<AnalysisJob>(`/autopilot/jobs/${reportTab.latest_job_id}`, { timeout: 20000 })).data;
      applyJob(job);
      if (job.status === "uploaded" || job.status === "analyzing") await pollAnalysis(job.job_id);
    } catch (err) {
      setError(readableError(err, "Unable to open this report tab"));
    } finally { setBusy(false); }
  };

  const executionPayload = () => ({
    target_kind: analysis?.target_kind || targetKind,
    target_url: analysis?.target_url || (targetKind === "web" ? targetUrl.trim() : null),
    provider: (analysis?.target_kind || targetKind) === "web" ? "playwright" : provider,
    appium_url: provider === "appium" ? appiumUrl : null,
    device_name: deviceName,
    platform_version: platformVersion || null,
    appium_app: provider === "appium" ? (appiumApp || null) : null,
    no_reset: false,
    auto_grant_permissions: autoGrantPermissions,
  });
  const openSetup = () => {
    if (!analysis) return;
    const sourceSetup = setup?.job_id === analysis.job_id
      ? setup
      : setupDraft.job_id === analysis.job_id
        ? setupDraft
        : null;
    const sourceRequests = sourceSetup
      ? [...(sourceSetup.input_requests || []), ...(sourceSetup.runtime_input_requests || [])]
      : [];
    const baseSetup = sourceSetup && sourceRequests.length > 0 ? sourceSetup : {
      ...emptySetup(analysis.job_id),
      ...(sourceSetup || {}),
      checkpoint_stage: analysis.checkpoint_stage || "input_collection",
      checkpoint_message: "Analysis paused safely. Review the required inputs before continuing.",
      input_requests: analysis.input_requests || [],
      missing_fields: (analysis.input_requests || []).map((item) => item.label),
      runtime_input_requests: [],
    };
    const nextSetup = {
      ...baseSetup,
      approved_test_ids: [...baseSetup.approved_test_ids],
      runtime_input_references: { ...(baseSetup.runtime_input_references || {}) },
      provided_fields: [...baseSetup.provided_fields],
      missing_fields: [...baseSetup.missing_fields],
      input_requests: [...baseSetup.input_requests],
      runtime_input_requests: [...(baseSetup.runtime_input_requests || [])],
    };
    setSetupDraft(nextSetup);
    setInputDrafts(buildInputDrafts(nextSetup));
    const nextRequests = [...(nextSetup.input_requests || []), ...(nextSetup.runtime_input_requests || [])];
    const firstPending = nextRequests.findIndex((item) => item.status === "pending");
    setCheckpointStep(firstPending >= 0 ? firstPending : 0);
    setSetupOpen(true);
  };
  const saveSetup = async () => {
    if (!analysis) return;
    const checkpointRequestMap = new Map(
      [...(setupDraft.input_requests || []), ...(setupDraft.runtime_input_requests || [])].map((item) => [item.key, item]),
    );
    const missingCredential = Object.entries(inputDrafts).find(([key, draft]) => {
      const request = checkpointRequestMap.get(key);
      return request?.credential_bundle && draft.decision === "provide" && (!draft.username.trim() || !draft.password);
    });
    if (missingCredential) {
      const request = checkpointRequestMap.get(missingCredential[0]);
      setError(`Enter both the UAT user ID/email and password for ${request?.label || "the sign-in account"}, or choose Skip.`);
      const step = [...checkpointRequestMap.keys()].indexOf(missingCredential[0]);
      if (step >= 0) setCheckpointStep(step);
      setSetupOpen(true);
      return;
    }
    setSetupBusy(true); setError("");
    try {
      const payload = {
        credential_reference: setupDraft.credential_reference,
        account_role: setupDraft.account_role,
        environment_name: setupDraft.environment_name,
        environment_url: setupDraft.environment_url,
        test_data_reference: setupDraft.test_data_reference,
        reset_hook_reference: setupDraft.reset_hook_reference,
        acceptance_criteria_reference: setupDraft.acceptance_criteria_reference,
        api_oracle_reference: setupDraft.api_oracle_reference,
        navigation_notes: setupDraft.navigation_notes,
        safe_authentication_approved: setupDraft.safe_authentication_approved,
        approved_test_ids: setupDraft.approved_test_ids,
        runtime_input_references: setupDraft.runtime_input_references || {},
        input_submissions: Object.entries(inputDrafts).filter(([key, draft]) => {
          const request = checkpointRequestMap.get(key);
          // Approval is a boolean checkpoint.  It deliberately has no value
          // field, so keep its decision in the encrypted-input boundary only
          // as metadata and let the setup flag carry the actual approval.
          if (request?.category === "approval") return true;
          return draft.decision !== "provide"
            || Boolean(request?.credential_bundle ? draft.username.trim() && draft.password : draft.value.trim());
        }).map(([key, draft]) => ({
          key,
          // The setup switch is the source of truth for this non-value
          // checkpoint; never let a stale draft default accidentally approve
          // authentication when the switch is off.
          decision: checkpointRequestMap.get(key)?.category === "approval"
            ? (setupDraft.safe_authentication_approved ? "provide" : "skip")
            : draft.decision,
          ...(draft.decision === "provide" && checkpointRequestMap.get(key)?.category !== "approval" ? {
            value: checkpointRequestMap.get(key)?.credential_bundle
              ? JSON.stringify({ username: draft.username.trim(), password: draft.password })
              : draft.value,
          } : {}),
          save_for_reuse: draft.decision === "provide" || draft.decision === "random" ? draft.save_for_reuse : false,
          ...(draft.decision === "random" ? { random_spec: draft.random_spec } : {}),
        })),
      };
      const response = await apiClient.put<SetupProfile>("/autopilot/" + analysis.job_id + "/setup", payload, { timeout: 20000 });
      setSetup(response.data);
      const pending = [...(response.data.input_requests || []), ...(response.data.runtime_input_requests || [])]
        .filter((item) => item.status === "pending");
      setSetupDraft(response.data);
      setInputDrafts(buildInputDrafts(response.data));
      if (pending.length > 0) {
        // Keep the checkpoint open when only part of the requested setup was
        // supplied, so the user can see exactly what remains and why.
        const firstPending = [...(response.data.input_requests || []), ...(response.data.runtime_input_requests || [])].findIndex((item) => item.status === "pending");
        setCheckpointStep(firstPending >= 0 ? firstPending : 0);
        setSetupDraft((current) => ({ ...current, input_requests: response.data.input_requests || [], missing_fields: response.data.missing_fields }));
        setContextNotice(`${pending.length} setup item${pending.length === 1 ? "" : "s"} still required. Complete the highlighted checkpoint inputs to continue.`);
        return;
      }
      setSetupOpen(false);
      await refreshAutomation(analysis.job_id);
      setResumeBusy(true);
      try {
        const resumeResponse = await apiClient.post<AnalysisJob>(
          `/autopilot/${analysis.job_id}/resume`,
          {
            confirm_saved_inputs: true,
            // The first checkpoint chains into discovery. Once a screen map
            // already exists, keep it and validate the newly supplied field
            // inputs instead of launching a duplicate discovery run.
            run_runtime_discovery: !discovery,
            discovery_provider: executionPayload().provider,
            discovery_device_name: deviceName,
            discovery_platform_version: platformVersion || null,
            discovery_appium_url: provider === "appium" ? appiumUrl || null : null,
            discovery_appium_app: provider === "appium" ? appiumApp || null : null,
          },
          { timeout: 20000 },
        );
        applyJob(resumeResponse.data);
        if (resumeResponse.data.status === "waiting_for_input") {
          // A concurrent discovery update or a stale browser tab can reveal a
          // newly required field after the setup PUT succeeds. Keep the
          // checkpoint visible instead of sending the user back to the main
          // "Analyze stored APK" action, which otherwise looks like a loop.
          setSetupOpen(true);
          setContextNotice(
            "Autopilot found additional setup inputs. Review the highlighted fields and save again to continue.",
          );
          return;
        }
        if (resumeResponse.data.status === "uploaded" || resumeResponse.data.status === "analyzing") {
          await pollAnalysis(analysis.job_id);
        }
        // The server continues discovery in the background. Give it a short
        // foreground window so the user gets the map immediately when the
        // provider is warm, then leave slower runs safely resumable.
        const discoveryDeadline = Date.now() + 60000;
        let discoveryReady = false;
        while (Date.now() < discoveryDeadline) {
          try {
            const discoveryResponse = await apiClient.get<Discovery | null>(`/autopilot/${analysis.job_id}/discovery`, { timeout: 15000 });
            if (discoveryResponse.data) {
              setDiscovery(discoveryResponse.data);
              discoveryReady = true;
              break;
            }
          } catch { /* background job is still running; retry */ }
          await new Promise((resolve) => window.setTimeout(resolve, 3000));
        }
        try {
          const latestSetup = (await apiClient.get<SetupProfile>(`/autopilot/${analysis.job_id}/setup`, { timeout: 15000 })).data;
          setSetup(latestSetup);
          setSetupDraft(latestSetup);
          setInputDrafts(buildInputDrafts(latestSetup));
        } catch { /* keep the saved checkpoint visible */ }
        await refreshAutomation(analysis.job_id);
        await refreshReport(analysis.job_id);
        if (!discoveryReady) setContextNotice("Setup validated. Runtime Discovery is continuing in the background; refresh this tab to see its evidence.");
      } finally {
        setResumeBusy(false);
      }
    } catch (err) { setError(readableError(err, "Test setup could not be saved")); }
    finally { setSetupBusy(false); }
  };
  const updateSetup = (field: keyof SetupProfile, value: string | boolean) => setSetupDraft((current) => ({ ...current, [field]: value }));
  const updateRuntimeReference = (key: string, value: string) => setSetupDraft((current) => ({
    ...current,
    runtime_input_references: { ...(current.runtime_input_references || {}), [key]: value },
  }));
  const updateInputDraft = (key: string, patch: Partial<InputDraft>) => setInputDrafts((current) => ({
    ...current,
    [key]: { ...(current[key] || { decision: "provide", value: "", username: "", password: "", save_for_reuse: false, random_spec: { ...DEFAULT_RANDOM_SPEC } }), ...patch },
  }));

  const runDiscovery = async () => {
    if (!analysis) return;
    setDiscoveryBusy(true); setError("");
    try {
      const response = await apiClient.post<Discovery>(`/autopilot/${analysis.job_id}/discover`, {
        ...executionPayload(),
        observe_only: discoveryMode === "observe",
        max_screens: discoveryMode === "observe" ? 1 : 12,
        max_actions: discoveryMode === "observe" ? 0 : 10,
      }, { timeout: 660000 });
      setDiscovery(response.data);
      try {
        const nextSetup = (await apiClient.get<SetupProfile>(`/autopilot/${analysis.job_id}/setup`, { timeout: 15000 })).data;
        setSetup(nextSetup);
        setSetupDraft(nextSetup);
        setInputDrafts(buildInputDrafts(nextSetup));
        const nextRequests = [...(nextSetup.input_requests || []), ...(nextSetup.runtime_input_requests || [])];
        const firstPending = nextRequests.findIndex((item) => item.status === "pending");
        if (firstPending >= 0) setCheckpointStep(firstPending);
      } catch { /* discovery evidence remains visible */ }
      await refreshAutomation(analysis.job_id);
      await refreshReport(analysis.job_id);
    } catch (err) { setError(readableError(err, "Runtime discovery failed")); }
    finally { setDiscoveryBusy(false); }
  };
  const runSuite = async () => {
    if (!analysis) return;
    setSuiteBusy(true); setError("");
    try {
      const response = await apiClient.post<SuiteResult>(`/autopilot/${analysis.job_id}/suite`, {
        ...executionPayload(),
        max_tests: 20,
        test_ids: [],
        buckets: suiteBucket === "all" ? [] : [suiteBucket],
        include_deferred: true,
      }, { timeout: 960000 });
      setSuite(response.data);
      await refreshReport(analysis.job_id);
    } catch (err) { setError(readableError(err, "Autonomous safe-suite execution failed")); }
    finally { setSuiteBusy(false); }
  };
  const runSmoke = async () => {
    if (!analysis) return;
    setSmokeBusy(true); setError("");
    try {
      setExecution((await apiClient.post<Execution>(`/autopilot/${analysis.job_id}/smoke`, executionPayload(), { timeout: 660000 })).data);
      await refreshExecutionHistory(analysis.job_id);
      await refreshReport(analysis.job_id);
    }
    catch (err) { setError(readableError(err, "Smoke execution failed")); }
    finally { setSmokeBusy(false); }
  };

  const rerunSmoke = async (executionId: string) => {
    if (!analysis) return;
    setSmokeBusy(true); setError("");
    try {
      const response = await apiClient.post<Execution>(
        `/autopilot/${analysis.job_id}/executions/${executionId}/rerun`,
        {},
        { timeout: 660000 },
      );
      setExecution(response.data);
      await refreshExecutionHistory(analysis.job_id);
      await refreshReport(analysis.job_id);
    } catch (err) { setError(readableError(err, "Smoke rerun failed")); }
    finally { setSmokeBusy(false); }
  };

  const rerunAnalysis = async (setupAction: "reuse" | "fresh" = "fresh") => {
    if (!analysis || !selectedProjectId) return;
    setAnalysisProgress(3); setAnalysisStage("queued");
    setBusy(true); setError(""); setSetupOpen(false); setExecution(null); setExecutionHistory([]); setReport(null);
    try {
      const response = await apiClient.post<AnalysisJob>(
        `/autopilot/${analysis.job_id}/rerun-analysis`,
        { upload_id: selectedUploadId || undefined, context: context || undefined, profile_id: profileId, surface_action: "new", setup_action: setupAction, target_url: targetKind === "web" ? targetUrl.trim() || undefined : undefined, document_asset_ids: selectedDocumentAssetIds, document_analysis_run_id: documentAnalysisRunId || undefined },
        { timeout: 300000 },
      );
      // Keep the last completed analysis visible while the replacement job
      // is being persisted/polled. The new result replaces it atomically.
      setDiscovery(null); setAutomation(null); setSuite(null);
      applyJob(response.data);
      await pollAnalysis(response.data.job_id);
      await refreshAutomation(response.data.job_id); await refreshReport(response.data.job_id);
      await refreshReportTabs(selectedProjectId);
    } catch (err) { setError(readableError(err, "Autopilot rerun failed")); }
    finally { setBusy(false); }
  };

  const startRerun = () => {
    if (setup?.provided_fields.length) {
      setRerunSetupPrompt(true);
      return;
    }
    void rerunAnalysis("fresh");
  };

  const deleteReport = async () => {
    const jobId = analysis?.job_id;
    if (!jobId || !selectedProjectId) return;
    setDeleteReportBusy(true); setError("");
    try {
      await apiClient.delete(`/autopilot/${jobId}/report`, { timeout: 30000 });
      setDeleteReportOpen(false);
      clearRunState({ clearSurface: true });
      setContextNotice("Report deleted. The original APK/IPA, documents and evidence uploads remain in the repository.");
      await refreshReportTabs(selectedProjectId);
    } catch (err) {
      setError(readableError(err, "The Test & Audit Report could not be deleted"));
    } finally { setDeleteReportBusy(false); }
  };

  const activeTargetKind = analysis?.target_kind || targetKind;
  const activeProvider: Provider = activeTargetKind === "web" ? "playwright" : provider;
  const browserStackUnavailable = activeProvider === "browserstack" && providerStatus !== null && !providerStatus.browserstack_configured;
  const customAppiumUnavailable = activeProvider === "appium" && providerStatus !== null && !providerStatus.custom_appium_available && isLoopbackAppiumUrl(appiumUrl);
  const providerStatusPending = activeTargetKind !== "web" && providerStatus === null;
  const noExecutionProvider = activeTargetKind !== "web" && providerStatus !== null && !providerStatus.browserstack_configured && !providerStatus.custom_appium_available && isLoopbackAppiumUrl(appiumUrl);
  const executionUnavailable = providerStatusPending || browserStackUnavailable || customAppiumUnavailable || !artifactAvailable;
  const reportPending = report?.recommendation === "PENDING";
  const contextBadge = analysis?.context_considered === true
    ? { label: "Profile context considered", color: "success" as const }
    : analysis?.context_considered === false
      ? { label: "Context not supplied", color: "warning" as const }
      : { label: "Context provenance unavailable", color: "default" as const };
  const aiBadge = analysis?.ai_enrichment_used === true
    ? { label: "AI enrichment used", color: "primary" as const }
    : analysis?.ai_enrichment_used === false
      ? { label: "Deterministic fallback", color: "default" as const }
      : { label: "AI provenance unavailable", color: "default" as const };
  const setupCandidates = analysis
    ? [setup, setupDraft].filter((candidate): candidate is SetupProfile => candidate?.job_id === analysis.job_id)
    : [];
  const activeSetup = setupCandidates.find((candidate) => (candidate.input_requests || []).length > 0 || (candidate.runtime_input_requests || []).length > 0)
    || setupCandidates[0]
    || emptySetup(analysis?.job_id || "");
  const checkpointRequests = [
    ...((activeSetup.input_requests || []).length > 0 ? activeSetup.input_requests : analysis?.input_requests || []),
    ...(activeSetup.runtime_input_requests || []),
  ];
  const pendingCheckpointRequests = checkpointRequests.filter((item) => item.status === "pending");
  const activeCheckpointIndex = checkpointRequests.length > 0
    ? Math.min(Math.max(checkpointStep, 0), checkpointRequests.length - 1)
    : 0;
  const activeCheckpointRequest = checkpointRequests[activeCheckpointIndex] || null;
  const activeCheckpointDraft = activeCheckpointRequest
    ? inputDrafts[activeCheckpointRequest.key] || { decision: "provide" as InputDecision, value: "", username: "", password: "", save_for_reuse: false, random_spec: { ...DEFAULT_RANDOM_SPEC } }
    : null;
  const activeCheckpointSaved = activeCheckpointRequest
    ? (setupDraft.saved_inputs || []).find((item) => item.key === activeCheckpointRequest.key)
    : null;
  const checkpointWaiting = Boolean(analysis && pendingCheckpointRequests.length > 0);
  const analysisButtonLabel = checkpointWaiting
    ? "Review required inputs"
    : busy
      ? "Inspecting target…"
      : resumeBusy
        ? "Resuming Autopilot…"
        : selectedStoredApk
          ? `Analyze stored ${selectedStoredApk.extension.toUpperCase()}`
          : "Start analysis";

  return <Stack spacing={3}>
    <Box>
      <Stack direction="row" spacing={1.5} alignItems="center"><AutoAwesomeIcon color="primary" /><Typography variant="h4" fontWeight={800}>Autopilot</Typography></Stack>
      <Typography color="text.secondary" sx={{ mt: 1, maxWidth: 920 }}>Inspect a web, Android or iOS target, generate complete coverage, discover safe journeys and report only evidence-backed outcomes.</Typography>
    </Box>

    <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 }, borderRadius: 3 }}>
      <Box sx={{ mb: 2.5 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }} justifyContent="space-between">
          <Box>
            <Typography variant="overline" color="primary" fontWeight={800} letterSpacing={1}>1 · Scope</Typography>
            <Typography variant="body2" color="text.secondary">Choose a domain profile; Autopilot uses it to focus coverage and reporting.</Typography>
          </Box>
          <Chip size="small" label={`Profile: ${selectedProfile.name}`} color="primary" variant="outlined" />
        </Stack>
        <Grid container spacing={2} alignItems="center" sx={{ mt: .25 }}>
          <Grid item xs={12} md={5}>
            <FormControl fullWidth size="small" disabled={busy || contextBusy}>
              <InputLabel id="autopilot-profile-label">Profile category</InputLabel>
              <Select labelId="autopilot-profile-label" label="Profile category" value={selectedProfile.id} onChange={(event) => selectProfile(event.target.value)}>
                {profiles.map((profile) => <MenuItem key={profile.id} value={profile.id}>{profile.name}</MenuItem>)}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={7}>
            <Typography variant="body2" color="text.secondary">{selectedProfile.description}</Typography>
            <Typography variant="caption" color="text.secondary">The brief updates automatically and remains editable.</Typography>
          </Grid>
        </Grid>
      </Box>
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} md={4}>
          <FormControl fullWidth size="small" disabled={busy || contextBusy}>
            <InputLabel id="autopilot-target-label">Target type</InputLabel>
            <Select labelId="autopilot-target-label" label="Target type" value={targetKind} onChange={(event) => {
               const next = event.target.value as TargetKind;
               setTargetKind(next);
               setFile(null); setSelectedUploadId(""); resetResult();
               // Switching target starts a new surface. Always replace the
               // old target identity in the brief instead of carrying a
               // previously loaded APK/URL context into this run.
               setContext(contextForTarget(selectedProfile, next, null, next === "web" ? targetUrl : null));
               setContextSource("default");
               if (next === "web") setProvider("playwright");
              else if (provider === "playwright") setProvider(providerStatus?.browserstack_configured ? "browserstack" : "appium");
            }}>
              <MenuItem value="web">Web</MenuItem>
              <MenuItem value="android">Android</MenuItem>
              <MenuItem value="ios">iOS</MenuItem>
            </Select>
          </FormControl>
        </Grid>
        {targetKind === "web" && <Grid item xs={12} md={8}><TextField fullWidth size="small" label="Website URL" placeholder="https://qa.example.com" value={targetUrl} disabled={busy} onChange={(event) => { setTargetUrl(event.target.value); if (contextSource === "default") setContext(contextForTarget(selectedProfile, "web", null, event.target.value)); resetResult(); }} helperText="Use a reachable non-production URL; credentials stay in approved setup references." /></Grid>}
      </Grid>
      <Grid container spacing={3}>
        <Grid item xs={12} md={5}><Stack spacing={2}>
          {targetKind !== "web" && <RepositoryAssetPicker
            projectId={selectedProjectId}
            value={selectedUploadId}
            assets={storedApks}
            assetsLoading={repositoryLoading}
            assetsError={mobileAssets.isError}
            extensions={["apk", "ipa"]}
            cacheKey="autopilot-mobile-assets"
            label="Existing APK / IPA from repository"
            emptyLabel="Upload a new build"
            helperText="Choose a build already stored for this project, or upload a new one below."
            onChange={(value, selected) => {
               setSelectedUploadId(value);
               if (selected) {
                 setFile(null);
                 const nextTarget = repositoryAssetExtension(selected) === "ipa" ? "ios" : "android";
                 setTargetKind(nextTarget);
                 setContext(contextForTarget(selectedProfile, nextTarget, selected.filename.replace(/\.(apk|ipa)$/i, "")));
                 setContextSource("default");
               }
              if (!analysis) resetResult(); else setError("");
            }}
            disabled={busy || contextBusy}
            onOpenRepository={() => navigate("/test-data/documents")}
          />}
          {targetKind !== "web" && (selectedStoredApk ? <Box sx={{ border: "1px solid", borderColor: "primary.main", borderRadius: 3, p: 2.5, bgcolor: "action.hover" }}><Stack direction="row" spacing={1.2} alignItems="center"><FolderOutlinedIcon color="primary" /><Box sx={{ minWidth: 0 }}><Typography fontWeight={800} noWrap>{selectedStoredApk.filename}</Typography><Typography variant="caption" color="text.secondary">Stored {selectedStoredApk.extension.toUpperCase()} · {formatBytes(selectedStoredApk.size_bytes)}</Typography></Box></Stack><Button size="small" sx={{ mt: 1 }} onClick={() => navigate("/test-data/documents")}>Open repository</Button></Box>
          : <Box sx={{ border: "1px dashed", borderColor: file ? "primary.main" : "divider", borderRadius: 3, p: 3, textAlign: "center", bgcolor: "action.hover" }}><CloudUploadOutlinedIcon sx={{ fontSize: 40, color: "primary.main" }} /><Typography fontWeight={700}>{file?.name || `Choose a ${targetKind === "ios" ? "iOS IPA" : "Android APK"}`}</Typography>{file && <Typography variant="caption" color="text.secondary">{formatBytes(file.size)}</Typography>}<Box sx={{ mt: 1.5 }}><Button component="label" variant="outlined" disabled={busy}>Choose build<input hidden type="file" accept=".apk,.ipa,application/vnd.android.package-archive,application/octet-stream" onChange={onFile} /></Button></Box></Box>)}
        </Stack></Grid>
        <Grid item xs={12} md={7}>
          <TextField fullWidth multiline minRows={5} maxRows={12} inputProps={{ maxLength: 8000 }} label="Testing context" placeholder="Select a profile or add product, audience, workflow and expected-outcome details." value={context} onChange={(event) => { setContext(event.target.value); setContextSource("custom"); setContextNotice(""); }} helperText={`${context.length.toLocaleString()} / 8,000 characters · Stored with this report; never paste passwords, tokens or OTPs.`} />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ mt: 1 }}>
            <Button size="small" variant="outlined" onClick={() => void generateContext("default")} disabled={contextBusy}>Reset to profile brief</Button>
            <Button size="small" variant="outlined" onClick={() => void generateContext(context.trim() ? "improve" : "generate")} disabled={contextBusy} startIcon={contextBusy ? <CircularProgress size={14} /> : <AutoAwesomeIcon />}>{contextBusy ? "Writing context…" : context.trim() ? "Improve with AI" : "Generate with AI"}</Button>
            <Chip size="small" label={`Context: ${contextSource}`} color={contextSource === "ai" ? "primary" : "default"} variant="outlined" />
          </Stack>
          {contextNotice && <Alert severity="info" sx={{ mt: 1.5 }}>{contextNotice}</Alert>}
          <Alert severity="info" sx={{ mt: 1.5 }}>The selected target and brief guide coverage. Claims stay separate from observed evidence; missing metrics remain pending.</Alert>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }} sx={{ mt: 2 }}>
            <Button disabled={(targetKind === "web" ? !targetUrl.trim() : (!file && !selectedUploadId)) || busy || resumeBusy || !selectedProjectId} onClick={checkpointWaiting ? openSetup : () => void analyze()} variant="contained" size="large" startIcon={busy || resumeBusy ? <CircularProgress size={18} color="inherit" /> : <AutoAwesomeIcon />}>{analysisButtonLabel}</Button>
            {analysis && <Button disabled={busy || resumeBusy || !selectedProjectId} onClick={startRerun} variant="outlined" size="large">Rerun this analysis</Button>}
          </Stack>
        </Grid>
      </Grid>
      <RepositoryDocumentsPicker
        projectId={selectedProjectId}
        selectedIds={selectedDocumentAssetIds}
        onSelectionChange={setSelectedDocumentAssetIds}
        sourceModule="autopilot"
        title="Supporting project documents (optional)"
        description="Reuse requirements, API contracts, test plans and other repository documents as bounded context for this Autopilot run."
        compact
        onOpenRepository={() => navigate("/test-data/documents")}
      />
      {resumeBusy && <Alert severity="info" sx={{ mt: 1.5 }}>Inputs saved. Autopilot is resuming this analysis now; Runtime Discovery will start automatically when validation completes.</Alert>}
      {documentAnalysisRunId && <Alert severity="info" sx={{ mt: 1.5 }}>
        Document Intelligence baseline attached. Static document findings guide coverage; runtime pass/fail is established only after execution.
      </Alert>}
    {busy && <Box sx={{ mt: 2 }}><Box sx={{ height: 4, borderRadius: 2, overflow: "hidden", bgcolor: "action.hover" }}><Box sx={{ height: "100%", width: `${Math.min(99, Math.max(3, analysisProgress))}%`, bgcolor: "primary.main", transition: "width .4s ease" }} /></Box><Typography variant="caption" color="text.secondary">{analysisStage === "complete" ? "finalizing" : analysisStage.replaceAll("_", " ")} · {Math.min(99, Math.max(3, analysisProgress))}%</Typography></Box>}
    </Paper>

    {!analysis && <Card variant="outlined" sx={{ borderRadius: 3 }}><CardContent>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} justifyContent="space-between">
        <Box><Typography variant="h6" fontWeight={800}>Run outputs</Typography><Typography variant="body2" color="text.secondary">Results appear here as evidence is collected.</Typography></Box>
        <Chip size="small" label="PENDING · not started" color="info" variant="outlined" />
      </Stack>
      <Grid container spacing={1.25} sx={{ mt: 1 }}>
        {[
          ["Application understanding & test design", "Generated journeys and coverage"],
          ["Safe runtime discovery & smoke", "Screens, controls and launch evidence"],
          ["Execution metrics", "Pass rate, failures, blocked and last run"],
          ["Security & performance", "Device, resource and load evidence"],
          ["Compliance & release decision", "CBUAE/SCA controls, risks and recommendation"],
        ].map(([title, detail]) => <Grid item xs={12} sm={6} md key={title}><Box sx={{ height: "100%", p: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 2 }}><Stack direction="row" spacing={1} alignItems="flex-start"><Chip size="small" label="PENDING" color="info" variant="outlined" /><Box><Typography variant="body2" fontWeight={700}>{title}</Typography><Typography variant="caption" color="text.secondary">{detail}</Typography></Box></Stack></Box></Grid>)}
      </Grid>
    </CardContent></Card>}

    {reportTabs.length > 0 && !report && <Card variant="outlined" sx={{ borderRadius: 3 }}><CardContent>
      <Typography variant="h6" fontWeight={800}>Test &amp; Audit Report</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: .35, mb: 1.5 }}>Choose a report tab to reopen its isolated analysis and evidence.</Typography>
      <ReportTabs reportTabs={reportTabs} profiles={profiles} activeReportTabKey={activeReportTabKey} loading={reportTabsLoading} disabled={busy} onSelect={(reportTab) => { void selectReportTab(reportTab); }} />
    </CardContent></Card>}

    {error && <Alert severity="error">{error}</Alert>}

    {analysis && pendingCheckpointRequests.length > 0 && <Alert
      severity="warning"
      action={<Button color="inherit" size="small" onClick={openSetup} disabled={resumeBusy}>Review inputs</Button>}
    >
      Analysis is paused for {pendingCheckpointRequests.length} required input{pendingCheckpointRequests.length === 1 ? "" : "s"}.
      Provide, skip, reuse or generate the non-production data before dependent tests continue.
    </Alert>}

    {analysis && stats && <>
      {report && <Card variant="outlined" sx={{ borderRadius: 3, borderColor: report.recommendation === "NO_GO" ? "error.main" : reportPending ? "info.main" : "warning.main" }}><CardContent>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2} alignItems={{ md: "center" }}>
          <Stack direction="row" spacing={1} alignItems="center"><FactCheckOutlinedIcon color="primary" /><Box><Typography variant="h6" fontWeight={800}>{report.report_title}</Typography><Typography variant="caption" color="text.secondary">{report.role} · {report.prepared_for}</Typography><Typography variant="caption" color="text.secondary" display="block">Last run: {report.last_run_at ? new Date(report.last_run_at).toLocaleString() : "Pending — execution is yet to be completed."}</Typography></Box></Stack>
          <Stack direction="row" spacing={1} alignItems="center">
            <Tooltip title="Delete this report">
              <IconButton
                size="small"
                color="error"
                aria-label="Delete this Test and Audit Report"
                onClick={() => setDeleteReportOpen(true)}
                disabled={busy || deleteReportBusy}
              >
                <CloseRoundedIcon />
              </IconButton>
            </Tooltip>
            <Chip label={`RELEASE: ${report.recommendation.replaceAll("_", "-")}`} color={report.recommendation === "NO_GO" ? "error" : reportPending ? "info" : "warning"} sx={{ fontWeight: 800 }} />
          </Stack>
        </Stack>
        <ReportTabs reportTabs={reportTabs} profiles={profiles} activeReportTabKey={activeReportTabKey} loading={reportTabsLoading} disabled={busy} onSelect={(reportTab) => { void selectReportTab(reportTab); }} />
        <Alert severity={report.recommendation === "NO_GO" ? "error" : reportPending ? "info" : "warning"} sx={{ mt: 2 }}><b>{report.recommendation.replaceAll("_", "-")}</b> — {report.rationale}</Alert>
        {reportPending ? <Grid container spacing={1.5} sx={{ mt: .5 }}>
          {[["Decision", "PENDING"], ["Execution", "Pending"], ["Functional", "Pending"], ["Non-functional", "Pending"], ["Compliance", "Pending"], ["Last run", "—"]].map(([label, value]) => <Grid item xs={6} sm={4} md={2} key={label}><Box sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h6" fontWeight={800}>{value}</Typography></Box></Grid>)}
        </Grid> : <Grid container spacing={1.5} sx={{ mt: .5 }}>
          <Grid item xs={6} sm={4} md={2}><Box sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">Designed cases</Typography><Typography variant="h5" fontWeight={800}>{report.metrics.designed_test_cases}</Typography></Box></Grid>
          <Grid item xs={6} sm={4} md={2}><Box sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">Executed</Typography><Typography variant="h5" fontWeight={800}>{report.metrics.executed_test_cases ?? "—"}</Typography></Box></Grid>
          <Grid item xs={6} sm={4} md={2}><Box sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">Pass rate</Typography><Typography variant="h5" fontWeight={800}>{report.metrics.pass_rate === null ? "—" : `${report.metrics.pass_rate}%`}</Typography></Box></Grid>
          <Grid item xs={6} sm={4} md={2}><Box sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">Failed / blocked</Typography><Typography variant="h5" fontWeight={800}>{report.metrics.failed_count} / {report.metrics.blocked_count}</Typography></Box></Grid>
          <Grid item xs={6} sm={4} md={2}><Box sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">Defects</Typography><Typography variant="h5" fontWeight={800}>{report.metrics.defect_count ?? "—"}</Typography></Box></Grid>
          <Grid item xs={6} sm={4} md={2}><Box sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">Open risks</Typography><Typography variant="h5" fontWeight={800}>{report.risk_matrix.filter((risk) => risk.status === "open" || risk.status === "pending_validation").length}</Typography></Box></Grid>
        </Grid>}
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>{report.metrics.evidence_state}</Typography>
        {!reportPending && report.executive_findings.length > 0 && <Stack spacing={.5} sx={{ mt: 1.5 }}>{report.executive_findings.map((finding) => <Typography key={finding} variant="body2">• {finding}</Typography>)}</Stack>}
        {!reportPending && report.reported_issues.length > 0 && <Alert severity="warning" sx={{ mt: 1.5 }}><b>Context-reported status (unverified):</b><Stack spacing={.25} sx={{ mt: .5 }}>{report.reported_issues.map((issue) => <Typography key={issue} variant="body2">• {issue}</Typography>)}</Stack></Alert>}
        {reportPending ? <Grid container spacing={1.25} sx={{ mt: 2 }}>
          {[
            ["Functional testing", "Pending — execution is yet to be completed."],
            ["Non-functional testing", "Pending — device, load and security evidence are required."],
            ["Compliance verification", "Pending — audit logs and residency evidence are required."],
            ["Risk matrix", "Pending — populated from conclusive findings."],
            ["Engineering recommendations", "Pending — generated after evidence review."],
          ].map(([title, detail]) => <Grid item xs={12} sm={6} key={title}><Box sx={{ p: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 2 }}><Typography variant="body2" fontWeight={700}>{title}</Typography><Typography variant="caption" color="text.secondary">{detail}</Typography></Box></Grid>)}
        </Grid> : <>
        <Divider sx={{ my: 2 }} />
        <Typography variant="subtitle1" fontWeight={800}>Application overview</Typography>
        <Grid container spacing={1.5} sx={{ mt: .25 }}>
          <Grid item xs={6} md={3}><Typography variant="caption" color="text.secondary">Application</Typography><Typography fontWeight={700}>{report.application_overview.name}</Typography></Grid>
          <Grid item xs={6} md={3}><Typography variant="caption" color="text.secondary">Publisher</Typography><Typography fontWeight={700}>{report.application_overview.publisher}</Typography></Grid>
          <Grid item xs={6} md={3}><Typography variant="caption" color="text.secondary">Package / version</Typography><Typography variant="body2" sx={{ wordBreak: "break-all" }}>{report.application_overview.package_name} · {report.application_overview.version}</Typography></Grid>
          <Grid item xs={6} md={3}><Typography variant="caption" color="text.secondary">Regulatory scope</Typography><Typography variant="body2">{report.application_overview.regulatory_bodies.join(", ")}</Typography></Grid>
          <Grid item xs={12}><Typography variant="caption" color="text.secondary">Core capabilities</Typography><Typography variant="body2">{report.application_overview.core_features.join(" · ")}</Typography></Grid>
        </Grid>
        <Divider sx={{ my: 2 }} />
        <Typography variant="subtitle1" fontWeight={800}>Functional testing specifications</Typography>
        <ReportChecksTable checks={report.functional_testing} />
        <Typography variant="subtitle1" fontWeight={800} sx={{ mt: 2 }}>Non-functional testing specifications</Typography>
        <ReportChecksTable checks={report.non_functional_testing} />
        <Typography variant="subtitle1" fontWeight={800} sx={{ mt: 2 }}>Audit and regulatory compliance verification</Typography>
        <ReportChecksTable checks={report.compliance_verification} />
        <Typography variant="subtitle1" fontWeight={800} sx={{ mt: 2 }}>Risk matrix</Typography>
        <ReportRiskTable risks={report.risk_matrix} />
        <Typography variant="subtitle1" fontWeight={800} sx={{ mt: 2 }}>Engineering recommendations</Typography>
        <Stack spacing={.5} sx={{ mt: 1 }}>{report.recommendations.map((item) => <Typography key={item} variant="body2">• {item}</Typography>)}</Stack>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5 }}>Evidence basis: {report.evidence.join(" · ")}</Typography>
        </>}
      </CardContent></Card>}
      {analysis.warnings.length > 0 && <Alert severity="warning">{analysis.warnings.join(" ")}</Alert>}
      <Grid container spacing={2}>{[["Generated tests", stats.tests], ["Coverage buckets", stats.buckets], ["Autonomous-safe", stats.autonomous], ["Critical / high", stats.critical]].map(([label, value]) => <Grid item xs={6} md={3} key={String(label)}><Card variant="outlined"><CardContent><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h4" fontWeight={800}>{value}</Typography></CardContent></Card></Grid>)}</Grid>

       <Grid container spacing={3}>
         <Grid item xs={12} lg={8}><Card variant="outlined" sx={{ height: "100%" }}><CardContent><Stack direction="row" spacing={1} alignItems="center"><AccountTreeOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Application intelligence</Typography></Stack><Typography sx={{ mt: 1.5 }}>{analysis.app_summary}</Typography><Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1.5 }}><Chip size="small" label={contextBadge.label} color={contextBadge.color} variant="outlined" /><Chip size="small" label={aiBadge.label} color={aiBadge.color} variant="outlined" /></Stack>{analysis.analysis_basis && analysis.analysis_basis.length > 0 && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>Basis: {analysis.analysis_basis.join(" · ")}</Typography>}<Divider sx={{ my: 2 }} /><Grid container spacing={2}><Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Application</Typography><Typography fontWeight={700}>{analysis.app_name || "Unknown"}</Typography></Grid><Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Domain</Typography><Typography fontWeight={700}>{analysis.inferred_domain}</Typography></Grid><Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Version</Typography><Typography fontWeight={700}>{analysis.version_name || "—"}</Typography></Grid><Grid item xs={12} md={6}><Typography variant="caption" color="text.secondary">Package</Typography><Typography sx={{ wordBreak: "break-all" }}>{analysis.package_name || "—"}</Typography></Grid><Grid item xs={12} md={6}><Typography variant="caption" color="text.secondary">Main activity</Typography><Typography sx={{ wordBreak: "break-all" }}>{analysis.main_activity || "—"}</Typography></Grid></Grid></CardContent></Card></Grid>
        <Grid item xs={12} lg={4}><Card variant="outlined" sx={{ height: "100%" }}><CardContent><Stack direction="row" spacing={1} alignItems="center"><SecurityOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Guardrails</Typography></Stack><Stack spacing={1} sx={{ mt: 1.5 }}><Chip label="Safe discovery: enabled" color="success" variant="outlined" /><Chip label="Transactions / destructive actions: blocked" color="warning" variant="outlined" /><Chip label={`Debuggable: ${analysis.debuggable === true ? "YES" : analysis.debuggable === false ? "No" : "Unknown"}`} variant="outlined" /></Stack></CardContent></Card></Grid>
      </Grid>

      <Card variant="outlined"><CardContent>
        <Stack direction="row" spacing={1} alignItems="center">
          <BugReportOutlinedIcon color="primary" />
          <Box>
            <Typography variant="h6" fontWeight={800}>Complete test coverage plan</Typography>
            <Typography variant="body2" color="text.secondary">
              Full coverage is designed up front; each bucket becomes conclusive only when its evidence is available.
            </Typography>
          </Box>
        </Stack>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1.5 }}>
          <Chip size="small" label={`All (${stats.tests})`} color={testBucketFilter === "all" ? "primary" : "default"} variant={testBucketFilter === "all" ? "filled" : "outlined"} onClick={() => setTestBucketFilter("all")} />
          {TEST_BUCKETS.filter((bucket) => bucketCounts[bucket]).map((bucket) => (
            <Chip
              key={bucket}
              size="small"
              label={`${testBucketLabel[bucket]} (${bucketCounts[bucket]})`}
              color={testBucketFilter === bucket ? "primary" : "default"}
              variant={testBucketFilter === bucket ? "filled" : "outlined"}
              onClick={() => setTestBucketFilter(bucket)}
            />
          ))}
        </Stack>
        <Alert severity="info" sx={{ mt: 1.5 }}>
          A generated case is a plan, not a pass. Authenticated journeys require a secure non-production credential reference,
          approved test data and an oracle/reset hook; no password is stored in the context or sent to the model.
        </Alert>
        <TableContainer sx={{ mt: 1.5, maxHeight: 460 }}>
          <Table stickyHeader size="small">
            <TableHead><TableRow>
              <TableCell>Test</TableCell><TableCell>Bucket</TableCell><TableCell>Priority</TableCell>
              <TableCell>Source</TableCell><TableCell>Execution state</TableCell>
            </TableRow></TableHead>
            <TableBody>
              {visibleTests.map((test) => {
                const bucket = normalizedBucket(test);
                const setupRequired = Boolean(test.requires_auth || test.requires_test_data || test.dependency);
                return <TableRow key={test.id} hover>
                  <TableCell sx={{ minWidth: 320 }}>
                    <Typography fontWeight={700} variant="body2">{test.title}</Typography>
                    <Typography variant="caption" color="text.secondary">{test.id} · {test.objective}</Typography>
                  </TableCell>
                  <TableCell><Chip size="small" label={testBucketLabel[bucket]} variant="outlined" /></TableCell>
                  <TableCell><Chip size="small" label={test.priority.toUpperCase()} color={priorityColor[test.priority]} variant="outlined" /></TableCell>
                  <TableCell>{test.source === "ai" ? "AI" : "RULE"}</TableCell>
                  <TableCell sx={{ minWidth: 250 }}>
                    <Chip size="small" label={testModeLabel(test)} color={test.destructive ? "warning" : setupRequired ? "info" : "success"} variant="outlined" />
                    {test.dependency && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: .5 }}>{test.dependency}</Typography>}
                  </TableCell>
                </TableRow>;
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </CardContent></Card>

      <Card variant="outlined"><CardContent>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2} alignItems={{ md: "center" }}><Box><Stack direction="row" spacing={1} alignItems="center"><TravelExploreOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Runtime discovery</Typography></Stack><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>{activeTargetKind === "web" ? "Map same-origin website pages and semantic controls with bounded, read-only browser navigation." : `Map screens and semantic controls from the running ${activeTargetKind === "ios" ? "iOS" : "Android"} app.`} Payments, transfers, delete, submit, confirm and OTP actions remain blocked.</Typography></Box><Stack direction="row" spacing={1}><FormControl size="small" sx={{ minWidth: 145 }}><InputLabel id="discovery-mode-label">Mode</InputLabel><Select labelId="discovery-mode-label" label="Mode" value={discoveryMode} onChange={(event) => setDiscoveryMode(event.target.value as "safe" | "observe")}><MenuItem value="safe">Safe navigation</MenuItem><MenuItem value="observe">Observe only</MenuItem></Select></FormControl><Button variant="contained" startIcon={discoveryBusy ? <CircularProgress size={16} color="inherit" /> : <TravelExploreOutlinedIcon />} disabled={discoveryBusy || executionUnavailable} onClick={runDiscovery}>{discoveryBusy ? "Discovering…" : "Run discovery"}</Button></Stack></Stack>
        {browserStackUnavailable && activeTargetKind !== "web" && <Alert severity="warning" sx={{ mt: 2 }}>BrowserStack credentials are not configured. Choose a reachable custom Appium endpoint or configure BrowserStack.</Alert>}
        {discovery && <><Grid container spacing={1.5} sx={{ mt: 1 }}>{[["Screens", discovery.screen_count], ["Controls", discovery.control_count], ["Safe controls", discovery.safe_control_count], ["Blocked", discovery.blocked_control_count], ["Actions", discovery.actions_attempted]].map(([label, value]) => <Grid item xs={6} sm={4} md key={String(label)}><Box sx={{ p: 1.25, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h6" fontWeight={800}>{value}</Typography></Box></Grid>)}</Grid><Alert severity={discovery.status === "completed" ? "success" : discovery.status === "blocked" ? "warning" : discovery.status === "failed" ? "error" : "info"} sx={{ mt: 2 }}>Discovery: <b>{discovery.status.toUpperCase()}</b> · {discovery.stop_reason}{discovery.error ? ` · ${discovery.error}` : ""}</Alert>{discovery.screens.length > 0 && <Grid container spacing={1.5} sx={{ mt: .5 }}>{discovery.screens.map((screen) => <Grid item xs={12} sm={6} lg={4} key={screen.screen_id}><RuntimeScreenPreview screen={screen} /></Grid>)}</Grid>}{discoveredRows.length > 0 && <TableContainer sx={{ mt: 2, maxHeight: 400 }}><Table stickyHeader size="small"><TableHead><TableRow><TableCell>Screen</TableCell><TableCell>Control</TableCell><TableCell>Risk</TableCell><TableCell>Best locator</TableCell><TableCell>Confidence</TableCell></TableRow></TableHead><TableBody>{discoveredRows.slice(0, 150).map(({ screen, control }) => { const locator = control.locators[0]; return <TableRow key={`${screen}-${control.control_id}`} hover><TableCell>{screen}</TableCell><TableCell><Typography variant="body2" fontWeight={700}>{control.semantic_label}</Typography><Typography variant="caption" color="text.secondary">{control.class_name.split(".").pop() || control.class_name}</Typography></TableCell><TableCell><Chip size="small" label={control.risk} color={riskColor[control.risk]} variant="outlined" /></TableCell><TableCell sx={{ maxWidth: 320 }}><Typography variant="caption" sx={{ wordBreak: "break-all" }}>{locator ? `${locator.strategy}: ${locator.value}` : "No deterministic locator"}</Typography></TableCell><TableCell>{locator ? `${Math.round(locator.confidence * 100)}%` : "—"}</TableCell></TableRow>; })}</TableBody></Table></TableContainer>}</>}
      </CardContent></Card>

      <Card variant="outlined"><CardContent>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2} alignItems={{ md: "center" }}>
          <Box>
            <Stack direction="row" spacing={1} alignItems="center"><SmartToyOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Semantic automation & safe execution</Typography></Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>
              Run only cases with safe deterministic actions. Functional/UAT cases are still shown with their setup dependency;
              they cannot be reported as passed until credentials, data, locators and assertions are supplied.
            </Typography>
          </Box>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <FormControl size="small" sx={{ minWidth: 170 }}>
              <InputLabel id="suite-bucket-label">Suite bucket</InputLabel>
              <Select labelId="suite-bucket-label" label="Suite bucket" value={suiteBucket} onChange={(event) => setSuiteBucket(event.target.value as "all" | TestBucket)}>
                <MenuItem value="all">All safe cases</MenuItem>
                {TEST_BUCKETS.filter((bucket) => (automation?.bucket_counts?.[bucket] || bucketCounts[bucket])).map((bucket) => <MenuItem key={bucket} value={bucket}>{testBucketLabel[bucket]}</MenuItem>)}
              </Select>
            </FormControl>
            <Button variant="contained" startIcon={suiteBusy ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRoundedIcon />} disabled={suiteBusy || executionUnavailable || suiteExecutableCount === 0} onClick={runSuite}>
              {suiteBusy ? "Running suite…" : suiteBucket === "all" ? "Run safe subset" : `Run ${testBucketLabel[suiteBucket]} safe subset`}
            </Button>
          </Stack>
        </Stack>
        <Box sx={{ mt: 2, p: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} justifyContent="space-between">
            <Box><Typography variant="subtitle2" fontWeight={800}>Autopilot checkpoint</Typography><Typography variant="caption" color="text.secondary">One guided input at a time: sign-in fields, test data and references are explained in plain language. Saved values are encrypted under Test Data and never shown again.</Typography></Box>
            <Button size="small" variant="outlined" onClick={openSetup} disabled={resumeBusy}>{pendingCheckpointRequests.length ? "Review required inputs" : activeSetup.provided_fields.length ? "Review inputs" : "Open checkpoint"}</Button>
          </Stack>
          {activeSetup.checkpoint_message && <Alert severity={pendingCheckpointRequests.length ? "warning" : "info"} sx={{ mt: 1.25 }}>{activeSetup.checkpoint_message}</Alert>}
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
            <Chip size="small" label={(activeSetup.provided_fields.length || 0) + " setup items provided"} color={activeSetup.provided_fields.length ? "success" : "default"} variant="outlined" />
            {pendingCheckpointRequests.length > 0 && <Chip size="small" label={`${pendingCheckpointRequests.length} input${pendingCheckpointRequests.length === 1 ? "" : "s"} still required`} color="warning" variant="outlined" />}
            {(automation?.setup_missing_fields || []).slice(0, 6).map((field) => <Chip key={field} size="small" label={"Pending: " + field} color="warning" variant="outlined" />)}
          </Stack>
          {pendingCheckpointRequests.slice(0, 6).map((request) => <Box key={request.key} sx={{ mt: 1, p: 1, borderRadius: 1.5, bgcolor: "warning.lighter", border: "1px solid", borderColor: "warning.light" }}><Stack direction="row" spacing={.75} alignItems="center"><Chip size="small" label={inputCategoryLabel(request.category)} variant="outlined" /><Typography variant="body2" fontWeight={700}>{request.label}</Typography></Stack><Typography variant="caption" color="text.secondary" display="block" sx={{ mt: .35 }}>{request.question || request.reason}</Typography><Typography variant="caption" color="text.secondary">Needed for: {requestDependentTitles(request, analysis.tests).join(" · ") || "this checkpoint"}</Typography></Box>)}
          {(activeSetup.runtime_input_requests || []).length > 0 && <Box sx={{ mt: 1.25, p: 1.25, borderRadius: 1.5, bgcolor: "info.lighter", border: "1px solid", borderColor: "info.light" }}><Typography variant="body2" fontWeight={700}>Runtime fields mapped</Typography><Typography variant="caption" color="text.secondary">{(activeSetup.runtime_input_requests || []).length} field{(activeSetup.runtime_input_requests || []).length === 1 ? "" : "s"} were found on the live screen map. Click “Review required inputs” above to enter the exact User ID, Password, Address or other field value.</Typography></Box>}
          {resumeBusy && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>Validating saved references and resuming the checkpoint…</Typography>}
        </Box>
        {automation && <><Grid container spacing={1.5} sx={{ mt: 1 }}>{[["Executable", automation.executable_count], ["Promoted by discovery", automation.promoted_count], ["Needs discovery/data", automation.discovery_required_count], ["Approval required", automation.approval_required_count]].map(([label, value]) => <Grid item xs={6} md={3} key={String(label)}><Box sx={{ p: 1.25, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h6" fontWeight={800}>{value}</Typography></Box></Grid>)}</Grid><Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>IR {automation.schema_version} · runtime discovery {automation.discovery_used ? "consumed" : "not yet available"} · full plan buckets are listed above</Typography><TableContainer sx={{ mt: 1.5, maxHeight: 360 }}><Table stickyHeader size="small"><TableHead><TableRow><TableCell>Test</TableCell><TableCell>Bucket</TableCell><TableCell>Readiness</TableCell><TableCell>Dependency / reason</TableCell></TableRow></TableHead><TableBody>{automation.tests.slice(0, 80).map((test) => { const bucket = normalizedBucket(test); return <TableRow key={test.test_id} hover><TableCell><Typography variant="body2" fontWeight={700}>{test.title}</Typography><Typography variant="caption" color="text.secondary">{test.test_id}</Typography></TableCell><TableCell><Chip size="small" label={testBucketLabel[bucket]} variant="outlined" /></TableCell><TableCell><Chip size="small" label={test.readiness.replaceAll("_", " ")} color={readinessColor[test.readiness]} variant="outlined" /></TableCell><TableCell sx={{ maxWidth: 430 }}><Typography variant="caption" color="text.secondary">{test.readiness_reason || test.dependency || "—"}</Typography>{test.readiness !== "executable" && <Button size="small" sx={{ ml: 1 }} onClick={openSetup}>Resolve</Button>}</TableCell></TableRow>; })}</TableBody></Table></TableContainer></>}
        {suite && <><Alert sx={{ mt: 2 }} severity={suite.status === "passed" ? "success" : suite.status === "blocked" ? "warning" : suite.status === "partial" ? "info" : "error"}>Safe subset: <b>{suite.status.toUpperCase()}</b> · {suite.passed_count} passed · {suite.failed_count} failed · {suite.skipped_count} deferred/blocked · {suite.duration_seconds}s{suite.deferred_count ? ` · ${suite.deferred_count} plan case(s) still pending` : ""}{suite.promoted_count ? ` · ${suite.promoted_count} discovery-promoted` : ""}{suite.error ? ` · ${suite.error}` : ""}</Alert>{suite.tests.length > 0 && <TableContainer sx={{ mt: 1.5, maxHeight: 360 }}><Table stickyHeader size="small"><TableHead><TableRow><TableCell>Test</TableCell><TableCell>Bucket</TableCell><TableCell>Status</TableCell><TableCell>Dependency / result</TableCell></TableRow></TableHead><TableBody>{suite.tests.map((test) => <TableRow key={test.test_id}><TableCell><Typography variant="body2" fontWeight={700}>{test.title}</Typography><Typography variant="caption" color="text.secondary">{test.test_id}</Typography></TableCell><TableCell>{test.bucket ? testBucketLabel[test.bucket] : "—"}</TableCell><TableCell><Chip size="small" label={test.status.toUpperCase()} color={test.status === "passed" ? "success" : test.status === "failed" ? "error" : "warning"} variant="outlined" /></TableCell><TableCell><Typography variant="caption" color={test.error ? "error" : "text.secondary"}>{test.error || test.dependency || "Evidence captured"}</Typography></TableCell></TableRow>)}</TableBody></Table></TableContainer>}</>}
      </CardContent></Card>

      <Card variant="outlined"><CardContent><Stack direction="row" spacing={1} alignItems="center"><PlayArrowRoundedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Execution target & safe smoke</Typography></Stack><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>This target is shared by Runtime Discovery, the autonomous safe suite and smoke execution.</Typography>
      {providerStatusPending && <Alert severity="info" sx={{ mt: 2 }}>Checking execution providers…</Alert>}
      {activeTargetKind === "web" && <Alert severity="info" sx={{ mt: 2 }}>Website execution uses bounded, read-only Playwright checks. Authenticated, transactional and destructive journeys remain pending until approved setup is supplied.</Alert>}
      {noExecutionProvider && <Alert severity="warning" sx={{ mt: 2 }}>No hosted mobile execution provider is configured. Configure BrowserStack credentials or enter a reachable HTTPS Appium endpoint before running.</Alert>}
      {browserStackUnavailable && activeTargetKind !== "web" && <Alert severity="warning" sx={{ mt: 2 }}>BrowserStack credentials are not configured. Choose Custom / local Appium and enter a reachable endpoint.</Alert>}
      {activeProvider === "appium" && providerStatus?.custom_appium_reason && <Alert severity="warning" sx={{ mt: 2 }}>{providerStatus.custom_appium_reason}</Alert>}
      <Grid container spacing={2} sx={{ mt: .5 }}>
        {activeTargetKind === "web" ? <Grid item xs={12} md={4}><TextField fullWidth size="small" label="Website target" value={analysis?.target_url || targetUrl} InputProps={{ readOnly: true }} /></Grid> : <Grid item xs={12} md={3}><FormControl fullWidth size="small"><InputLabel id="autopilot-provider-label">Execution provider</InputLabel><Select labelId="autopilot-provider-label" label="Execution provider" value={provider} onChange={(event) => setProvider(event.target.value as Provider)}><MenuItem value="browserstack" disabled={providerStatus !== null && !providerStatus.browserstack_configured}>BrowserStack real device</MenuItem><MenuItem value="appium">Custom / local Appium</MenuItem></Select></FormControl></Grid>}
        {activeTargetKind !== "web" && <Grid item xs={12} md={3}><TextField fullWidth size="small" label="Device name" value={deviceName} onChange={(event) => setDeviceName(event.target.value)} /></Grid>}
        {activeTargetKind !== "web" && <Grid item xs={12} md={2}><TextField fullWidth size="small" label={`${activeTargetKind === "ios" ? "iOS" : "Android"} version`} value={platformVersion} onChange={(event) => setPlatformVersion(event.target.value)} /></Grid>}
        <Grid item xs={12} md={activeTargetKind === "web" ? 8 : 4}><Button fullWidth sx={{ height: 40 }} variant="outlined" disabled={smokeBusy || executionUnavailable} onClick={runSmoke} startIcon={smokeBusy ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRoundedIcon />}>{smokeBusy ? "Running…" : "Run safe smoke only"}</Button></Grid>
        {activeTargetKind !== "web" && provider === "appium" && <><Grid item xs={12} md={6}><TextField fullWidth size="small" label="Appium server URL" value={appiumUrl} onChange={(event) => setAppiumUrl(event.target.value)} helperText="Hosted runs require a reachable HTTPS endpoint; leave blank only when the backend has one configured." /></Grid><Grid item xs={12} md={6}><TextField fullWidth size="small" label="Optional remote app reference" value={appiumApp} onChange={(event) => setAppiumApp(event.target.value)} /></Grid></>}
        {activeTargetKind !== "web" && <Grid item xs={12}><FormControlLabel control={<Switch checked={autoGrantPermissions} onChange={(event) => setAutoGrantPermissions(event.target.checked)} />} label="Auto-grant runtime permissions" /><Typography variant="caption" color="text.secondary" display="block">Prevents unattended runs from stalling on platform permission dialogs; grant/deny behavior remains covered by generated tests.</Typography></Grid>}
      </Grid>
      {execution && <Alert sx={{ mt: 2 }} severity={execution.status === "passed" ? "success" : execution.status === "blocked" ? "warning" : "error"}>Smoke: <b>{execution.status.toUpperCase()}</b> · {execution.provider} · {execution.duration_seconds}s{execution.current_package ? ` · ${execution.current_package}` : ""}{execution.error ? ` · ${execution.error}` : ""}</Alert>}
      {execution && (execution.screenshot_asset_id || execution.page_source_asset_id) && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>Evidence is retained with this run and is available in Test Reports.</Typography>}
      {executionHistory.length > 0 && <Box sx={{ mt: 2 }}><Typography variant="subtitle2" fontWeight={800}>Previous smoke runs</Typography><Stack spacing={1} sx={{ mt: 1 }}>{executionHistory.map((item) => <Paper key={item.execution_id} variant="outlined" sx={{ p: 1.25 }}><Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} justifyContent="space-between"><Box><Typography variant="body2" fontWeight={700}>{item.status.toUpperCase()} · {item.request.provider} · {item.request.device_name}</Typography><Typography variant="caption" color="text.secondary">{new Date(item.created_at).toLocaleString()} · {item.duration_seconds}s</Typography></Box><Button size="small" variant="outlined" disabled={smokeBusy} onClick={() => rerunSmoke(item.execution_id)}>Rerun</Button></Stack></Paper>)}</Stack></Box>}
      </CardContent></Card>

      {analysis.release_risks.length > 0 && <Alert severity="info"><b>Initial release risks:</b> {analysis.release_risks.join(" • ")}</Alert>}
    </>}

    <Dialog open={Boolean(duplicatePrompt)} onClose={() => !busy && setDuplicatePrompt(null)} fullWidth maxWidth="sm">
      <DialogTitle>Existing Test &amp; Audit Report tab</DialogTitle>
      <DialogContent>
        <Alert severity="info" sx={{ mb: 2 }}>{duplicatePrompt?.message}</Alert>
        {duplicatePrompt?.createdAt && <Typography variant="body2" color="text.secondary">Previous result: {new Date(duplicatePrompt.createdAt).toLocaleString()}</Typography>}
        <Typography variant="body2" sx={{ mt: 1 }}>Keep the existing evidence and create a new report tab, or override the existing tab and make this run current.</Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setDuplicatePrompt(null)} disabled={busy}>Cancel</Button>
        <Button variant="outlined" onClick={() => { setDuplicatePrompt(null); void analyze("new"); }} disabled={busy}>Create new report tab</Button>
        <Button variant="contained" color="warning" onClick={() => { setDuplicatePrompt(null); void analyze("override"); }} disabled={busy}>Override existing tab</Button>
      </DialogActions>
    </Dialog>

    <Dialog open={deleteReportOpen} onClose={() => !deleteReportBusy && setDeleteReportOpen(false)} fullWidth maxWidth="sm">
      <DialogTitle>Delete this Test &amp; Audit Report?</DialogTitle>
      <DialogContent>
        <Alert severity="warning" sx={{ mb: 2 }}>
          This permanently removes the selected report tab’s analysis, setup/checkpoint data, runtime discovery, safe-smoke history and generated report state.
        </Alert>
        <Typography variant="body2" color="text.secondary">
          The original APK/IPA, uploaded documents and captured evidence assets remain in the project repository and can be reused for a new report. This action cannot be undone for the report data.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setDeleteReportOpen(false)} disabled={deleteReportBusy}>Cancel</Button>
        <Button variant="contained" color="error" onClick={() => void deleteReport()} disabled={deleteReportBusy} startIcon={deleteReportBusy ? <CircularProgress size={16} color="inherit" /> : <CloseRoundedIcon />}>
          {deleteReportBusy ? "Deleting…" : "Delete report"}
        </Button>
      </DialogActions>
    </Dialog>

    <Dialog open={rerunSetupPrompt} onClose={() => !busy && setRerunSetupPrompt(false)} fullWidth maxWidth="sm">
      <DialogTitle>Validate saved setup before rerun</DialogTitle>
      <DialogContent>
        <Alert severity="info" sx={{ mb: 2 }}>
          This target already has saved setup references. They are shown only as references and never contain passwords, tokens or OTPs. Confirm they still point to the correct non-production resources, or start with a fresh checkpoint.
        </Alert>
        <Stack spacing={.75}>
          {(setup?.provided_fields || []).map((field) => <Chip key={field} size="small" label={`Saved: ${field.replaceAll("_", " ")}`} variant="outlined" sx={{ justifyContent: "flex-start" }} />)}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setRerunSetupPrompt(false)} disabled={busy}>Cancel</Button>
        <Button variant="outlined" onClick={() => { setRerunSetupPrompt(false); void rerunAnalysis("fresh"); }} disabled={busy}>Start fresh checkpoint</Button>
        <Button variant="contained" onClick={() => { setRerunSetupPrompt(false); void rerunAnalysis("reuse"); }} disabled={busy}>Reuse after confirmation</Button>
      </DialogActions>
    </Dialog>

    <Dialog open={setupOpen} onClose={() => !setupBusy && !resumeBusy && setSetupOpen(false)} fullWidth maxWidth="md">
      <DialogTitle>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} justifyContent="space-between">
          <Box><Typography variant="h6" fontWeight={800}>Autopilot checkpoint</Typography><Typography variant="caption" color="text.secondary">Confirm each input before the dependent tests continue.</Typography></Box>
          {checkpointRequests.length > 0 && <Chip size="small" color="primary" variant="outlined" label={`Input ${activeCheckpointIndex + 1} of ${checkpointRequests.length}`} />}
        </Stack>
      </DialogTitle>
      <DialogContent>
        <Alert severity={pendingCheckpointRequests.length > 0 ? "warning" : "info"} sx={{ mb: 2 }}>
          {pendingCheckpointRequests.length > 0
            ? `${pendingCheckpointRequests.length} input${pendingCheckpointRequests.length === 1 ? "" : "s"} still need a decision.`
            : "All checkpoint inputs have a decision. Save to continue to Runtime Discovery."}
          {" "}Use only non-production data. Values are encrypted under Test Data, never returned, added to context, or written to logs. Choose Skip when the case is not in scope for this run.
        </Alert>
        {activeCheckpointRequest && activeCheckpointDraft && <>
          <Stack direction="row" spacing={.75} alignItems="center" sx={{ mb: 1 }}>
            <Chip size="small" label={inputCategoryLabel(activeCheckpointRequest.category)} color="primary" variant="outlined" />
            {activeCheckpointRequest.source === "runtime" && <Chip size="small" label="Found on live screen" color="info" variant="outlined" />}
            {activeCheckpointRequest.status !== "pending" && <Chip size="small" label={activeCheckpointRequest.status} color={activeCheckpointRequest.status === "skipped" ? "warning" : "success"} variant="outlined" />}
          </Stack>
          <Box sx={{ p: 2, border: "1px solid", borderColor: activeCheckpointDraft.decision === "skip" ? "divider" : "info.light", bgcolor: activeCheckpointDraft.decision === "skip" ? "action.hover" : "info.lighter", borderRadius: 2 }}>
            <Typography variant="subtitle1" fontWeight={800}>{activeCheckpointRequest.label}</Typography>
            <Typography variant="body2" sx={{ mt: .5 }}>{activeCheckpointRequest.question || "What should Autopilot use for this setup item?"}</Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: .75 }}>{activeCheckpointRequest.format_hint || activeCheckpointRequest.reason}</Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: .5 }}>Needed for: {requestDependentTitles(activeCheckpointRequest, analysis?.tests || []).join(" · ") || "this checkpoint"}</Typography>
            {activeCheckpointRequest.screen_id && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: .5 }}>Screen: {activeCheckpointRequest.screen_id}{activeCheckpointRequest.locator ? ` · Control: ${activeCheckpointRequest.locator}` : ""}</Typography>}
            {activeCheckpointSaved?.save_for_reuse && <Alert severity="success" sx={{ mt: 1.25 }}>A saved encrypted value exists for this field. Choose “Reuse saved” to use it without revealing it.</Alert>}
            {activeCheckpointRequest.category === "approval" ? <Alert severity="info" sx={{ mt: 1.5 }}>
              <Typography variant="body2" fontWeight={700}>Authentication permission</Typography>
              <Typography variant="body2" sx={{ mt: .25 }}>Allow Autopilot to sign in to the approved non-production environment. Payments, OTP submission and destructive actions remain blocked.</Typography>
              <FormControlLabel
                control={<Switch checked={setupDraft.safe_authentication_approved && activeCheckpointDraft.decision !== "skip"} onChange={(event) => {
                  const approved = event.target.checked;
                  updateSetup("safe_authentication_approved", approved);
                  updateInputDraft(activeCheckpointRequest.key, { decision: approved ? "provide" : "skip", value: "" });
                }} />}
                label="Approve safe sign-in for this run"
              />
            </Alert> : <>
              <FormControl size="small" fullWidth sx={{ mt: 1.5 }}>
                <InputLabel>What should Autopilot do?</InputLabel>
                <Select label="What should Autopilot do?" value={activeCheckpointDraft.decision} onChange={(event) => updateInputDraft(activeCheckpointRequest.key, { decision: event.target.value as InputDecision, value: event.target.value === "provide" ? activeCheckpointDraft.value : "", username: event.target.value === "provide" ? activeCheckpointDraft.username : "", password: event.target.value === "provide" ? activeCheckpointDraft.password : "" })}>
                  <MenuItem value="provide">Enter this value</MenuItem>
                  <MenuItem value="skip">Skip this case input</MenuItem>
                  <MenuItem value="reuse" disabled={!activeCheckpointSaved?.save_for_reuse}>Reuse saved encrypted value</MenuItem>
                  {activeCheckpointRequest.category === "test_data" && !activeCheckpointRequest.sensitive && <MenuItem value="random">Generate safe random data</MenuItem>}
                </Select>
              </FormControl>
              {activeCheckpointDraft.decision === "provide" && activeCheckpointRequest.credential_bundle ? <>
                <Alert severity="info" sx={{ mt: 1.25 }}>Authentication details: enter the non-production User ID/email and password for the account described above. These values are encrypted immediately and are never added to the context or logs.</Alert>
                <Grid container spacing={1.25} sx={{ mt: .5 }}>
                  <Grid item xs={12} md={6}><TextField fullWidth size="small" label="User ID / email" placeholder="qa.investor@example.test" value={activeCheckpointDraft.username} onChange={(event) => updateInputDraft(activeCheckpointRequest.key, { username: event.target.value })} autoComplete="off" helperText="Use the non-production account ID or email." /></Grid>
                  <Grid item xs={12} md={6}><TextField fullWidth size="small" type="password" label="Password" placeholder="Password for this UAT account" value={activeCheckpointDraft.password} onChange={(event) => updateInputDraft(activeCheckpointRequest.key, { password: event.target.value })} autoComplete="new-password" helperText="Encrypted immediately; never echoed or sent to the model." /></Grid>
                  <Grid item xs={12}><FormControlLabel control={<Switch size="small" checked={activeCheckpointDraft.save_for_reuse} onChange={(event) => updateInputDraft(activeCheckpointRequest.key, { save_for_reuse: event.target.checked })} />} label="Save this sign-in securely for this target" /></Grid>
                </Grid>
              </> : activeCheckpointDraft.decision === "provide" && <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mt: 1 }}><TextField fullWidth size="small" type={activeCheckpointRequest.input_hint === "password" || activeCheckpointRequest.input_hint === "otp" ? "password" : "text"} label={activeCheckpointRequest.input_hint === "password" ? "Password" : activeCheckpointRequest.input_hint === "otp" ? "One-time code" : activeCheckpointRequest.input_hint === "username" ? "User ID / email" : "Value or reference"} placeholder={activeCheckpointRequest.placeholder || undefined} value={activeCheckpointDraft.value} onChange={(event) => updateInputDraft(activeCheckpointRequest.key, { value: event.target.value })} autoComplete="off" helperText={activeCheckpointRequest.format_hint || "Use synthetic/non-production data only."} /><FormControlLabel control={<Switch size="small" checked={activeCheckpointDraft.save_for_reuse} onChange={(event) => updateInputDraft(activeCheckpointRequest.key, { save_for_reuse: event.target.checked })} />} label="Save encrypted" /></Stack>}
            </>}
            {activeCheckpointDraft.decision === "random" && <Grid container spacing={1} sx={{ mt: .25 }}><Grid item xs={12} sm={4}><FormControl fullWidth size="small"><InputLabel>Generator</InputLabel><Select label="Generator" value={activeCheckpointDraft.random_spec.kind} onChange={(event) => updateInputDraft(activeCheckpointRequest.key, { random_spec: { ...activeCheckpointDraft.random_spec, kind: event.target.value as RandomSpec["kind"] } })}>{["text", "digits", "number", "amount", "email", "phone", "date"].map((kind) => <MenuItem key={kind} value={kind}>{kind}</MenuItem>)}</Select></FormControl></Grid><Grid item xs={6} sm={2}><TextField fullWidth size="small" type="number" label="Length" value={activeCheckpointDraft.random_spec.length} onChange={(event) => updateInputDraft(activeCheckpointRequest.key, { random_spec: { ...activeCheckpointDraft.random_spec, length: Math.max(1, Number(event.target.value) || 1) } })} /></Grid><Grid item xs={6} sm={3}><TextField fullWidth size="small" type="number" label="Minimum" value={activeCheckpointDraft.random_spec.minimum ?? ""} onChange={(event) => updateInputDraft(activeCheckpointRequest.key, { random_spec: { ...activeCheckpointDraft.random_spec, minimum: event.target.value === "" ? undefined : Number(event.target.value) } })} /></Grid><Grid item xs={6} sm={3}><TextField fullWidth size="small" type="number" label="Maximum" value={activeCheckpointDraft.random_spec.maximum ?? ""} onChange={(event) => updateInputDraft(activeCheckpointRequest.key, { random_spec: { ...activeCheckpointDraft.random_spec, maximum: event.target.value === "" ? undefined : Number(event.target.value) } })} /></Grid><Grid item xs={12}><FormControlLabel control={<Switch size="small" checked={activeCheckpointDraft.save_for_reuse} onChange={(event) => updateInputDraft(activeCheckpointRequest.key, { save_for_reuse: event.target.checked })} />} label="Save generated value encrypted" /><Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>Generated data is bounded synthetic input; it never uses production data.</Typography></Grid></Grid>}
            {activeCheckpointRequest.category !== "approval" && activeCheckpointDraft.decision !== "skip" && activeCheckpointDraft.decision !== "reuse" && <Button size="small" sx={{ mt: .75 }} onClick={() => updateInputDraft(activeCheckpointRequest.key, { decision: "skip", value: "", username: "", password: "", save_for_reuse: false })}>Skip this input</Button>}
            {activeCheckpointRequest.category !== "approval" && activeCheckpointDraft.decision === "skip" && <Button size="small" sx={{ mt: .75 }} onClick={() => updateInputDraft(activeCheckpointRequest.key, { decision: activeCheckpointSaved?.save_for_reuse ? "reuse" : "provide" })}>Undo skip</Button>}
          </Box>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1.25 }}>
            <Button size="small" variant="outlined" disabled={activeCheckpointIndex === 0} onClick={() => setCheckpointStep((current) => Math.max(0, current - 1))}>Previous input</Button>
            <Button size="small" variant="outlined" disabled={activeCheckpointIndex >= checkpointRequests.length - 1} onClick={() => setCheckpointStep((current) => Math.min(checkpointRequests.length - 1, current + 1))}>Next input</Button>
            <Typography variant="caption" color="text.secondary">You can revisit any input before saving.</Typography>
          </Stack>
        </>}
        <Typography variant="overline" color="text.secondary" fontWeight={800} display="block" sx={{ mt: 2 }}>Optional setup references</Typography>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>Use these only when your team already has a vault, fixture, reset hook or oracle reference. Direct values entered above are enough for this checkpoint.</Typography>
        <Grid container spacing={2}>
          <Grid item xs={12} md={6}><TextField fullWidth label="Credential-set reference (optional)" value={setupDraft.credential_reference} onChange={(event) => updateSetup("credential_reference", event.target.value)} helperText="Example: qtxpert://credentials/uat · never paste a password" /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Test account role (optional)" value={setupDraft.account_role} onChange={(event) => updateSetup("account_role", event.target.value)} placeholder="Retail investor / relationship manager" /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Environment name (optional)" value={setupDraft.environment_name} onChange={(event) => updateSetup("environment_name", event.target.value)} placeholder="UAT" /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Environment URL / identifier (optional)" value={setupDraft.environment_url} onChange={(event) => updateSetup("environment_url", event.target.value)} /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Synthetic test-data reference (optional)" value={setupDraft.test_data_reference} onChange={(event) => updateSetup("test_data_reference", event.target.value)} /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Reset / cleanup reference (optional)" value={setupDraft.reset_hook_reference} onChange={(event) => updateSetup("reset_hook_reference", event.target.value)} /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Acceptance-criteria reference (optional)" value={setupDraft.acceptance_criteria_reference} onChange={(event) => updateSetup("acceptance_criteria_reference", event.target.value)} /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="API / oracle reference (optional)" value={setupDraft.api_oracle_reference} onChange={(event) => updateSetup("api_oracle_reference", event.target.value)} /></Grid>
          <Grid item xs={12}><TextField fullWidth multiline minRows={3} label="Safe navigation and data notes" value={setupDraft.navigation_notes} onChange={(event) => updateSetup("navigation_notes", event.target.value)} helperText="Describe seeded users, permitted paths and expected reset behavior. Never include secret values." /></Grid>
          <Grid item xs={12}><FormControlLabel control={<Switch checked={setupDraft.safe_authentication_approved} onChange={(event) => updateSetup("safe_authentication_approved", event.target.checked)} />} label="Approve safe non-transactional authentication in this UAT environment" /></Grid>
        </Grid>
      </DialogContent>
      <DialogActions><Button onClick={() => setSetupOpen(false)} disabled={setupBusy || resumeBusy}>Cancel</Button><Button variant="contained" onClick={saveSetup} disabled={setupBusy || resumeBusy}>{setupBusy ? "Saving…" : resumeBusy ? "Continuing…" : "Save and continue"}</Button></DialogActions>
    </Dialog>
  </Stack>;
}

