import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  IconButton,
  LinearProgress,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import AssignmentOutlinedIcon from "@mui/icons-material/AssignmentOutlined";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import BugReportOutlinedIcon from "@mui/icons-material/BugReportOutlined";
import CheckCircleOutlineOutlinedIcon from "@mui/icons-material/CheckCircleOutlineOutlined";
import HistoryOutlinedIcon from "@mui/icons-material/HistoryOutlined";
import TuneOutlinedIcon from "@mui/icons-material/TuneOutlined";
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import RestoreOutlinedIcon from "@mui/icons-material/RestoreOutlined";
import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import { dashboardApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import PageHeader from "@/components/PageHeader";
import type { DashboardSummary, ExecutionRun } from "@/types/domain";

type MetricKey =
  | "requirements"
  | "test_cases"
  | "execution_runs"
  | "pass_rate"
  | "open_defects"
  | "automation_candidates";

type WidgetKey = "metrics" | "posture" | "execution" | "signals";

interface DashboardPreferences {
  title: string;
  description: string;
  visibleMetrics: Record<MetricKey, boolean>;
  visibleWidgets: Record<WidgetKey, boolean>;
  metricLabels: Record<MetricKey, string>;
}

const defaultPreferences = (): DashboardPreferences => ({
  title: "Quality portfolio overview",
  description: "A concise view of delivery confidence, execution health and the decisions that need attention.",
  visibleMetrics: {
    requirements: true,
    test_cases: true,
    execution_runs: true,
    pass_rate: true,
    open_defects: true,
    automation_candidates: true,
  },
  visibleWidgets: {
    metrics: true,
    posture: true,
    execution: true,
    signals: true,
  },
  metricLabels: {
    requirements: "Requirements",
    test_cases: "Test cases",
    execution_runs: "Execution runs",
    pass_rate: "Pass rate",
    open_defects: "Open defects",
    automation_candidates: "Automation-ready",
  },
});

const metricDefinitions: Array<{ key: MetricKey; helper: string }> = [
  { key: "requirements", helper: "requirements in scope" },
  { key: "test_cases", helper: "designed test cases" },
  { key: "execution_runs", helper: "recorded execution cycles" },
  { key: "pass_rate", helper: "across completed checks" },
  { key: "open_defects", helper: "requiring triage" },
  { key: "automation_candidates", helper: "ready for automation" },
];

const widgetDefinitions: Array<{ key: WidgetKey; label: string; description: string }> = [
  { key: "metrics", label: "Executive metrics", description: "The KPI cards at the top of the dashboard." },
  { key: "posture", label: "Quality posture", description: "Progress signals that support release decisions." },
  { key: "execution", label: "Recent execution", description: "The latest execution cycles and their outcomes." },
  { key: "signals", label: "Management signals", description: "Short, actionable observations derived from the project data." },
];

const preferenceKey = (projectId: string) => `qtxpert-dashboard-preferences:${projectId}`;

function readPreferences(projectId: string): DashboardPreferences {
  const fallback = defaultPreferences();
  try {
    const raw = localStorage.getItem(preferenceKey(projectId));
    if (!raw) return fallback;
    const saved = JSON.parse(raw) as Partial<DashboardPreferences>;
    return {
      ...fallback,
      ...saved,
      visibleMetrics: { ...fallback.visibleMetrics, ...(saved.visibleMetrics || {}) },
      visibleWidgets: { ...fallback.visibleWidgets, ...(saved.visibleWidgets || {}) },
      metricLabels: { ...fallback.metricLabels, ...(saved.metricLabels || {}) },
    };
  } catch {
    return fallback;
  }
}

function copyPreferences(preferences: DashboardPreferences): DashboardPreferences {
  return {
    ...preferences,
    visibleMetrics: { ...preferences.visibleMetrics },
    visibleWidgets: { ...preferences.visibleWidgets },
    metricLabels: { ...preferences.metricLabels },
  };
}

function formatDate(value: string | null | undefined) {
  if (!value) return "No activity yet";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function runColor(status: string): "success" | "error" | "warning" | "info" | "default" {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  if (status === "running") return "info";
  if (status === "cancelled") return "warning";
  return "default";
}

function postureFor(summary: DashboardSummary | undefined) {
  if (!summary || summary.execution_runs === 0) return { label: "Not yet measured", color: "default" as const };
  if (summary.open_defects > 0) return { label: "Needs attention", color: "warning" as const };
  if (summary.pass_rate >= 90) return { label: "Healthy", color: "success" as const };
  return { label: "Watch", color: "info" as const };
}

function progressValue(numerator: number, denominator: number) {
  if (!denominator) return 0;
  return Math.min(100, Math.round((numerator / denominator) * 100));
}

export default function DashboardPage() {
  const { selectedProjectId, selectedProject } = useSelectedProject();
  const [preferences, setPreferences] = useState<DashboardPreferences>(defaultPreferences);
  const [draftPreferences, setDraftPreferences] = useState<DashboardPreferences>(defaultPreferences);
  const [customizeOpen, setCustomizeOpen] = useState(false);

  const summary = useQuery({
    queryKey: ["dashboard", selectedProjectId],
    queryFn: () => dashboardApi.summary(selectedProjectId).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
  });

  useEffect(() => {
    if (!selectedProjectId) {
      setPreferences(defaultPreferences());
      return;
    }
    setPreferences(readPreferences(selectedProjectId));
  }, [selectedProjectId]);

  const data = summary.data;
  const posture = postureFor(data);
  const visibleMetricDefinitions = metricDefinitions.filter(({ key }) => preferences.visibleMetrics[key]);
  const visibleWidgetCount = Object.values(preferences.visibleWidgets).filter(Boolean).length;

  const metricValues = useMemo<Record<MetricKey, number | string>>(() => ({
    requirements: data?.requirements ?? 0,
    test_cases: data?.test_cases ?? 0,
    execution_runs: data?.execution_runs ?? 0,
    pass_rate: `${data?.pass_rate ?? 0}%`,
    open_defects: data?.open_defects ?? 0,
    automation_candidates: data?.automation_candidates ?? 0,
  }), [data]);

  const managementSignals = useMemo(() => {
    const signals: Array<{ tone: "success" | "warning" | "info"; title: string; detail: string }> = [];
    if (!data || data.execution_runs === 0) {
      signals.push({ tone: "info", title: "Establish a baseline", detail: "Run the first execution cycle to give leadership a measured quality signal." });
    } else if (data.pass_rate >= 90 && data.open_defects === 0) {
      signals.push({ tone: "success", title: "Release confidence is strong", detail: "Completed checks are passing at a healthy rate with no open defects." });
    } else if (data.open_defects > 0) {
      signals.push({ tone: "warning", title: "Defect triage is required", detail: `${data.open_defects} open defect${data.open_defects === 1 ? "" : "s"} should be reviewed before sign-off.` });
    } else {
      signals.push({ tone: "info", title: "Quality signal needs monitoring", detail: "Continue execution coverage to confirm the current pass rate is stable." });
    }
    if (data && data.test_cases > 0 && data.automation_candidates < data.test_cases) {
      signals.push({ tone: "info", title: "Expand automation coverage", detail: `${data.test_cases - data.automation_candidates} test case${data.test_cases - data.automation_candidates === 1 ? "" : "s"} still need an automation decision.` });
    }
    if (data && data.requirements === 0) {
      signals.push({ tone: "warning", title: "Requirements are not mapped", detail: "Add or link requirements to keep the quality view traceable." });
    }
    return signals.slice(0, 3);
  }, [data]);

  const openCustomize = () => {
    setDraftPreferences(copyPreferences(preferences));
    setCustomizeOpen(true);
  };

  const savePreferences = () => {
    if (!selectedProjectId) return;
    try {
      localStorage.setItem(preferenceKey(selectedProjectId), JSON.stringify(draftPreferences));
    } catch {
      // The dashboard remains usable if browser storage is unavailable.
    }
    setPreferences(copyPreferences(draftPreferences));
    setCustomizeOpen(false);
  };

  const restoreDefaults = () => setDraftPreferences(defaultPreferences());

  const updateMetricLabel = (key: MetricKey, value: string) => {
    setDraftPreferences((current) => ({
      ...current,
      metricLabels: { ...current.metricLabels, [key]: value },
    }));
  };

  const toggleMetric = (key: MetricKey) => {
    setDraftPreferences((current) => ({
      ...current,
      visibleMetrics: { ...current.visibleMetrics, [key]: !current.visibleMetrics[key] },
    }));
  };

  const toggleWidget = (key: WidgetKey) => {
    setDraftPreferences((current) => ({
      ...current,
      visibleWidgets: { ...current.visibleWidgets, [key]: !current.visibleWidgets[key] },
    }));
  };

  if (!selectedProjectId) {
    return <Alert severity="info">Select a project from the top bar to open its quality dashboard.</Alert>;
  }

  return (
    <Box>
      <PageHeader
        eyebrow="EXECUTIVE QUALITY VIEW"
        title={preferences.title}
        description={preferences.description}
        actions={
          <Stack direction="row" spacing={1} alignItems="center">
            <Tooltip title="Refresh dashboard data">
              <span>
                <IconButton onClick={() => summary.refetch()} disabled={summary.isFetching} aria-label="Refresh dashboard">
                  <RefreshOutlinedIcon />
                </IconButton>
              </span>
            </Tooltip>
            <Button variant="outlined" startIcon={<TuneOutlinedIcon />} onClick={openCustomize}>
              Customize view
            </Button>
          </Stack>
        }
      />

      <Card
        variant="outlined"
        sx={{
          mb: 3,
          borderRadius: 3,
          background: "linear-gradient(120deg, rgba(14, 124, 119, 0.14), rgba(14, 124, 119, 0.03) 62%, transparent)",
        }}
      >
        <CardContent sx={{ p: { xs: 2.5, md: 3.25 }, "&:last-child": { pb: { xs: 2.5, md: 3.25 } } }}>
          <Grid container spacing={3} alignItems="center">
            <Grid size={{ xs: 12, md: 8 }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <Chip label="Management snapshot" size="small" color="primary" variant="outlined" />
                <Typography variant="caption" color="text.secondary">{selectedProject?.name}</Typography>
              </Stack>
              <Typography variant="h5" sx={{ mb: 0.75 }}>Make the next quality decision with confidence.</Typography>
              <Typography color="text.secondary" sx={{ maxWidth: 720 }}>
                This view keeps delivery leaders focused on measurable coverage, execution outcomes and unresolved risk.
              </Typography>
            </Grid>
            <Grid size={{ xs: 12, md: 4 }}>
              <Stack direction="row" spacing={2} alignItems="center" justifyContent={{ xs: "flex-start", md: "flex-end" }}>
                <Box sx={{ position: "relative", display: "inline-flex" }}>
                  <CircularProgress
                    variant="determinate"
                    value={data?.pass_rate ?? 0}
                    size={76}
                    thickness={5}
                    color={data?.pass_rate && data.pass_rate >= 90 ? "success" : "primary"}
                  />
                  <Box sx={{ inset: 0, position: "absolute", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <Typography fontWeight={800}>{data?.pass_rate ?? 0}%</Typography>
                  </Box>
                </Box>
                <Box>
                  <Typography variant="body2" color="text.secondary">Current posture</Typography>
                  <Typography variant="h6" sx={{ mt: 0.25 }}>{posture.label}</Typography>
                  <Typography variant="caption" color="text.secondary">Updated {formatDate(data?.recent_runs[0]?.created_at)}</Typography>
                </Box>
              </Stack>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {summary.isLoading && <LinearProgress sx={{ mb: 2 }} />}
      {summary.isError && <Alert severity="warning" sx={{ mb: 2 }}>Dashboard data is temporarily unavailable. Try refreshing the view.</Alert>}

      {preferences.visibleWidgets.metrics && visibleMetricDefinitions.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
            <Box>
              <Typography variant="overline" color="primary.main" sx={{ fontWeight: 700, letterSpacing: ".12em" }}>AT A GLANCE</Typography>
              <Typography variant="h6">Executive metrics</Typography>
            </Box>
            <Typography variant="caption" color="text.secondary">{visibleMetricDefinitions.length} of {metricDefinitions.length} metrics shown</Typography>
          </Stack>
          <Grid container spacing={2}>
            {visibleMetricDefinitions.map(({ key, helper }, index) => {
              const value = metricValues[key];
              const tone = key === "open_defects" && Number(value) > 0 ? "error.main" : key === "pass_rate" ? "success.main" : "primary.main";
              const icons = [<AssignmentOutlinedIcon key="requirements" />, <CheckCircleOutlineOutlinedIcon key="tests" />, <HistoryOutlinedIcon key="runs" />, <CheckCircleOutlineOutlinedIcon key="pass" />, <BugReportOutlinedIcon key="defects" />, <AutoAwesomeOutlinedIcon key="automation" />];
              return (
                <Grid key={key} size={{ xs: 12, sm: 6, lg: 4 }}>
                  <Card variant="outlined" sx={{ height: "100%", borderRadius: 3, transition: "transform .2s ease, box-shadow .2s ease", "&:hover": { transform: "translateY(-2px)", boxShadow: 3 } }}>
                    <CardContent sx={{ p: 2.25, "&:last-child": { pb: 2.25 } }}>
                      <Stack direction="row" alignItems="flex-start" justifyContent="space-between" spacing={2}>
                        <Box>
                          <Typography variant="body2" color="text.secondary">{preferences.metricLabels[key]}</Typography>
                          <Typography variant="h3" sx={{ mt: 0.75, color: tone }}>{value}</Typography>
                        </Box>
                        <Box sx={{ p: 1, borderRadius: 2, bgcolor: "action.hover", color: tone, display: "flex" }}>{icons[index]}</Box>
                      </Stack>
                      <Typography variant="caption" color="text.secondary">{helper}</Typography>
                      {key === "pass_rate" && <LinearProgress variant="determinate" value={Number(data?.pass_rate ?? 0)} color={data?.pass_rate && data.pass_rate >= 90 ? "success" : "primary"} sx={{ mt: 1.25, height: 5, borderRadius: 4 }} />}
                    </CardContent>
                  </Card>
                </Grid>
              );
            })}
          </Grid>
        </Box>
      )}

      {visibleWidgetCount > 0 && (
        <Grid container spacing={2.5}>
          {preferences.visibleWidgets.posture && (
            <Grid size={{ xs: 12, md: 7 }}>
              <Card variant="outlined" sx={{ height: "100%", borderRadius: 3 }}>
                <CardContent sx={{ p: 2.5, "&:last-child": { pb: 2.5 } }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={2}>
                    <Box>
                      <Typography variant="h6">Quality posture</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>Signals that help leaders decide where to focus next.</Typography>
                    </Box>
                    <Chip label={posture.label} color={posture.color} size="small" />
                  </Stack>
                  <Stack spacing={2.25} sx={{ mt: 3 }}>
                    <Box>
                      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.75 }}>
                        <Typography variant="body2">Test depth</Typography>
                        <Typography variant="body2" fontWeight={700}>{progressValue(data?.test_cases ?? 0, data?.requirements ?? 0)}%</Typography>
                      </Stack>
                      <LinearProgress variant="determinate" value={progressValue(data?.test_cases ?? 0, data?.requirements ?? 0)} sx={{ height: 7, borderRadius: 4 }} />
                      <Typography variant="caption" color="text.secondary">{data?.test_cases ?? 0} test cases across {data?.requirements ?? 0} requirements</Typography>
                    </Box>
                    <Box>
                      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.75 }}>
                        <Typography variant="body2">Automation readiness</Typography>
                        <Typography variant="body2" fontWeight={700}>{progressValue(data?.automation_candidates ?? 0, data?.test_cases ?? 0)}%</Typography>
                      </Stack>
                      <LinearProgress variant="determinate" value={progressValue(data?.automation_candidates ?? 0, data?.test_cases ?? 0)} color="secondary" sx={{ height: 7, borderRadius: 4 }} />
                      <Typography variant="caption" color="text.secondary">{data?.automation_candidates ?? 0} candidates ready for automation</Typography>
                    </Box>
                    <Box>
                      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.75 }}>
                        <Typography variant="body2">Execution confidence</Typography>
                        <Typography variant="body2" fontWeight={700}>{data?.pass_rate ?? 0}%</Typography>
                      </Stack>
                      <LinearProgress variant="determinate" value={data?.pass_rate ?? 0} color={data?.pass_rate && data.pass_rate >= 90 ? "success" : "primary"} sx={{ height: 7, borderRadius: 4 }} />
                      <Typography variant="caption" color="text.secondary">Based on completed execution results</Typography>
                    </Box>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
          )}

          {preferences.visibleWidgets.execution && (
            <Grid size={{ xs: 12, md: 5 }}>
              <Card variant="outlined" sx={{ height: "100%", borderRadius: 3 }}>
                <CardContent sx={{ p: 2.5, "&:last-child": { pb: 2.5 } }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
                    <Box>
                      <Typography variant="h6">Recent execution</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>Latest delivery confidence signals.</Typography>
                    </Box>
                    <Chip label={`${data?.execution_runs ?? 0} total`} size="small" variant="outlined" />
                  </Stack>
                  <Stack spacing={1.25}>
                    {data?.recent_runs.map((run) => <ExecutionRow key={run.id} run={run} />)}
                    {!data?.recent_runs.length && <Typography color="text.secondary" sx={{ py: 2 }}>No execution activity yet.</Typography>}
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
          )}

          {preferences.visibleWidgets.signals && (
            <Grid size={{ xs: 12 }}>
              <Card variant="outlined" sx={{ borderRadius: 3 }}>
                <CardContent sx={{ p: 2.5, "&:last-child": { pb: 2.5 } }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
                    <Box>
                      <Typography variant="h6">Management signals</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>Clear observations generated from the current project data.</Typography>
                    </Box>
                    <WarningAmberOutlinedIcon color="action" />
                  </Stack>
                  <Grid container spacing={1.5}>
                    {managementSignals.map((signal) => (
                      <Grid key={signal.title} size={{ xs: 12, md: 4 }}>
                        <Box sx={{ p: 1.75, borderRadius: 2, bgcolor: "action.hover", height: "100%" }}>
                          <Stack direction="row" spacing={1} alignItems="flex-start">
                            <Box sx={{ width: 8, height: 8, borderRadius: "50%", mt: 0.75, bgcolor: `${signal.tone}.main` }} />
                            <Box>
                              <Typography variant="body2" fontWeight={700}>{signal.title}</Typography>
                              <Typography variant="caption" color="text.secondary">{signal.detail}</Typography>
                            </Box>
                          </Stack>
                        </Box>
                      </Grid>
                    ))}
                  </Grid>
                </CardContent>
              </Card>
            </Grid>
          )}
        </Grid>
      )}

      <Dialog open={customizeOpen} onClose={() => setCustomizeOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>Customize dashboard</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={3} sx={{ pt: 0.5 }}>
            <Box>
              <Typography variant="subtitle1" fontWeight={700}>Presentation</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>Use language that fits your leadership audience.</Typography>
              <Stack spacing={1.5}>
                <TextField label="Dashboard title" value={draftPreferences.title} onChange={(event) => setDraftPreferences((current) => ({ ...current, title: event.target.value }))} fullWidth inputProps={{ maxLength: 80 }} />
                <TextField label="Executive summary" value={draftPreferences.description} onChange={(event) => setDraftPreferences((current) => ({ ...current, description: event.target.value }))} fullWidth multiline minRows={2} inputProps={{ maxLength: 180 }} />
              </Stack>
            </Box>
            <Divider />
            <Box>
              <Typography variant="subtitle1" fontWeight={700}>Visible sections</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>Hide sections that are not relevant to this review.</Typography>
              <Grid container spacing={1}>
                {widgetDefinitions.map((widget) => (
                  <Grid key={widget.key} size={{ xs: 12, sm: 6 }}>
                    <FormControlLabel
                      control={<Checkbox checked={draftPreferences.visibleWidgets[widget.key]} onChange={() => toggleWidget(widget.key)} />}
                      label={<Box><Typography variant="body2" fontWeight={700}>{widget.label}</Typography><Typography variant="caption" color="text.secondary">{widget.description}</Typography></Box>}
                      sx={{ alignItems: "flex-start", m: 0, p: 1, border: "1px solid", borderColor: "divider", borderRadius: 2, width: "100%" }}
                    />
                  </Grid>
                ))}
              </Grid>
            </Box>
            <Divider />
            <Box>
              <Typography variant="subtitle1" fontWeight={700}>Metric labels and visibility</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>Rename a KPI for your organisation or remove it from the executive view.</Typography>
              <Grid container spacing={1.5}>
                {metricDefinitions.map(({ key }) => (
                  <Grid key={key} size={{ xs: 12, sm: 6 }}>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Checkbox checked={draftPreferences.visibleMetrics[key]} onChange={() => toggleMetric(key)} inputProps={{ "aria-label": `Show ${key}` }} />
                      <TextField label={key.replaceAll("_", " ")} value={draftPreferences.metricLabels[key]} onChange={(event) => updateMetricLabel(key, event.target.value)} fullWidth size="small" disabled={!draftPreferences.visibleMetrics[key]} />
                    </Stack>
                  </Grid>
                ))}
              </Grid>
            </Box>
            <Alert severity="info">Your dashboard preferences are saved for this project in this browser. They do not change the underlying test data.</Alert>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ justifyContent: "space-between", px: 3, py: 2 }}>
          <Button startIcon={<RestoreOutlinedIcon />} onClick={restoreDefaults}>Restore defaults</Button>
          <Stack direction="row" spacing={1}>
            <Button onClick={() => setCustomizeOpen(false)}>Cancel</Button>
            <Button variant="contained" onClick={savePreferences}>Save view</Button>
          </Stack>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function ExecutionRow({ run }: { run: ExecutionRun }) {
  return (
    <Box sx={{ p: 1.5, borderRadius: 2, bgcolor: "action.hover" }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" fontWeight={700} noWrap>{run.name}</Typography>
          <Typography variant="caption" color="text.secondary">{formatDate(run.created_at)}</Typography>
        </Box>
        <Chip label={run.status} size="small" color={runColor(run.status)} />
      </Stack>
      <Stack direction="row" spacing={1.5} sx={{ mt: 1 }}>
        <Typography variant="caption" color="success.main">{run.passed_tests} passed</Typography>
        <Typography variant="caption" color={run.failed_tests ? "error.main" : "text.secondary"}>{run.failed_tests} failed</Typography>
        <Typography variant="caption" color={run.blocked_tests ? "warning.main" : "text.secondary"}>{run.blocked_tests} blocked</Typography>
      </Stack>
    </Box>
  );
}

