import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Divider,
  FormControl, Grid, InputLabel, MenuItem, Paper, Select, Stack, Table,
  TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import SecurityOutlinedIcon from "@mui/icons-material/SecurityOutlined";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import BugReportOutlinedIcon from "@mui/icons-material/BugReportOutlined";
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import TravelExploreOutlinedIcon from "@mui/icons-material/TravelExploreOutlined";
import { apiClient } from "@/services/apiClient";
import { uploadsApi } from "@/services/api";
import { UploadedAsset } from "@/types/domain";
import { useSelectedProject } from "@/hooks/useSelectedProject";

type TestCase = {
  id: string; suite: string; title: string; priority: "critical" | "high" | "medium" | "low";
  objective: string; steps: string[]; expected: string[]; autonomous: boolean;
  destructive: boolean; source: "deterministic" | "ai";
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
type ProviderStatus = { browserstack_configured: boolean; custom_appium_available: boolean; recommended_provider: "browserstack" | "appium" };
type AnalysisJob = {
  job_id: string; filename: string; status: "uploaded" | "analyzing" | "analyzed" | "failed";
  stage: string; progress: number; artifact_available?: boolean; error?: string; analysis?: Analysis | null;
};
type Execution = {
  status: "passed" | "failed" | "blocked"; provider: "browserstack" | "appium";
  duration_seconds: number; current_package?: string; current_activity?: string;
  error?: string; evidence: Record<string, unknown>;
};
type Locator = { strategy: "accessibility_id" | "id" | "xpath"; value: string; confidence: number };
type DiscoveredControl = {
  control_id: string; semantic_label: string; class_name: string; text: string;
  content_description: string; resource_id: string; bounds: string; clickable: boolean;
  enabled: boolean; input_capable: boolean; risk: "safe" | "review" | "blocked";
  risk_reason?: string | null; locators: Locator[];
};
type DiscoveredScreen = {
  screen_id: string; fingerprint: string; package_name?: string; activity_name?: string;
  screenshot_path?: string; page_source_path?: string; controls: DiscoveredControl[];
};
type Discovery = {
  job_id: string; status: "completed" | "partial" | "blocked" | "failed";
  provider: "browserstack" | "appium"; duration_seconds: number; device_name: string;
  observe_only: boolean; screen_count: number; control_count: number; safe_control_count: number;
  blocked_control_count: number; actions_attempted: number; stop_reason: string;
  screens: DiscoveredScreen[]; warnings: string[]; error?: string | null;
};

const priorityColor: Record<TestCase["priority"], "error" | "warning" | "info" | "default"> = {
  critical: "error", high: "warning", medium: "info", low: "default",
};
const riskColor: Record<DiscoveredControl["risk"], "success" | "warning" | "error"> = {
  safe: "success", review: "warning", blocked: "error",
};

function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, value / 1024).toFixed(0)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
function readableError(error: unknown, fallback: string) {
  const candidate = error as { response?: { data?: { detail?: unknown } }; message?: unknown };
  if (typeof candidate?.response?.data?.detail === "string") return candidate.response.data.detail;
  if (error instanceof Error && error.message) return error.message;
  if (typeof candidate?.message === "string") return candidate.message;
  return fallback;
}

export default function AutopilotPage() {
  const navigate = useNavigate();
  const { selectedProjectId } = useSelectedProject();
  const [file, setFile] = useState<File | null>(null);
  const [storedApks, setStoredApks] = useState<UploadedAsset[]>([]);
  const [selectedUploadId, setSelectedUploadId] = useState("");
  const [repositoryLoading, setRepositoryLoading] = useState(false);
  const [context, setContext] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [execution, setExecution] = useState<Execution | null>(null);
  const [discovery, setDiscovery] = useState<Discovery | null>(null);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);
  const [provider, setProvider] = useState<"browserstack" | "appium">("browserstack");
  const [busy, setBusy] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [analysisStage, setAnalysisStage] = useState("");
  const [artifactAvailable, setArtifactAvailable] = useState(true);
  const [smokeBusy, setSmokeBusy] = useState(false);
  const [discoveryBusy, setDiscoveryBusy] = useState(false);
  const [discoveryMode, setDiscoveryMode] = useState<"safe" | "observe">("safe");
  const [error, setError] = useState("");
  const [appiumUrl, setAppiumUrl] = useState("http://127.0.0.1:4723");
  const [deviceName, setDeviceName] = useState("Google Pixel 8");
  const [platformVersion, setPlatformVersion] = useState("14.0");
  const [appiumApp, setAppiumApp] = useState("");

  const refreshStoredApks = useCallback(async (projectId: string) => {
    if (!projectId) { setStoredApks([]); return; }
    setRepositoryLoading(true);
    try { setStoredApks((await uploadsApi.list({ category: "apk", project_id: projectId })).data); }
    catch { setStoredApks([]); }
    finally { setRepositoryLoading(false); }
  }, []);

  useEffect(() => {
    apiClient.get<ProviderStatus>("/autopilot/providers").then((response) => {
      setProviderStatus(response.data);
      setProvider(response.data.recommended_provider);
      if (response.data.recommended_provider === "appium") setDeviceName("Android Emulator");
    }).catch(() => setProviderStatus(null));
  }, []);
  useEffect(() => { void refreshStoredApks(selectedProjectId); }, [refreshStoredApks, selectedProjectId]);

  const applyJob = useCallback((job: AnalysisJob) => {
    setAnalysisProgress(job.progress); setAnalysisStage(job.stage);
    setArtifactAvailable(job.artifact_available !== false);
    if (job.status === "analyzed" && job.analysis) setAnalysis(job.analysis);
    if (job.status === "failed" && job.error) setError(job.error);
  }, []);
  const pollAnalysis = useCallback(async (jobId: string) => {
    const deadline = Date.now() + 20 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      const job = (await apiClient.get<AnalysisJob>(`/autopilot/jobs/${jobId}`, { timeout: 15000 })).data;
      applyJob(job);
      if (job.status === "failed") throw new Error(job.error || "Autopilot analysis failed");
      if (job.status === "analyzed" && job.analysis) return job.analysis;
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
      } catch { if (active) setBusy(false); }
    };
    void restore();
    return () => { active = false; };
  }, [selectedProjectId, applyJob, pollAnalysis]);

  useEffect(() => {
    let active = true;
    if (!analysis?.job_id) { setDiscovery(null); return; }
    apiClient.get<Discovery | null>(`/autopilot/${analysis.job_id}/discovery`, { timeout: 15000 })
      .then((response) => { if (active) setDiscovery(response.data); })
      .catch(() => { if (active) setDiscovery(null); });
    return () => { active = false; };
  }, [analysis?.job_id]);

  const stats = useMemo(() => analysis ? {
    tests: analysis.tests.length,
    suites: new Set(analysis.tests.map((test) => test.suite)).size,
    autonomous: analysis.tests.filter((test) => test.autonomous).length,
    critical: analysis.tests.filter((test) => ["critical", "high"].includes(test.priority)).length,
  } : null, [analysis]);
  const selectedStoredApk = useMemo(() => storedApks.find((asset) => asset.id === selectedUploadId) ?? null, [storedApks, selectedUploadId]);
  const discoveredRows = useMemo(() => discovery?.screens.flatMap((screen) => screen.controls.map((control) => ({ screen: screen.screen_id, control }))) ?? [], [discovery]);

  const resetResult = () => { setAnalysis(null); setExecution(null); setDiscovery(null); setArtifactAvailable(true); setError(""); };
  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected); if (selected) setSelectedUploadId(""); resetResult();
  };
  const analyze = async () => {
    if ((!file && !selectedUploadId) || !selectedProjectId) { setError("Select a project and APK before starting Autopilot."); return; }
    setBusy(true); setError(""); setExecution(null); setDiscovery(null);
    try {
      let response;
      if (selectedUploadId) {
        response = await apiClient.post<AnalysisJob>("/autopilot/analyze-existing", { upload_id: selectedUploadId, context }, { timeout: 300000 });
      } else {
        const form = new FormData(); form.append("file", file as File); form.append("context", context);
        response = await apiClient.post<AnalysisJob>("/autopilot/analyze", form, { headers: { "Content-Type": "multipart/form-data" }, timeout: 300000 });
        await refreshStoredApks(selectedProjectId);
      }
      applyJob(response.data); await pollAnalysis(response.data.job_id);
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
    auto_grant_permissions: false,
  });
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
    } catch (err) { setError(readableError(err, "Runtime discovery failed")); }
    finally { setDiscoveryBusy(false); }
  };
  const runSmoke = async () => {
    if (!analysis) return;
    setSmokeBusy(true); setError("");
    try { setExecution((await apiClient.post<Execution>(`/autopilot/${analysis.job_id}/smoke`, executionPayload(), { timeout: 660000 })).data); }
    catch (err) { setError(readableError(err, "Smoke execution failed")); }
    finally { setSmokeBusy(false); }
  };

  const browserStackUnavailable = provider === "browserstack" && providerStatus?.browserstack_configured === false;
  const executionUnavailable = browserStackUnavailable || !artifactAvailable;

  return <Stack spacing={3}>
    <Box>
      <Stack direction="row" spacing={1.5} alignItems="center"><AutoAwesomeIcon color="primary" /><Typography variant="h4" fontWeight={800}>QTXpert Autopilot</Typography><Chip size="small" label="ANDROID" color="primary" variant="outlined" /></Stack>
      <Typography color="text.secondary" sx={{ mt: 1, maxWidth: 920 }}>Upload or reuse an APK, understand the application, safely discover its runtime UI, generate the test portfolio and execute evidence-backed checks.</Typography>
    </Box>

    <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 }, borderRadius: 3 }}>
      <Grid container spacing={3}>
        <Grid item xs={12} md={5}><Stack spacing={2}>
          <FormControl fullWidth size="small"><InputLabel id="stored-apk-label">APK source</InputLabel><Select labelId="stored-apk-label" label="APK source" value={selectedUploadId} disabled={repositoryLoading || busy} onChange={(event) => { setSelectedUploadId(event.target.value); if (event.target.value) setFile(null); resetResult(); }}>
            <MenuItem value="">Upload a new APK</MenuItem>{storedApks.map((asset) => <MenuItem key={asset.id} value={asset.id}>{asset.filename} · {formatBytes(asset.size_bytes)} · {new Date(asset.created_at).toLocaleDateString()}</MenuItem>)}
          </Select></FormControl>
          {selectedStoredApk ? <Box sx={{ border: "1px solid", borderColor: "primary.main", borderRadius: 3, p: 2.5, bgcolor: "action.hover" }}><Stack direction="row" spacing={1.2} alignItems="center"><FolderOutlinedIcon color="primary" /><Box sx={{ minWidth: 0 }}><Typography fontWeight={800} noWrap>{selectedStoredApk.filename}</Typography><Typography variant="caption" color="text.secondary">Stored APK · {formatBytes(selectedStoredApk.size_bytes)}</Typography></Box></Stack><Button size="small" sx={{ mt: 1 }} onClick={() => navigate("/test-data/uploads")}>Open repository</Button></Box>
          : <Box sx={{ border: "1px dashed", borderColor: file ? "primary.main" : "divider", borderRadius: 3, p: 3, textAlign: "center", bgcolor: "action.hover" }}><CloudUploadOutlinedIcon sx={{ fontSize: 40, color: "primary.main" }} /><Typography fontWeight={700}>{file?.name || "Choose an Android APK"}</Typography>{file && <Typography variant="caption" color="text.secondary">{formatBytes(file.size)}</Typography>}<Box sx={{ mt: 1.5 }}><Button component="label" variant="outlined" disabled={busy}>Choose APK<input hidden type="file" accept=".apk,application/vnd.android.package-archive" onChange={onFile} /></Button></Box></Box>}
        </Stack></Grid>
        <Grid item xs={12} md={7}><TextField fullWidth multiline minRows={5} label="Optional business context" placeholder="Example: UAT retail banking app. Login and balance inquiry are critical. Do not perform real transfers or customer notifications." value={context} onChange={(event) => setContext(event.target.value)} helperText="Do not paste production passwords or secrets." /><Button sx={{ mt: 2 }} disabled={(!file && !selectedUploadId) || busy || !selectedProjectId} onClick={analyze} variant="contained" size="large" startIcon={busy ? <CircularProgress size={18} color="inherit" /> : <AutoAwesomeIcon />}>{busy ? "Learning application…" : selectedStoredApk ? "Analyze stored APK" : "Start Autopilot analysis"}</Button></Grid>
      </Grid>
      {busy && <Box sx={{ mt: 2 }}><Box sx={{ height: 4, borderRadius: 2, overflow: "hidden", bgcolor: "action.hover" }}><Box sx={{ height: "100%", width: `${Math.max(3, analysisProgress)}%`, bgcolor: "primary.main", transition: "width .4s ease" }} /></Box><Typography variant="caption" color="text.secondary">{analysisStage.replaceAll("_", " ")} · {analysisProgress}%</Typography></Box>}
    </Paper>

    {error && <Alert severity="error">{error}</Alert>}

    {analysis && stats && <>
      {analysis.warnings.length > 0 && <Alert severity="warning">{analysis.warnings.join(" ")}</Alert>}
      <Grid container spacing={2}>{[["Generated tests", stats.tests], ["Test suites", stats.suites], ["Autonomous-safe", stats.autonomous], ["Critical / high", stats.critical]].map(([label, value]) => <Grid item xs={6} md={3} key={String(label)}><Card variant="outlined"><CardContent><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h4" fontWeight={800}>{value}</Typography></CardContent></Card></Grid>)}</Grid>

      <Grid container spacing={3}>
        <Grid item xs={12} lg={8}><Card variant="outlined" sx={{ height: "100%" }}><CardContent><Stack direction="row" spacing={1} alignItems="center"><AccountTreeOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Application intelligence</Typography></Stack><Typography sx={{ mt: 1.5 }}>{analysis.app_summary}</Typography><Divider sx={{ my: 2 }} /><Grid container spacing={2}><Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Application</Typography><Typography fontWeight={700}>{analysis.app_name || "Unknown"}</Typography></Grid><Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Domain</Typography><Typography fontWeight={700}>{analysis.inferred_domain}</Typography></Grid><Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Version</Typography><Typography fontWeight={700}>{analysis.version_name || "—"}</Typography></Grid><Grid item xs={12} md={6}><Typography variant="caption" color="text.secondary">Package</Typography><Typography sx={{ wordBreak: "break-all" }}>{analysis.package_name || "—"}</Typography></Grid><Grid item xs={12} md={6}><Typography variant="caption" color="text.secondary">Main activity</Typography><Typography sx={{ wordBreak: "break-all" }}>{analysis.main_activity || "—"}</Typography></Grid></Grid></CardContent></Card></Grid>
        <Grid item xs={12} lg={4}><Card variant="outlined" sx={{ height: "100%" }}><CardContent><Stack direction="row" spacing={1} alignItems="center"><SecurityOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Guardrails</Typography></Stack><Stack spacing={1} sx={{ mt: 1.5 }}><Chip label="Safe discovery: enabled" color="success" variant="outlined" /><Chip label="Transactions / destructive actions: blocked" color="warning" variant="outlined" /><Chip label={`Debuggable: ${analysis.debuggable === true ? "YES" : analysis.debuggable === false ? "No" : "Unknown"}`} variant="outlined" /></Stack></CardContent></Card></Grid>
      </Grid>

      <Card variant="outlined"><CardContent><Stack direction="row" spacing={1} alignItems="center"><BugReportOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Autonomous test portfolio</Typography></Stack><TableContainer sx={{ mt: 1.5, maxHeight: 420 }}><Table stickyHeader size="small"><TableHead><TableRow><TableCell>Test</TableCell><TableCell>Suite</TableCell><TableCell>Priority</TableCell><TableCell>Source</TableCell><TableCell>Mode</TableCell></TableRow></TableHead><TableBody>{analysis.tests.map((test) => <TableRow key={test.id} hover><TableCell sx={{ minWidth: 300 }}><Typography fontWeight={700} variant="body2">{test.title}</Typography><Typography variant="caption" color="text.secondary">{test.objective}</Typography></TableCell><TableCell>{test.suite}</TableCell><TableCell><Chip size="small" label={test.priority.toUpperCase()} color={priorityColor[test.priority]} variant="outlined" /></TableCell><TableCell>{test.source === "ai" ? "AI" : "RULE"}</TableCell><TableCell><Chip size="small" label={test.destructive ? "Approval required" : "Autonomous"} color={test.destructive ? "warning" : "success"} variant="outlined" /></TableCell></TableRow>)}</TableBody></Table></TableContainer></CardContent></Card>

      <Card variant="outlined"><CardContent>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2} alignItems={{ md: "center" }}><Box><Stack direction="row" spacing={1} alignItems="center"><TravelExploreOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Runtime discovery</Typography></Stack><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>Map screens and semantic controls from the running Android app. Payments, transfers, delete, submit, confirm and OTP actions remain blocked.</Typography></Box><Stack direction="row" spacing={1}><FormControl size="small" sx={{ minWidth: 145 }}><InputLabel id="discovery-mode-label">Mode</InputLabel><Select labelId="discovery-mode-label" label="Mode" value={discoveryMode} onChange={(event) => setDiscoveryMode(event.target.value as "safe" | "observe")}><MenuItem value="safe">Safe navigation</MenuItem><MenuItem value="observe">Observe only</MenuItem></Select></FormControl><Button variant="contained" startIcon={discoveryBusy ? <CircularProgress size={16} color="inherit" /> : <TravelExploreOutlinedIcon />} disabled={discoveryBusy || executionUnavailable} onClick={runDiscovery}>{discoveryBusy ? "Discovering…" : "Run discovery"}</Button></Stack></Stack>
        {browserStackUnavailable && provider === "browserstack" && <Alert severity="warning" sx={{ mt: 2 }}>BrowserStack credentials are not configured. Choose a reachable custom Appium endpoint or configure BrowserStack.</Alert>}
        {discovery && <><Grid container spacing={1.5} sx={{ mt: 1 }}>{[["Screens", discovery.screen_count], ["Controls", discovery.control_count], ["Safe controls", discovery.safe_control_count], ["Blocked", discovery.blocked_control_count], ["Actions", discovery.actions_attempted]].map(([label, value]) => <Grid item xs={6} sm={4} md key={String(label)}><Box sx={{ p: 1.25, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h6" fontWeight={800}>{value}</Typography></Box></Grid>)}</Grid><Alert severity={discovery.status === "completed" ? "success" : discovery.status === "blocked" ? "warning" : discovery.status === "failed" ? "error" : "info"} sx={{ mt: 2 }}>Discovery: <b>{discovery.status.toUpperCase()}</b> · {discovery.stop_reason}{discovery.error ? ` · ${discovery.error}` : ""}</Alert>{discoveredRows.length > 0 && <TableContainer sx={{ mt: 2, maxHeight: 400 }}><Table stickyHeader size="small"><TableHead><TableRow><TableCell>Screen</TableCell><TableCell>Control</TableCell><TableCell>Risk</TableCell><TableCell>Best locator</TableCell><TableCell>Confidence</TableCell></TableRow></TableHead><TableBody>{discoveredRows.slice(0, 150).map(({ screen, control }) => { const locator = control.locators[0]; return <TableRow key={`${screen}-${control.control_id}`} hover><TableCell>{screen}</TableCell><TableCell><Typography variant="body2" fontWeight={700}>{control.semantic_label}</Typography><Typography variant="caption" color="text.secondary">{control.class_name.split(".").pop() || control.class_name}</Typography></TableCell><TableCell><Chip size="small" label={control.risk} color={riskColor[control.risk]} variant="outlined" /></TableCell><TableCell sx={{ maxWidth: 320 }}><Typography variant="caption" sx={{ wordBreak: "break-all" }}>{locator ? `${locator.strategy}: ${locator.value}` : "No deterministic locator"}</Typography></TableCell><TableCell>{locator ? `${Math.round(locator.confidence * 100)}%` : "—"}</TableCell></TableRow>; })}</TableBody></Table></TableContainer>}</>}
      </CardContent></Card>

      <Card variant="outlined"><CardContent><Stack direction="row" spacing={1} alignItems="center"><PlayArrowRoundedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Safe smoke execution</Typography></Stack><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>Install, launch and capture screenshot/UI hierarchy without performing a business transaction.</Typography><Grid container spacing={2} sx={{ mt: .5 }}><Grid item xs={12} md={3}><FormControl fullWidth size="small"><InputLabel id="autopilot-provider-label">Execution target</InputLabel><Select labelId="autopilot-provider-label" label="Execution target" value={provider} onChange={(event) => setProvider(event.target.value as "browserstack" | "appium")}><MenuItem value="browserstack">BrowserStack real device</MenuItem><MenuItem value="appium">Custom / local Appium</MenuItem></Select></FormControl></Grid><Grid item xs={12} md={3}><TextField fullWidth size="small" label="Device name" value={deviceName} onChange={(event) => setDeviceName(event.target.value)} /></Grid><Grid item xs={12} md={2}><TextField fullWidth size="small" label="Android version" value={platformVersion} onChange={(event) => setPlatformVersion(event.target.value)} /></Grid><Grid item xs={12} md={4}><Button fullWidth sx={{ height: 40 }} variant="contained" disabled={smokeBusy || executionUnavailable} onClick={runSmoke} startIcon={smokeBusy ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRoundedIcon />}>{smokeBusy ? "Running…" : "Run safe smoke"}</Button></Grid>{provider === "appium" && <><Grid item xs={12} md={6}><TextField fullWidth size="small" label="Appium server URL" value={appiumUrl} onChange={(event) => setAppiumUrl(event.target.value)} /></Grid><Grid item xs={12} md={6}><TextField fullWidth size="small" label="Optional remote app reference" value={appiumApp} onChange={(event) => setAppiumApp(event.target.value)} /></Grid></>}</Grid>{execution && <Alert sx={{ mt: 2 }} severity={execution.status === "passed" ? "success" : execution.status === "blocked" ? "warning" : "error"}>Smoke: <b>{execution.status.toUpperCase()}</b> · {execution.provider} · {execution.duration_seconds}s{execution.current_package ? ` · ${execution.current_package}` : ""}{execution.error ? ` · ${execution.error}` : ""}</Alert>}</CardContent></Card>

      {analysis.release_risks.length > 0 && <Alert severity="info"><b>Initial release risks:</b> {analysis.release_risks.join(" • ")}</Alert>}
    </>}
  </Stack>;
}
