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
  Skeleton,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import ArchitectureOutlinedIcon from "@mui/icons-material/ArchitectureOutlined";
import AssessmentOutlinedIcon from "@mui/icons-material/AssessmentOutlined";
import CheckCircleOutlineOutlinedIcon from "@mui/icons-material/CheckCircleOutlineOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import HistoryOutlinedIcon from "@mui/icons-material/HistoryOutlined";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import SecurityOutlinedIcon from "@mui/icons-material/SecurityOutlined";
import TuneOutlinedIcon from "@mui/icons-material/TuneOutlined";
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import RestoreOutlinedIcon from "@mui/icons-material/RestoreOutlined";
import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import AddRoundedIcon from "@mui/icons-material/AddRounded";
import ArrowForwardRoundedIcon from "@mui/icons-material/ArrowForwardRounded";
import { Link as RouterLink } from "react-router-dom";
import { dashboardApi, documentIntelligenceApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import { useAuth } from "@/contexts/AuthContext";
import { PROJECT_CREATE_EVENT } from "@/components/ProjectSelector";
import type { AutopilotDashboardSummary, DocumentAnalysisRun, ExecutionRun } from "@/types/domain";
import { qtxpertColors, qtxpertEffects } from "@/theme/theme";

type MetricKey =
  | "active_work"
  | "test_cases"
  | "attention_areas"
  | "pass_rate";

type WidgetKey = "metrics" | "posture" | "execution" | "signals" | "documentation" | "autopilot";

interface DashboardPreferences {
  title: string;
  description: string;
  visibleMetrics: Record<MetricKey, boolean>;
  visibleWidgets: Record<WidgetKey, boolean>;
  metricLabels: Record<MetricKey, string>;
}

const DEFAULT_DASHBOARD_TITLE = "Dashboard";
const DEFAULT_DASHBOARD_DESCRIPTION = "Project health and latest test evidence.";
const LEGACY_DASHBOARD_TITLE = "Quality portfolio overview";
const LEGACY_DASHBOARD_DESCRIPTION = "A concise view of delivery confidence, execution health and the decisions that need attention.";

const defaultPreferences = (): DashboardPreferences => ({
  title: DEFAULT_DASHBOARD_TITLE,
  description: DEFAULT_DASHBOARD_DESCRIPTION,
  visibleMetrics: {
    active_work: true,
    test_cases: true,
    attention_areas: true,
    pass_rate: true,
  },
  visibleWidgets: {
    metrics: true,
    posture: true,
    execution: true,
    signals: true,
    documentation: true,
    autopilot: true,
  },
  metricLabels: {
    active_work: "In progress",
    test_cases: "Test cases",
    attention_areas: "Open defects",
    pass_rate: "Pass rate",
  },
});

const metricDefinitions: Array<{ key: MetricKey; helper: string }> = [
  { key: "active_work", helper: "execution runs and Autopilot analyses currently in progress" },
  { key: "test_cases", helper: "test cases saved for the selected project" },
  { key: "attention_areas", helper: "unresolved defects recorded for the selected project" },
  { key: "pass_rate", helper: "observed pass rate for recorded execution results; not a coverage measure" },
];

const metricIcons: Record<MetricKey, ReactNode> = {
  active_work: <HistoryOutlinedIcon />,
  test_cases: <CheckCircleOutlineOutlinedIcon />,
  attention_areas: <WarningAmberOutlinedIcon />,
  pass_rate: <CheckCircleOutlineOutlinedIcon />,
};

const metricRoutes: Record<MetricKey, string> = {
  active_work: "/execution",
  test_cases: "/design",
  attention_areas: "/reports",
  pass_rate: "/reports",
};

const widgetDefinitions: Array<{ key: WidgetKey; label: string; description: string }> = [
  { key: "metrics", label: "Test results", description: "The result cards at the top of the dashboard." },
  { key: "posture", label: "Coverage results", description: "Observed coverage and completion rates." },
  { key: "execution", label: "Last run", description: "The latest saved execution run and its test counts." },
  { key: "signals", label: "Action required", description: "Counts of items that need follow-up." },
  { key: "documentation", label: "Documentation quality gate", description: "Early findings from Document Intelligence before test design." },
  { key: "autopilot", label: "Autopilot activity", description: "Generated cases, safe-suite execution and evidence for this project." },
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
      metricLabels: {
        ...fallback.metricLabels,
        ...(saved.metricLabels || {}),
        active_work: saved.metricLabels?.active_work === "Active work" ? fallback.metricLabels.active_work : saved.metricLabels?.active_work || fallback.metricLabels.active_work,
        attention_areas: saved.metricLabels?.attention_areas === "Attention areas" ? fallback.metricLabels.attention_areas : saved.metricLabels?.attention_areas || fallback.metricLabels.attention_areas,
      },
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

export default function DashboardPage() {
  const { selectedProjectId, selectedProject } = useSelectedProject();
  const { user } = useAuth();
  const [preferences, setPreferences] = useState<DashboardPreferences>(defaultPreferences);
  const [draftPreferences, setDraftPreferences] = useState<DashboardPreferences>(defaultPreferences);
  const [customizeOpen, setCustomizeOpen] = useState(false);

  const summary = useQuery({
    queryKey: ["dashboard", selectedProjectId],
    queryFn: () => dashboardApi.summary(selectedProjectId).then((response) => response.data),
    // Wait for the project list to confirm the selection. This prevents a
    // stale localStorage id from producing a 404 that looks like a dashboard
    // outage while the current account has no matching project.
    enabled: Boolean(selectedProjectId && selectedProject),
    // Keep the dashboard as a stable snapshot. React Query refreshes this
    // query when the browser tab regains focus, or the user clicks Refresh.
    refetchInterval: false,
    refetchOnWindowFocus: true,
  });
  const documentReview = useQuery<DocumentAnalysisRun | null>({
    queryKey: ["document-intelligence-latest", selectedProjectId],
    queryFn: () => documentIntelligenceApi.latest(selectedProjectId).then((response) => response.data),
    enabled: Boolean(selectedProjectId && selectedProject),
    refetchInterval: false,
    refetchOnWindowFocus: true,
  });

  useEffect(() => {
    if (!selectedProjectId) {
      setPreferences(defaultPreferences());
      return;
    }
    setPreferences(readPreferences(selectedProjectId));
  }, [selectedProjectId]);

  // Do not render cached metrics while a refresh is in flight or has failed.
  // Showing the previous project snapshot during that window makes stale
  // results look current; cards repopulate from the confirmed project response.
  const data = summary.isFetching || summary.isError ? undefined : summary.data;
  const documentReviewData = documentReview.isFetching || documentReview.isError
    ? null
    : documentReview.data;
  const autopilotActivity = useMemo<AutopilotDashboardSummary>(() => data?.autopilot ?? {
    report_tabs: 0,
    active_jobs: 0,
    waiting_for_input_jobs: 0,
    generated_test_cases: 0,
    suite_runs: 0,
    smoke_runs: 0,
    selected_tests: 0,
    executed_tests: 0,
    passed_tests: 0,
    failed_tests: 0,
    blocked_tests: 0,
    deferred_tests: 0,
    skipped_tests: 0,
    last_run_at: null,
  }, [data?.autopilot]);
  const visibleMetricDefinitions = metricDefinitions.filter(({ key }) => preferences.visibleMetrics[key]);
  const visibleWidgetCount = Object.values(preferences.visibleWidgets).filter(Boolean).length;

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
    if (autopilotActivity.waiting_for_input_jobs > 0) {
      items.push({ key: "autopilot-inputs", count: autopilotActivity.waiting_for_input_jobs, title: "Autopilot inputs awaiting review", detail: "Review the checkpoint inputs before dependent checks continue.", route: "/autopilot" });
    }
    if (autopilotActivity.deferred_tests > 0) {
      items.push({ key: "autopilot-deferred", count: autopilotActivity.deferred_tests, title: "Autopilot checks awaiting setup", detail: "Open Autopilot to resolve discovery, data or approval dependencies.", route: "/autopilot" });
    }
    if (data.execution_runs === 0) {
      items.push({ key: "first-execution", count: 1, title: "Execution run", detail: "Run the selected test cases to populate results.", route: "/execution" });
    }
    return items;
  }, [autopilotActivity.deferred_tests, autopilotActivity.waiting_for_input_jobs, data]);
  const activeWorkCount = (data?.recent_runs.filter((run) => run.status === "running").length ?? 0) + autopilotActivity.active_jobs;
  const actionRequiredCount = actionItems.length;
  const metricValues = useMemo<Record<MetricKey, number | string>>(() => ({
    active_work: data ? activeWorkCount : "—",
    test_cases: data?.test_cases ?? "—",
    attention_areas: data?.open_defects ?? "—",
    pass_rate: data?.total_execution_tests ? `${data.pass_rate}%` : "—",
  }), [activeWorkCount, data]);
  const autopilotExecutionProgress = autopilotActivity.selected_tests > 0
    ? progressValue(autopilotActivity.executed_tests, autopilotActivity.selected_tests)
    : null;
  const latestRun = data?.recent_runs[0];
  const latestEvidenceAt = [autopilotActivity.last_run_at, latestRun?.created_at]
    .filter((value): value is string => Boolean(value))
    .reduce<string | null>((latest, value) => !latest || Date.parse(value) > Date.parse(latest) ? value : latest, null);
  const autopilotStages = useMemo<WorkflowStage[]>(() => {
    const generated = autopilotActivity.generated_test_cases;
    const selected = autopilotActivity.selected_tests;
    const executed = autopilotActivity.executed_tests;
    const reportCount = autopilotActivity.report_tabs;
    return [
      {
        key: "analyze",
        step: "01",
        title: "Analyze",
        description: "Inspect the selected target and saved scope.",
        to: "/autopilot",
        icon: <AutoAwesomeOutlinedIcon />,
        state: autopilotActivity.active_jobs > 0 ? "active" : reportCount > 0 || generated > 0 ? "ready" : "pending",
        stateLabel: autopilotActivity.active_jobs > 0 ? "Running" : reportCount > 0 || generated > 0 ? "Available" : "Start here",
      },
      {
        key: "plan",
        step: "02",
        title: "Plan",
        description: "Turn observed and supplied scope into reviewable journeys.",
        to: "/autopilot",
        icon: <DescriptionOutlinedIcon />,
        state: generated > 0 ? "ready" : "pending",
        stateLabel: generated > 0 ? "Created" : "Pending",
      },
      {
        key: "generate",
        step: "03",
        title: "Generate",
        description: "Create test cases from the available target evidence.",
        to: "/autopilot",
        icon: <ArchitectureOutlinedIcon />,
        state: generated > 0 ? "ready" : "pending",
        stateLabel: generated > 0 ? `${generated} cases` : "Pending",
      },
      {
        key: "execute",
        step: "04",
        title: "Execute",
        description: "Run selected checks in the approved execution mode.",
        to: "/execution",
        icon: <PlayArrowRoundedIcon />,
        state: executed > 0 ? "ready" : "pending",
        stateLabel: executed > 0 ? `${executed} executed` : selected > 0 ? `${selected} selected` : "Not run",
      },
      {
        key: "validate",
        step: "05",
        title: "Validate",
        description: "Review observed outcomes, failures and deferred checks.",
        to: "/reports",
        icon: <CheckCircleOutlineOutlinedIcon />,
        state: executed > 0 ? "ready" : "pending",
        stateLabel: executed > 0 ? "Results to review" : "Pending",
      },
      {
        key: "report",
        step: "06",
        title: "Report",
        description: "Open the saved report tabs for this project.",
        to: "/reports",
        icon: <AssessmentOutlinedIcon />,
        state: reportCount > 0 ? "ready" : "pending",
        stateLabel: reportCount > 0 ? `${reportCount} reports` : "Pending",
      },
    ];
  }, [autopilotActivity]);

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

  const openNewProject = () => window.dispatchEvent(new Event(PROJECT_CREATE_EVENT));

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

  const greeting = new Date().getHours() < 12 ? "morning" : new Date().getHours() < 18 ? "afternoon" : "evening";
  const firstName = user?.full_name.trim().split(/\s+/)[0] || "there";
  const passRate = data?.total_execution_tests ? Math.max(0, Math.min(100, Number(data.pass_rate))) : null;
  const automationReady = data?.test_cases ? progressValue(data.automation_candidates, data.test_cases) : null;

  return (
    <Box
      className="qtxpert-dashboard"
      sx={{
        position: "relative",
        isolation: "isolate",
        pb: 2.5,
        "&::before": {
          content: "\"\"",
          position: "absolute",
          zIndex: -1,
          top: -24,
          left: -30,
          right: -30,
          height: 420,
          pointerEvents: "none",
          background: (theme) => theme.palette.mode === "dark"
            ? "radial-gradient(ellipse at 12% 8%, rgba(167,139,250,.12), transparent 42%), radial-gradient(ellipse at 88% 12%, rgba(196,181,253,.08), transparent 40%)"
            : qtxpertEffects.atmosphere,
        },
        "& .dashboard-glass": {
          borderColor: (theme) => theme.palette.mode === "dark" ? "rgba(255,255,255,.14)" : qtxpertEffects.glassBorder,
          background: (theme) => theme.palette.mode === "dark"
            ? "rgba(48,45,58,.82)"
            : qtxpertEffects.glassBackground,
          backdropFilter: "blur(28px) saturate(155%)",
          WebkitBackdropFilter: "blur(28px) saturate(155%)",
          boxShadow: (theme) => theme.palette.mode === "dark"
            ? "0 8px 24px rgba(0,0,0,.18)"
            : qtxpertEffects.glassShadow,
        },
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1} sx={{ mb: 1.1 }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="overline" color="primary.main" sx={{ fontWeight: 800, letterSpacing: ".14em", lineHeight: 1.4 }}>
            {preferences.title} · {selectedProject?.name || "Selected project"}
          </Typography>
          <Typography variant="body2" color="text.secondary" noWrap>{preferences.description}</Typography>
        </Box>
        <Stack direction="row" spacing={0.45} alignItems="center" flexShrink={0}>
          <Tooltip title="Refresh dashboard and document status">
            <span>
              <IconButton
                onClick={() => { void summary.refetch(); void documentReview.refetch(); }}
                disabled={summary.isFetching || documentReview.isFetching}
                aria-label="Refresh dashboard"
                size="small"
                sx={{ border: "1px solid", borderColor: "divider", bgcolor: "background.paper" }}
              >
                <RefreshOutlinedIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Customize dashboard">
            <IconButton onClick={openCustomize} aria-label="Customize dashboard" size="small" sx={{ border: "1px solid", borderColor: "divider", bgcolor: "background.paper" }}>
              <TuneOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      </Stack>

      {summary.isFetching && <LinearProgress sx={{ mb: 1, height: 3, borderRadius: 9, bgcolor: qtxpertColors.lightLavender }} />}
      {summary.isError && <Alert severity="warning" sx={{ mb: 1 }}>Dashboard data is temporarily unavailable. Refresh to try again.</Alert>}

      <Paper
        component="section"
        className="dashboard-glass"
        aria-labelledby="dashboard-welcome"
        sx={{
          mb: 1.2,
          p: { xs: 1.4, sm: 1.8, lg: 2.2 },
          position: "relative",
          overflow: "hidden",
          borderRadius: { xs: 3, md: 4 },
          border: "1px solid",
          borderColor: (theme) => theme.palette.mode === "dark" ? "rgba(255,255,255,.18)" : qtxpertEffects.glassBorder,
          background: (theme) => theme.palette.mode === "dark"
            ? "linear-gradient(110deg, rgba(48,45,58,.92), rgba(63,55,79,.88) 58%, rgba(48,52,63,.88))"
            : qtxpertEffects.heroGradient,
          backdropFilter: "blur(28px) saturate(155%)",
          WebkitBackdropFilter: "blur(28px) saturate(155%)",
          boxShadow: (theme) => theme.palette.mode === "dark"
            ? "0 12px 32px rgba(0,0,0,.20)"
            : qtxpertEffects.glassShadow,
        }}
      >
        <Box aria-hidden="true" sx={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden" }}>
          <Box
            component="img"
            src="/dashboard-cityscape.svg"
            alt=""
            sx={{
              position: "absolute",
              left: { xs: "-12%", md: "18%" },
              bottom: -2,
              width: { xs: "124%", md: "69%" },
              height: { xs: 90, md: 162 },
              objectFit: "fill",
              opacity: { xs: 0.18, md: 0.38 },
              maskImage: "linear-gradient(90deg, transparent 0%, black 20%, black 80%, transparent 100%)",
            }}
          />
          <Box sx={{ position: "absolute", width: 360, height: 360, borderRadius: "50%", right: { xs: -130, md: 96 }, top: -220, background: "radial-gradient(circle at 42% 38%, rgba(255,255,255,.86), rgba(237,229,255,.36) 34%, rgba(167,139,250,.20) 54%, transparent 74%)", filter: "blur(2px)" }} />
        </Box>

        <Grid container spacing={1} alignItems="center" sx={{ position: "relative", zIndex: 1 }}>
          <Grid size={{ xs: 12, md: 7 }}>
            <Stack spacing={0.85} sx={{ maxWidth: 660 }}>
              <Chip size="small" icon={<AutoAwesomeOutlinedIcon />} label="AUTONOMOUS QUALITY LOOP" variant="outlined" color="primary" sx={{ alignSelf: "flex-start", bgcolor: "rgba(255,255,255,.76)", fontWeight: 800, letterSpacing: ".04em" }} />
              <Typography id="dashboard-welcome" component="h1" variant="h3" sx={{ fontSize: { xs: "1.65rem", md: "2rem", xl: "2.25rem" }, fontWeight: 800, letterSpacing: "-.045em" }}>
                Good {greeting}, {firstName} <AutoAwesomeOutlinedIcon aria-hidden="true" sx={{ fontSize: ".75em", verticalAlign: "middle", color: "primary.main" }} />
              </Typography>
              <Typography variant="body1" color="text.secondary" sx={{ maxWidth: 580 }}>
                Your project health, test progress and latest evidence—at a glance.
              </Typography>
              <Stack direction="row" spacing={0.8} useFlexGap flexWrap="wrap" sx={{ pt: 0.25 }}>
                <Button component={RouterLink} to="/autopilot" variant="contained" startIcon={<PlayArrowRoundedIcon />} endIcon={<ArrowForwardRoundedIcon />}>
                  Start Autopilot
                </Button>
                <Button variant="outlined" startIcon={<AddRoundedIcon />} onClick={openNewProject} sx={{ bgcolor: qtxpertColors.softLilac }}>
                  New project
                </Button>
              </Stack>
            </Stack>
          </Grid>
          <Grid size={{ xs: 12, md: 5 }}>
            <Box sx={{ minHeight: { xs: 76, md: 138 }, position: "relative", display: "flex", alignItems: "center", justifyContent: { xs: "flex-start", md: "flex-end" } }}>
              <Box aria-hidden="true" sx={{ position: "absolute", right: { xs: "auto", md: 138 }, left: { xs: 0, md: "auto" }, top: "50%", transform: "translateY(-50%)", width: { xs: 90, md: 136 }, height: { xs: 90, md: 136 }, borderRadius: "50%", border: `1px solid ${qtxpertEffects.glassBorder}`, boxShadow: "inset 0 2px 10px rgba(255,255,255,.94), inset -10px -14px 24px rgba(117,70,232,.10), 0 0 0 10px rgba(255,255,255,.28), 0 0 0 24px rgba(167,139,250,.16), 0 18px 42px rgba(117,70,232,.16)", background: "radial-gradient(circle at 28% 22%, rgba(255,255,255,.98) 0%, rgba(255,255,255,.66) 10%, transparent 28%), radial-gradient(circle at 35% 30%, rgba(255,255,255,.90), rgba(196,181,253,.56) 46%, rgba(167,139,250,.42) 70%, rgba(255,255,255,.20))", backdropFilter: "blur(20px) saturate(175%)", WebkitBackdropFilter: "blur(20px) saturate(175%)", display: "grid", placeItems: "center" }}>
                <Box sx={{ width: { xs: 52, md: 74 }, height: { xs: 52, md: 74 }, display: "grid", placeItems: "center", borderRadius: "50%", border: `1px solid ${qtxpertEffects.glassBorder}`, color: "primary.main", bgcolor: qtxpertEffects.glassBackground, boxShadow: "inset 0 2px 8px rgba(255,255,255,.92), 0 8px 20px rgba(117,70,232,.14)" }}>
                  <AutoAwesomeOutlinedIcon sx={{ fontSize: { xs: 28, md: 40 } }} />
                </Box>
              </Box>
              <Paper className="dashboard-glass" variant="outlined" sx={{ position: "relative", zIndex: 1, mr: { md: 0.5 }, ml: { xs: 12, md: 0 }, p: { xs: 0.85, md: 1.15 }, maxWidth: { xs: 196, md: 238 }, borderRadius: 2.5, bgcolor: qtxpertEffects.glassBackground }}>
                <Stack direction="row" spacing={0.7} alignItems="center">
                  <SecurityOutlinedIcon color="primary" fontSize="small" />
                  <Typography variant="body2" fontWeight={800}>Your AI test copilot</Typography>
                </Stack>
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.35 }}>Ready when you are.</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: "block" }} noWrap>
                  {latestEvidenceAt ? `Evidence updated ${formatDate(latestEvidenceAt)}` : "No execution evidence yet"}
                </Typography>
              </Paper>
            </Box>
          </Grid>
        </Grid>
      </Paper>

      {preferences.visibleWidgets.metrics && visibleMetricDefinitions.length > 0 && (
        <Grid container spacing={0.9} sx={{ mb: 1.2 }}>
          {visibleMetricDefinitions.map(({ key, helper }) => {
            const value = metricValues[key];
            const tone = key === "pass_rate" ? "success.main" : key === "attention_areas" ? "warning.main" : "primary.main";
            const iconTone = key === "test_cases" ? "info.main" : tone;
            const iconSurface = key === "test_cases" ? qtxpertColors.paleSkyBlue : key === "attention_areas" ? qtxpertColors.peach : key === "pass_rate" ? qtxpertColors.mint : qtxpertColors.iconLilac;
            const metricHelper = key === "pass_rate" && data
              ? data.total_execution_tests
                ? `${data.passed_tests} passed · ${data.executed_tests} executed checks`
                : "No execution denominator is available yet."
              : helper;
            return (
              <Grid key={key} size={{ xs: 6, md: 3 }}>
                <Card variant="outlined" sx={{ height: "100%", minHeight: 82, borderRadius: 2.5, overflow: "hidden", transition: "transform 160ms ease, border-color 160ms ease", "&:hover": { transform: "translateY(-2px)", borderColor: "primary.main" } }}>
                  <CardActionArea component={RouterLink} to={metricRoutes[key]} aria-label={`Open ${preferences.metricLabels[key]}`} sx={{ height: "100%", alignItems: "stretch" }}>
                    <CardContent sx={{ p: 1.1, "&:last-child": { pb: 1.1 } }}>
                      {summary.isFetching ? <Skeleton variant="rounded" height={55} /> : (
                        <Stack direction="row" alignItems="center" spacing={0.9}>
                          <Box sx={{ width: 36, height: 36, display: "grid", placeItems: "center", borderRadius: 2, bgcolor: iconSurface, color: iconTone, flexShrink: 0, "& .MuiSvgIcon-root": { fontSize: 21 } }}>{metricIcons[key]}</Box>
                          <Box sx={{ minWidth: 0, flex: 1 }}>
                            <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>{preferences.metricLabels[key]}</Typography>
                            <Typography variant="h5" sx={{ mt: 0.1, color: tone, lineHeight: 1.05, fontWeight: 800 }}>{summary.isError ? "—" : value}</Typography>
                          </Box>
                          <Tooltip title={metricHelper} placement="top-end">
                            <Box component="span" tabIndex={0} aria-label={`${preferences.metricLabels[key]}: ${metricHelper}`} sx={{ display: "flex", color: "text.secondary", p: 0.4, flexShrink: 0 }}><InfoOutlinedIcon fontSize="small" /></Box>
                          </Tooltip>
                        </Stack>
                      )}
                      {key === "pass_rate" && passRate !== null && !summary.isFetching && <LinearProgress variant="determinate" value={passRate} color={passRate >= 90 ? "success" : "primary"} sx={{ mt: 0.75, height: 3, borderRadius: 4 }} />}
                    </CardContent>
                  </CardActionArea>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      )}

      {preferences.visibleWidgets.posture && (
        <Grid container spacing={0.9} sx={{ mb: 1.2 }}>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card variant="outlined" sx={{ height: "100%", minHeight: 180, borderRadius: 2.5 }}>
              <CardContent sx={{ p: 1.25, "&:last-child": { pb: 1.25 } }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={0.6}>
                  <Stack direction="row" spacing={0.45} alignItems="center">
                    <Typography variant="subtitle2" fontWeight={800}>Execution health</Typography>
                    <Tooltip title="Observed pass rate from saved execution results. It does not measure full application coverage."><InfoOutlinedIcon fontSize="small" color="action" /></Tooltip>
                  </Stack>
                  <AssessmentOutlinedIcon color="primary" fontSize="small" />
                </Stack>
                <Stack direction="row" spacing={1.1} alignItems="center" sx={{ mt: 1.1 }}>
                  <Box role="img" aria-label={passRate === null ? "No execution results" : `${passRate}% observed pass rate`} sx={{ width: 88, height: 88, p: 0.8, borderRadius: "50%", flexShrink: 0, background: (theme) => `conic-gradient(${theme.palette.success.main} ${passRate ?? 0}%, ${theme.palette.action.hover} 0)` }}>
                    <Box sx={{ height: "100%", display: "grid", placeItems: "center", borderRadius: "50%", bgcolor: "background.paper", boxShadow: "inset 0 2px 8px rgba(41,38,61,.08)" }}>
                      <Typography variant="subtitle1" fontWeight={800} color={passRate === null ? "text.secondary" : "success.main"}>{passRate === null ? "—" : `${passRate}%`}</Typography>
                    </Box>
                  </Box>
                  <Stack spacing={0.45} sx={{ minWidth: 0, flex: 1 }}>
                    {[
                      { label: "Passed", count: data?.passed_tests ?? "—", color: "success.main" },
                      { label: "Failed", count: data?.failed_tests ?? "—", color: "error.main" },
                      { label: "Blocked", count: data?.blocked_tests ?? "—", color: "warning.main" },
                      { label: "Pending", count: data?.pending_tests ?? "—", color: "text.secondary" },
                    ].map((item) => (
                      <Stack key={item.label} direction="row" justifyContent="space-between" alignItems="center" spacing={0.5}>
                        <Typography variant="caption" color="text.secondary" noWrap>{item.label}</Typography>
                        <Typography variant="caption" fontWeight={800} color={item.color}>{item.count}</Typography>
                      </Stack>
                    ))}
                  </Stack>
                </Stack>
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.9 }}>{data?.total_execution_tests ? `${data.executed_tests} of ${data.total_execution_tests} checks executed` : "No execution results recorded"}</Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, md: 4 }}>
            <Card variant="outlined" sx={{ height: "100%", minHeight: 180, borderRadius: 2.5 }}>
              <CardContent sx={{ p: 1.25, "&:last-child": { pb: 1.25 } }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={0.6}>
                  <Stack direction="row" spacing={0.45} alignItems="center">
                    <Typography variant="subtitle2" fontWeight={800}>Automation readiness</Typography>
                    <Tooltip title="Share of designed test cases currently marked as automation candidates—not application coverage."><InfoOutlinedIcon fontSize="small" color="action" /></Tooltip>
                  </Stack>
                  <AutoAwesomeOutlinedIcon color="primary" fontSize="small" />
                </Stack>
                <Stack direction="row" spacing={1.15} alignItems="center" sx={{ mt: 0.9 }}>
                  <Box
                    role="img"
                    aria-label={automationReady === null ? "No test cases are available yet" : `${automationReady}% of designed cases are marked as automation candidates`}
                    sx={{
                      position: "relative",
                      width: 58,
                      height: 108,
                      flexShrink: 0,
                      overflow: "hidden",
                      border: "1px solid rgba(117,70,232,.28)",
                      borderRadius: "30px 30px 22px 22px",
                      background: "linear-gradient(180deg, rgba(255,255,255,.9), rgba(237,229,255,.36))",
                      boxShadow: "inset 0 2px 8px rgba(255,255,255,.95), inset 0 -8px 16px rgba(117,70,232,.08), 0 8px 16px rgba(117,70,232,.08)",
                    }}
                  >
                    <Box sx={{ position: "absolute", left: 4, right: 4, bottom: 4, height: `${automationReady ?? 0}%`, minHeight: automationReady ? 5 : 0, borderRadius: "0 0 22px 22px", background: "linear-gradient(180deg, rgba(196,181,253,.66), rgba(117,70,232,.48))", transition: "height 240ms ease" }} />
                    <Box sx={{ position: "absolute", left: 7, right: 7, top: 3, height: 10, border: "1px solid rgba(255,255,255,.94)", borderRadius: "50%", boxShadow: "0 2px 8px rgba(117,70,232,.12)" }} />
                    <Box sx={{ position: "absolute", left: 8, right: 8, top: 18, bottom: 9, borderLeft: "1px solid rgba(255,255,255,.64)", borderRight: "1px solid rgba(255,255,255,.48)", borderRadius: "18px" }} />
                  </Box>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="h4" fontWeight={800} color={automationReady === null ? "text.secondary" : "primary.main"} sx={{ lineHeight: 1 }}>{automationReady === null ? "—" : `${automationReady}%`}</Typography>
                    <Typography variant="body2" fontWeight={800} sx={{ mt: 0.55 }}>{data?.test_cases ? `${data.automation_candidates} of ${data.test_cases} cases` : "No cases yet"}</Typography>
                    <Typography variant="caption" color="text.secondary">marked as automation candidates</Typography>
                  </Box>
                </Stack>
                <Divider sx={{ my: 0.85 }} />
                <Stack direction="row" justifyContent="space-between" spacing={1}>
                  <Typography variant="caption" color="text.secondary">Requirements</Typography>
                  <Typography variant="caption" fontWeight={800}>{data?.requirements ?? "—"}</Typography>
                  <Typography variant="caption" color="text.secondary">Cases</Typography>
                  <Typography variant="caption" fontWeight={800}>{data?.test_cases ?? "—"}</Typography>
                </Stack>
              </CardContent>
            </Card>
          </Grid>

          {preferences.visibleWidgets.execution && (
            <Grid size={{ xs: 12, md: 4 }}>
              <Card variant="outlined" sx={{ height: "100%", minHeight: 180, borderRadius: 2.5 }}>
                <CardContent sx={{ p: 1.25, "&:last-child": { pb: 1.25 } }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={0.7} sx={{ mb: 0.7 }}>
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <Typography variant="subtitle2" fontWeight={800}>Recent activity</Typography>
                      <Tooltip title="Latest saved execution runs. Open one to inspect its outcome and evidence."><InfoOutlinedIcon fontSize="small" color="action" /></Tooltip>
                    </Stack>
                    <Button component={RouterLink} to="/execution" size="small" endIcon={<ArrowForwardRoundedIcon />} sx={{ whiteSpace: "nowrap" }}>All runs</Button>
                  </Stack>
                  {summary.isFetching ? <Stack spacing={0.55}><Skeleton variant="rounded" height={42} /><Skeleton variant="rounded" height={42} /></Stack> : data?.recent_runs.length ? (
                    <Stack spacing={0.55}>{data.recent_runs.slice(0, 3).map((run) => <ExecutionRow key={run.id} run={run} />)}</Stack>
                  ) : (
                    <Stack direction="row" alignItems="center" spacing={1} sx={{ py: 2, color: "text.secondary" }}>
                      <HistoryOutlinedIcon />
                      <Typography variant="body2">No execution runs yet.</Typography>
                    </Stack>
                  )}
                </CardContent>
              </Card>
            </Grid>
          )}
        </Grid>
      )}

      {visibleWidgetCount > 0 && (
        <Grid container spacing={0.9} sx={{ mb: 1.2 }}>
          <Grid size={{ xs: 12, md: preferences.visibleWidgets.autopilot ? 3 : 4 }}>
            <Card variant="outlined" sx={{ height: "100%", minHeight: 164, borderRadius: 2.5 }}>
              <CardContent sx={{ p: 1.15, "&:last-child": { pb: 1.15 } }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={0.5} sx={{ mb: 0.8 }}>
                  <Typography variant="subtitle2" fontWeight={800}>Quick actions</Typography>
                  <Tooltip title="Jump to the most-used project tasks."><InfoOutlinedIcon fontSize="small" color="action" /></Tooltip>
                </Stack>
                <Grid container spacing={0.65}>
                  <Grid size={6}><Button component={RouterLink} to="/autopilot" size="small" variant="contained" startIcon={<PlayArrowRoundedIcon />} fullWidth sx={{ minHeight: 48, justifyContent: "flex-start", px: 0.9 }}>Autopilot</Button></Grid>
                  <Grid size={6}><Button size="small" variant="outlined" startIcon={<AddRoundedIcon />} onClick={openNewProject} fullWidth sx={{ minHeight: 48, justifyContent: "flex-start", px: 0.9 }}>New project</Button></Grid>
                  <Grid size={6}><Button component={RouterLink} to="/design" size="small" variant="outlined" startIcon={<ArchitectureOutlinedIcon />} fullWidth sx={{ minHeight: 48, justifyContent: "flex-start", px: 0.9 }}>Test design</Button></Grid>
                  <Grid size={6}><Button component={RouterLink} to="/reports" size="small" variant="outlined" startIcon={<AssessmentOutlinedIcon />} fullWidth sx={{ minHeight: 48, justifyContent: "flex-start", px: 0.9 }}>Reports</Button></Grid>
                </Grid>
              </CardContent>
            </Card>
          </Grid>

          {preferences.visibleWidgets.autopilot && (
            <Grid size={{ xs: 12, md: 6 }}>
              <Card variant="outlined" sx={{ height: "100%", minHeight: 164, borderRadius: 2.5 }}>
                <CardContent sx={{ p: 1.15, "&:last-child": { pb: 1.15 } }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={0.75}>
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <AutoAwesomeOutlinedIcon color="primary" fontSize="small" />
                      <Typography variant="subtitle2" fontWeight={800}>Autopilot progress</Typography>
                      <Tooltip title="Counts reflect saved Autopilot data. A stage is not marked complete unless its corresponding result is recorded."><InfoOutlinedIcon fontSize="small" color="action" /></Tooltip>
                    </Stack>
                    <Chip size="small" variant="outlined" color={autopilotActivity.active_jobs > 0 ? "info" : autopilotActivity.waiting_for_input_jobs > 0 ? "warning" : "default"} label={autopilotActivity.active_jobs > 0 ? "Running" : autopilotActivity.waiting_for_input_jobs > 0 ? "Input needed" : autopilotActivity.generated_test_cases > 0 ? "Plan available" : "Not started"} />
                  </Stack>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1} sx={{ mt: 0.55, mb: 0.45 }}>
                    <Typography variant="caption" color="text.secondary" noWrap>
                      {autopilotExecutionProgress === null ? "No selected checks" : `${autopilotActivity.executed_tests} of ${autopilotActivity.selected_tests} selected checks executed`}
                    </Typography>
                    <Typography variant="caption" fontWeight={800}>{autopilotExecutionProgress === null ? "—" : `${autopilotExecutionProgress}%`}</Typography>
                  </Stack>
                  <LinearProgress variant="determinate" value={autopilotExecutionProgress ?? 0} color={autopilotActivity.waiting_for_input_jobs ? "warning" : "primary"} sx={{ height: 4, borderRadius: 5 }} />
                  <Grid container spacing={0.35} sx={{ mt: 1.0 }}>
                    {autopilotStages.map((stage) => (
                      <Grid key={stage.key} size={{ xs: 4, sm: 2 }}>
                        <Tooltip title={stage.description} placement="top">
                          <CardActionArea component={RouterLink} to={stage.to} aria-label={`${stage.title}: ${stage.stateLabel}`} sx={{ minHeight: 56, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", px: 0.25, py: 0.4, borderRadius: 1.5, textAlign: "center", "&:hover": { bgcolor: qtxpertColors.softLilac } }}>
                            <Box sx={{ width: 25, height: 25, display: "grid", placeItems: "center", borderRadius: "50%", bgcolor: stage.state === "ready" ? qtxpertColors.mint : stage.state === "active" ? qtxpertColors.lightLavender : qtxpertColors.iconLilac, color: stage.state === "ready" ? "success.main" : "primary.main", "& .MuiSvgIcon-root": { fontSize: 16 } }}>{stage.icon}</Box>
                            <Typography variant="caption" fontWeight={800} noWrap sx={{ lineHeight: 1.25, mt: 0.2, maxWidth: "100%" }}>{stage.title}</Typography>
                            <Typography variant="caption" color="text.secondary" noWrap sx={{ fontSize: 10, lineHeight: 1.2, maxWidth: "100%" }}>{stage.stateLabel}</Typography>
                          </CardActionArea>
                        </Tooltip>
                      </Grid>
                    ))}
                  </Grid>
                </CardContent>
              </Card>
            </Grid>
          )}

          {(preferences.visibleWidgets.signals || preferences.visibleWidgets.documentation) && (
            <Grid size={{ xs: 12, md: preferences.visibleWidgets.autopilot ? 3 : 4 }}>
              <Card variant="outlined" sx={{ height: "100%", minHeight: 164, borderRadius: 2.5 }}>
                <CardContent sx={{ p: 1.15, "&:last-child": { pb: 1.15 } }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={0.5} sx={{ mb: 0.55 }}>
                    <Stack direction="row" spacing={0.45} alignItems="center">
                      <Typography variant="subtitle2" fontWeight={800}>Project insights</Typography>
                      <Tooltip title="Evidence-backed signals from saved project and document data; not a generated compliance or release claim."><InfoOutlinedIcon fontSize="small" color="action" /></Tooltip>
                    </Stack>
                    {preferences.visibleWidgets.signals && <Chip size="small" label={actionRequiredCount} color={actionRequiredCount ? "warning" : "success"} variant="outlined" />}
                  </Stack>
                  {preferences.visibleWidgets.signals && (summary.isFetching ? <Skeleton variant="rounded" height={54} /> : summary.isError ? (
                    <Typography variant="caption" color="text.secondary">Project signals unavailable.</Typography>
                  ) : actionItems.length ? (
                    <Stack spacing={0.15}>
                      {actionItems.slice(0, preferences.visibleWidgets.documentation ? 2 : 3).map((item) => (
                        <Tooltip key={item.key} title={item.detail} placement="left">
                          <Box component={RouterLink} to={item.route} sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 0.5, px: 0.4, py: 0.28, borderRadius: 1.2, color: "text.primary", textDecoration: "none", "&:hover": { bgcolor: "action.hover" } }}>
                            <Typography variant="caption" noWrap sx={{ minWidth: 0 }}>{item.title}</Typography>
                            <Typography variant="caption" fontWeight={800} color="warning.main">{item.count}</Typography>
                          </Box>
                        </Tooltip>
                      ))}
                    </Stack>
                  ) : (
                    <Stack direction="row" spacing={0.5} alignItems="center" sx={{ py: 0.4 }}>
                      <CheckCircleOutlineOutlinedIcon color="success" fontSize="small" />
                      <Typography variant="caption" color="text.secondary">No open actions</Typography>
                    </Stack>
                  ))}
                  {preferences.visibleWidgets.documentation && (
                    <>
                      {preferences.visibleWidgets.signals && <Divider sx={{ my: 0.45 }} />}
                      <CardActionArea component={RouterLink} to="/documents" aria-label="Open Document Intelligence" sx={{ display: "flex", justifyContent: "space-between", gap: 0.5, borderRadius: 1.2, px: 0.4, py: 0.3 }}>
                        <Stack direction="row" spacing={0.45} alignItems="center" minWidth={0}>
                          <DescriptionOutlinedIcon color="primary" sx={{ fontSize: 17 }} />
                          <Typography variant="caption" fontWeight={700} noWrap>Document review</Typography>
                        </Stack>
                        <Chip size="small" variant="outlined" color={documentReviewData?.status === "completed" ? "success" : documentReviewData?.status === "failed" ? "error" : "default"} label={documentReview.isFetching ? "Checking" : documentReviewData?.status === "completed" ? "Reviewed" : documentReviewData?.status ? displayDocumentStatus(documentReviewData.status) : "Not reviewed"} sx={{ height: 20, maxWidth: "58%", "& .MuiChip-label": { overflow: "hidden", textOverflow: "ellipsis" } }} />
                      </CardActionArea>
                    </>
                  )}
                </CardContent>
              </Card>
            </Grid>
          )}
        </Grid>
      )}

      {visibleWidgetCount === 0 && <Alert severity="info">All dashboard sections are hidden. Use Customize dashboard to restore a section.</Alert>}

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
    <Box
      component={RouterLink}
      to="/execution"
      aria-label={"Open execution run " + run.name}
      sx={{ p: 0.7, borderRadius: 1.5, bgcolor: "action.hover", color: "text.primary", textDecoration: "none", "&:hover": { bgcolor: "action.selected" } }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={0.8}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" fontWeight={700} noWrap>{run.name}</Typography>
          <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
            {formatDate(run.created_at)} · {run.passed_tests} passed · {run.failed_tests} failed · {run.blocked_tests} blocked
          </Typography>
        </Box>
        <Chip label={run.status} size="small" color={runColor(run.status)} sx={{ flexShrink: 0 }} />
      </Stack>
    </Box>
  );
}



