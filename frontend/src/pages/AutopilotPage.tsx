import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import SecurityOutlinedIcon from "@mui/icons-material/SecurityOutlined";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import BugReportOutlinedIcon from "@mui/icons-material/BugReportOutlined";
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import { apiClient } from "@/services/apiClient";
import { uploadsApi } from "@/services/api";
import { UploadedAsset } from "@/types/domain";

type TestCase = {
  id: string;
  suite: string;
  title: string;
  priority: "critical" | "high" | "medium" | "low";
  objective: string;
  steps: string[];
  expected: string[];
  autonomous: boolean;
  destructive: boolean;
  source: "deterministic" | "ai";
};

type Analysis = {
  job_id: string;
  filename: string;
  status: string;
  app_name?: string;
  package_name?: string;
  version_name?: string;
  version_code?: string;
  min_sdk?: string;
  target_sdk?: string;
  main_activity?: string;
  activities: string[];
  services: string[];
  receivers: string[];
  permissions: string[];
  file_count: number;
  size_bytes: number;
  sha256: string;
  debuggable?: boolean;
  inferred_domain: string;
  app_summary: string;
  critical_journeys: string[];
  clarification_questions: string[];
  tests: TestCase[];
  release_risks: string[];
  warnings: string[];
  capabilities: Record<string, boolean>;
};

type ProviderStatus = {
  browserstack_configured: boolean;
  custom_appium_available: boolean;
  recommended_provider: "browserstack" | "appium";
};

type AnalysisJob = {
  job_id: string;
  filename: string;
  status: "uploaded" | "analyzing" | "analyzed" | "failed";
  stage: string;
  progress: number;
  artifact_available?: boolean;
  error?: string;
  analysis?: Analysis | null;
};

type Execution = {
  status: "passed" | "failed" | "blocked";
  provider: "browserstack" | "appium";
  duration_seconds: number;
  current_package?: string;
  current_activity?: string;
  error?: string;
  evidence: Record<string, unknown>;
};

const priorityColor: Record<TestCase["priority"], "error" | "warning" | "info" | "default"> = {
  critical: "error",
  high: "warning",
  medium: "info",
  low: "default",
};

function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, value / 1024).toFixed(0)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export default function AutopilotPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [storedApks, setStoredApks] = useState<UploadedAsset[]>([]);
  const [selectedUploadId, setSelectedUploadId] = useState("");
  const [repositoryLoading, setRepositoryLoading] = useState(false);
  const [context, setContext] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [execution, setExecution] = useState<Execution | null>(null);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);
  const [provider, setProvider] = useState<"browserstack" | "appium">("browserstack");
  const [busy, setBusy] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [analysisStage, setAnalysisStage] = useState("");
  const [artifactAvailable, setArtifactAvailable] = useState(true);
  const [smokeBusy, setSmokeBusy] = useState(false);
  const [error, setError] = useState("");
  const [appiumUrl, setAppiumUrl] = useState("http://127.0.0.1:4723");
  const [deviceName, setDeviceName] = useState("Google Pixel 8");
  const [platformVersion, setPlatformVersion] = useState("14.0");
  const [appiumApp, setAppiumApp] = useState("");

  const refreshStoredApks = async () => {
    setRepositoryLoading(true);
    try {
      const response = await uploadsApi.list({ category: "apk" });
      setStoredApks(response.data);
    } catch {
      setStoredApks([]);
    } finally {
      setRepositoryLoading(false);
    }
  };

  useEffect(() => {
    apiClient.get<ProviderStatus>("/autopilot/providers")
      .then((response) => {
        setProviderStatus(response.data);
        setProvider(response.data.recommended_provider);
        if (response.data.recommended_provider === "appium") setDeviceName("Android Emulator");
      })
      .catch(() => setProviderStatus(null));
  }, []);

  useEffect(() => {
    void refreshStoredApks();
  }, []);

  useEffect(() => {
    let active = true;
    const applyJob = (job: AnalysisJob) => {
      setAnalysisProgress(job.progress);
      setAnalysisStage(job.stage);
      setArtifactAvailable(job.artifact_available !== false);
      if (job.status === "analyzed" && job.analysis) {
        setAnalysis(job.analysis);
      } else if (job.status === "failed" && job.error) {
        setError(job.error);
      }
    };
    const restore = async () => {
      try {
        const response = await apiClient.get<AnalysisJob | null>("/autopilot/jobs/latest", { timeout: 15000 });
        if (!active || !response.data) return;
        applyJob(response.data);
        // If the page was refreshed while the worker was running, continue the
        // same bounded polling loop instead of leaving the user on stale progress.
        if (response.data.status === "uploaded" || response.data.status === "analyzing") {
          const deadline = Date.now() + 20 * 60 * 1000;
          while (active && Date.now() < deadline) {
            await new Promise((resolve) => window.setTimeout(resolve, 2000));
            if (!active) return;
            const poll = await apiClient.get<AnalysisJob>(`/autopilot/jobs/${response.data.job_id}`, { timeout: 15000 });
            applyJob(poll.data);
            if (poll.data.status === "analyzed" || poll.data.status === "failed") break;
          }
        }
      } catch {
        // A first visit may not have a previous Autopilot job; keep the upload form usable.
      }
    };
    void restore();
    return () => {
      active = false;
    };
  }, []);

  const stats = useMemo(() => {
    if (!analysis) return null;
    return {
      tests: analysis.tests.length,
      suites: new Set(analysis.tests.map((test) => test.suite)).size,
      autonomous: analysis.tests.filter((test) => test.autonomous).length,
      critical: analysis.tests.filter((test) => test.priority === "critical" || test.priority === "high").length,
    };
  }, [analysis]);

  const selectedStoredApk = useMemo(
    () => storedApks.find((asset) => asset.id === selectedUploadId) ?? null,
    [storedApks, selectedUploadId],
  );

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    if (selected) setSelectedUploadId("");
    setAnalysis(null);
    setExecution(null);
    setArtifactAvailable(true);
    setError("");
  };

  const pollAnalysis = async (jobId: string) => {
    const deadline = Date.now() + 20 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      const poll = await apiClient.get<AnalysisJob>(`/autopilot/jobs/${jobId}`, { timeout: 15000 });
      setAnalysisProgress(poll.data.progress);
      setAnalysisStage(poll.data.stage);
      setArtifactAvailable(poll.data.artifact_available !== false);
      if (poll.data.status === "failed") throw new Error(poll.data.error || "Autopilot analysis failed");
      if (poll.data.status === "analyzed" && poll.data.analysis) {
        setAnalysis(poll.data.analysis);
        return;
      }
    }
    throw new Error("Analysis is still running after 20 minutes. The job is saved; retry status shortly.");
  };

  const analyze = async () => {
    if (!file && !selectedUploadId) return;
    setBusy(true);
    setError("");
    setExecution(null);
    try {
      let response;
      if (selectedUploadId) {
        response = await apiClient.post<AnalysisJob>("/autopilot/analyze-existing", {
          upload_id: selectedUploadId,
          context,
        }, { timeout: 300000 });
      } else {
        const form = new FormData();
        form.append("file", file as File);
        form.append("context", context);
        response = await apiClient.post<AnalysisJob>("/autopilot/analyze", form, {
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 300000,
        });
        await refreshStoredApks();
      }

      const jobId = response.data.job_id;
      setAnalysisProgress(response.data.progress);
      setAnalysisStage(response.data.stage);
      setArtifactAvailable(response.data.artifact_available !== false);
      await pollAnalysis(jobId);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Autopilot analysis failed");
    } finally {
      setBusy(false);
    }
  };

  const runSmoke = async () => {
    if (!analysis) return;
    setSmokeBusy(true);
    setError("");
    try {
      const response = await apiClient.post<Execution>(`/autopilot/${analysis.job_id}/smoke`, {
        provider,
        appium_url: provider === "appium" ? appiumUrl : null,
        device_name: deviceName,
        platform_version: platformVersion || null,
        appium_app: provider === "appium" ? (appiumApp || null) : null,
        no_reset: false,
        auto_grant_permissions: false,
      }, { timeout: 300000 });
      setExecution(response.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Smoke execution failed");
    } finally {
      setSmokeBusy(false);
    }
  };

  const browserStackUnavailable = provider === "browserstack" && providerStatus?.browserstack_configured === false;

  return (
    <Stack spacing={3}>
      <Box>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <AutoAwesomeIcon color="primary" />
          <Typography variant="h4" fontWeight={800}>QTXpert Autopilot</Typography>
          <Chip size="small" label="ANDROID PROTOTYPE" color="primary" variant="outlined" />
        </Stack>
        <Typography color="text.secondary" sx={{ mt: 1, maxWidth: 920 }}>
          Upload an APK once, or reuse a build already stored in QTXpert. Autopilot inspects the application, infers its testing surface, creates an initial autonomous test portfolio and prepares safe execution with evidence capture.
        </Typography>
      </Box>

      <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 }, borderRadius: 3 }}>
        <Grid container spacing={3}>
          <Grid item xs={12} md={5}>
            <Stack spacing={2}>
              <FormControl fullWidth size="small">
                <InputLabel id="stored-apk-label">APK source</InputLabel>
                <Select
                  labelId="stored-apk-label"
                  label="APK source"
                  value={selectedUploadId}
                  disabled={repositoryLoading || busy}
                  onChange={(event) => {
                    setSelectedUploadId(event.target.value);
                    if (event.target.value) setFile(null);
                    setAnalysis(null);
                    setExecution(null);
                    setError("");
                  }}
                >
                  <MenuItem value="">Upload a new APK</MenuItem>
                  {storedApks.map((asset) => (
                    <MenuItem key={asset.id} value={asset.id}>
                      {asset.filename} · {formatBytes(asset.size_bytes)} · {new Date(asset.created_at).toLocaleDateString()}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>

              {selectedStoredApk ? (
                <Box sx={{ border: "1px solid", borderColor: "primary.main", borderRadius: 3, p: 3, bgcolor: "action.hover" }}>
                  <Stack direction="row" spacing={1.2} alignItems="center">
                    <FolderOutlinedIcon color="primary" />
                    <Box sx={{ minWidth: 0 }}>
                      <Typography fontWeight={800} noWrap>{selectedStoredApk.filename}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        Reusing stored APK · {formatBytes(selectedStoredApk.size_bytes)} · uploaded {new Date(selectedStoredApk.created_at).toLocaleString()}
                      </Typography>
                    </Box>
                  </Stack>
                  <Button size="small" sx={{ mt: 1.5 }} onClick={() => navigate("/test-data/uploads")}>Open Upload Repository</Button>
                </Box>
              ) : (
                <Box sx={{ border: "1px dashed", borderColor: file ? "primary.main" : "divider", borderRadius: 3, p: 3, textAlign: "center", bgcolor: "action.hover" }}>
                  <CloudUploadOutlinedIcon sx={{ fontSize: 42, color: "primary.main", mb: 1 }} />
                  <Typography fontWeight={700}>{file?.name || "Drop or choose an Android APK"}</Typography>
                  {file && <Typography variant="caption" color="text.secondary">{(file.size / 1024 / 1024).toFixed(1)} MB</Typography>}
                  <Box sx={{ mt: 2 }}>
                    <Button component="label" variant="outlined" disabled={busy}>
                      Choose APK
                      <input hidden type="file" accept=".apk,application/vnd.android.package-archive" onChange={onFile} />
                    </Button>
                  </Box>
                  {storedApks.length > 0 && (
                    <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 1.5 }}>
                      Or select one of {storedApks.length} stored APK{storedApks.length === 1 ? "" : "s"} above.
                    </Typography>
                  )}
                </Box>
              )}
            </Stack>
          </Grid>
          <Grid item xs={12} md={7}>
            <TextField
              fullWidth
              multiline
              minRows={5}
              label="Optional business context"
              placeholder="Example: This is our UAT retail banking app. Login and balance inquiry are critical. Do not perform real transfers or customer notifications."
              value={context}
              onChange={(event) => setContext(event.target.value)}
              helperText="Do not paste production passwords or secrets. Autopilot will ask only for context it cannot infer."
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }} sx={{ mt: 2 }}>
              <Button disabled={(!file && !selectedUploadId) || busy} onClick={analyze} variant="contained" size="large" startIcon={busy ? <CircularProgress size={18} color="inherit" /> : <AutoAwesomeIcon />}>
                {busy ? "Learning application…" : selectedStoredApk ? "Analyze Stored APK" : "Start Autopilot Analysis"}
              </Button>
              <Typography variant="caption" color="text.secondary">Android APK · prototype limit 250 MB · new uploads are saved automatically</Typography>
            </Stack>
          </Grid>
        </Grid>
        {busy && <><LinearProgressCompat progress={analysisProgress} /><Typography variant="caption" color="text.secondary">{analysisStage.replaceAll("_", " ")} · {analysisProgress}%</Typography></>}
      </Paper>

      {error && <Alert severity="error">{error}</Alert>}

      {analysis && stats && (
        <>
          {analysis.warnings.length > 0 && <Alert severity="warning">{analysis.warnings.join(" ")}</Alert>}
          <Grid container spacing={2}>
            {[
              ["Generated tests", stats.tests],
              ["Test suites", stats.suites],
              ["Autonomous-safe", stats.autonomous],
              ["Critical / high", stats.critical],
            ].map(([label, value]) => (
              <Grid item xs={6} md={3} key={String(label)}>
                <Card variant="outlined" sx={{ height: "100%" }}><CardContent><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h4" fontWeight={800}>{value}</Typography></CardContent></Card>
              </Grid>
            ))}
          </Grid>

          <Grid container spacing={3}>
            <Grid item xs={12} lg={8}>
              <Card variant="outlined" sx={{ height: "100%" }}>
                <CardContent>
                  <Stack direction="row" alignItems="center" spacing={1}><AccountTreeOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Application intelligence</Typography></Stack>
                  <Typography sx={{ mt: 2 }}>{analysis.app_summary}</Typography>
                  <Divider sx={{ my: 2 }} />
                  <Grid container spacing={2}>
                    <Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Application</Typography><Typography fontWeight={700}>{analysis.app_name || "Unknown"}</Typography></Grid>
                    <Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Domain</Typography><Typography fontWeight={700}>{analysis.inferred_domain}</Typography></Grid>
                    <Grid item xs={6} md={4}><Typography variant="caption" color="text.secondary">Version</Typography><Typography fontWeight={700}>{analysis.version_name || "—"}</Typography></Grid>
                    <Grid item xs={12} md={6}><Typography variant="caption" color="text.secondary">Package</Typography><Typography sx={{ wordBreak: "break-all" }}>{analysis.package_name || "—"}</Typography></Grid>
                    <Grid item xs={12} md={6}><Typography variant="caption" color="text.secondary">Main activity</Typography><Typography sx={{ wordBreak: "break-all" }}>{analysis.main_activity || "—"}</Typography></Grid>
                    <Grid item xs={4}><Typography variant="caption" color="text.secondary">Activities</Typography><Typography fontWeight={700}>{analysis.activities.length}</Typography></Grid>
                    <Grid item xs={4}><Typography variant="caption" color="text.secondary">Permissions</Typography><Typography fontWeight={700}>{analysis.permissions.length}</Typography></Grid>
                    <Grid item xs={4}><Typography variant="caption" color="text.secondary">APK files</Typography><Typography fontWeight={700}>{analysis.file_count}</Typography></Grid>
                  </Grid>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} lg={4}>
              <Card variant="outlined" sx={{ height: "100%" }}>
                <CardContent>
                  <Stack direction="row" alignItems="center" spacing={1}><SecurityOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Autopilot guardrails</Typography></Stack>
                  <Stack spacing={1.2} sx={{ mt: 2 }}>
                    <Chip label="Safe smoke: enabled" color="success" variant="outlined" />
                    <Chip label="Destructive actions: blocked" color="warning" variant="outlined" />
                    <Chip label={`Debuggable: ${analysis.debuggable === true ? "YES" : analysis.debuggable === false ? "No" : "Unknown"}`} variant="outlined" />
                  </Stack>
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 2 }}>SHA-256</Typography>
                  <Typography variant="caption" sx={{ wordBreak: "break-all" }}>{analysis.sha256}</Typography>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          <Grid container spacing={3}>
            <Grid item xs={12} md={6}>
              <Card variant="outlined"><CardContent><Typography variant="h6" fontWeight={800}>Critical journeys inferred</Typography><Stack spacing={1} sx={{ mt: 1.5 }}>{analysis.critical_journeys.map((item, index) => <Typography key={item} variant="body2"><b>{index + 1}.</b> {item}</Typography>)}</Stack></CardContent></Card>
            </Grid>
            <Grid item xs={12} md={6}>
              <Card variant="outlined"><CardContent><Typography variant="h6" fontWeight={800}>What QTXpert still needs to know</Typography><Stack spacing={1} sx={{ mt: 1.5 }}>{analysis.clarification_questions.map((item, index) => <Typography key={item} variant="body2"><b>{index + 1}.</b> {item}</Typography>)}</Stack></CardContent></Card>
            </Grid>
          </Grid>

          <Card variant="outlined">
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center"><BugReportOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Autonomous test portfolio</Typography></Stack>
              <TableContainer sx={{ mt: 2, maxHeight: 520 }}>
                <Table stickyHeader size="small">
                  <TableHead><TableRow><TableCell>Test</TableCell><TableCell>Suite</TableCell><TableCell>Priority</TableCell><TableCell>Source</TableCell><TableCell>Mode</TableCell></TableRow></TableHead>
                  <TableBody>
                    {analysis.tests.map((test) => (
                      <TableRow key={test.id} hover>
                        <TableCell sx={{ minWidth: 320 }}><Typography fontWeight={700} variant="body2">{test.title}</Typography><Typography variant="caption" color="text.secondary">{test.objective}</Typography></TableCell>
                        <TableCell>{test.suite}</TableCell>
                        <TableCell><Chip size="small" label={test.priority.toUpperCase()} color={priorityColor[test.priority]} variant="outlined" /></TableCell>
                        <TableCell><Chip size="small" label={test.source === "ai" ? "AI" : "RULE"} variant="outlined" /></TableCell>
                        <TableCell><Chip size="small" label={test.destructive ? "Approval required" : "Autonomous"} color={test.destructive ? "warning" : "success"} variant="outlined" /></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </CardContent>
          </Card>

          <Card variant="outlined">
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center"><PlayArrowRoundedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Safe smoke execution</Typography></Stack>
              <Typography color="text.secondary" variant="body2" sx={{ mt: 1 }}>
                QTXpert installs and launches the uploaded build, captures a screenshot and UI hierarchy, and records foreground package/activity. No business transaction is performed.
              </Typography>
              <Grid container spacing={2} sx={{ mt: 0.5 }}>
                <Grid item xs={12} md={3}>
                  <FormControl fullWidth size="small">
                    <InputLabel id="autopilot-provider-label">Execution target</InputLabel>
                    <Select labelId="autopilot-provider-label" label="Execution target" value={provider} onChange={(e) => setProvider(e.target.value as "browserstack" | "appium")}>
                      <MenuItem value="browserstack">BrowserStack real device</MenuItem>
                      <MenuItem value="appium">Custom / local Appium</MenuItem>
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} md={3}><TextField fullWidth size="small" label="Device name" value={deviceName} onChange={(e) => setDeviceName(e.target.value)} /></Grid>
                <Grid item xs={12} md={2}><TextField fullWidth size="small" label="Android version" value={platformVersion} onChange={(e) => setPlatformVersion(e.target.value)} /></Grid>
                <Grid item xs={12} md={4}><Button fullWidth sx={{ height: 40 }} variant="contained" disabled={smokeBusy || browserStackUnavailable || !artifactAvailable} onClick={runSmoke} startIcon={smokeBusy ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRoundedIcon />}>{smokeBusy ? "Running" : "Run safe smoke"}</Button></Grid>
                {provider === "appium" && <>
                  <Grid item xs={12} md={6}><TextField fullWidth size="small" label="Appium server URL" value={appiumUrl} onChange={(e) => setAppiumUrl(e.target.value)} /></Grid>
                  <Grid item xs={12} md={6}><TextField fullWidth size="small" label="Optional remote app reference" placeholder="Leave blank when the Appium server can access the uploaded APK path" value={appiumApp} onChange={(e) => setAppiumApp(e.target.value)} /></Grid>
                </>}
              </Grid>
              {provider === "browserstack" && (
                <Alert sx={{ mt: 2 }} severity={providerStatus?.browserstack_configured ? "success" : "warning"}>
                  {providerStatus?.browserstack_configured
                    ? "BrowserStack is configured. QTXpert will upload this APK server-side and launch it on the selected real device; credentials remain server-side."
                    : "BrowserStack credentials are not configured on the backend yet. Add BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY as Render secrets to enable real-device execution."}
                </Alert>
              )}
              {!artifactAvailable && <Alert sx={{ mt: 2 }} severity="warning">This analysis was created before durable APK storage was enabled and the original APK is no longer available on this service instance. Upload that APK once more; future runs can reuse it from Test Data → Uploads.</Alert>}
              {execution && <Alert sx={{ mt: 2 }} severity={execution.status === "passed" ? "success" : execution.status === "blocked" ? "warning" : "error"}>Smoke status: <b>{execution.status.toUpperCase()}</b> · {execution.provider} · {execution.duration_seconds}s{execution.current_package ? ` · ${execution.current_package}` : ""}{execution.current_activity ? ` · ${execution.current_activity}` : ""}{execution.error ? ` · ${execution.error}` : ""}</Alert>}
            </CardContent>
          </Card>

          {analysis.release_risks.length > 0 && <Alert severity="info"><b>Initial release risks:</b> {analysis.release_risks.join(" • ")}</Alert>}
        </>
      )}
    </Stack>
  );
}

function LinearProgressCompat({ progress }: { progress: number }) {
  return <Box sx={{ mt: 2, height: 4, borderRadius: 2, overflow: "hidden", bgcolor: "action.hover" }}><Box sx={{ height: "100%", width: `${Math.max(3, progress)}%`, bgcolor: "primary.main", transition: "width .4s ease" }} /></Box>;
}
