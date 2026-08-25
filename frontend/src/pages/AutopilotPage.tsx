import { ChangeEvent, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  Grid,
  LinearProgress,
  Paper,
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
import { apiClient } from "@/services/apiClient";

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

type Execution = {
  status: "passed" | "failed" | "blocked";
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

export default function AutopilotPage() {
  const [file, setFile] = useState<File | null>(null);
  const [context, setContext] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [execution, setExecution] = useState<Execution | null>(null);
  const [busy, setBusy] = useState(false);
  const [smokeBusy, setSmokeBusy] = useState(false);
  const [error, setError] = useState("");
  const [appiumUrl, setAppiumUrl] = useState("http://127.0.0.1:4723");
  const [deviceName, setDeviceName] = useState("Android Emulator");
  const [platformVersion, setPlatformVersion] = useState("");
  const [appiumApp, setAppiumApp] = useState("");

  const stats = useMemo(() => {
    if (!analysis) return null;
    return {
      tests: analysis.tests.length,
      suites: new Set(analysis.tests.map((test) => test.suite)).size,
      autonomous: analysis.tests.filter((test) => test.autonomous).length,
      critical: analysis.tests.filter((test) => test.priority === "critical" || test.priority === "high").length,
    };
  }, [analysis]);

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    setAnalysis(null);
    setExecution(null);
    setError("");
  };

  const analyze = async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    setExecution(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("context", context);
      const response = await apiClient.post<Analysis>("/autopilot/analyze", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 180000,
      });
      setAnalysis(response.data);
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
        appium_url: appiumUrl,
        device_name: deviceName,
        platform_version: platformVersion || null,
        appium_app: appiumApp || null,
        no_reset: false,
        auto_grant_permissions: false,
      }, { timeout: 180000 });
      setExecution(response.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Smoke execution failed");
    } finally {
      setSmokeBusy(false);
    }
  };

  return (
    <Stack spacing={3}>
      <Box>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <AutoAwesomeIcon color="primary" />
          <Typography variant="h4" fontWeight={800}>QTXpert Autopilot</Typography>
          <Chip size="small" label="ANDROID PROTOTYPE" color="primary" variant="outlined" />
        </Stack>
        <Typography color="text.secondary" sx={{ mt: 1, maxWidth: 920 }}>
          Upload an APK once. QTXpert inspects the application, infers its testing surface, creates an initial autonomous test portfolio and prepares a safe smoke execution with evidence capture.
        </Typography>
      </Box>

      <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 }, borderRadius: 3 }}>
        <Grid container spacing={3}>
          <Grid item xs={12} md={5}>
            <Box sx={{ border: "1px dashed", borderColor: file ? "primary.main" : "divider", borderRadius: 3, p: 3, textAlign: "center", bgcolor: "action.hover" }}>
              <CloudUploadOutlinedIcon sx={{ fontSize: 42, color: "primary.main", mb: 1 }} />
              <Typography fontWeight={700}>{file?.name || "Drop or choose an Android APK"}</Typography>
              {file && <Typography variant="caption" color="text.secondary">{(file.size / 1024 / 1024).toFixed(1)} MB</Typography>}
              <Box sx={{ mt: 2 }}>
                <Button component="label" variant="outlined">
                  Choose APK
                  <input hidden type="file" accept=".apk,application/vnd.android.package-archive" onChange={onFile} />
                </Button>
              </Box>
            </Box>
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
            <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 2 }}>
              <Button disabled={!file || busy} onClick={analyze} variant="contained" size="large" startIcon={busy ? <CircularProgress size={18} color="inherit" /> : <AutoAwesomeIcon />}>
                {busy ? "Learning application…" : "Start Autopilot Analysis"}
              </Button>
              <Typography variant="caption" color="text.secondary">Prototype limit: Android APK, 250 MB</Typography>
            </Stack>
          </Grid>
        </Grid>
        {busy && <LinearProgress sx={{ mt: 2, borderRadius: 2 }} />}
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
              <Typography color="text.secondary" variant="body2" sx={{ mt: 1 }}>Connect an Appium-compatible Android device. QTXpert will install/launch the uploaded build, capture a screenshot and UI hierarchy, and report the foreground package/activity. No business transaction is performed.</Typography>
              <Grid container spacing={2} sx={{ mt: 0.5 }}>
                <Grid item xs={12} md={5}><TextField fullWidth size="small" label="Appium server URL" value={appiumUrl} onChange={(e) => setAppiumUrl(e.target.value)} /></Grid>
                <Grid item xs={12} md={3}><TextField fullWidth size="small" label="Device name" value={deviceName} onChange={(e) => setDeviceName(e.target.value)} /></Grid>
                <Grid item xs={12} md={2}><TextField fullWidth size="small" label="Android version" value={platformVersion} onChange={(e) => setPlatformVersion(e.target.value)} /></Grid>
                <Grid item xs={12} md={2}><Button fullWidth sx={{ height: 40 }} variant="contained" disabled={smokeBusy} onClick={runSmoke} startIcon={smokeBusy ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRoundedIcon />}>{smokeBusy ? "Running" : "Run smoke"}</Button></Grid>
                <Grid item xs={12}><TextField fullWidth size="small" label="Optional cloud app reference" placeholder="Leave blank for local Appium; enter provider app reference for a configured remote endpoint" value={appiumApp} onChange={(e) => setAppiumApp(e.target.value)} /></Grid>
              </Grid>
              {execution && <Alert sx={{ mt: 2 }} severity={execution.status === "passed" ? "success" : execution.status === "blocked" ? "warning" : "error"}>Smoke status: <b>{execution.status.toUpperCase()}</b> · {execution.duration_seconds}s{execution.current_package ? ` · ${execution.current_package}` : ""}{execution.current_activity ? ` · ${execution.current_activity}` : ""}{execution.error ? ` · ${execution.error}` : ""}</Alert>}
            </CardContent>
          </Card>

          {analysis.release_risks.length > 0 && <Alert severity="info"><b>Initial release risks:</b> {analysis.release_risks.join(" • ")}</Alert>}
        </>
      )}
    </Stack>
  );
}
