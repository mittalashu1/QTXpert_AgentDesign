import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  Divider,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  LinearProgress,
  MenuItem,
  Select,
  Stack,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Typography,
  Switch,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import AddTaskOutlinedIcon from "@mui/icons-material/AddTaskOutlined";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import RuleOutlinedIcon from "@mui/icons-material/RuleOutlined";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import OpenInNewOutlinedIcon from "@mui/icons-material/OpenInNewOutlined";
import SearchOutlinedIcon from "@mui/icons-material/SearchOutlined";
import SaveOutlinedIcon from "@mui/icons-material/SaveOutlined";
import { AxiosError } from "axios";
import { executionPlansApi, executionsApi, testCasesApi, uploadsApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import PageHeader from "@/components/PageHeader";
import RepositoryAssetPicker from "@/components/RepositoryAssetPicker";
import { repositoryAssetExtension, useRepositoryAssets } from "@/components/repositoryAssets";
import type { ExecutionPlan, ExecutionPlanCase, ExecutionProvider, ExecutionRun, ExecutionTargetKind, UploadedAsset } from "@/types/domain";

type CaseExecutionUpdate = {
  id: string;
  steps?: string[];
  expected_result?: string;
  test_data?: Record<string, unknown> | null;
};

const STEPS = ["Import from Test Design", "Select cases", "Preflight and run", "Review evidence"];

type ApiErrorDetail = {
  loc?: unknown;
  msg?: unknown;
  message?: unknown;
  detail?: unknown;
};

function apiErrorMessage(reason: unknown, fallback: string): string {
  const error = reason as AxiosError<{ detail?: unknown }>;
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return String(item);
      const entry = item as ApiErrorDetail;
      const message = typeof entry.msg === "string"
        ? entry.msg
        : typeof entry.message === "string"
          ? entry.message
          : typeof entry.detail === "string" ? entry.detail : "";
      const location = Array.isArray(entry.loc)
        ? entry.loc.filter((part): part is string | number => typeof part === "string" || typeof part === "number").join(".")
        : "";
      return message ? (location ? `${location}: ${message}` : message) : "";
    }).filter(Boolean);
    if (messages.length) return messages.join(" · ");
  }

  if (detail && typeof detail === "object") {
    const entry = detail as ApiErrorDetail;
    const message = typeof entry.message === "string"
      ? entry.message
      : typeof entry.msg === "string"
        ? entry.msg
        : typeof entry.detail === "string" ? entry.detail : "";
    if (message) return message;
  }

  if (reason instanceof Error && reason.message) return reason.message;
  const status = error?.response?.status;
  return status ? `${fallback} (HTTP ${status})` : fallback;
}

function compactTitle(value: string, maxLength = 68) {
  const normalized = value.trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function planTitle(plan: ExecutionPlan, maxLength = 68) {
  return compactTitle(plan.name || plan.source_title || "Execution plan", maxLength);
}

function sourceRunTitle(run: { title?: string | null; requirement_summary: string | null; generation_profile: string }) {
  return compactTitle(run.title || run.requirement_summary || `${run.generation_profile} test set`);
}

function readinessColor(readiness: string): "success" | "error" | "warning" | "info" | "default" {
  if (readiness === "ready") return "success";
  if (readiness === "blocked") return "error";
  if (readiness === "approval_required" || readiness === "manual_review") return "warning";
  if (readiness === "pending") return "info";
  return "default";
}

function runStatusColor(status: string): "success" | "error" | "warning" | "info" {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  if (status === "queued") return "warning";
  return "info";
}

function executionTargetLabel(run: ExecutionRun) {
  if (run.target_kind === "android") return `Android · ${run.device_name || "device"}${run.platform_version ? ` · ${run.platform_version}` : ""}`;
  if (run.target_kind === "ios") return `iOS · ${run.device_name || "device"}${run.platform_version ? ` · ${run.platform_version}` : ""}`;
  return `Web · ${run.base_url || "target unavailable"}`;
}

function executionRunDate(run: ExecutionRun) {
  return new Date(run.completed_at || run.started_at || run.created_at).toLocaleString();
}

export default function TestExecutionPage() {
  const { selectedProjectId } = useSelectedProject();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [sourceRunId, setSourceRunId] = useState("");
  const [planId, setPlanId] = useState("");
  const [planName, setPlanName] = useState("");
  const [suiteType, setSuiteType] = useState<"smoke" | "feature" | "regression" | "deep_regression">("regression");
  const [targetKind, setTargetKind] = useState<ExecutionTargetKind>("web");
  const [provider, setProvider] = useState<ExecutionProvider>("playwright");
  const [baseUrl, setBaseUrl] = useState("");
  const [appAssetId, setAppAssetId] = useState("");
  const [deviceName, setDeviceName] = useState("Google Pixel 8");
  const [platformVersion, setPlatformVersion] = useState("14.0");
  const [appiumUrl, setAppiumUrl] = useState("");
  const [appiumApp, setAppiumApp] = useState("");
  const [noReset, setNoReset] = useState(false);
  const [autoGrantPermissions, setAutoGrantPermissions] = useState(true);
  const [runName, setRunName] = useState("");
  const [preflightSignature, setPreflightSignature] = useState("");
  const [caseFilter, setCaseFilter] = useState("all");
  const [caseSearch, setCaseSearch] = useState("");
  const [runSearch, setRunSearch] = useState("");
  const [runFilter, setRunFilter] = useState("all");
  const [selection, setSelection] = useState<Record<string, boolean>>({});
  const [modes, setModes] = useState<Record<string, "automated" | "manual">>({});
  const [selectionDirty, setSelectionDirty] = useState(false);
  const [inputDraft, setInputDraft] = useState<Record<string, string>>({});
  const [inputDirty, setInputDirty] = useState(false);
  const [caseEditor, setCaseEditor] = useState<{
    id: string;
    steps: string;
    expectedResult: string;
    testData: string;
  } | null>(null);
  const [caseEditorError, setCaseEditorError] = useState("");
  const [uploadError, setUploadError] = useState("");

  const history = useQuery({
    queryKey: ["execution-source-runs", selectedProjectId],
    queryFn: () => testCasesApi.historySummaries(selectedProjectId!, 200, 0).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
  });
  const mobileAssets = useRepositoryAssets({
    projectId: selectedProjectId,
    extensions: ["apk", "ipa"],
    excludeCategories: ["autopilot_evidence", "execution_evidence"],
    excludeSourceModules: ["autopilot_evidence", "execution_report"],
    cacheKey: "execution-mobile-assets",
  });
  const plans = useQuery({
    queryKey: ["execution-plans", selectedProjectId],
    queryFn: () => executionPlansApi.list(selectedProjectId!).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
  });
  const plan = useQuery({
    queryKey: ["execution-plan", planId],
    queryFn: () => executionPlansApi.get(planId).then((response) => response.data),
    enabled: Boolean(planId),
  });
  const runs = useQuery({
    queryKey: ["executions", selectedProjectId],
    queryFn: () => executionsApi.list(selectedProjectId!).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
    refetchInterval: (query) => query.state.data?.some((run) => ["queued", "running"].includes(run.status)) ? 4000 : false,
  });

  const appUpload = useMutation({
    mutationFn: (file: File) => uploadsApi.upload(file, {
      projectId: selectedProjectId!,
      sourceModule: "test_execution",
      category: file.name.toLowerCase().endsWith(".ipa") ? "ipa" : "apk",
    }).then((response) => response.data),
    onSuccess: (asset: UploadedAsset) => {
      setAppAssetId(asset.id);
      setUploadError("");
      queryClient.invalidateQueries({ queryKey: ["execution-mobile-assets", selectedProjectId] });
      setPreflightSignature("");
    },
    onError: (reason) => setUploadError(apiErrorMessage(reason, "The mobile app could not be uploaded.")),
  });

  const completedRuns = useMemo(
    () => (history.data ?? []).filter((run) => run.status === "completed" && run.test_case_count > 0),
    [history.data],
  );
  const currentPlan = plan.data;
  const currentCases = useMemo(() => currentPlan?.cases ?? [], [currentPlan]);
  const sourceRun = useMemo(
    () => currentPlan?.source_generation_run_id
      ? (history.data ?? []).find((item) => item.id === currentPlan.source_generation_run_id)
      : undefined,
    [currentPlan?.source_generation_run_id, history.data],
  );
  const selectedMobileAsset = useMemo(
    () => mobileAssets.assets.find((asset) => asset.id === appAssetId) ?? null,
    [appAssetId, mobileAssets.assets],
  );
  const targetPayload = useMemo(() => ({
    target_kind: targetKind,
    provider: targetKind === "web" ? "playwright" as const : provider,
    ...(targetKind === "web"
      ? { base_url: baseUrl.trim() }
      : {
        app_asset_id: appAssetId || undefined,
        device_name: deviceName.trim() || undefined,
        platform_version: platformVersion.trim() || undefined,
        ...(provider === "appium" ? {
          appium_url: appiumUrl.trim() || undefined,
          appium_app: appiumApp.trim() || undefined,
        } : {}),
        no_reset: noReset,
        auto_grant_permissions: autoGrantPermissions,
      }),
  }), [appAssetId, appiumApp, appiumUrl, autoGrantPermissions, baseUrl, deviceName, noReset, platformVersion, provider, targetKind]);
  const targetSignature = useMemo(() => JSON.stringify(targetPayload), [targetPayload]);
  const targetConfigured = targetKind === "web"
    ? Boolean(baseUrl.trim())
    : Boolean(appAssetId && deviceName.trim() && provider !== "playwright");

  useEffect(() => {
    if (!currentPlan) return;
    const nextSelection: Record<string, boolean> = {};
    const nextModes: Record<string, "automated" | "manual"> = {};
    currentPlan.cases.forEach((item) => {
      nextSelection[item.id] = item.selected;
      nextModes[item.id] = item.execution_mode;
    });
    setSelection(nextSelection);
    setModes(nextModes);
    setSelectionDirty(false);
    setInputDraft(currentPlan.input_references ?? {});
    setInputDirty(false);
    setRunName((value) => value || `${currentPlan.name} run`);
  }, [currentPlan]);

  useEffect(() => {
    if (targetKind === "web") {
      setProvider("playwright");
      setAppAssetId("");
      setPreflightSignature("");
      return;
    }
    setProvider((value) => value === "playwright" ? "browserstack" : value);
    const selected = mobileAssets.assets.find((asset) => asset.id === appAssetId);
    if (selected && repositoryAssetExtension(selected) !== (targetKind === "android" ? "apk" : "ipa")) {
      setAppAssetId("");
    }
    setPreflightSignature("");
  }, [appAssetId, mobileAssets.assets, targetKind]);

  const importPlan = useMutation({
    mutationFn: () => executionPlansApi.import({
      project_id: selectedProjectId!,
      generation_run_id: sourceRunId,
      name: planName.trim() || undefined,
      suite_type: suiteType,
    }).then((response) => response.data),
    onSuccess: (created) => {
      setPlanId(created.id);
      setPlanName("");
      queryClient.invalidateQueries({ queryKey: ["execution-plans", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["execution-plan", created.id] });
    },
  });

  const saveSelection = useMutation({
    mutationFn: (override?: CaseExecutionUpdate) => executionPlansApi.updateCases(
      planId,
      currentCases.map((item) => ({
        id: item.id,
        selected: Boolean(selection[item.id]),
        execution_mode: modes[item.id] ?? item.execution_mode,
        ...(override?.id === item.id ? {
          steps: override.steps,
          expected_result: override.expected_result,
          test_data: override.test_data,
        } : {}),
      })),
    ).then((response) => response.data),
    onSuccess: (updated) => {
      queryClient.setQueryData(["execution-plan", updated.id], updated);
      queryClient.invalidateQueries({ queryKey: ["execution-plans", selectedProjectId] });
      setPreflightSignature("");
      setSelectionDirty(false);
    },
  });

  const saveInputs = useMutation({
    mutationFn: () => executionPlansApi.updateInputs(planId, inputDraft).then((response) => response.data),
    onSuccess: (updated) => {
      queryClient.setQueryData(["execution-plan", updated.id], updated);
      queryClient.invalidateQueries({ queryKey: ["execution-plans", selectedProjectId] });
      setPreflightSignature("");
      setInputDirty(false);
    },
  });

  const preflight = useMutation({
    mutationFn: () => executionPlansApi.preflight(planId, targetPayload).then((response) => response.data),
    onSuccess: (updated) => {
      queryClient.setQueryData(["execution-plan", updated.id], updated);
      queryClient.invalidateQueries({ queryKey: ["execution-plans", selectedProjectId] });
      setPreflightSignature(targetSignature);
    },
  });

  const execute = useMutation({
    mutationFn: () => executionPlansApi.execute(planId, { ...targetPayload, name: runName.trim() || undefined }).then((response) => response.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["executions", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["execution-plan", planId] });
      queryClient.invalidateQueries({ queryKey: ["execution-plans", selectedProjectId] });
    },
  });

  const onMobileFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const extension = file.name.toLowerCase().split(".").pop();
    const expected = targetKind === "ios" ? "ipa" : "apk";
    if (targetKind === "web" || extension !== expected) {
      setUploadError(`Select a .${expected} file for the chosen mobile target.`);
      return;
    }
    appUpload.mutate(file);
  };

  const openCaseEditor = (item: ExecutionPlanCase) => {
    setCaseEditorError("");
    setCaseEditor({
      id: item.id,
      steps: (item.steps ?? []).join("\n"),
      expectedResult: item.expected_result ?? "",
      testData: item.test_data ? JSON.stringify(item.test_data, null, 2) : "",
    });
  };

  const saveCaseEditor = () => {
    if (!caseEditor) return;
    const steps = caseEditor.steps.split("\n").map((step) => step.trim()).filter(Boolean);
    if (!steps.length) {
      setCaseEditorError("Add at least one explicit automation step before saving.");
      return;
    }
    if (!caseEditor.expectedResult.trim()) {
      setCaseEditorError("Add the expected result so the runner knows what to verify.");
      return;
    }
    let testData: Record<string, unknown> | null = null;
    if (caseEditor.testData.trim()) {
      try {
        const parsed: unknown = JSON.parse(caseEditor.testData);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setCaseEditorError("Test data must be a JSON object, for example { \"account_reference\": \"qa-001\" }.");
          return;
        }
        testData = parsed as Record<string, unknown>;
      } catch {
        setCaseEditorError("Test data must be valid JSON, or leave it empty when no data is needed.");
        return;
      }
    }
    setCaseEditorError("");
    saveSelection.mutate(
      { id: caseEditor.id, steps, expected_result: caseEditor.expectedResult.trim(), test_data: testData },
      {
        onSuccess: () => setCaseEditor(null),
        onError: (reason) => setCaseEditorError(apiErrorMessage(reason, "The execution case could not be saved.")),
      },
    );
  };

  const filteredCases = useMemo(() => {
    const search = caseSearch.trim().toLowerCase();
    return currentCases.filter((item) => {
      const matchesFilter = caseFilter === "all"
        || (caseFilter === "selected" && selection[item.id])
        || (caseFilter === "automation" && item.is_automation_candidate)
        || (caseFilter === "blocked" && ["blocked", "approval_required", "manual_review"].includes(item.readiness));
      const matchesSearch = !search || `${item.test_case_key} ${item.scenario} ${item.test_type}`.toLowerCase().includes(search);
      return matchesFilter && matchesSearch;
    });
  }, [caseFilter, caseSearch, currentCases, selection]);

  const caseGroups = useMemo(() => {
    const groups = new Map<string, ExecutionPlanCase[]>();
    filteredCases.forEach((item) => {
      const key = item.test_type || "functional";
      const current = groups.get(key) ?? [];
      current.push(item);
      groups.set(key, current);
    });
    return [...groups.entries()];
  }, [filteredCases]);

  const filteredExecutionRuns = useMemo(() => {
    const search = runSearch.trim().toLowerCase();
    return [...(runs.data ?? [])]
      .filter((run) => runFilter === "all" || run.status === runFilter)
      .filter((run) => !search || `${run.name} ${executionTargetLabel(run)} ${run.provider}`.toLowerCase().includes(search))
      .sort((left, right) => new Date(right.completed_at || right.created_at).getTime() - new Date(left.completed_at || left.created_at).getTime());
  }, [runFilter, runSearch, runs.data]);

  const selectedAutomated = currentCases.filter((item) => selection[item.id] && (modes[item.id] ?? item.execution_mode) === "automated");
  const readyCount = currentPlan?.ready_cases ?? 0;
  const needsAttentionCount = currentPlan ? Math.max(0, currentPlan.total_cases - currentPlan.ready_cases) : 0;
  const inputRequirements = currentPlan?.input_requirements ?? [];
  const globalInputRequirements = inputRequirements.filter((item) => !item.key.startsWith("case:"));
  const caseInputRequirements = inputRequirements.filter((item) => item.key.startsWith("case:"));
  const unresolvedRequirements = inputRequirements.filter((item) => !item.provided);
  const selectedAttention = currentCases.filter((item) => (
    selection[item.id]
    && (modes[item.id] ?? item.execution_mode) === "automated"
    && item.readiness !== "ready"
  ));
  const canExecute = Boolean(
    currentPlan
    && selectedAutomated.length > 0
    && readyCount > 0
    && selectedAttention.length === 0
    && unresolvedRequirements.length === 0
    && preflightSignature === targetSignature
    && !selectionDirty
    && !inputDirty
    && !execute.isPending,
  );
  const planRuns = (runs.data ?? []).filter((run) => !planId || run.execution_plan_id === planId);
  const activeStep = !currentPlan ? 0 : planRuns.length ? 3 : currentPlan.ready_cases > 0 ? 2 : 1;

  if (!selectedProjectId) {
    return <Alert severity="info">Create or select a project before importing test cases for execution.</Alert>;
  }

  return (
    <Box>
      <PageHeader
        eyebrow="M4 · EXECUTION FABRIC"
        title="Test execution"
        description="Import a versioned Test Design set, select the cases to automate, validate readiness, and retain evidence for every run."
      />

      <Stepper activeStep={activeStep} alternativeLabel sx={{ mb: 3 }}>
        {STEPS.map((label) => <Step key={label}><StepLabel>{label}</StepLabel></Step>)}
      </Stepper>

      <Card variant="outlined" sx={{ mb: 3 }}>
        <CardContent>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "flex-end" }}>
            <FormControl fullWidth>
              <InputLabel id="source-run-label">Completed Test Design set</InputLabel>
              <Select
                labelId="source-run-label"
                label="Completed Test Design set"
                value={sourceRunId}
                onChange={(event) => setSourceRunId(event.target.value)}
              >
                <MenuItem value=""><em>Select a generated test set</em></MenuItem>
                {completedRuns.map((run) => (
                  <MenuItem key={run.id} value={run.id} title={run.title || run.requirement_summary || undefined}>
                    <Box sx={{ maxWidth: { xs: 260, md: 560 }, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {sourceRunTitle(run)} · {run.test_case_count} cases · {new Date(run.created_at).toLocaleString()}
                    </Box>
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl sx={{ minWidth: 180 }}>
              <InputLabel id="suite-type-label">Suite type</InputLabel>
              <Select labelId="suite-type-label" label="Suite type" value={suiteType} onChange={(event) => setSuiteType(event.target.value as typeof suiteType)}>
                <MenuItem value="smoke">Smoke</MenuItem>
                <MenuItem value="feature">Feature</MenuItem>
                <MenuItem value="regression">Regression</MenuItem>
                <MenuItem value="deep_regression">Deep regression</MenuItem>
              </Select>
            </FormControl>
            <TextField label="Execution plan name (optional)" value={planName} onChange={(event) => setPlanName(event.target.value)} sx={{ minWidth: { md: 240 } }} />
            <Button
              variant="contained"
              startIcon={<AddTaskOutlinedIcon />}
              disabled={!sourceRunId || importPlan.isPending}
              onClick={() => importPlan.mutate()}
            >
              {importPlan.isPending ? "Importing…" : "Import test set"}
            </Button>
          </Stack>
          {history.isLoading && <LinearProgress sx={{ mt: 2 }} />}
          {!history.isLoading && completedRuns.length === 0 && <Alert severity="info" sx={{ mt: 2 }}>Complete a Test Design run before importing cases into execution.</Alert>}
          {importPlan.isError && <Alert severity="error" sx={{ mt: 2 }}>{apiErrorMessage(importPlan.error, "The Test Design set could not be imported.")}</Alert>}
        </CardContent>
      </Card>

      {plans.data && plans.data.length > 0 && (
        <Card variant="outlined" sx={{ mb: 3 }}>
          <CardContent>
            <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }}>
              <FormControl fullWidth>
                <InputLabel id="plan-label">Execution plan</InputLabel>
                <Select labelId="plan-label" label="Execution plan" value={planId} onChange={(event) => { setPlanId(event.target.value); setPreflightSignature(""); }}>
                  <MenuItem value=""><em>Choose an imported plan</em></MenuItem>
                  {plans.data.map((item) => <MenuItem key={item.id} value={item.id} title={item.name || item.source_title || undefined}><Box sx={{ maxWidth: { xs: 260, md: 560 }, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{planTitle(item)} · {item.selected_automated_cases} automated · {item.status}</Box></MenuItem>)}
                </Select>
              </FormControl>
              {currentPlan && <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip icon={<FactCheckOutlinedIcon />} label={`${currentPlan.total_cases} imported`} variant="outlined" />
                <Chip label={`${currentPlan.selected_automated_cases} automated`} color="primary" variant="outlined" />
                <Chip label={`${currentPlan.ready_cases} ready`} color="success" variant="outlined" />
                {currentPlan.blocked_cases > 0 && <Chip label={`${currentPlan.blocked_cases} blocked`} color="warning" variant="outlined" />}
              </Stack>}
            </Stack>
          </CardContent>
        </Card>
      )}

      {currentPlan && (
        <>
          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2}>
                <Box>
                  <Typography variant="h6" sx={{ fontWeight: 800 }}>{planTitle(currentPlan)}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    Imported from <strong>{currentPlan.source_title || "Test Design"}</strong>{currentPlan.source_created_at ? ` · ${new Date(currentPlan.source_created_at).toLocaleString()}` : ""}. The snapshot is independent of later Design edits.
                  </Typography>
                  {sourceRun?.source_document_analysis_id && <Chip size="small" label="Document Intelligence baseline" variant="outlined" clickable onClick={() => navigate("/documents")} sx={{ mt: 0.75 }} />}
                </Box>
                <Chip label={currentPlan.status} color={currentPlan.status === "ready" ? "success" : currentPlan.status === "blocked" ? "warning" : "info"} />
              </Stack>
              <Divider sx={{ my: 2 }} />
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ mb: 2 }}>
                <TextField size="small" label="Search imported cases" value={caseSearch} onChange={(event) => setCaseSearch(event.target.value)} />
                <FormControl size="small" sx={{ minWidth: 180 }}>
                  <InputLabel id="case-filter-label">Show</InputLabel>
                  <Select labelId="case-filter-label" label="Show" value={caseFilter} onChange={(event) => setCaseFilter(event.target.value)}>
                    <MenuItem value="all">All cases</MenuItem>
                    <MenuItem value="selected">Selected cases</MenuItem>
                    <MenuItem value="automation">Automation candidates</MenuItem>
                    <MenuItem value="blocked">Needs attention</MenuItem>
                  </Select>
                </FormControl>
                <Button size="small" onClick={() => {
                  const next = { ...selection };
                  currentCases.forEach((item) => { next[item.id] = item.is_automation_candidate; });
                  setSelection(next);
                  setSelectionDirty(true);
                }}>Select candidates</Button>
                <Button size="small" onClick={() => { setSelection(Object.fromEntries(currentCases.map((item) => [item.id, false]))); setSelectionDirty(true); }}>Clear selection</Button>
                <Box sx={{ flex: 1 }} />
                <Button variant="outlined" startIcon={<RuleOutlinedIcon />} disabled={saveSelection.isPending} onClick={() => saveSelection.mutate(undefined)}>
                  {saveSelection.isPending ? "Saving…" : "Save selection"}
                </Button>
              </Stack>
              <Grid container spacing={1.25} sx={{ mb: 2 }}>
                {[["Imported", currentPlan.total_cases, "Cases in this snapshot"], ["Selected", currentPlan.selected_cases, "Included in this plan"], ["Ready", currentPlan.ready_cases, "Eligible for automation"], ["Needs attention", needsAttentionCount, "Discovery, data or approval"]].map(([label, value, helper]) => <Grid key={String(label)} size={{ xs: 6, sm: 3 }}><Box sx={{ p: 1.2, borderRadius: 2, bgcolor: "action.hover", height: "100%" }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h6" sx={{ fontWeight: 800 }}>{value}</Typography><Typography variant="caption" color="text.secondary">{helper}</Typography></Box></Grid>)}
              </Grid>
              {saveSelection.isError && <Alert severity="error" sx={{ mb: 2 }}>{apiErrorMessage(saveSelection.error, "The case selection could not be saved.")}</Alert>}
              {selectionDirty && <Alert severity="info" sx={{ mb: 2 }}>You have unsaved case changes. Save the selection before running preflight.</Alert>}
              <Stack spacing={1.25}>
                {caseGroups.map(([group, items]) => <Box key={group}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}><Typography variant="subtitle2" sx={{ fontWeight: 800, textTransform: "capitalize" }}>{group.replace(/[_-]/g, " ")}</Typography><Chip size="small" label={`${items.length} ${items.length === 1 ? "case" : "cases"}`} /></Stack>
                  <Stack spacing={0.8}>
                    {items.map((item: ExecutionPlanCase) => {
                      const selected = Boolean(selection[item.id]);
                      const mode = modes[item.id] ?? item.execution_mode;
                      return <Box key={item.id} sx={{ border: "1px solid", borderColor: selected ? "primary.main" : "divider", borderRadius: 2, p: 1.1, bgcolor: selected ? "action.selected" : "background.paper" }}>
                        <Stack direction={{ xs: "column", md: "row" }} spacing={1.25} alignItems={{ md: "center" }}>
                          <Checkbox checked={selected} onChange={(event) => { setSelection((previous) => ({ ...previous, [item.id]: event.target.checked })); setSelectionDirty(true); }} inputProps={{ "aria-label": `Select ${item.test_case_key}` }} />
                          <Box sx={{ flex: 1, minWidth: 0 }}>
                            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                              <Typography fontWeight={800}>{item.test_case_key}</Typography>
                              <Chip size="small" label={item.test_type.replace(/_/g, " ")} />
                              <Chip size="small" label={`Risk: ${item.risk_level}`} color={item.risk_level === "high" ? "error" : "default"} variant="outlined" />
                              {item.is_automation_candidate && <Chip size="small" label="Design candidate" color="primary" variant="outlined" />}
                            </Stack>
                            <Typography variant="body2" sx={{ mt: 0.25 }}>{item.scenario}</Typography>
                            {item.blocker_reason && <Typography variant="caption" color="error.main">{item.blocker_reason}</Typography>}
                          </Box>
                          {selected && <FormControl size="small" sx={{ minWidth: 145 }}>
                            <InputLabel id={`mode-${item.id}`}>Mode</InputLabel>
                            <Select labelId={`mode-${item.id}`} label="Mode" value={mode} onChange={(event) => { setModes((previous) => ({ ...previous, [item.id]: event.target.value as "automated" | "manual" })); setSelectionDirty(true); }}>
                              <MenuItem value="automated">Automated</MenuItem>
                              <MenuItem value="manual">Manual review</MenuItem>
                            </Select>
                          </FormControl>}
                          <Chip size="small" label={selected ? item.readiness : "not selected"} color={selected ? readinessColor(item.readiness) : "default"} variant="outlined" />
                          {selected && <Button
                            size="small"
                            variant="text"
                            startIcon={<EditOutlinedIcon />}
                            onClick={() => openCaseEditor(item)}
                            sx={{ whiteSpace: "nowrap" }}
                          >
                            Edit steps/data
                          </Button>}
                        </Stack>
                      </Box>;
                    })}
                  </Stack>
                </Box>)}
                {!caseGroups.length && <Alert severity="info">No imported cases match this filter.</Alert>}
              </Stack>
            </CardContent>
          </Card>

          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 800, mb: 0.5 }}>Preflight and execute</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Choose a web URL or a mobile package. Preflight validates the target and selected snapshot before any test is run.</Typography>
              <Grid container spacing={2} alignItems="center">
                <Grid size={{ xs: 12, md: 3 }}>
                  <FormControl fullWidth size="small">
                    <InputLabel id="target-kind-label">Application target</InputLabel>
                    <Select labelId="target-kind-label" label="Application target" value={targetKind} onChange={(event) => setTargetKind(event.target.value as ExecutionTargetKind)}>
                      <MenuItem value="web">Web application</MenuItem>
                      <MenuItem value="android">Android APK</MenuItem>
                      <MenuItem value="ios">iOS IPA</MenuItem>
                    </Select>
                  </FormControl>
                </Grid>
                {targetKind === "web" ? (
                  <Grid size={{ xs: 12, md: 5 }}><TextField fullWidth size="small" label="Application target URL" placeholder="https://staging.example.com" value={baseUrl} onChange={(event) => { setBaseUrl(event.target.value); setPreflightSignature(""); }} helperText="Use a publicly reachable HTTPS staging URL." /></Grid>
                ) : (
                  <>
                    <Grid size={{ xs: 12, md: 4 }}>
                      <RepositoryAssetPicker
                        projectId={selectedProjectId}
                        value={appAssetId}
                        assets={mobileAssets.assets}
                        assetsLoading={mobileAssets.isLoading || mobileAssets.isFetching}
                        assetsError={mobileAssets.isError}
                        extensions={[targetKind === "ios" ? "ipa" : "apk"]}
                        cacheKey="execution-mobile-assets"
                        label={`Existing ${targetKind === "ios" ? "IPA" : "APK"} from repository`}
                        emptyLabel={`Upload a new ${targetKind === "ios" ? "IPA" : "APK"}`}
                        helperText="Select a reusable build from this project, or upload a new package beside it."
                        selectedAsset={selectedMobileAsset}
                        onChange={(value) => { setAppAssetId(value); setPreflightSignature(""); }}
                        onOpenRepository={() => navigate("/test-data/documents")}
                      />
                    </Grid>
                    <Grid size={{ xs: 12, md: 2 }}>
                      <Button component="label" fullWidth size="small" variant="outlined" startIcon={<CloudUploadOutlinedIcon />} disabled={appUpload.isPending}>
                        {appUpload.isPending ? "Uploading…" : "Upload package"}
                        <input hidden type="file" accept={targetKind === "ios" ? ".ipa,application/octet-stream" : ".apk,application/vnd.android.package-archive"} onChange={onMobileFile} />
                      </Button>
                    </Grid>
                  </>
                )}
                <Grid size={{ xs: 12, md: targetKind === "web" ? 4 : 3 }}><TextField fullWidth size="small" label="Run name (optional)" value={runName} onChange={(event) => setRunName(event.target.value)} /></Grid>
                {targetKind !== "web" && <>
                  <Grid size={{ xs: 12, md: 3 }}>
                    <FormControl fullWidth size="small">
                      <InputLabel id="mobile-provider-label">Execution provider</InputLabel>
                      <Select labelId="mobile-provider-label" label="Execution provider" value={provider} onChange={(event) => { setProvider(event.target.value as ExecutionProvider); setPreflightSignature(""); }}>
                        <MenuItem value="browserstack">BrowserStack real device</MenuItem>
                        <MenuItem value="appium">Custom / local Appium</MenuItem>
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid size={{ xs: 12, md: 3 }}><TextField fullWidth size="small" label="Device name" value={deviceName} onChange={(event) => { setDeviceName(event.target.value); setPreflightSignature(""); }} placeholder={targetKind === "ios" ? "iPhone 15" : "Google Pixel 8"} /></Grid>
                  <Grid size={{ xs: 12, md: 2 }}><TextField fullWidth size="small" label="OS version" value={platformVersion} onChange={(event) => { setPlatformVersion(event.target.value); setPreflightSignature(""); }} placeholder={targetKind === "ios" ? "17" : "14.0"} /></Grid>
                  {provider === "appium" && <>
                    <Grid size={{ xs: 12, md: 4 }}><TextField fullWidth size="small" label="Appium server URL (optional)" value={appiumUrl} onChange={(event) => { setAppiumUrl(event.target.value); setPreflightSignature(""); }} helperText="Hosted runs need a reachable HTTPS endpoint; local development can use 127.0.0.1." /></Grid>
                    <Grid size={{ xs: 12, md: 4 }}><TextField fullWidth size="small" label="Remote app reference (optional)" value={appiumApp} onChange={(event) => { setAppiumApp(event.target.value); setPreflightSignature(""); }} helperText="Required for a hosted Appium lab unless it shares the API filesystem." /></Grid>
                  </>}
                  <Grid size={{ xs: 12 }}>
                    <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                      <FormControlLabel control={<Switch size="small" checked={noReset} onChange={(event) => { setNoReset(event.target.checked); setPreflightSignature(""); }} />} label="Keep app state (no reset)" />
                      <FormControlLabel control={<Switch size="small" checked={autoGrantPermissions} onChange={(event) => { setAutoGrantPermissions(event.target.checked); setPreflightSignature(""); }} />} label="Auto-grant Android permissions" />
                    </Stack>
                  </Grid>
                </>}
                <Grid size={{ xs: 12 }}>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="flex-end">
                    <Button variant="outlined" startIcon={<RuleOutlinedIcon />} disabled={!targetConfigured || selectionDirty || preflight.isPending} onClick={() => preflight.mutate()}>{preflight.isPending ? "Checking…" : "Run preflight"}</Button>
                    <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={!canExecute} onClick={() => execute.mutate()}>{execute.isPending ? "Queuing…" : "Run selected"}</Button>
                  </Stack>
                </Grid>
              </Grid>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
                <Chip label={`${selectedAutomated.length} selected for automation`} color="primary" variant="outlined" />
                <Chip label={`${currentPlan.ready_cases} ready`} color="success" variant="outlined" />
                <Chip label={`${currentPlan.blocked_cases} blocked/approval`} color={currentPlan.blocked_cases ? "warning" : "default"} variant="outlined" />
                {preflightSignature && <Chip label="Preflight matches target" color="success" variant="outlined" />}
              </Stack>
              {inputRequirements.length > 0 && <Box sx={{ mt: 2, p: 1.75, border: "1px solid", borderColor: "warning.light", borderRadius: 2, bgcolor: "rgba(237, 108, 2, 0.04)" }}>
                <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" spacing={1} sx={{ mb: 1 }}>
                  <Box>
                    <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>Guided setup before execution</Typography>
                    <Typography variant="body2" color="text.secondary">
                      Preflight has walked the selected cases and found {inputRequirements.length} setup item{inputRequirements.length === 1 ? "" : "s"}. Provide safe references or edit the case; it will re-check every dependency before a run is enabled.
                    </Typography>
                  </Box>
                  <Chip size="small" label={`${unresolvedRequirements.length} unresolved`} color={unresolvedRequirements.length ? "warning" : "success"} variant="outlined" />
                </Stack>
                <Alert severity="info" sx={{ mb: 1.5 }}>
                  Use non-production references such as <strong>vault://qa/investor</strong> or <strong>dataset://seeded-customer-01</strong>. QTXpert never stores raw passwords, tokens, or OTPs.
                </Alert>
                {globalInputRequirements.length > 0 && <Stack spacing={1.25}>
                  {globalInputRequirements.map((requirement) => <TextField
                    key={requirement.key}
                    fullWidth
                    size="small"
                    label={requirement.label}
                    value={inputDraft[requirement.key] ?? ""}
                    onChange={(event) => {
                      setInputDraft((previous) => ({ ...previous, [requirement.key]: event.target.value }));
                      setInputDirty(true);
                      setPreflightSignature("");
                    }}
                    placeholder={requirement.category === "authentication" ? "vault://qa/role-or-credential" : requirement.category === "test_data" ? "dataset://seeded/non-production" : "reference://..."}
                    helperText={`${requirement.description}${requirement.case_keys.length ? ` Affects ${requirement.case_keys.join(", ")}.` : ""}`}
                  />)}
                  <Box>
                    <Button
                      variant="outlined"
                      size="small"
                      startIcon={<SaveOutlinedIcon />}
                      disabled={!inputDirty || saveInputs.isPending}
                      onClick={() => saveInputs.mutate()}
                    >
                      {saveInputs.isPending ? "Saving…" : "Save inputs"}
                    </Button>
                  </Box>
                </Stack>}
                {caseInputRequirements.length > 0 && <Stack spacing={0.8} sx={{ mt: globalInputRequirements.length ? 1.5 : 0 }}>
                  <Typography variant="caption" sx={{ fontWeight: 800, textTransform: "uppercase", letterSpacing: ".04em" }}>Case actions</Typography>
                  {caseInputRequirements.map((requirement) => {
                    const caseToEdit = currentCases.find((item) => requirement.case_ids.includes(item.id));
                    return <Stack key={requirement.key} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ p: 1, borderRadius: 1.5, bgcolor: "background.paper" }}>
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography variant="body2" fontWeight={800}>{requirement.label} · {requirement.case_keys.join(", ") || "selected case"}</Typography>
                        <Typography variant="caption" color="text.secondary">{requirement.description}</Typography>
                      </Box>
                      {caseToEdit && <Button size="small" variant="outlined" startIcon={<EditOutlinedIcon />} onClick={() => openCaseEditor(caseToEdit)}>Edit case</Button>}
                    </Stack>;
                  })}
                </Stack>}
              </Box>}
              {saveInputs.isError && <Alert severity="error" sx={{ mt: 2 }}>{apiErrorMessage(saveInputs.error, "The setup references could not be saved.")}</Alert>}
              {preflight.isSuccess && preflight.data && preflightSignature === targetSignature && <Alert severity="success" sx={{ mt: 2 }}>
                Preflight completed: {preflight.data.ready_cases} case{preflight.data.ready_cases === 1 ? " is" : "s are"} ready. {(preflight.data.input_requirements ?? []).filter((item) => !item.provided).length} setup item{(preflight.data.input_requirements ?? []).filter((item) => !item.provided).length === 1 ? " remains" : "s remain"} unresolved.
              </Alert>}
              {targetKind !== "web" && <Alert severity="info" sx={{ mt: 2 }}>Mobile results, device metadata and captured evidence are saved with the run in Test reports. The selected APK/IPA remains reusable in the project repository.</Alert>}
              {uploadError && <Alert severity="error" sx={{ mt: 2 }}>{uploadError}</Alert>}
              {mobileAssets.isError && <Alert severity="warning" sx={{ mt: 2 }}>Stored mobile packages could not be loaded. You can retry the page or upload a new package.</Alert>}
              {preflight.isError && <Alert severity="error" sx={{ mt: 2 }}>{apiErrorMessage(preflight.error, "The execution preflight failed.")}</Alert>}
              {execute.isError && <Alert severity="error" sx={{ mt: 2 }}>{apiErrorMessage(execute.error, "The execution could not be queued.")}</Alert>}
              {(currentPlan.blocked_cases > 0 || selectedAttention.length > 0) && <Alert severity="warning" sx={{ mt: 2 }}>
                Resolve {selectedAttention.length || currentPlan.blocked_cases} selected case{(selectedAttention.length || currentPlan.blocked_cases) === 1 ? "" : "s"} above. Preflight will re-check conversions, runtime discovery, approval, and data before execution is enabled.
              </Alert>}
            </CardContent>
          </Card>
        </>
      )}

      <Card variant="outlined">
        <CardContent>
          <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ md: "center" }} spacing={2} sx={{ mb: 1.5 }}>
            <Box>
              <Typography variant="h6" sx={{ fontWeight: 800 }}>Recent execution runs</Typography>
              <Typography variant="body2" color="text.secondary">A compact history of this project. Open any run for the full report, evidence and timeline.</Typography>
            </Box>
            <Button variant="outlined" endIcon={<OpenInNewOutlinedIcon />} onClick={() => navigate("/reports")}>Open Test reports</Button>
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1.5 }}>
            <TextField size="small" value={runSearch} onChange={(event) => setRunSearch(event.target.value)} placeholder="Search runs or targets" InputProps={{ startAdornment: <SearchOutlinedIcon sx={{ mr: 0.75, color: "text.secondary" }} /> }} sx={{ minWidth: { sm: 260 } }} />
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel id="execution-run-filter">Status</InputLabel>
              <Select labelId="execution-run-filter" label="Status" value={runFilter} onChange={(event) => setRunFilter(event.target.value)}>
                <MenuItem value="all">All statuses</MenuItem>
                <MenuItem value="running">Running</MenuItem>
                <MenuItem value="queued">Queued</MenuItem>
                <MenuItem value="completed">Completed</MenuItem>
                <MenuItem value="failed">Failed</MenuItem>
                <MenuItem value="cancelled">Cancelled</MenuItem>
              </Select>
            </FormControl>
            {runs.isFetching && <LinearProgress sx={{ flex: 1, alignSelf: "center" }} />}
          </Stack>
          {!runs.isLoading && !filteredExecutionRuns.length && <Alert severity="info">No execution runs match the current filter.</Alert>}
          <Stack spacing={0.8} sx={{ maxHeight: 300, overflowY: "auto" }}>
            {filteredExecutionRuns.map((run) => <Box key={run.id} onClick={() => navigate(`/reports?run=${run.id}`)} sx={{ p: 1.1, border: "1px solid", borderColor: "divider", borderRadius: 2, cursor: "pointer", transition: "border-color .15s, background-color .15s", "&:hover": { borderColor: "primary.main", bgcolor: "action.hover" } }}>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
                <Box sx={{ minWidth: 0, flex: 1 }}><Typography variant="body2" fontWeight={800} noWrap>{run.name}</Typography><Typography variant="caption" color="text.secondary" noWrap>{executionTargetLabel(run)} · {run.provider}</Typography></Box>
                <Chip size="small" label={run.status} color={runStatusColor(run.status)} />
                <Typography variant="caption" sx={{ whiteSpace: "nowrap" }}>{run.passed_tests}/{run.total_tests} passed</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: "nowrap" }}>{executionRunDate(run)}</Typography>
                <Button size="small" onClick={(event) => { event.stopPropagation(); navigate(`/reports?run=${run.id}`); }}>View</Button>
              </Stack>
            </Box>)}
          </Stack>
          {runs.isLoading && <LinearProgress sx={{ mt: 1.5 }} />}
          {!runs.isLoading && !filteredExecutionRuns.length && planRuns.length === 0 && <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>Runs will appear here after a successful preflight and execution.</Typography>}
        </CardContent>
      </Card>
      <Dialog open={Boolean(caseEditor)} onClose={() => { if (!saveSelection.isPending) setCaseEditor(null); }} fullWidth maxWidth="md">
        <DialogTitle>Edit case for execution</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Convert the generated journey into explicit safe commands. One command per line; unsupported prose is blocked instead of guessed.
          </Typography>
          <Stack spacing={2}>
            <TextField
              autoFocus
              fullWidth
              multiline
              minRows={5}
              label="Automation steps"
              value={caseEditor?.steps ?? ""}
              onChange={(event) => setCaseEditor((previous) => previous ? { ...previous, steps: event.target.value } : previous)}
              helperText="Web: navigate / click / fill locator :: value / assert-text / assert-url. Mobile also supports launch, tap, back, and assert-visible."
            />
            <TextField
              fullWidth
              multiline
              minRows={2}
              label="Expected result"
              value={caseEditor?.expectedResult ?? ""}
              onChange={(event) => setCaseEditor((previous) => previous ? { ...previous, expectedResult: event.target.value } : previous)}
            />
            <TextField
              fullWidth
              multiline
              minRows={3}
              label="Synthetic test data JSON (optional)"
              value={caseEditor?.testData ?? ""}
              onChange={(event) => setCaseEditor((previous) => previous ? { ...previous, testData: event.target.value } : previous)}
              placeholder={'{\n  "account_reference": "qa-customer-01"\n}'}
              helperText="Use references or synthetic values only. Passwords, tokens, and OTPs are rejected and never stored."
            />
            {caseEditorError && <Alert severity="error">{caseEditorError}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCaseEditor(null)} disabled={saveSelection.isPending}>Cancel</Button>
          <Button variant="contained" startIcon={<SaveOutlinedIcon />} onClick={saveCaseEditor} disabled={saveSelection.isPending}>
            {saveSelection.isPending ? "Saving…" : "Save and recheck"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

