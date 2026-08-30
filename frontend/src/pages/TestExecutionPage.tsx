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
import OpenInNewOutlinedIcon from "@mui/icons-material/OpenInNewOutlined";
import { AxiosError } from "axios";
import { executionPlansApi, executionsApi, testCasesApi, uploadsApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import PageHeader from "@/components/PageHeader";
import type { ExecutionPlan, ExecutionPlanCase, ExecutionProvider, ExecutionTargetKind, UploadedAsset } from "@/types/domain";

const STEPS = ["Import from Test Design", "Select cases", "Preflight and run", "Review evidence"];

function apiErrorMessage(reason: unknown, fallback: string): string {
  const detail = (reason as AxiosError<{ detail?: string }>)?.response?.data?.detail;
  return typeof detail === "string" ? detail : reason instanceof Error ? reason.message : fallback;
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

function mobileAssetExtension(asset: UploadedAsset) {
  const declared = (asset.extension || "").trim().toLowerCase();
  if (declared) return declared;
  const fromFilename = asset.filename.split(".").pop()?.trim().toLowerCase();
  return fromFilename || (asset.category || "").trim().toLowerCase();
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
  const [selection, setSelection] = useState<Record<string, boolean>>({});
  const [modes, setModes] = useState<Record<string, "automated" | "manual">>({});
  const [selectionDirty, setSelectionDirty] = useState(false);
  const [uploadError, setUploadError] = useState("");

  const history = useQuery({
    queryKey: ["execution-source-runs", selectedProjectId],
    queryFn: () => testCasesApi.historySummaries(selectedProjectId!, 200, 0).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
  });
  const mobileAssets = useQuery({
    queryKey: ["execution-mobile-assets", selectedProjectId],
    queryFn: () => uploadsApi.list({ project_id: selectedProjectId! }).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
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
  const availableMobileAssets = useMemo(
    () => (mobileAssets.data ?? []).filter((asset) =>
      (targetKind === "android" ? mobileAssetExtension(asset) === "apk" : targetKind === "ios" ? mobileAssetExtension(asset) === "ipa" : false)
      && !["autopilot_evidence", "execution_evidence"].includes(asset.category),
    ),
    [mobileAssets.data, targetKind],
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
    const selected = (mobileAssets.data ?? []).find((asset) => asset.id === appAssetId);
    if (selected && mobileAssetExtension(selected) !== (targetKind === "android" ? "apk" : "ipa")) {
      setAppAssetId("");
    }
    setPreflightSignature("");
  }, [appAssetId, mobileAssets.data, targetKind]);

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
    mutationFn: () => executionPlansApi.updateCases(
      planId,
      currentCases.map((item) => ({
        id: item.id,
        selected: Boolean(selection[item.id]),
        execution_mode: modes[item.id] ?? item.execution_mode,
      })),
    ).then((response) => response.data),
    onSuccess: (updated) => {
      queryClient.setQueryData(["execution-plan", updated.id], updated);
      queryClient.invalidateQueries({ queryKey: ["execution-plans", selectedProjectId] });
      setPreflightSignature("");
      setSelectionDirty(false);
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

  const selectedAutomated = currentCases.filter((item) => selection[item.id] && (modes[item.id] ?? item.execution_mode) === "automated");
  const readyCount = currentPlan?.ready_cases ?? 0;
  const canExecute = Boolean(
    currentPlan
    && selectedAutomated.length > 0
    && readyCount > 0
    && preflightSignature === targetSignature
    && !selectionDirty
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
                <Button variant="outlined" startIcon={<RuleOutlinedIcon />} disabled={saveSelection.isPending} onClick={() => saveSelection.mutate()}>
                  {saveSelection.isPending ? "Saving…" : "Save selection"}
                </Button>
              </Stack>
              {saveSelection.isError && <Alert severity="error" sx={{ mb: 2 }}>{apiErrorMessage(saveSelection.error, "The case selection could not be saved.")}</Alert>}
              {selectionDirty && <Alert severity="info" sx={{ mb: 2 }}>You have unsaved case changes. Save the selection before running preflight.</Alert>}
              <Stack spacing={1}>
                {filteredCases.map((item: ExecutionPlanCase) => {
                  const selected = Boolean(selection[item.id]);
                  const mode = modes[item.id] ?? item.execution_mode;
                  return <Box key={item.id} sx={{ border: "1px solid", borderColor: selected ? "primary.main" : "divider", borderRadius: 2, p: 1.25, bgcolor: selected ? "action.selected" : "background.paper" }}>
                    <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }}>
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
                    </Stack>
                  </Box>;
                })}
                {!filteredCases.length && <Alert severity="info">No imported cases match this filter.</Alert>}
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
                      <FormControl fullWidth size="small">
                        <InputLabel id="mobile-asset-label">APK / IPA package</InputLabel>
                        <Select labelId="mobile-asset-label" label="APK / IPA package" value={appAssetId} onChange={(event) => { setAppAssetId(event.target.value); setPreflightSignature(""); }}>
                          <MenuItem value=""><em>Select a stored {targetKind === "ios" ? "IPA" : "APK"}</em></MenuItem>
                          {availableMobileAssets.map((asset) => <MenuItem key={asset.id} value={asset.id} title={asset.filename}><Box sx={{ maxWidth: { xs: 260, md: 380 }, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{asset.filename} · {(asset.size_bytes / 1024 / 1024).toFixed(1)} MB</Box></MenuItem>)}
                        </Select>
                      </FormControl>
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
              {targetKind !== "web" && <Alert severity="info" sx={{ mt: 2 }}>Mobile results, device metadata and captured evidence are saved with the run in Test reports. The selected APK/IPA remains reusable in the project repository.</Alert>}
              {uploadError && <Alert severity="error" sx={{ mt: 2 }}>{uploadError}</Alert>}
              {mobileAssets.isError && <Alert severity="warning" sx={{ mt: 2 }}>Stored mobile packages could not be loaded. You can retry the page or upload a new package.</Alert>}
              {preflight.isError && <Alert severity="error" sx={{ mt: 2 }}>{apiErrorMessage(preflight.error, "The execution preflight failed.")}</Alert>}
              {execute.isError && <Alert severity="error" sx={{ mt: 2 }}>{apiErrorMessage(execute.error, "The execution could not be queued.")}</Alert>}
              {currentPlan.blocked_cases > 0 && <Alert severity="warning" sx={{ mt: 2 }}>Some selected cases need conversion, runtime discovery, or approval. They will not be silently executed.</Alert>}
            </CardContent>
          </Card>
        </>
      )}

      <Card variant="outlined">
        <CardContent>
          <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} spacing={2}>
            <Box>
              <Typography variant="h6" sx={{ fontWeight: 800 }}>Results live in Test reports</Typography>
              <Typography variant="body2" color="text.secondary">Execution history, per-case outcomes, defects and mobile evidence are report-owned. Original packages remain available in Repositories → Documents for reuse.</Typography>
            </Box>
            <Button variant="outlined" endIcon={<OpenInNewOutlinedIcon />} onClick={() => navigate("/reports")}>Open Test reports</Button>
          </Stack>
          {runs.isFetching && <LinearProgress sx={{ mt: 2 }} />}
          {!runs.isLoading && planRuns.length > 0 && <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>{planRuns.slice(0, 3).map((run) => <Chip key={run.id} label={`${run.name}: ${run.status}`} color={runStatusColor(run.status)} variant="outlined" />)}</Stack>}
          {!runs.isLoading && !planRuns.length && <Alert severity="info" sx={{ mt: 2 }}>No execution runs for this plan yet. Select cases and run preflight first.</Alert>}
        </CardContent>
      </Card>
    </Box>
  );
}
