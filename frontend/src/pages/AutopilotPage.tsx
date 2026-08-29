import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Dialog, DialogActions,
  DialogContent, DialogTitle, Divider, FormControl, FormControlLabel, Grid, InputLabel,
  MenuItem, Paper, Select, Stack, Switch, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TextField, Typography,
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
import { apiClient } from "@/services/apiClient";
import { uploadsApi } from "@/services/api";
import { UploadedAsset } from "@/types/domain";
import { useSelectedProject } from "@/hooks/useSelectedProject";

type TestBucket =
  | "installation" | "page_level" | "functional" | "uat" | "ui" | "accessibility"
  | "integration" | "performance" | "security" | "compatibility" | "resilience"
  | "permissions" | "regression";
type TestCase = {
  id: string; suite: string; title: string; priority: "critical" | "high" | "medium" | "low";
  objective: string; steps: string[]; expected: string[]; autonomous: boolean;
  destructive: boolean; source: "deterministic" | "ai"; bucket?: TestBucket;
  requires_auth?: boolean; requires_test_data?: boolean; dependency?: string | null;
  evidence_required?: string[];
};
type Analysis = {
  job_id: string; filename: string; status: string; app_name?: string; package_name?: string;
  version_name?: string; version_code?: string; min_sdk?: string; target_sdk?: string;
  main_activity?: string; activities: string[]; services: string[]; receivers: string[];
  permissions: string[]; file_count: number; size_bytes: number; sha256: string;
  debuggable?: boolean; inferred_domain: string; app_summary: string; critical_journeys: string[];
  clarification_questions: string[]; tests: TestCase[]; release_risks: string[];
  warnings: string[]; capabilities: Record<string, boolean>;
};
type ProviderStatus = { browserstack_configured: boolean; custom_appium_available: boolean; custom_appium_reason?: string | null; custom_appium_url?: string | null; recommended_provider: "browserstack" | "appium" };
type AnalysisJob = {
  job_id: string; filename: string; status: "uploaded" | "analyzing" | "analyzed" | "failed";
  stage: string; progress: number; context?: string; artifact_available?: boolean; error?: string; analysis?: Analysis | null;
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
  status: "passed" | "failed" | "blocked"; provider: "browserstack" | "appium";
  duration_seconds: number; current_package?: string; current_activity?: string;
  screenshot_asset_id?: string; page_source_asset_id?: string; error?: string; evidence: Record<string, unknown>;
};
type ExecutionRequest = {
  provider: "browserstack" | "appium"; appium_url?: string | null; device_name: string;
  platform_version?: string | null; appium_app?: string | null; no_reset: boolean; auto_grant_permissions: boolean;
};
type ExecutionRecord = Execution & { execution_id: string; job_id: string; created_at: string; request: ExecutionRequest };
type Locator = { strategy: "accessibility_id" | "id" | "xpath"; value: string; confidence: number };
type DiscoveredControl = {
  control_id: string; semantic_label: string; class_name: string; text: string;
  content_description: string; resource_id: string; bounds: string; clickable: boolean;
  enabled: boolean; input_capable: boolean; risk: "safe" | "review" | "blocked";
  risk_reason?: string | null; locators: Locator[];
};
type DiscoveredScreen = {
  screen_id: string; fingerprint: string; package_name?: string; activity_name?: string;
  screenshot_path?: string; page_source_path?: string; screenshot_asset_id?: string | null;
  page_source_asset_id?: string | null; controls: DiscoveredControl[];
};
type Discovery = {
  job_id: string; status: "completed" | "partial" | "blocked" | "failed";
  provider: "browserstack" | "appium"; duration_seconds: number; device_name: string;
  observe_only: boolean; screen_count: number; control_count: number; safe_control_count: number;
  blocked_control_count: number; actions_attempted: number; stop_reason: string;
  screens: DiscoveredScreen[]; warnings: string[]; error?: string | null;
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
  provider: "browserstack" | "appium"; duration_seconds: number; selected_count: number;
  executed_count: number; deferred_count?: number; passed_count: number; failed_count: number; skipped_count: number;
  promoted_count: number; bucket_counts?: Record<string, number>; error?: string | null; tests: SuiteTestResult[];
};

type ProfileOption = {
  id: string; name: string; description: string; brief_context: string;
};
type ContextResponse = { context: string; source: "default" | "ai" | "fallback"; profile_id?: string; warning?: string | null };
type SetupProfile = {
  job_id: string; credential_reference: string; account_role: string; environment_name: string;
  environment_url: string; test_data_reference: string; reset_hook_reference: string;
  acceptance_criteria_reference: string; api_oracle_reference: string; navigation_notes: string;
  safe_authentication_approved: boolean; approved_test_ids: string[]; updated_at?: string | null;
  provided_fields: string[]; missing_fields: string[];
};

function emptySetup(jobId = ""): SetupProfile {
  return {
    job_id: jobId, credential_reference: "", account_role: "", environment_name: "",
    environment_url: "", test_data_reference: "", reset_hook_reference: "",
    acceptance_criteria_reference: "", api_oracle_reference: "", navigation_notes: "",
    safe_authentication_approved: false, approved_test_ids: [], provided_fields: [], missing_fields: [],
  };
}

const DEFAULT_PROFILE_ID = "uae_fintech";
const DEFAULT_PROFILE_OPTIONS: ProfileOption[] = [
  {
    id: "uae_fintech", name: "UAE Digital Banking & Wealth",
    description: "UAE fintech QA, investment journeys and CBUAE/SCA evidence.",
    brief_context: "Act as a Fintech QA Lead and Compliance Auditor for Investnation by Finance House. Scope UAE PASS, digital KYC, risk profiling, Saver/Flex/Growth portfolios and the Investnation Credit Card. Apply CBUAE/SCA, security and data-residency checks on Android. Use non-production data; keep payments, transfers, OTP and destructive actions approval-gated. Produce an evidence-led executive Test and Audit Report. Do not invent metrics, defects or compliance evidence.",
  },
  {
    id: "payments_cards", name: "Payments & Cards",
    description: "Wallets, cards, checkout, transaction integrity and fraud controls.",
    brief_context: "Act as a Payments QA Lead. Validate the Android app's wallet, card, checkout, authentication, ledger, refunds, limits and fraud controls. Keep money movement, OTP and irreversible actions approval-gated; use non-production data. Capture device, API, audit-log and transaction evidence. Do not invent metrics, defects or security/compliance evidence.",
  },
  {
    id: "healthcare_regulated", name: "Healthcare & Regulated Data",
    description: "Patient journeys, privacy, consent, access control and regulated data handling.",
    brief_context: "Act as a Healthcare QA and Privacy Auditor for the Android app. Validate identity, consent, patient/provider journeys, sensitive-data handling, access control, audit trails and retention/deletion safeguards. Use synthetic data; keep clinical, payment and destructive actions approval-gated. Produce an evidence-led release report and do not invent metrics, defects or regulatory evidence.",
  },
  {
    id: "ecommerce_marketplace", name: "E-commerce & Marketplace",
    description: "Catalog, search, cart, checkout, orders, delivery and refunds.",
    brief_context: "Act as an E-commerce QA Lead for the Android app. Validate catalog/search, account, cart, checkout, payment hand-off, order state, delivery, returns and refunds. Use non-production products and payment data; keep purchases, refunds and destructive actions approval-gated. Report only observed evidence and mark missing metrics, defects and compliance controls as pending validation.",
  },
  {
    id: "general_mobile", name: "General Mobile Application",
    description: "A neutral profile for apps without a specialised industry scope.",
    brief_context: "Act as a Senior Mobile QA Lead for the Android application. Discover critical user journeys, permissions, navigation, resilience, accessibility and security guardrails. Use non-production data; keep authentication, payments and destructive actions approval-gated. Create an evidence-led executive release report and do not invent metrics, defects or compliance evidence.",
  },
  {
    id: "custom", name: "Custom profile",
    description: "Start with a short neutral brief and tailor it in the context editor.",
    brief_context: "Act as a Senior QA Lead for the Android application. Focus on critical journeys, risk controls, security, performance and release evidence. Use non-production data and keep irreversible actions approval-gated. Add product-specific details below; do not invent metrics, defects or compliance evidence.",
  },
];
function contextForProfile(profile: ProfileOption) {
  const application = profile.id === DEFAULT_PROFILE_ID ? "Investnation by Finance House" : "[TO CONFIRM]";
  return `Profile category: ${profile.name}\nApplication: ${application}\n${profile.brief_context}`;
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
  if (error instanceof Error && error.message) return error.message;
  if (typeof candidate?.message === "string") return candidate.message;
  return fallback;
}

function ReportChecksTable({ checks }: { checks: ReportCheck[] }) {
  return <TableContainer sx={{ mt: 1.5, maxHeight: 360 }}><Table stickyHeader size="small"><TableHead><TableRow><TableCell>Control area</TableCell><TableCell>Status</TableCell><TableCell>Evidence-led assessment</TableCell><TableCell>Next action</TableCell></TableRow></TableHead><TableBody>{checks.map((check) => { const pending = check.status === "pending"; return <TableRow key={check.key} hover><TableCell sx={{ minWidth: 210 }}><Typography variant="body2" fontWeight={700}>{check.title}</Typography></TableCell><TableCell><Chip size="small" label={reportStatusLabel(check.status)} color={reportStatusColor[check.status]} variant="outlined" /></TableCell><TableCell sx={{ minWidth: 300 }}><Typography variant="body2">{pending ? (check.dependency || "Execution is yet to be completed.") : check.summary}</Typography>{!pending && check.evidence.map((item) => <Typography key={item} variant="caption" color="text.secondary" display="block">• {item}</Typography>)}</TableCell><TableCell sx={{ minWidth: 280 }}><Typography variant="caption" color="text.secondary">{pending ? "Pending" : check.recommendation || "—"}</Typography></TableCell></TableRow>; })}</TableBody></Table></TableContainer>;
}

function ReportRiskTable({ risks }: { risks: ReportRisk[] }) {
  if (risks.length === 0) return <Alert severity="success" sx={{ mt: 1.5 }}>No open risks were derived from the available evidence.</Alert>;
  return <TableContainer sx={{ mt: 1.5, maxHeight: 360 }}><Table stickyHeader size="small"><TableHead><TableRow><TableCell>Risk</TableCell><TableCell>Severity</TableCell><TableCell>Likelihood / impact</TableCell><TableCell>Evidence and mitigation</TableCell></TableRow></TableHead><TableBody>{risks.map((risk) => <TableRow key={risk.risk_id} hover><TableCell sx={{ minWidth: 220 }}><Typography variant="body2" fontWeight={700}>{risk.title}</Typography><Typography variant="caption" color="text.secondary">{risk.risk_id} · {reportStatusLabel(risk.status)}</Typography></TableCell><TableCell><Chip size="small" label={risk.severity.toUpperCase()} color={reportRiskColor[risk.severity]} variant="outlined" /></TableCell><TableCell>{risk.likelihood.toUpperCase()} / {risk.impact.toUpperCase()}</TableCell><TableCell sx={{ minWidth: 340 }}><Typography variant="caption" display="block">{risk.evidence}</Typography><Typography variant="caption" color="text.secondary" display="block" sx={{ mt: .5 }}>Mitigation: {risk.mitigation}</Typography></TableCell></TableRow>)}</TableBody></Table></TableContainer>;
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
    <Typography variant="subtitle2" fontWeight={800} sx={{ mt: 1 }}>{screen.screen_id}</Typography>
    <Typography variant="caption" color="text.secondary" display="block">{screen.package_name || "Package pending"}{screen.activity_name ? " · " + screen.activity_name : ""}</Typography>
    <Stack direction="row" spacing={.75} sx={{ mt: 1 }}><Chip size="small" label={screen.controls.length + " controls"} variant="outlined" />{screen.page_source_asset_id && <Chip size="small" label="UI hierarchy saved" color="success" variant="outlined" />}</Stack>
  </CardContent></Card>;
}

export default function AutopilotPage() {
  const navigate = useNavigate();
  const { selectedProjectId } = useSelectedProject();
  const [file, setFile] = useState<File | null>(null);
  const [storedApks, setStoredApks] = useState<UploadedAsset[]>([]);
  const [selectedUploadId, setSelectedUploadId] = useState("");
  const [repositoryLoading, setRepositoryLoading] = useState(false);
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
  const [setupOpen, setSetupOpen] = useState(false);
  const [setupBusy, setSetupBusy] = useState(false);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);
  const [provider, setProvider] = useState<"browserstack" | "appium">("browserstack");
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

  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.id === profileId) ?? DEFAULT_PROFILE_OPTIONS[0],
    [profileId, profiles],
  );

  const refreshProfiles = useCallback(async () => {
    try {
      const response = await apiClient.get<ProfileOption[]>("/autopilot/profiles", { timeout: 15000 });
      if (response.data.length > 0) setProfiles(response.data);
    } catch {
      // The local catalog is intentionally kept as a safe fallback for older
      // deployments while the backend rolls forward.
    }
  }, []);

  const refreshStoredApks = useCallback(async (projectId: string) => {
    if (!projectId) { setStoredApks([]); return; }
    setRepositoryLoading(true);
    try { setStoredApks((await uploadsApi.list({ category: "apk", project_id: projectId })).data); }
    catch { setStoredApks([]); }
    finally { setRepositoryLoading(false); }
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
  useEffect(() => { void refreshStoredApks(selectedProjectId); }, [refreshStoredApks, selectedProjectId]);

  const applyJob = useCallback((job: AnalysisJob) => {
    setAnalysisProgress(job.progress); setAnalysisStage(job.stage);
    if (job.context !== undefined && job.context.trim()) {
      setContext(job.context);
      setProfileId(profileIdFromContext(job.context, profiles));
      setContextSource("custom");
    }
    setArtifactAvailable(job.artifact_available !== false);
    if (job.status === "analyzed" && job.analysis) {
      setAnalysis(job.analysis);
      void refreshExecutionHistory(job.analysis.job_id);
      void refreshReport(job.analysis.job_id);
    }
    if (job.status === "failed" && job.error) setError(job.error);
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
        if (job.status === "failed") throw new Error(job.error || "Autopilot analysis failed");
        if (job.status === "analyzed" && job.analysis) return job.analysis;
      } catch (err) {
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
      try {
        const job = (await apiClient.get<AnalysisJob | null>("/autopilot/jobs/latest", { timeout: 15000 })).data;
        if (!active || !job) return;
        applyJob(job);
        if (job.status === "uploaded" || job.status === "analyzing") {
          setBusy(true);
          await pollAnalysis(job.job_id);
          if (active) setBusy(false);
        }
      } catch (err) {
        if (active) {
          setBusy(false);
          setError(readableError(err, "Unable to restore the latest Autopilot analysis"));
        }
      }
    };
    void restore();
    return () => { active = false; };
  }, [selectedProjectId, applyJob, pollAnalysis]);

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
      setSetup(setupResult.status === "fulfilled" ? setupResult.value.data : emptySetup(analysis.job_id));
      setReport(reportResult.status === "fulfilled" ? reportResult.value.data : null);
    });
    return () => { active = false; };
  }, [analysis?.job_id]);

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
  const discoveredRows = useMemo(() => discovery?.screens.flatMap((screen) => screen.controls.map((control) => ({ screen: screen.screen_id, control }))) ?? [], [discovery]);

  const resetResult = () => { setAnalysis(null); setReport(null); setExecution(null); setExecutionHistory([]); setDiscovery(null); setAutomation(null); setSuite(null); setSetup(null); setSetupOpen(false); setArtifactAvailable(true); setError(""); };
  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected); if (selected) setSelectedUploadId(""); resetResult();
  };
  const selectProfile = (nextProfileId: string) => {
    const nextProfile = profiles.find((profile) => profile.id === nextProfileId) ?? DEFAULT_PROFILE_OPTIONS[0];
    // A report is evidence for the context used by its job. Clear an older
    // result when the governing profile changes so it cannot be mistaken for
    // an assessment of the newly selected scope.
    resetResult();
    setProfileId(nextProfile.id);
    setContext(contextForProfile(nextProfile));
    setContextSource("default");
    setContextNotice(`${nextProfile.name} brief applied. You can edit it before starting the run.`);
    setError("");
  };
  const generateContext = async (mode: "default" | "generate" | "improve") => {
    if (mode === "default") {
      resetResult();
      setContext(contextForProfile(selectedProfile));
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
        application_name: analysis?.app_name || selectedStoredApk?.filename?.replace(/\.apk$/i, "") || null,
        package_name: analysis?.package_name || null,
        platform: "Android",
        focus: "UAE fintech release readiness, functional QA and CBUAE/SCA audit evidence",
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
  const analyze = async () => {
    if ((!file && !selectedUploadId) || !selectedProjectId) { setError("Select a project and APK before starting Autopilot."); return; }
    setBusy(true); setError(""); setContextNotice(""); setExecution(null); setExecutionHistory([]); setDiscovery(null); setAutomation(null); setSuite(null); setReport(null);
    try {
      let response;
      if (selectedUploadId) {
        response = await apiClient.post<AnalysisJob>("/autopilot/analyze-existing", { upload_id: selectedUploadId, context, profile_id: profileId }, { timeout: 300000 });
      } else {
        const form = new FormData(); form.append("file", file as File); form.append("context", context); form.append("profile_id", profileId);
        response = await apiClient.post<AnalysisJob>("/autopilot/analyze", form, { headers: { "Content-Type": "multipart/form-data" }, timeout: 300000 });
        await refreshStoredApks(selectedProjectId);
      }
      applyJob(response.data); await pollAnalysis(response.data.job_id); await refreshAutomation(response.data.job_id); await refreshReport(response.data.job_id);
    } catch (err) { setError(readableError(err, "Autopilot analysis failed")); }
    finally { setBusy(false); }
  };

  const executionPayload = () => ({
    provider,
    appium_url: provider === "appium" ? appiumUrl : null,
    device_name: deviceName,
    platform_version: platformVersion || null,
    appium_app: provider === "appium" ? (appiumApp || null) : null,
    no_reset: false,
    auto_grant_permissions: autoGrantPermissions,
  });
  const openSetup = () => {
    if (!analysis) return;
    setSetupDraft(setup ? { ...setup, approved_test_ids: [...setup.approved_test_ids], provided_fields: [...setup.provided_fields], missing_fields: [...setup.missing_fields] } : emptySetup(analysis.job_id));
    setSetupOpen(true);
  };
  const saveSetup = async () => {
    if (!analysis) return;
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
      };
      const response = await apiClient.put<SetupProfile>("/autopilot/" + analysis.job_id + "/setup", payload, { timeout: 20000 });
      setSetup(response.data);
      setSetupOpen(false);
      await refreshAutomation(analysis.job_id);
    } catch (err) { setError(readableError(err, "Test setup could not be saved")); }
    finally { setSetupBusy(false); }
  };
  const updateSetup = (field: keyof SetupProfile, value: string | boolean) => setSetupDraft((current) => ({ ...current, [field]: value }));

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

  const rerunAnalysis = async () => {
    if (!analysis || !selectedProjectId) return;
    setBusy(true); setError(""); setExecution(null); setExecutionHistory([]); setReport(null);
    try {
      const response = await apiClient.post<AnalysisJob>(
        `/autopilot/${analysis.job_id}/rerun-analysis`,
        { upload_id: selectedUploadId || undefined, context: context || undefined, profile_id: profileId },
        { timeout: 300000 },
      );
      // Keep the last completed analysis visible while the replacement job
      // is being persisted/polled. The new result replaces it atomically.
      setDiscovery(null); setAutomation(null); setSuite(null);
      applyJob(response.data);
      await pollAnalysis(response.data.job_id);
      await refreshAutomation(response.data.job_id); await refreshReport(response.data.job_id);
    } catch (err) { setError(readableError(err, "Autopilot rerun failed")); }
    finally { setBusy(false); }
  };

  const browserStackUnavailable = provider === "browserstack" && providerStatus !== null && !providerStatus.browserstack_configured;
  const customAppiumUnavailable = provider === "appium" && providerStatus !== null && !providerStatus.custom_appium_available && isLoopbackAppiumUrl(appiumUrl);
  const providerStatusPending = providerStatus === null;
  const noExecutionProvider = providerStatus !== null && !providerStatus.browserstack_configured && !providerStatus.custom_appium_available && isLoopbackAppiumUrl(appiumUrl);
  const executionUnavailable = providerStatusPending || browserStackUnavailable || customAppiumUnavailable || !artifactAvailable;
  const reportPending = report?.recommendation === "PENDING";

  return <Stack spacing={3}>
    <Box>
      <Stack direction="row" spacing={1.5} alignItems="center"><AutoAwesomeIcon color="primary" /><Typography variant="h4" fontWeight={800}>QTXpert Autopilot</Typography><Chip size="small" label="ANDROID" color="primary" variant="outlined" /></Stack>
      <Typography color="text.secondary" sx={{ mt: 1, maxWidth: 920 }}>Upload or reuse an APK, understand the application, safely discover its runtime UI, resolve semantic automation and execute evidence-backed checks.</Typography>
    </Box>

    <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 }, borderRadius: 3 }}>
      <Box sx={{ mb: 2.5 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }} justifyContent="space-between">
          <Box>
            <Typography variant="overline" color="primary" fontWeight={800} letterSpacing={1}>1 · Choose a test profile</Typography>
            <Typography variant="body2" color="text.secondary">The profile controls the brief context, generated journeys and report controls.</Typography>
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
            <Typography variant="caption" color="text.secondary">Changing the profile replaces the brief; you can refine it below.</Typography>
          </Grid>
        </Grid>
      </Box>
      <Grid container spacing={3}>
        <Grid item xs={12} md={5}><Stack spacing={2}>
          <FormControl fullWidth size="small"><InputLabel id="stored-apk-label">APK source</InputLabel><Select labelId="stored-apk-label" label="APK source" value={selectedUploadId} disabled={repositoryLoading || busy} onChange={(event) => { setSelectedUploadId(event.target.value); if (event.target.value) setFile(null); if (!analysis) resetResult(); else setError(""); }}>
            <MenuItem value="">Upload a new APK</MenuItem>{storedApks.map((asset) => <MenuItem key={asset.id} value={asset.id}>{asset.filename} · {formatBytes(asset.size_bytes)} · {new Date(asset.created_at).toLocaleDateString()}</MenuItem>)}
          </Select></FormControl>
          {selectedStoredApk ? <Box sx={{ border: "1px solid", borderColor: "primary.main", borderRadius: 3, p: 2.5, bgcolor: "action.hover" }}><Stack direction="row" spacing={1.2} alignItems="center"><FolderOutlinedIcon color="primary" /><Box sx={{ minWidth: 0 }}><Typography fontWeight={800} noWrap>{selectedStoredApk.filename}</Typography><Typography variant="caption" color="text.secondary">Stored APK · {formatBytes(selectedStoredApk.size_bytes)}</Typography></Box></Stack><Button size="small" sx={{ mt: 1 }} onClick={() => navigate("/test-data/uploads")}>Open repository</Button></Box>
          : <Box sx={{ border: "1px dashed", borderColor: file ? "primary.main" : "divider", borderRadius: 3, p: 3, textAlign: "center", bgcolor: "action.hover" }}><CloudUploadOutlinedIcon sx={{ fontSize: 40, color: "primary.main" }} /><Typography fontWeight={700}>{file?.name || "Choose an Android APK"}</Typography>{file && <Typography variant="caption" color="text.secondary">{formatBytes(file.size)}</Typography>}<Box sx={{ mt: 1.5 }}><Button component="label" variant="outlined" disabled={busy}>Choose APK<input hidden type="file" accept=".apk,application/vnd.android.package-archive" onChange={onFile} /></Button></Box></Box>}
        </Stack></Grid>
        <Grid item xs={12} md={7}>
          <TextField fullWidth multiline minRows={5} maxRows={9} inputProps={{ maxLength: 2400 }} label="Brief context" placeholder="Select a profile above, or add a short product-specific context." value={context} onChange={(event) => { setContext(event.target.value); setContextSource("custom"); setContextNotice(""); }} helperText="This brief is sent to the analysis prompt and report. Never paste production passwords, tokens or OTPs." />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ mt: 1 }}>
            <Button size="small" variant="outlined" onClick={() => void generateContext("default")} disabled={contextBusy}>Reset to profile brief</Button>
            <Button size="small" variant="outlined" onClick={() => void generateContext(context.trim() ? "improve" : "generate")} disabled={contextBusy} startIcon={contextBusy ? <CircularProgress size={14} /> : <AutoAwesomeIcon />}>{contextBusy ? "Writing context…" : context.trim() ? "Improve with AI" : "Generate with AI"}</Button>
            <Chip size="small" label={`Context: ${contextSource}`} color={contextSource === "ai" ? "primary" : "default"} variant="outlined" />
          </Stack>
          {contextNotice && <Alert severity="info" sx={{ mt: 1.5 }}>{contextNotice}</Alert>}
          <Alert severity="info" sx={{ mt: 1.5 }}>Autopilot reasons over the APK and this context. The report labels user-supplied statements separately from observed execution evidence; missing metrics remain pending validation.</Alert>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }} sx={{ mt: 2 }}>
            <Button disabled={(!file && !selectedUploadId) || busy || !selectedProjectId} onClick={analyze} variant="contained" size="large" startIcon={busy ? <CircularProgress size={18} color="inherit" /> : <AutoAwesomeIcon />}>{busy ? "Learning application…" : selectedStoredApk ? "Analyze stored APK" : "Start Autopilot analysis"}</Button>
            {analysis && <Button disabled={busy || !selectedProjectId} onClick={rerunAnalysis} variant="outlined" size="large">Rerun this analysis</Button>}
          </Stack>
        </Grid>
      </Grid>
      {busy && <Box sx={{ mt: 2 }}><Box sx={{ height: 4, borderRadius: 2, overflow: "hidden", bgcolor: "action.hover" }}><Box sx={{ height: "100%", width: `${Math.max(3, analysisProgress)}%`, bgcolor: "primary.main", transition: "width .4s ease" }} /></Box><Typography variant="caption" color="text.secondary">{analysisStage.replaceAll("_", " ")} · {analysisProgress}%</Typography></Box>}
    </Paper>

    {!analysis && <Card variant="outlined" sx={{ borderRadius: 3 }}><CardContent>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} justifyContent="space-between">
        <Box><Typography variant="h6" fontWeight={800}>What Autopilot will deliver</Typography><Typography variant="body2" color="text.secondary">These areas stay pending until a conclusive run supplies evidence.</Typography></Box>
        <Chip size="small" label="PENDING — run not started" color="info" variant="outlined" />
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

    {error && <Alert severity="error">{error}</Alert>}

    {analysis && stats && <>
      {report && <Card variant="outlined" sx={{ borderRadius: 3, borderColor: report.recommendation === "NO_GO" ? "error.main" : reportPending ? "info.main" : "warning.main" }}><CardContent>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2} alignItems={{ md: "center" }}>
          <Stack direction="row" spacing={1} alignItems="center"><FactCheckOutlinedIcon color="primary" /><Box><Typography variant="h6" fontWeight={800}>{report.report_title}</Typography><Typography variant="caption" color="text.secondary">{report.role} · {report.prepared_for}</Typography><Typography variant="caption" color="text.secondary" display="block">Last run: {report.last_run_at ? new Date(report.last_run_at).toLocaleString() : "Pending — execution is yet to be completed."}</Typography></Box></Stack>
          <Chip label={`RELEASE: ${report.recommendation.replaceAll("_", "-")}`} color={report.recommendation === "NO_GO" ? "error" : reportPending ? "info" : "warning"} sx={{ fontWeight: 800 }} />
        </Stack>
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
        <Grid item xs={12} lg={8}><Card variant="outlined" sx={{ height: "100%" }}><CardContent><Stack direction="row" spacing={1} alignItems="center"><AccountTreeOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Application intelligence</Typography></Stack><Typography sx={{ mt: 1.5 }}>{analysis.app_summary}</Typography><Divider sx={{ my: 2 }} /><Grid container spacing={2}><Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Application</Typography><Typography fontWeight={700}>{analysis.app_name || "Unknown"}</Typography></Grid><Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Domain</Typography><Typography fontWeight={700}>{analysis.inferred_domain}</Typography></Grid><Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Version</Typography><Typography fontWeight={700}>{analysis.version_name || "—"}</Typography></Grid><Grid item xs={12} md={6}><Typography variant="caption" color="text.secondary">Package</Typography><Typography sx={{ wordBreak: "break-all" }}>{analysis.package_name || "—"}</Typography></Grid><Grid item xs={12} md={6}><Typography variant="caption" color="text.secondary">Main activity</Typography><Typography sx={{ wordBreak: "break-all" }}>{analysis.main_activity || "—"}</Typography></Grid></Grid></CardContent></Card></Grid>
        <Grid item xs={12} lg={4}><Card variant="outlined" sx={{ height: "100%" }}><CardContent><Stack direction="row" spacing={1} alignItems="center"><SecurityOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Guardrails</Typography></Stack><Stack spacing={1} sx={{ mt: 1.5 }}><Chip label="Safe discovery: enabled" color="success" variant="outlined" /><Chip label="Transactions / destructive actions: blocked" color="warning" variant="outlined" /><Chip label={`Debuggable: ${analysis.debuggable === true ? "YES" : analysis.debuggable === false ? "No" : "Unknown"}`} variant="outlined" /></Stack></CardContent></Card></Grid>
      </Grid>

      <Card variant="outlined"><CardContent>
        <Stack direction="row" spacing={1} alignItems="center">
          <BugReportOutlinedIcon color="primary" />
          <Box>
            <Typography variant="h6" fontWeight={800}>Complete test coverage plan</Typography>
            <Typography variant="body2" color="text.secondary">
              Autopilot always designs the full app plan. Functional, UAT, page-level, UI, installation, integration,
              performance, security, compatibility and regression cases remain pending until their required evidence exists.
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
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2} alignItems={{ md: "center" }}><Box><Stack direction="row" spacing={1} alignItems="center"><TravelExploreOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Runtime discovery</Typography></Stack><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>Map screens and semantic controls from the running Android app. Payments, transfers, delete, submit, confirm and OTP actions remain blocked.</Typography></Box><Stack direction="row" spacing={1}><FormControl size="small" sx={{ minWidth: 145 }}><InputLabel id="discovery-mode-label">Mode</InputLabel><Select labelId="discovery-mode-label" label="Mode" value={discoveryMode} onChange={(event) => setDiscoveryMode(event.target.value as "safe" | "observe")}><MenuItem value="safe">Safe navigation</MenuItem><MenuItem value="observe">Observe only</MenuItem></Select></FormControl><Button variant="contained" startIcon={discoveryBusy ? <CircularProgress size={16} color="inherit" /> : <TravelExploreOutlinedIcon />} disabled={discoveryBusy || executionUnavailable} onClick={runDiscovery}>{discoveryBusy ? "Discovering…" : "Run discovery"}</Button></Stack></Stack>
        {browserStackUnavailable && provider === "browserstack" && <Alert severity="warning" sx={{ mt: 2 }}>BrowserStack credentials are not configured. Choose a reachable custom Appium endpoint or configure BrowserStack.</Alert>}
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
            <Box><Typography variant="subtitle2" fontWeight={800}>Resolve test dependencies</Typography><Typography variant="caption" color="text.secondary">Add non-secret credential, role, data, reset and acceptance references. Passwords, tokens and OTPs are never stored here.</Typography></Box>
            <Button size="small" variant="outlined" onClick={openSetup}>{setup?.provided_fields.length ? "Update inputs" : "Provide inputs"}</Button>
          </Stack>
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
            <Chip size="small" label={(setup?.provided_fields.length || 0) + " setup items provided"} color={setup?.provided_fields.length ? "success" : "default"} variant="outlined" />
            {(automation?.setup_missing_fields || []).slice(0, 6).map((field) => <Chip key={field} size="small" label={"Pending: " + field} color="warning" variant="outlined" />)}
          </Stack>
        </Box>
        {automation && <><Grid container spacing={1.5} sx={{ mt: 1 }}>{[["Executable", automation.executable_count], ["Promoted by discovery", automation.promoted_count], ["Needs discovery/data", automation.discovery_required_count], ["Approval required", automation.approval_required_count]].map(([label, value]) => <Grid item xs={6} md={3} key={String(label)}><Box sx={{ p: 1.25, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h6" fontWeight={800}>{value}</Typography></Box></Grid>)}</Grid><Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>IR {automation.schema_version} · runtime discovery {automation.discovery_used ? "consumed" : "not yet available"} · full plan buckets are listed above</Typography><TableContainer sx={{ mt: 1.5, maxHeight: 360 }}><Table stickyHeader size="small"><TableHead><TableRow><TableCell>Test</TableCell><TableCell>Bucket</TableCell><TableCell>Readiness</TableCell><TableCell>Dependency / reason</TableCell></TableRow></TableHead><TableBody>{automation.tests.slice(0, 80).map((test) => { const bucket = normalizedBucket(test); return <TableRow key={test.test_id} hover><TableCell><Typography variant="body2" fontWeight={700}>{test.title}</Typography><Typography variant="caption" color="text.secondary">{test.test_id}</Typography></TableCell><TableCell><Chip size="small" label={testBucketLabel[bucket]} variant="outlined" /></TableCell><TableCell><Chip size="small" label={test.readiness.replaceAll("_", " ")} color={readinessColor[test.readiness]} variant="outlined" /></TableCell><TableCell sx={{ maxWidth: 430 }}><Typography variant="caption" color="text.secondary">{test.readiness_reason || test.dependency || "—"}</Typography>{test.readiness !== "executable" && <Button size="small" sx={{ ml: 1 }} onClick={openSetup}>Resolve</Button>}</TableCell></TableRow>; })}</TableBody></Table></TableContainer></>}
        {suite && <><Alert sx={{ mt: 2 }} severity={suite.status === "passed" ? "success" : suite.status === "blocked" ? "warning" : suite.status === "partial" ? "info" : "error"}>Safe subset: <b>{suite.status.toUpperCase()}</b> · {suite.passed_count} passed · {suite.failed_count} failed · {suite.skipped_count} deferred/blocked · {suite.duration_seconds}s{suite.deferred_count ? ` · ${suite.deferred_count} plan case(s) still pending` : ""}{suite.promoted_count ? ` · ${suite.promoted_count} discovery-promoted` : ""}{suite.error ? ` · ${suite.error}` : ""}</Alert>{suite.tests.length > 0 && <TableContainer sx={{ mt: 1.5, maxHeight: 360 }}><Table stickyHeader size="small"><TableHead><TableRow><TableCell>Test</TableCell><TableCell>Bucket</TableCell><TableCell>Status</TableCell><TableCell>Dependency / result</TableCell></TableRow></TableHead><TableBody>{suite.tests.map((test) => <TableRow key={test.test_id}><TableCell><Typography variant="body2" fontWeight={700}>{test.title}</Typography><Typography variant="caption" color="text.secondary">{test.test_id}</Typography></TableCell><TableCell>{test.bucket ? testBucketLabel[test.bucket] : "—"}</TableCell><TableCell><Chip size="small" label={test.status.toUpperCase()} color={test.status === "passed" ? "success" : test.status === "failed" ? "error" : "warning"} variant="outlined" /></TableCell><TableCell><Typography variant="caption" color={test.error ? "error" : "text.secondary"}>{test.error || test.dependency || "Evidence captured"}</Typography></TableCell></TableRow>)}</TableBody></Table></TableContainer>}</>}
      </CardContent></Card>

      <Card variant="outlined"><CardContent><Stack direction="row" spacing={1} alignItems="center"><PlayArrowRoundedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Execution target & safe smoke</Typography></Stack><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>This target is shared by Runtime Discovery, the autonomous safe suite and smoke execution.</Typography>
      {providerStatusPending && <Alert severity="info" sx={{ mt: 2 }}>Checking execution providers…</Alert>}
      {noExecutionProvider && <Alert severity="warning" sx={{ mt: 2 }}>No hosted execution provider is configured. Configure BrowserStack credentials or enter a reachable HTTPS Appium endpoint before running.</Alert>}
      {browserStackUnavailable && <Alert severity="warning" sx={{ mt: 2 }}>BrowserStack credentials are not configured. Choose Custom / local Appium and enter a reachable endpoint.</Alert>}
      {provider === "appium" && providerStatus?.custom_appium_reason && <Alert severity="warning" sx={{ mt: 2 }}>{providerStatus.custom_appium_reason}</Alert>}
      <Grid container spacing={2} sx={{ mt: .5 }}><Grid item xs={12} md={3}><FormControl fullWidth size="small"><InputLabel id="autopilot-provider-label">Execution target</InputLabel><Select labelId="autopilot-provider-label" label="Execution target" value={provider} onChange={(event) => setProvider(event.target.value as "browserstack" | "appium")}><MenuItem value="browserstack" disabled={providerStatus !== null && !providerStatus.browserstack_configured}>BrowserStack real device</MenuItem><MenuItem value="appium">Custom / local Appium</MenuItem></Select></FormControl></Grid><Grid item xs={12} md={3}><TextField fullWidth size="small" label="Device name" value={deviceName} onChange={(event) => setDeviceName(event.target.value)} /></Grid><Grid item xs={12} md={2}><TextField fullWidth size="small" label="Android version" value={platformVersion} onChange={(event) => setPlatformVersion(event.target.value)} /></Grid><Grid item xs={12} md={4}><Button fullWidth sx={{ height: 40 }} variant="outlined" disabled={smokeBusy || executionUnavailable} onClick={runSmoke} startIcon={smokeBusy ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRoundedIcon />}>{smokeBusy ? "Running…" : "Run safe smoke only"}</Button></Grid>{provider === "appium" && <><Grid item xs={12} md={6}><TextField fullWidth size="small" label="Appium server URL" value={appiumUrl} onChange={(event) => setAppiumUrl(event.target.value)} helperText="Hosted runs require a reachable HTTPS endpoint; leave blank only when the backend has one configured." /></Grid><Grid item xs={12} md={6}><TextField fullWidth size="small" label="Optional remote app reference" value={appiumApp} onChange={(event) => setAppiumApp(event.target.value)} /></Grid></>}<Grid item xs={12}><FormControlLabel control={<Switch checked={autoGrantPermissions} onChange={(event) => setAutoGrantPermissions(event.target.checked)} />} label="Auto-grant runtime permissions for this smoke" /><Typography variant="caption" color="text.secondary" display="block">Enabled by default so unattended smoke runs do not stall on Android permission dialogs. Permission grant/deny behavior remains covered by generated permission tests.</Typography></Grid></Grid>{execution && <Alert sx={{ mt: 2 }} severity={execution.status === "passed" ? "success" : execution.status === "blocked" ? "warning" : "error"}>Smoke: <b>{execution.status.toUpperCase()}</b> · {execution.provider} · {execution.duration_seconds}s{execution.current_package ? ` · ${execution.current_package}` : ""}{execution.error ? ` · ${execution.error}` : ""}</Alert>}{execution && (execution.screenshot_asset_id || execution.page_source_asset_id) && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>Evidence is retained with this run and is available in Test Reports.</Typography>}{executionHistory.length > 0 && <Box sx={{ mt: 2 }}><Typography variant="subtitle2" fontWeight={800}>Previous smoke runs</Typography><Stack spacing={1} sx={{ mt: 1 }}>{executionHistory.map((item) => <Paper key={item.execution_id} variant="outlined" sx={{ p: 1.25 }}><Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} justifyContent="space-between"><Box><Typography variant="body2" fontWeight={700}>{item.status.toUpperCase()} · {item.request.provider} · {item.request.device_name}</Typography><Typography variant="caption" color="text.secondary">{new Date(item.created_at).toLocaleString()} · {item.duration_seconds}s</Typography></Box><Button size="small" variant="outlined" disabled={smokeBusy} onClick={() => rerunSmoke(item.execution_id)}>Rerun</Button></Stack></Paper>)}</Stack></Box>}</CardContent></Card>

      {analysis.release_risks.length > 0 && <Alert severity="info"><b>Initial release risks:</b> {analysis.release_risks.join(" • ")}</Alert>}
    </>}

    <Dialog open={setupOpen} onClose={() => !setupBusy && setSetupOpen(false)} fullWidth maxWidth="md">
      <DialogTitle>Resolve Autopilot test dependencies</DialogTitle>
      <DialogContent>
        <Alert severity="info" sx={{ mb: 2 }}>Enter references to approved non-production resources. Do not paste passwords, access tokens or OTPs; keep secrets in the configured vault/provider.</Alert>
        <Grid container spacing={2}>
          <Grid item xs={12} md={6}><TextField fullWidth label="Credential set reference" value={setupDraft.credential_reference} onChange={(event) => updateSetup("credential_reference", event.target.value)} helperText="Example: qtxpert://credentials/investnation-uat" /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Test account role" value={setupDraft.account_role} onChange={(event) => updateSetup("account_role", event.target.value)} placeholder="Retail investor / relationship manager" /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Environment name" value={setupDraft.environment_name} onChange={(event) => updateSetup("environment_name", event.target.value)} placeholder="UAT" /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Environment URL / identifier" value={setupDraft.environment_url} onChange={(event) => updateSetup("environment_url", event.target.value)} /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Synthetic test-data reference" value={setupDraft.test_data_reference} onChange={(event) => updateSetup("test_data_reference", event.target.value)} /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Reset / cleanup reference" value={setupDraft.reset_hook_reference} onChange={(event) => updateSetup("reset_hook_reference", event.target.value)} /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="Acceptance-criteria reference" value={setupDraft.acceptance_criteria_reference} onChange={(event) => updateSetup("acceptance_criteria_reference", event.target.value)} /></Grid>
          <Grid item xs={12} md={6}><TextField fullWidth label="API / oracle reference" value={setupDraft.api_oracle_reference} onChange={(event) => updateSetup("api_oracle_reference", event.target.value)} /></Grid>
          <Grid item xs={12}><TextField fullWidth multiline minRows={3} label="Safe navigation and data notes" value={setupDraft.navigation_notes} onChange={(event) => updateSetup("navigation_notes", event.target.value)} helperText="Describe seeded users, permitted paths and expected reset behavior. Never include secret values." /></Grid>
          <Grid item xs={12}><FormControlLabel control={<Switch checked={setupDraft.safe_authentication_approved} onChange={(event) => updateSetup("safe_authentication_approved", event.target.checked)} />} label="Approve safe non-transactional authentication in this UAT environment" /></Grid>
        </Grid>
      </DialogContent>
      <DialogActions><Button onClick={() => setSetupOpen(false)} disabled={setupBusy}>Cancel</Button><Button variant="contained" onClick={saveSetup} disabled={setupBusy}>{setupBusy ? "Saving…" : "Save and recheck readiness"}</Button></DialogActions>
    </Dialog>
  </Stack>;
}
