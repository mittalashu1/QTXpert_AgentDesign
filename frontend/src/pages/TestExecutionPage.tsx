import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
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
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import AddTaskOutlinedIcon from "@mui/icons-material/AddTaskOutlined";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import RuleOutlinedIcon from "@mui/icons-material/RuleOutlined";
import ReplayOutlinedIcon from "@mui/icons-material/ReplayOutlined";
import { AxiosError } from "axios";
import { executionPlansApi, executionsApi, testCasesApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import PageHeader from "@/components/PageHeader";
import type { ExecutionPlan, ExecutionPlanCase, ExecutionResult, ExecutionRun } from "@/types/domain";

const STEPS = ["Import from Test Design", "Select cases", "Preflight and run", "Review evidence"];

function apiErrorMessage(reason: unknown, fallback: string): string {
  const detail = (reason as AxiosError<{ detail?: string }>)?.response?.data?.detail;
  return typeof detail === "string" ? detail : reason instanceof Error ? reason.message : fallback;
}

function planTitle(plan: ExecutionPlan) {
  return plan.name || plan.source_title || "Execution plan";
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
  const queryClient = useQueryClient();
  const [sourceRunId, setSourceRunId] = useState("");
  const [planId, setPlanId] = useState("");
  const [planName, setPlanName] = useState("");
  const [suiteType, setSuiteType] = useState<"smoke" | "feature" | "regression" | "deep_regression">("regression");
  const [baseUrl, setBaseUrl] = useState("");
  const [runName, setRunName] = useState("");
  const [preflightBaseUrl, setPreflightBaseUrl] = useState("");
  const [caseFilter, setCaseFilter] = useState("all");
  const [caseSearch, setCaseSearch] = useState("");
  const [selection, setSelection] = useState<Record<string, boolean>>({});
  const [modes, setModes] = useState<Record<string, "automated" | "manual">>({});
  const [selectionDirty, setSelectionDirty] = useState(false);
  const [defectResult, setDefectResult] = useState<ExecutionResult | null>(null);
  const [defectTitle, setDefectTitle] = useState("");
  const [defectDescription, setDefectDescription] = useState("");

  const history = useQuery({
    queryKey: ["execution-source-runs", selectedProjectId],
    queryFn: () => testCasesApi.historySummaries(selectedProjectId!, 200, 0).then((response) => response.data),
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

  const completedRuns = useMemo(
    () => (history.data ?? []).filter((run) => run.status === "completed" && run.test_case_count > 0),
    [history.data],
  );
  const currentPlan = plan.data;
  const currentCases = useMemo(() => currentPlan?.cases ?? [], [currentPlan]);

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
      setPreflightBaseUrl("");
      setSelectionDirty(false);
    },
  });

  const preflight = useMutation({
    mutationFn: () => executionPlansApi.preflight(planId, baseUrl.trim()).then((response) => response.data),
    onSuccess: (updated) => {
      queryClient.setQueryData(["execution-plan", updated.id], updated);
      queryClient.invalidateQueries({ queryKey: ["execution-plans", selectedProjectId] });
      setPreflightBaseUrl(baseUrl.trim());
    },
  });

  const execute = useMutation({
    mutationFn: () => executionPlansApi.execute(planId, { base_url: baseUrl.trim(), name: runName.trim() || undefined }).then((response) => response.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["executions", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["execution-plan", planId] });
      queryClient.invalidateQueries({ queryKey: ["execution-plans", selectedProjectId] });
    },
  });

  const rerun = useMutation({
    mutationFn: (run: ExecutionRun) => executionPlansApi.rerun(planId, run.id).then((response) => response.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["executions", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["execution-plan", planId] });
    },
  });

  const createDefect = useMutation({
    mutationFn: () => executionsApi.createDefect(defectResult!.id, {
      title: defectTitle,
      description: defectDescription,
      severity: "major",
    }),
    onSuccess: () => {
      setDefectResult(null);
      setDefectTitle("");
      setDefectDescription("");
      queryClient.invalidateQueries({ queryKey: ["executions", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["dashboard", selectedProjectId] });
    },
  });

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
    && preflightBaseUrl === baseUrl.trim()
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
                  <MenuItem key={run.id} value={run.id}>
                    {run.title || run.requirement_summary || `${run.generation_profile} test set`} · {run.test_case_count} cases · {new Date(run.created_at).toLocaleString()}
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
                <Select labelId="plan-label" label="Execution plan" value={planId} onChange={(event) => { setPlanId(event.target.value); setPreflightBaseUrl(""); }}>
                  <MenuItem value=""><em>Choose an imported plan</em></MenuItem>
                  {plans.data.map((item) => <MenuItem key={item.id} value={item.id}>{planTitle(item)} · {item.selected_automated_cases} automated · {item.status}</MenuItem>)}
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
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Preflight compiles the selected snapshot into the supported execution DSL. Unsupported or business-impacting steps remain visible as blockers.</Typography>
              <Grid container spacing={2} alignItems="center">
                <Grid size={{ xs: 12, md: 5 }}><TextField fullWidth label="Application target URL" placeholder="https://staging.example.com" value={baseUrl} onChange={(event) => { setBaseUrl(event.target.value); setPreflightBaseUrl(""); }} /></Grid>
                <Grid size={{ xs: 12, md: 4 }}><TextField fullWidth label="Run name (optional)" value={runName} onChange={(event) => setRunName(event.target.value)} /></Grid>
                <Grid size={{ xs: 12, md: 3 }}><Stack direction="row" spacing={1}><Button fullWidth variant="outlined" startIcon={<RuleOutlinedIcon />} disabled={!baseUrl.trim() || selectionDirty || preflight.isPending} onClick={() => preflight.mutate()}>{preflight.isPending ? "Checking…" : "Run preflight"}</Button><Button fullWidth variant="contained" startIcon={<PlayArrowIcon />} disabled={!canExecute} onClick={() => execute.mutate()}>{execute.isPending ? "Queuing…" : "Run selected"}</Button></Stack></Grid>
              </Grid>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
                <Chip label={`${selectedAutomated.length} selected for automation`} color="primary" variant="outlined" />
                <Chip label={`${currentPlan.ready_cases} ready`} color="success" variant="outlined" />
                <Chip label={`${currentPlan.blocked_cases} blocked/approval`} color={currentPlan.blocked_cases ? "warning" : "default"} variant="outlined" />
                {preflightBaseUrl && <Chip label="Preflight matches target" color="success" variant="outlined" />}
              </Stack>
              {preflight.isError && <Alert severity="error" sx={{ mt: 2 }}>{apiErrorMessage(preflight.error, "The execution preflight failed.")}</Alert>}
              {execute.isError && <Alert severity="error" sx={{ mt: 2 }}>{apiErrorMessage(execute.error, "The execution could not be queued.")}</Alert>}
              {currentPlan.blocked_cases > 0 && <Alert severity="warning" sx={{ mt: 2 }}>Some selected cases need conversion, runtime discovery, or approval. They will not be silently executed.</Alert>}
            </CardContent>
          </Card>
        </>
      )}

      <Card variant="outlined">
        <CardContent>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
            <Box><Typography variant="h6" sx={{ fontWeight: 800 }}>Execution evidence</Typography><Typography variant="body2" color="text.secondary">Runs remain linked to their imported plan and source Test Design snapshot.</Typography></Box>
            {runs.isFetching && <LinearProgress sx={{ width: 120 }} />}
          </Stack>
          <Stack spacing={1.5}>
            {planRuns.map((run) => <Card key={run.id} variant="outlined"><CardContent>
              <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1}>
                <Box><Typography fontWeight={800}>{run.name}</Typography><Typography variant="body2" color="text.secondary">{run.browser} · {run.base_url} · {new Date(run.created_at).toLocaleString()}</Typography></Box>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap><Chip label={run.status} color={runStatusColor(run.status)} /><Chip label={`${run.passed_tests} passed`} variant="outlined" /><Chip label={`${run.failed_tests} failed`} variant="outlined" color="error" /><Chip label={`${run.blocked_tests} blocked`} variant="outlined" color="warning" />{currentPlan && <Button size="small" startIcon={<ReplayOutlinedIcon />} disabled={rerun.isPending || ["queued", "running"].includes(run.status)} onClick={() => rerun.mutate(run)}>Rerun</Button>}</Stack>
              </Stack>
              {run.results.length > 0 && <Stack spacing={1} sx={{ mt: 2 }}>{run.results.map((result) => <Box key={result.id} sx={{ p: 1.25, borderRadius: 2, bgcolor: "action.hover" }}><Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1}><Box><Typography variant="body2" fontWeight={700}>{result.test_case_key} · {result.scenario}</Typography><Typography variant="caption" color={result.status === "failed" ? "error.main" : "text.secondary"}>{result.error_message ?? `${result.duration_ms ?? 0} ms`}</Typography></Box><Stack direction="row" spacing={1} alignItems="center"><Chip size="small" label={result.status} color={result.status === "passed" ? "success" : result.status === "failed" ? "error" : result.status === "blocked" ? "warning" : "default"} />{result.status === "failed" && !result.defects.length && <Button size="small" color="error" onClick={() => { setDefectResult(result); setDefectTitle(`Failure: ${result.scenario}`); setDefectDescription(result.error_message ?? "Execution failed."); }}>Log defect</Button>}{result.defects.map((defect) => <Chip key={defect.id} size="small" label={defect.defect_key} variant="outlined" />)}</Stack></Stack></Box>)}</Stack>}
            </CardContent></Card>)}
            {!runs.isLoading && !planRuns.length && <Alert severity="info">No execution runs for this plan yet. Import a completed Design set, select cases, and run preflight first.</Alert>}
          </Stack>
        </CardContent>
      </Card>

      <Dialog open={Boolean(defectResult)} onClose={() => setDefectResult(null)} fullWidth maxWidth="sm">
        <DialogTitle>Log defect from execution evidence</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{ pt: 1 }}><TextField label="Title" value={defectTitle} onChange={(event) => setDefectTitle(event.target.value)} fullWidth /><TextField label="Description" value={defectDescription} onChange={(event) => setDefectDescription(event.target.value)} multiline minRows={4} fullWidth /><Alert severity="info">The defect remains linked to the failed execution result and imported test snapshot.</Alert></Stack></DialogContent>
        <DialogActions><Button onClick={() => setDefectResult(null)}>Cancel</Button><Button variant="contained" color="error" disabled={!defectTitle || !defectDescription || createDefect.isPending} onClick={() => createDefect.mutate()}>Create defect</Button></DialogActions>
      </Dialog>
    </Box>
  );
}

