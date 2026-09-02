import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  IconButton,
  LinearProgress,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import AssignmentOutlinedIcon from "@mui/icons-material/AssignmentOutlined";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import ArrowForwardRoundedIcon from "@mui/icons-material/ArrowForwardRounded";
import ArchitectureOutlinedIcon from "@mui/icons-material/ArchitectureOutlined";
import AssessmentOutlinedIcon from "@mui/icons-material/AssessmentOutlined";
import BugReportOutlinedIcon from "@mui/icons-material/BugReportOutlined";
import CheckCircleOutlineOutlinedIcon from "@mui/icons-material/CheckCircleOutlineOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import HistoryOutlinedIcon from "@mui/icons-material/HistoryOutlined";
import SecurityOutlinedIcon from "@mui/icons-material/SecurityOutlined";
import TuneOutlinedIcon from "@mui/icons-material/TuneOutlined";
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import RestoreOutlinedIcon from "@mui/icons-material/RestoreOutlined";
import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import { Link as RouterLink } from "react-router-dom";
import { dashboardApi, documentIntelligenceApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import PageHeader from "@/components/PageHeader";
import type { DocumentAnalysisRun, ExecutionRun } from "@/types/domain";

type MetricKey =
  | "requirements"
  | "test_cases"
  | "execution_runs"
  | "pass_rate"
  | "open_defects"
  | "automation_candidates";

type WidgetKey = "metrics" | "posture" | "execution" | "signals" | "documentation";

interface DashboardPreferences {
  title: string;
  description: string;
  visibleMetrics: Record<MetricKey, boolean>;
  visibleWidgets: Record<WidgetKey, boolean>;
  metricLabels: Record<MetricKey, string>;
}

const DEFAULT_DASHBOARD_TITLE = "Dashboard";
const DEFAULT_DASHBOARD_DESCRIPTION = "Last run and observed test results for the selected project.";
const LEGACY_DASHBOARD_TITLE = "Quality portfolio overview";
const LEGACY_DASHBOARD_DESCRIPTION = "A concise view of delivery confidence, execution health and the decisions that need attention.";

const defaultPreferences = (): DashboardPreferences => ({
  title: DEFAULT_DASHBOARD_TITLE,
  description: DEFAULT_DASHBOARD_DESCRIPTION,
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
    documentation: true,
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
  { key: "pass_rate", helper: "passed tests across all execution results" },
  { key: "open_defects", helper: "requiring triage" },
  { key: "automation_candidates", helper: "ready for automation" },
];

const metricIcons: Record<MetricKey, ReactNode> = {
  requirements: <AssignmentOutlinedIcon />,
  test_cases: <CheckCircleOutlineOutlinedIcon />,
  execution_runs: <HistoryOutlinedIcon />,
  pass_rate: <CheckCircleOutlineOutlinedIcon />,
  open_defects: <BugReportOutlinedIcon />,
  automation_candidates: <AutoAwesomeOutlinedIcon />,
};

const metricRoutes: Record<MetricKey, string> = {
  requirements: "/documents",
  test_cases: "/design",
  execution_runs: "/execution",
  pass_rate: "/reports",
  open_defects: "/reports",
  automation_candidates: "/execution",
};

const widgetDefinitions: Array<{ key: WidgetKey; label: string; description: string }> = [
  { key: "metrics", label: "Test results", description: "The result cards at the top of the dashboard." },
  { key: "posture", label: "Coverage results", description: "Observed coverage and completion rates." },
  { key: "execution", label: "Last run", description: "The latest saved execution run and its test counts." },
  { key: "signals", label: "Action required", description: "Counts of items that need follow-up." },
  { key: "documentation", label: "Documentation quality gate", description: "Early findings from Document Intelligence before test design." },
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
      title: saved.title === LEGACY_DASHBOARD_TITLE ? fallback.title : saved.title || fallback.title,
      description: saved.description === LEGACY_DASHBOARD_DESCRIPTION ? fallback.description : saved.description || fallback.description,
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

function displayDocumentStatus(status: string) {
  return status.replace(/[_-]+/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function progressValue(numerator: number, denominator: number) {
  if (!denominator) return 0;
  return Math.min(100, Math.round((numerator / denominator) * 100));
}

interface ActionItem {
  key: string;
  count: number;
  title: string;
  detail: string;
  route: string;
}

type WorkflowState = "ready" | "active" | "pending";

interface WorkflowStage {
  key: string;
  step: string;
  title: string;
  description: string;
  to: string;
  icon: ReactNode;
  state: WorkflowState;
  stateLabel: string;
}

const workflowStateColor: Record<WorkflowState, "success" | "info" | "default"> = {
  ready: "success",
  active: "info",
  pending: "default",
};

export default function DashboardPage() {
  const { selectedProjectId } = useSelectedProject();
  const [preferences, setPreferences] = useState<DashboardPreferences>(defaultPreferences);
  const [draftPreferences, setDraftPreferences] = useState<DashboardPreferences>(defaultPreferences);
  const [customizeOpen, setCustomizeOpen] = useState(false);

  const summary = useQuery({
    queryKey: ["dashboard", selectedProjectId],
    queryFn: () => dashboardApi.summary(selectedProjectId).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
  });
  const documentReview = useQuery<DocumentAnalysisRun | null>({
    queryKey: ["document-intelligence-latest", selectedProjectId],
    queryFn: () => documentIntelligenceApi.latest(selectedProjectId).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["queued", "extracting", "analyzing"].includes(status) ? 3000 : false;
    },
  });

  useEffect(() => {
    if (!selectedProjectId) {
      setPreferences(defaultPreferences());
      return;
    }
    setPreferences(readPreferences(selectedProjectId));
  }, [selectedProjectId]);

  const data = summary.data;
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

  const actionItems = useMemo<ActionItem[]>(() => {
    if (!data) return [];
    const failedTests = data.recent_runs.reduce((total, run) => total + run.failed_tests, 0);
    const blockedTests = data.recent_runs.reduce((total, run) => total + run.blocked_tests, 0);
    const awaitingAutomation = Math.max(data.test_cases - data.automation_candidates, 0);
    const items: ActionItem[] = [];
    if (data.open_defects > 0) {
      items.push({ key: "open-defects", count: data.open_defects, title: "Open defects", detail: "Review and triage the recorded defects.", route: "/reports" });
    }
    if (failedTests > 0) {
      items.push({ key: "failed-tests", count: failedTests, title: "Failed tests", detail: "Open the results and review failed checks.", route: "/reports" });
    }
    if (blockedTests > 0) {
      items.push({ key: "blocked-tests", count: blockedTests, title: "Blocked tests", detail: "Resolve prerequisites and rerun blocked checks.", route: "/execution" });
    }
    if (awaitingAutomation > 0) {
      items.push({ key: "automation", count: awaitingAutomation, title: "Tests awaiting automation", detail: "Select cases and decide how they should run.", route: "/execution" });
    }
    if (data.execution_runs === 0) {
      items.push({ key: "first-execution", count: 1, title: "Execution run", detail: "Run the selected test cases to populate results.", route: "/execution" });
    }
    return items;
  }, [data]);
  const actionRequiredCount = actionItems.reduce((total, item) => total + item.count, 0);
  const actionCards: ActionItem[] = actionItems.length > 0 ? actionItems : [{
    key: "none",
    count: 0,
    title: "No action items recorded",
    detail: "Open reports to review the latest observed results.",
    route: "/reports",
  }];

  const workflowStages = useMemo<WorkflowStage[]>(() => {
    const documentStatus = documentReview.data?.status;
    const documentRunning = Boolean(documentStatus && ["queued", "extracting", "analyzing"].includes(documentStatus));
    const documentCompleted = documentStatus === "completed";
    const documentFailed = documentStatus === "failed";
    const executionAvailable = Boolean(data?.execution_runs);
    return [
      {
        key: "understand",
        step: "01",
        title: "Understand",
        description: "Review requirements and surface gaps before cases are designed.",
        to: "/documents",
        icon: <DescriptionOutlinedIcon />,
        state: documentRunning ? "active" : documentCompleted ? "ready" : "pending",
        stateLabel: documentRunning ? "Reviewing" : documentCompleted ? "Baseline ready" : documentFailed ? "Review needed" : "Start here",
      },
      {
        key: "design",
        step: "02",
        title: "Design",
        description: "Turn trusted context into traceable, reviewable test journeys.",
        to: "/design",
        icon: <ArchitectureOutlinedIcon />,
        state: data?.test_cases ? "ready" : documentCompleted ? "active" : "pending",
        stateLabel: data?.test_cases ? `${data.test_cases} cases` : documentCompleted ? "Ready to generate" : "After review",
      },
      {
        key: "execute",
        step: "03",
        title: "Autopilot",
        description: "Explore web, Android and iOS targets with safe, evidence-led execution.",
        to: "/autopilot",
        icon: <AutoAwesomeOutlinedIcon />,
        state: executionAvailable ? "ready" : data?.test_cases ? "active" : "pending",
        stateLabel: executionAvailable ? "Run available" : data?.test_cases ? "Ready to run" : "After design",
      },
      {
        key: "evidence",
        step: "04",
        title: "Evidence",
        description: "Inspect outcomes, defects and release readiness in one report trail.",
        to: "/reports",
        icon: <AssessmentOutlinedIcon />,
        state: executionAvailable ? "ready" : "pending",
        stateLabel: executionAvailable ? "Evidence available" : "After execution",
      },
    ];
  }, [data, documentReview.data?.status]);

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
        eyebrow="TEST RESULTS"
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

      {summary.isLoading && <LinearProgress sx={{ mb: 2 }} />}
      {summary.isError && <Alert severity="warning" sx={{ mb: 2 }}>Dashboard data is temporarily unavailable. Try refreshing the view.</Alert>}

      <Card
        variant="outlined"
        sx={{
          mb: 3,
          overflow: "hidden",
          borderRadius: 4,
          borderColor: "rgba(14, 124, 119, .28)",
          background: (theme) => theme.palette.mode === "dark"
            ? "linear-gradient(135deg, rgba(18, 199, 192, .12), rgba(17, 30, 46, .82) 58%, rgba(232, 160, 61, .06))"
            : "linear-gradient(135deg, rgba(14, 124, 119, .10), rgba(255, 255, 255, .86) 58%, rgba(232, 160, 61, .08))",
        }}
      >
        <CardContent sx={{ p: { xs: 2.25, md: 3 }, "&:last-child": { pb: { xs: 2.25, md: 3 } } }}>
          <Grid container spacing={{ xs: 2.5, md: 4 }} alignItems="center">
            <Grid size={{ xs: 12, md: 7 }}>
              <Stack spacing={1.25}>
                <Chip size="small" label="AUTONOMOUS QUALITY LOOP" color="primary" variant="outlined" sx={{ alignSelf: "flex-start", fontWeight: 800, letterSpacing: ".06em" }} />
                <Typography variant="h4" sx={{ fontWeight: 800, letterSpacing: "-.02em" }}>From product intent to release evidence.</Typography>
                <Typography color="text.secondary" sx={{ maxWidth: 680 }}>
                  QTXpert brings documentation, test design, safe exploration, execution and reporting into one traceable path. AI proposes the next best check; deterministic engines and human approvals keep the evidence trustworthy.
                </Typography>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ pt: .5 }}>
                  <Button component={RouterLink} to="/autopilot" variant="contained" endIcon={<ArrowForwardRoundedIcon />}>Open Autopilot</Button>
                  <Button component={RouterLink} to="/documents" variant="outlined">Review documents</Button>
                </Stack>
              </Stack>
            </Grid>
            <Grid size={{ xs: 12, md: 5 }}>
              <Paper
                variant="outlined"
                sx={{
                  p: 2,
                  borderRadius: 3,
                  backgroundColor: (theme) => theme.palette.mode === "dark" ? "rgba(7, 18, 29, .46)" : "rgba(255, 255, 255, .64)",
                  backdropFilter: "blur(14px)",
                  WebkitBackdropFilter: "blur(14px)",
                }}
              >
                <Stack direction="row" spacing={1} alignItems="center">
                  <SecurityOutlinedIcon color="primary" fontSize="small" />
                  <Typography variant="subtitle2" fontWeight={800}>Operating model</Typography>
                </Stack>
                <Typography variant="body2" sx={{ mt: 1 }}>AI plans · engines execute · people approve risk</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: .75 }}>
                  One report lineage across every target and build.
                </Typography>
                <Stack direction="row" spacing={.75} useFlexGap flexWrap="wrap" sx={{ mt: 1.5 }}>
                  {["Web", "Android", "iOS"].map((target) => <Chip key={target} size="small" label={target} variant="outlined" />)}
                </Stack>
              </Paper>
            </Grid>
          </Grid>

          <Divider sx={{ my: { xs: 2.25, md: 2.75 } }} />
          <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} spacing={.5} sx={{ mb: 1.5 }}>
            <Box>
              <Typography variant="subtitle1" fontWeight={800}>Quality loop</Typography>
              <Typography variant="body2" color="text.secondary">Follow the evidence from source to release.</Typography>
            </Box>
            <Typography variant="caption" color="text.secondary">Select a stage to continue</Typography>
          </Stack>
          <Grid container spacing={1.25}>
            {workflowStages.map((stage) => (
              <Grid key={stage.key} size={{ xs: 12, sm: 6, lg: 3 }}>
                <CardActionArea
                  component={RouterLink}
                  to={stage.to}
                  aria-label={`Open ${stage.title}`}
                  sx={{
                    height: "100%",
                    p: 1.5,
                    border: "1px solid",
                    borderColor: "divider",
                    borderRadius: 2.5,
                    bgcolor: "background.paper",
                    transition: "transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease",
                    "&:hover": { transform: "translateY(-2px)", borderColor: "primary.main", boxShadow: 2 },
                  }}
                >
                  <Stack direction="row" spacing={1.1} alignItems="flex-start">
                    <Box sx={{ display: "grid", placeItems: "center", width: 34, height: 34, borderRadius: 2, bgcolor: "action.hover", color: "primary.main", flexShrink: 0 }}>{stage.icon}</Box>
                    <Box sx={{ minWidth: 0 }}>
                      <Stack direction="row" spacing={.75} alignItems="center" justifyContent="space-between">
                        <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace", fontWeight: 700 }}>{stage.step}</Typography>
                        <Chip size="small" label={stage.stateLabel} color={workflowStateColor[stage.state]} variant="outlined" sx={{ height: 22, maxWidth: "100%", "& .MuiChip-label": { overflow: "hidden", textOverflow: "ellipsis" } }} />
                      </Stack>
                      <Typography variant="body2" fontWeight={800} sx={{ mt: .5 }}>{stage.title}</Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: .35, lineHeight: 1.45 }}>{stage.description}</Typography>
                    </Box>
                  </Stack>
                </CardActionArea>
              </Grid>
            ))}
          </Grid>
        </CardContent>
      </Card>

      {preferences.visibleWidgets.metrics && visibleMetricDefinitions.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
            <Box>
              <Typography variant="overline" color="primary.main" sx={{ fontWeight: 700, letterSpacing: ".12em" }}>TEST RESULTS</Typography>
              <Typography variant="h6">Test results</Typography>
            </Box>
            <Typography variant="caption" color="text.secondary">{visibleMetricDefinitions.length} of {metricDefinitions.length} metrics shown</Typography>
          </Stack>
          <Grid container spacing={2}>
            {visibleMetricDefinitions.map(({ key, helper }) => {
              const value = metricValues[key];
              const tone = key === "open_defects" && Number(value) > 0 ? "error.main" : key === "pass_rate" ? "success.main" : "primary.main";
              const metricHelper = key === "pass_rate" && data
                ? `${data.passed_tests} passed · ${data.executed_tests} executed of ${data.total_execution_tests} total tests`
                : helper;
              return (
                <Grid key={key} size={{ xs: 12, sm: 6, lg: 4 }}>
                  <Card variant="outlined" sx={{ height: "100%", borderRadius: 3, transition: "transform .2s ease, box-shadow .2s ease", "&:hover": { transform: "translateY(-2px)", boxShadow: 3 } }}>
                    <CardActionArea component={RouterLink} to={metricRoutes[key]} aria-label={`Open ${preferences.metricLabels[key]}`} sx={{ height: "100%", alignItems: "stretch" }}>
                      <CardContent sx={{ p: 2.25, "&:last-child": { pb: 2.25 } }}>
                        <Stack direction="row" alignItems="flex-start" justifyContent="space-between" spacing={2}>
                          <Box>
                            <Typography variant="body2" color="text.secondary">{preferences.metricLabels[key]}</Typography>
                            <Typography variant="h3" sx={{ mt: 0.75, color: tone }}>{value}</Typography>
                          </Box>
                          <Box sx={{ p: 1, borderRadius: 2, bgcolor: "action.hover", color: tone, display: "flex" }}>{metricIcons[key]}</Box>
                        </Stack>
                        <Typography variant="caption" color="text.secondary">{metricHelper}</Typography>
                        {key === "pass_rate" && <LinearProgress variant="determinate" value={Number(data?.pass_rate ?? 0)} color={data?.pass_rate && data.pass_rate >= 90 ? "success" : "primary"} sx={{ mt: 1.25, height: 5, borderRadius: 4 }} />}
                      </CardContent>
                    </CardActionArea>
                  </Card>
                </Grid>
              );
            })}
          </Grid>
        </Box>
      )}

      {visibleWidgetCount > 0 && (
        <Grid container spacing={2.5}>
          {preferences.visibleWidgets.documentation && (
            <Grid size={{ xs: 12 }}>
              <Card variant="outlined" sx={{ borderRadius: 3 }}>
                <CardActionArea component={RouterLink} to="/documents" aria-label="Open Document Intelligence quality gate" sx={{ alignItems: "stretch" }}>
                  <CardContent sx={{ p: 2.25, "&:last-child": { pb: 2.25 } }}>
                    <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} spacing={1.5}>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography variant="h6">Documentation quality gate</Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.35 }}>
                          Document Intelligence surfaces missing requirements, ambiguity and control gaps before cases are designed.
                        </Typography>
                      </Box>
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Chip
                          size="small"
                          color={documentReview.data?.status === "completed" ? "success" : documentReview.data?.status === "failed" ? "error" : "info"}
                          variant="outlined"
                          label={documentReview.isLoading ? "Loading" : documentReview.data ? documentReview.data.status === "completed" ? `${Math.round(documentReview.data.readiness_score)}% ready` : displayDocumentStatus(documentReview.data.status) : "Not reviewed"}
                        />
                        {documentReview.data?.status === "completed" && <Chip size="small" variant="outlined" label={`${documentReview.data.findings.filter((finding) => !["resolved", "rejected"].includes(finding.status)).length} open findings`} />}
                      </Stack>
                    </Stack>
                    <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
                      {documentReview.data?.status === "completed"
                        ? `Last review: ${formatDate(documentReview.data.updated_at)} · findings remain static evidence until runtime execution confirms behaviour.`
                        : documentReview.data?.status === "failed"
                          ? documentReview.data.error_message || "Open Document Intelligence to retry the review."
                          : "Run a documentation review to establish the evidence baseline for Test Design and Autopilot."}
                    </Typography>
                  </CardContent>
                </CardActionArea>
              </Card>
            </Grid>
          )}
          {preferences.visibleWidgets.posture && (
            <Grid size={{ xs: 12, md: 7 }}>
              <Card variant="outlined" sx={{ height: "100%", borderRadius: 3 }}>
                <CardContent sx={{ p: 2.5, "&:last-child": { pb: 2.5 } }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={2}>
                    <Box>
                      <Typography variant="h6">Coverage results</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>Observed coverage and completion rates from the project data.</Typography>
                    </Box>
                  </Stack>
                  <Stack spacing={2.25} sx={{ mt: 3 }}>
                    <Box component={RouterLink} to="/design" aria-label="Open test design coverage" sx={{ display: "block", color: "inherit", textDecoration: "none", p: 1, mx: -1, borderRadius: 2, "&:hover": { bgcolor: "action.hover" } }}>
                      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.75 }}>
                        <Typography variant="body2">Test depth</Typography>
                        <Typography variant="body2" fontWeight={700}>{progressValue(data?.test_cases ?? 0, data?.requirements ?? 0)}%</Typography>
                      </Stack>
                      <LinearProgress variant="determinate" value={progressValue(data?.test_cases ?? 0, data?.requirements ?? 0)} sx={{ height: 7, borderRadius: 4 }} />
                      <Typography variant="caption" color="text.secondary">{data?.test_cases ?? 0} test cases across {data?.requirements ?? 0} requirements</Typography>
                    </Box>
                    <Box component={RouterLink} to="/execution" aria-label="Open automation coverage" sx={{ display: "block", color: "inherit", textDecoration: "none", p: 1, mx: -1, borderRadius: 2, "&:hover": { bgcolor: "action.hover" } }}>
                      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.75 }}>
                        <Typography variant="body2">Automation coverage</Typography>
                        <Typography variant="body2" fontWeight={700}>{progressValue(data?.automation_candidates ?? 0, data?.test_cases ?? 0)}%</Typography>
                      </Stack>
                      <LinearProgress variant="determinate" value={progressValue(data?.automation_candidates ?? 0, data?.test_cases ?? 0)} color="secondary" sx={{ height: 7, borderRadius: 4 }} />
                      <Typography variant="caption" color="text.secondary">{data?.automation_candidates ?? 0} candidates ready for automation</Typography>
                    </Box>
                    <Box component={RouterLink} to="/reports" aria-label="Open observed pass rate" sx={{ display: "block", color: "inherit", textDecoration: "none", p: 1, mx: -1, borderRadius: 2, "&:hover": { bgcolor: "action.hover" } }}>
                      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.75 }}>
                        <Typography variant="body2">Observed pass rate</Typography>
                        <Typography variant="body2" fontWeight={700}>{data?.pass_rate ?? 0}%</Typography>
                      </Stack>
                      <LinearProgress variant="determinate" value={data?.pass_rate ?? 0} color={data?.pass_rate && data.pass_rate >= 90 ? "success" : "primary"} sx={{ height: 7, borderRadius: 4 }} />
                      <Typography variant="caption" color="text.secondary">{data?.passed_tests ?? 0} passed · {data?.executed_tests ?? 0} executed of {data?.total_execution_tests ?? 0} total tests</Typography>
                    </Box>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
          )}

          {preferences.visibleWidgets.execution && (
            <Grid size={{ xs: 12, md: 5 }}>
              <Card variant="outlined" sx={{ height: "100%", borderRadius: 3 }}>
                <CardActionArea component={RouterLink} to="/execution" aria-label="Open last execution results" sx={{ height: "100%", alignItems: "stretch" }}>
                  <CardContent sx={{ p: 2.5, "&:last-child": { pb: 2.5 } }}>
                    <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
                      <Box>
                        <Typography variant="h6">Last run</Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>Latest saved execution and test counts.</Typography>
                        <Typography variant="caption" color="text.secondary">Last run: {formatDate(data?.recent_runs[0]?.created_at)}</Typography>
                      </Box>
                      <Chip label={`${data?.execution_runs ?? 0} total`} size="small" variant="outlined" />
                    </Stack>
                    <Stack spacing={1.25}>
                      {data?.recent_runs.map((run) => <ExecutionRow key={run.id} run={run} />)}
                      {!data?.recent_runs.length && <Typography color="text.secondary" sx={{ py: 2 }}>No execution activity yet.</Typography>}
                    </Stack>
                  </CardContent>
                </CardActionArea>
              </Card>
            </Grid>
          )}

          {preferences.visibleWidgets.signals && (
            <Grid size={{ xs: 12 }}>
              <Card variant="outlined" sx={{ borderRadius: 3 }}>
                <CardContent sx={{ p: 2.5, "&:last-child": { pb: 2.5 } }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
                    <Box>
                      <Typography variant="h6">Action required</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>Counts of items that need follow-up from the observed project data.</Typography>
                    </Box>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Chip component={RouterLink} to="/reports" clickable aria-label={`Open all ${actionRequiredCount} action items`} label={`${actionRequiredCount} total`} size="small" variant="outlined" />
                      <WarningAmberOutlinedIcon color="action" />
                    </Stack>
                  </Stack>
                  <Grid container spacing={1.5}>
                    {actionCards.map((item) => (
                      <Grid key={item.key} size={{ xs: 12, sm: 6, md: 4 }}>
                        <Card variant="outlined" sx={{ height: "100%", borderRadius: 2 }}>
                          <CardActionArea component={RouterLink} to={item.route} aria-label={`Open ${item.title}: ${item.count}`} sx={{ height: "100%", alignItems: "stretch" }}>
                            <CardContent sx={{ p: 1.75, "&:last-child": { pb: 1.75 } }}>
                              <Typography variant="h4" color={item.count > 0 ? "primary.main" : "text.secondary"}>{item.count}</Typography>
                              <Typography variant="body2" fontWeight={700} sx={{ mt: 0.5 }}>{item.title}</Typography>
                              <Typography variant="caption" color="text.secondary">{item.detail}</Typography>
                            </CardContent>
                          </CardActionArea>
                        </Card>
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
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>Use a short, neutral label for this dashboard.</Typography>
              <Stack spacing={1.5}>
                <TextField label="Dashboard title" value={draftPreferences.title} onChange={(event) => setDraftPreferences((current) => ({ ...current, title: event.target.value }))} fullWidth inputProps={{ maxLength: 80 }} />
                <TextField label="Dashboard description" value={draftPreferences.description} onChange={(event) => setDraftPreferences((current) => ({ ...current, description: event.target.value }))} fullWidth multiline minRows={2} inputProps={{ maxLength: 180 }} />
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

