import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { AxiosError } from "axios";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  LinearProgress,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import ReplayOutlinedIcon from "@mui/icons-material/ReplayOutlined";
import SearchOutlinedIcon from "@mui/icons-material/SearchOutlined";
import TimelineOutlinedIcon from "@mui/icons-material/TimelineOutlined";
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import { dashboardApi, executionPlansApi, executionsApi, uploadsApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import PageHeader from "@/components/PageHeader";
import type { ExecutionResult, ExecutionRun } from "@/types/domain";

type RunFilter = "all" | ExecutionRun["status"];
type ResultFilter = "all" | ExecutionResult["status"];

function statusColor(status: string): "success" | "error" | "warning" | "info" | "default" {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  if (status === "queued") return "warning";
  return "info";
}

function resultColor(status: string): "success" | "error" | "warning" | "info" | "default" {
  if (status === "passed") return "success";
  if (status === "failed") return "error";
  if (status === "blocked") return "warning";
  if (status === "pending") return "info";
  return "default";
}

function displayStatus(value: string) {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function targetLabel(run: ExecutionRun) {
  const targetKind = run.target_kind || "web";
  if (targetKind === "android") return `Android · ${run.device_name || "device"}${run.platform_version ? ` · ${run.platform_version}` : ""}`;
  if (targetKind === "ios") return `iOS · ${run.device_name || "device"}${run.platform_version ? ` · ${run.platform_version}` : ""}`;
  return `Web · ${run.base_url || "target unavailable"}`;
}

function providerLabel(run: ExecutionRun) {
  return run.provider || (run.target_kind === "web" ? "playwright" : run.browser) || "provider unavailable";
}

function runDate(run: ExecutionRun) {
  return new Date(run.completed_at || run.started_at || run.created_at).toLocaleString();
}

function durationLabel(durationMs: number | null | undefined) {
  if (durationMs === null || durationMs === undefined) return "Duration unavailable";
  if (durationMs < 1000) return `${durationMs} ms`;
  const seconds = durationMs / 1000;
  return seconds < 60 ? `${seconds.toFixed(1)} s` : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function runDuration(run: ExecutionRun) {
  if (!run.started_at) return "Duration unavailable";
  const end = run.completed_at ? new Date(run.completed_at).getTime() : new Date(run.created_at).getTime();
  const start = new Date(run.started_at).getTime();
  return durationLabel(Math.max(0, end - start));
}

function evidenceIds(run: ExecutionRun) {
  const ids = new Set<string>();
  run.results.forEach((result) => {
    [result.evidence?.screenshot_asset_id, result.evidence?.page_source_asset_id].forEach((value) => {
      if (typeof value === "string" && value) ids.add(value);
    });
  });
  return [...ids];
}

function resultCounts(run: ExecutionRun) {
  const results = run.results ?? [];
  const fromResults = {
    passed: results.filter((result) => result.status === "passed").length,
    failed: results.filter((result) => result.status === "failed").length,
    blocked: results.filter((result) => result.status === "blocked").length,
    skipped: results.filter((result) => result.status === "skipped").length,
    pending: results.filter((result) => result.status === "pending").length,
  };
  const total = Math.max(run.total_tests || 0, results.length);
  if (!results.length) {
    const accounted = (run.passed_tests || 0) + (run.failed_tests || 0) + (run.blocked_tests || 0);
    return { total, passed: run.passed_tests || 0, failed: run.failed_tests || 0, blocked: run.blocked_tests || 0, skipped: 0, pending: Math.max(0, total - accounted) };
  }
  const accounted = fromResults.passed + fromResults.failed + fromResults.blocked + fromResults.skipped + fromResults.pending;
  return { total, ...fromResults, pending: fromResults.pending + Math.max(0, total - accounted) };
}

function OverviewCount({ color, label, value }: { color: string; label: string; value: number }) {
  return <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between"><Stack direction="row" spacing={0.75} alignItems="center"><Box sx={{ width: 9, height: 9, borderRadius: "50%", bgcolor: color }} /><Typography variant="body2">{label}</Typography></Stack><Typography variant="body2" fontWeight={800}>{value}</Typography></Stack>;
}

function RunOverview({ run, counts }: { run: ExecutionRun; counts: ReturnType<typeof resultCounts> }) {
  const total = Math.max(counts.total, 1);
  const passedStop = counts.passed / total * 100;
  const failedStop = passedStop + counts.failed / total * 100;
  const blockedStop = failedStop + counts.blocked / total * 100;
  const skippedStop = blockedStop + counts.skipped / total * 100;
  const background = `conic-gradient(#1f9d68 0% ${passedStop}%, #d84b4b ${passedStop}% ${failedStop}%, #d28a22 ${failedStop}% ${blockedStop}%, #7d8797 ${blockedStop}% ${skippedStop}%, #dfe4e8 ${skippedStop}% 100%)`;
  return <Card variant="outlined" sx={{ height: "100%" }}>
    <CardContent>
      <Stack direction="row" justifyContent="space-between" alignItems="center"><Typography variant="h6" fontWeight={800}>Run overview</Typography><Chip size="small" label={displayStatus(run.status)} color={statusColor(run.status)} /></Stack>
      <Box sx={{ width: 164, height: 164, borderRadius: "50%", background, position: "relative", mx: "auto", my: 2.25, display: "grid", placeItems: "center" }} aria-label={`${counts.passed} passed, ${counts.failed} failed, ${counts.blocked} blocked, ${counts.pending} pending`}>
        <Box sx={{ width: 112, height: 112, borderRadius: "50%", bgcolor: "background.paper", display: "grid", placeItems: "center", alignContent: "center" }}><Typography variant="h4" fontWeight={800}>{counts.total}</Typography><Typography variant="caption" color="text.secondary">tests</Typography></Box>
      </Box>
      <Stack spacing={0.9}><OverviewCount color="#1f9d68" label="Passed" value={counts.passed} /><OverviewCount color="#d84b4b" label="Failed" value={counts.failed} /><OverviewCount color="#d28a22" label="Blocked" value={counts.blocked} /><OverviewCount color="#7d8797" label="Skipped / pending" value={counts.skipped + counts.pending} /></Stack>
      <Divider sx={{ my: 2 }} />
      <Stack spacing={1.25}><Box><Typography variant="caption" color="text.secondary">Target</Typography><Typography variant="body2" fontWeight={700}>{targetLabel(run)}</Typography></Box><Box><Typography variant="caption" color="text.secondary">Provider</Typography><Typography variant="body2" fontWeight={700}>{providerLabel(run)}</Typography></Box><Box><Typography variant="caption" color="text.secondary">Started</Typography><Typography variant="body2" fontWeight={700}>{run.started_at ? new Date(run.started_at).toLocaleString() : "Not started"}</Typography></Box><Box><Typography variant="caption" color="text.secondary">Duration</Typography><Typography variant="body2" fontWeight={700}>{runDuration(run)}</Typography></Box></Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 2 }}>Pass rate is calculated as passed tests ÷ total tests. Pending and blocked cases remain visible until conclusive evidence is available.</Typography>
    </CardContent>
  </Card>;
}

export default function TestReportsPage() {
  const { selectedProjectId } = useSelectedProject();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState(searchParams.get("run") || "");
  const [runSearch, setRunSearch] = useState("");
  const [runFilter, setRunFilter] = useState<RunFilter>("all");
  const [resultSearch, setResultSearch] = useState("");
  const [resultFilter, setResultFilter] = useState<ResultFilter>("all");
  const [downloadError, setDownloadError] = useState("");

  const summary = useQuery({
    queryKey: ["dashboard", selectedProjectId],
    queryFn: () => dashboardApi.summary(selectedProjectId!).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
  });
  const runs = useQuery({
    queryKey: ["executions", selectedProjectId],
    queryFn: () => executionsApi.list(selectedProjectId!).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
    refetchInterval: (query) => query.state.data?.some((run) => ["queued", "running"].includes(run.status)) ? 4000 : false,
  });

  const filteredRuns = useMemo(() => {
    const search = runSearch.trim().toLowerCase();
    return [...(runs.data ?? [])]
      .filter((run) => runFilter === "all" || run.status === runFilter)
      .filter((run) => !search || `${run.name} ${targetLabel(run)} ${providerLabel(run)}`.toLowerCase().includes(search))
      .sort((left, right) => new Date(right.completed_at || right.started_at || right.created_at).getTime() - new Date(left.completed_at || left.started_at || left.created_at).getTime());
  }, [runFilter, runSearch, runs.data]);

  const selectedRun = useMemo(() => (runs.data ?? []).find((run) => run.id === selectedRunId) ?? null, [runs.data, selectedRunId]);
  const selectedCounts = useMemo(() => selectedRun ? resultCounts(selectedRun) : null, [selectedRun]);
  const selectedResults = useMemo(() => {
    if (!selectedRun) return [];
    const search = resultSearch.trim().toLowerCase();
    return selectedRun.results.filter((result) => {
      const matchesFilter = resultFilter === "all" || result.status === resultFilter;
      const matchesSearch = !search || `${result.test_case_key} ${result.scenario} ${result.error_message || ""}`.toLowerCase().includes(search);
      return matchesFilter && matchesSearch;
    });
  }, [resultFilter, resultSearch, selectedRun]);

  useEffect(() => {
    const queryRun = searchParams.get("run");
    if (queryRun && queryRun !== selectedRunId) setSelectedRunId(queryRun);
  }, [searchParams, selectedRunId]);

  useEffect(() => {
    if (!runs.data?.length) return;
    if (!selectedRunId || !runs.data.some((run) => run.id === selectedRunId)) {
      const latest = [...runs.data].sort((left, right) => new Date(right.completed_at || right.started_at || right.created_at).getTime() - new Date(left.completed_at || left.started_at || left.created_at).getTime())[0];
      setSelectedRunId(latest.id);
      setSearchParams({ run: latest.id }, { replace: true });
    }
  }, [runs.data, selectedRunId, setSearchParams]);

  const rerun = useMutation({
    mutationFn: (run: ExecutionRun) => {
      if (!run.execution_plan_id) throw new Error("This legacy run is not linked to an execution plan.");
      return executionPlansApi.rerun(run.execution_plan_id, run.id).then((response) => response.data);
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["executions", selectedProjectId] });
      setSelectedRunId(created.id);
      setSearchParams({ run: created.id });
    },
  });

  const chooseRun = (run: ExecutionRun) => {
    setSelectedRunId(run.id);
    setSearchParams({ run: run.id });
    setResultSearch("");
    setResultFilter("all");
  };

  const downloadEvidence = async (assetId: string, filename: string) => {
    try {
      setDownloadError("");
      const response = await uploadsApi.download(assetId);
      const url = window.URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (reason: unknown) {
      const detail = (reason as AxiosError<{ detail?: string }>)?.response?.data?.detail;
      setDownloadError(typeof detail === "string" ? detail : reason instanceof Error ? reason.message : "Evidence download failed");
    }
  };

  if (!selectedProjectId) return <Alert severity="info">Select a project to view reports.</Alert>;

  const summaryTotal = summary.data?.total_execution_tests ?? 0;
  const summaryPassed = summary.data?.passed_tests ?? 0;
  const summaryPassRate = summaryTotal > 0 ? Math.round(summaryPassed / summaryTotal * 100) : summary.data?.pass_rate ?? 0;
  const metricCards = selectedRun && selectedCounts
    ? [["Tests in run", selectedCounts.total, "Selected execution snapshot"], ["Pass rate", `${Math.round(selectedCounts.passed / Math.max(selectedCounts.total, 1) * 100)}%`, "Passed ÷ total tests"], ["Failed", selectedCounts.failed, "Needs triage"], ["Blocked / pending", selectedCounts.blocked + selectedCounts.pending + selectedCounts.skipped, "Awaiting conclusive evidence"]]
    : [["Tests executed", summaryTotal, "Across recorded runs"], ["Pass rate", `${summaryPassRate}%`, "Passed ÷ total tests"], ["Execution runs", summary.data?.execution_runs ?? 0, "Recorded cycles"], ["Open defects", summary.data?.open_defects ?? 0, "Requiring triage"]];

  return <Box>
    <PageHeader eyebrow="QUALITY INTELLIGENCE" title="Test reports" description="A concise, traceable view of every execution, result and evidence trail." actions={<Tooltip title="Refresh reports"><IconButton onClick={() => { void runs.refetch(); void summary.refetch(); }} aria-label="Refresh reports"><RefreshOutlinedIcon /></IconButton></Tooltip>} />
    <Grid container spacing={1.5} sx={{ mb: 2.5 }}>{metricCards.map(([label, value, helper]) => <Grid key={String(label)} size={{ xs: 6, md: 3 }}><Card variant="outlined" sx={{ height: "100%" }}><CardContent sx={{ p: 1.5, "&:last-child": { pb: 1.5 } }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h5" sx={{ mt: 0.35, fontWeight: 800 }}>{value}</Typography><Typography variant="caption" color="text.secondary">{helper}</Typography></CardContent></Card></Grid>)}</Grid>

    {downloadError && <Alert severity="error" onClose={() => setDownloadError("")} sx={{ mb: 2 }}>{downloadError}</Alert>}
    {runs.isLoading && <LinearProgress sx={{ mb: 2 }} />}
    <Grid container spacing={2} alignItems="stretch">
      <Grid size={{ xs: 12, lg: 3 }}>
        <Card variant="outlined" sx={{ height: "100%" }}>
          <CardContent sx={{ p: 1.5, "&:last-child": { pb: 1.5 } }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.25 }}><Box><Typography variant="h6" fontWeight={800}>Test runs</Typography><Typography variant="caption" color="text.secondary">Select a run to inspect</Typography></Box><Chip size="small" label={`${runs.data?.length ?? 0} total`} /></Stack>
            <TextField size="small" fullWidth value={runSearch} onChange={(event) => setRunSearch(event.target.value)} placeholder="Search runs or targets" InputProps={{ startAdornment: <SearchOutlinedIcon sx={{ mr: 0.75, color: "text.secondary" }} /> }} sx={{ mb: 1 }} />
            <FormControl size="small" fullWidth sx={{ mb: 1.25 }}><InputLabel id="report-run-filter">Status</InputLabel><Select labelId="report-run-filter" label="Status" value={runFilter} onChange={(event) => setRunFilter(event.target.value as RunFilter)}><MenuItem value="all">All statuses</MenuItem><MenuItem value="running">Running</MenuItem><MenuItem value="queued">Queued</MenuItem><MenuItem value="completed">Completed</MenuItem><MenuItem value="failed">Failed</MenuItem><MenuItem value="cancelled">Cancelled</MenuItem></Select></FormControl>
            {!runs.isLoading && !filteredRuns.length && <Alert severity="info">No runs match this filter.</Alert>}
            <Stack spacing={0.75} sx={{ maxHeight: { xs: 300, lg: "calc(100vh - 350px)" }, overflowY: "auto", pr: 0.25 }}>
              {filteredRuns.map((run) => <Box key={run.id} role="button" tabIndex={0} onClick={() => chooseRun(run)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); chooseRun(run); } }} sx={{ p: 1.1, border: "1px solid", borderColor: run.id === selectedRunId ? "primary.main" : "divider", borderRadius: 1.75, cursor: "pointer", bgcolor: run.id === selectedRunId ? "action.selected" : "background.paper", transition: "border-color .15s, background-color .15s", "&:hover": { borderColor: "primary.main" }, "&:focus-visible": { outline: "2px solid", outlineColor: "primary.main", outlineOffset: 1 } }}>
                <Stack direction="row" spacing={0.75} alignItems="center"><Typography variant="body2" fontWeight={800} noWrap sx={{ minWidth: 0, flex: 1 }}>{run.name || "Untitled run"}</Typography><Chip size="small" label={displayStatus(run.status)} color={statusColor(run.status)} sx={{ height: 21, "& .MuiChip-label": { px: 0.75, fontSize: ".66rem" } }} /></Stack>
                <Typography variant="caption" color="text.secondary" noWrap display="block" sx={{ mt: 0.35 }}>{targetLabel(run)}</Typography>
                <Stack direction="row" justifyContent="space-between" sx={{ mt: 0.65 }}><Typography variant="caption">{run.passed_tests}/{run.total_tests} passed</Typography><Typography variant="caption" color="text.secondary">{runDate(run)}</Typography></Stack>
              </Box>)}
            </Stack>
          </CardContent>
        </Card>
      </Grid>

      <Grid size={{ xs: 12, lg: 6 }}>
        <Card variant="outlined" sx={{ height: "100%" }}>
          <CardContent>
            {!selectedRun || !selectedCounts ? <Alert severity="info">Select a run to inspect its results.</Alert> : <>
              <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1.25}>
                <Box sx={{ minWidth: 0 }}><Stack direction="row" spacing={0.75} alignItems="center"><TimelineOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800} noWrap>{selectedRun.name || "Untitled run"}</Typography></Stack><Typography variant="body2" color="text.secondary" sx={{ mt: 0.35 }}>{targetLabel(selectedRun)} · {providerLabel(selectedRun)} · {runDate(selectedRun)}</Typography></Box>
                <Stack direction="row" spacing={0.8} alignItems="center"><Chip label={displayStatus(selectedRun.status)} color={statusColor(selectedRun.status)} /><Button size="small" variant="outlined" startIcon={<ReplayOutlinedIcon />} disabled={!selectedRun.execution_plan_id || rerun.isPending || ["queued", "running"].includes(selectedRun.status)} onClick={() => rerun.mutate(selectedRun)}>Rerun</Button></Stack>
              </Stack>
              {rerun.isError && <Alert severity="error" sx={{ mt: 2 }}>{rerun.error instanceof Error ? rerun.error.message : "The run could not be queued again."}</Alert>}
              <Divider sx={{ my: 2 }} />
              <Grid container spacing={1} sx={{ mb: 2 }}>{[["Total", selectedCounts.total], ["Passed", selectedCounts.passed], ["Failed", selectedCounts.failed], ["Blocked", selectedCounts.blocked + selectedCounts.pending + selectedCounts.skipped]].map(([label, value]) => <Grid key={String(label)} size={{ xs: 6, sm: 3 }}><Box sx={{ p: 1.1, borderRadius: 1.75, bgcolor: "action.hover" }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h6" fontWeight={800}>{value}</Typography></Box></Grid>)}</Grid>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1.25 }}><TextField size="small" fullWidth value={resultSearch} onChange={(event) => setResultSearch(event.target.value)} placeholder="Search cases or errors" InputProps={{ startAdornment: <SearchOutlinedIcon sx={{ mr: 0.75, color: "text.secondary" }} /> }} /><FormControl size="small" sx={{ minWidth: 170 }}><InputLabel id="report-result-filter">Result status</InputLabel><Select labelId="report-result-filter" label="Result status" value={resultFilter} onChange={(event) => setResultFilter(event.target.value as ResultFilter)}><MenuItem value="all">All results</MenuItem><MenuItem value="passed">Passed</MenuItem><MenuItem value="failed">Failed</MenuItem><MenuItem value="blocked">Blocked</MenuItem><MenuItem value="skipped">Skipped</MenuItem><MenuItem value="pending">Pending</MenuItem></Select></FormControl></Stack>
              {selectedRun.results.length === 0 ? <Alert severity="info">This run has no per-case results yet. Refresh while the worker is running.</Alert> : !selectedResults.length ? <Alert severity="info">No results match the current filter.</Alert> : <Stack spacing={0.9} sx={{ maxHeight: { lg: "calc(100vh - 520px)" }, overflowY: { lg: "auto" }, pr: { lg: 0.5 } }}>
                {selectedResults.map((result) => <Box key={result.id} sx={{ p: 1.1, border: "1px solid", borderColor: result.status === "failed" ? "error.light" : "divider", borderRadius: 1.75 }}>
                  <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" spacing={0.75}><Box sx={{ minWidth: 0, flex: 1 }}><Typography variant="body2" fontWeight={800}>{result.test_case_key} · {result.scenario}</Typography><Typography variant="caption" color={result.status === "failed" ? "error.main" : "text.secondary"}>{result.error_message || durationLabel(result.duration_ms)}</Typography></Box><Stack direction="row" spacing={0.6} alignItems="center" flexWrap="wrap" useFlexGap><Chip size="small" label={displayStatus(result.status)} color={resultColor(result.status)} />{result.defects.map((defect) => <Chip key={defect.id} size="small" label={defect.defect_key} variant="outlined" color="error" />)}</Stack></Stack>
                  {result.evidence && <Stack direction="row" spacing={0.8} flexWrap="wrap" useFlexGap sx={{ mt: 0.8 }}>{typeof result.evidence.final_url === "string" && <Chip size="small" variant="outlined" label={`URL: ${result.evidence.final_url}`} />}{typeof result.evidence.current_package === "string" && <Chip size="small" variant="outlined" label={`Package: ${result.evidence.current_package}`} />}{typeof result.evidence.screenshot_asset_id === "string" && <Button size="small" startIcon={<DownloadOutlinedIcon />} onClick={() => downloadEvidence(result.evidence!.screenshot_asset_id as string, `${selectedRun.name}-launch.png`)}>Screenshot</Button>}{typeof result.evidence.page_source_asset_id === "string" && <Button size="small" startIcon={<DownloadOutlinedIcon />} onClick={() => downloadEvidence(result.evidence!.page_source_asset_id as string, `${selectedRun.name}-page-source.xml`)}>Page source</Button>}</Stack>}
                </Box>)}
              </Stack>}
              {evidenceIds(selectedRun).length > 0 && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5 }}>Evidence assets are linked to this report and intentionally excluded from the general Upload Repository list.</Typography>}
            </>}
          </CardContent>
        </Card>
      </Grid>

      <Grid size={{ xs: 12, lg: 3 }}>{selectedRun && selectedCounts ? <RunOverview run={selectedRun} counts={selectedCounts} /> : <Card variant="outlined" sx={{ height: "100%" }}><CardContent><Stack spacing={1}><VisibilityOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Run overview</Typography><Typography variant="body2" color="text.secondary">Choose a run to see status distribution, target metadata, duration and evidence context.</Typography></Stack></CardContent></Card>}</Grid>
    </Grid>
  </Box>;
}
