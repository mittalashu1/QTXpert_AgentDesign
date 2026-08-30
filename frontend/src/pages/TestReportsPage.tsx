import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  LinearProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import ReplayOutlinedIcon from "@mui/icons-material/ReplayOutlined";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import { dashboardApi, executionPlansApi, executionsApi, uploadsApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import PageHeader from "@/components/PageHeader";
import type { ExecutionRun } from "@/types/domain";

function statusColor(status: string): "success" | "error" | "warning" | "info" | "default" {
  if (status === "completed") return "success";
  if (status === "failed") return "error";
  if (status === "queued") return "warning";
  return "info";
}

function resultColor(status: string): "success" | "error" | "warning" | "default" {
  if (status === "passed") return "success";
  if (status === "failed") return "error";
  if (status === "blocked") return "warning";
  return "default";
}

function targetLabel(run: ExecutionRun) {
  const targetKind = run.target_kind || "web";
  if (targetKind === "android") return `Android · ${run.device_name || "device"}${run.platform_version ? ` · ${run.platform_version}` : ""}`;
  if (targetKind === "ios") return `iOS · ${run.device_name || "device"}${run.platform_version ? ` · ${run.platform_version}` : ""}`;
  return `Web · ${run.base_url || "target unavailable"}`;
}

function providerLabel(run: ExecutionRun) {
  return run.provider || (run.target_kind === "web" ? "playwright" : run.browser);
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

export default function TestReportsPage() {
  const { selectedProjectId } = useSelectedProject();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState(searchParams.get("run") || "");
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

  const selectedRun = useMemo(
    () => (runs.data ?? []).find((run) => run.id === selectedRunId) ?? null,
    [runs.data, selectedRunId],
  );

  useEffect(() => {
    if (!selectedRunId && runs.data?.[0]) setSelectedRunId(runs.data[0].id);
  }, [runs.data, selectedRunId]);

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
    } catch (reason: any) {
      setDownloadError(reason?.response?.data?.detail || reason?.message || "Evidence download failed");
    }
  };

  if (!selectedProjectId) return <Alert severity="info">Select a project to view reports.</Alert>;

  return (
    <Box>
      <PageHeader eyebrow="QUALITY INTELLIGENCE" title="Test reports" description="Traceable execution outcomes, mobile evidence and defect signals from every run." />
      <Grid container spacing={2} sx={{ mb: 3 }}>
        {[["Pass rate", `${summary.data?.pass_rate ?? 0}%`], ["Execution runs", summary.data?.execution_runs ?? 0], ["Open defects", summary.data?.open_defects ?? 0], ["Automation candidates", summary.data?.automation_candidates ?? 0]].map(([label, value]) => (
          <Grid key={String(label)} size={{ xs: 12, sm: 6, md: 3 }}><Card variant="outlined"><CardContent><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="h4" sx={{ mt: 1 }}>{value}</Typography></CardContent></Card></Grid>
        ))}
      </Grid>

      {downloadError && <Alert severity="error" onClose={() => setDownloadError("")} sx={{ mb: 2 }}>{downloadError}</Alert>}
      {runs.isLoading && <LinearProgress sx={{ mb: 2 }} />}
      <Card variant="outlined" sx={{ mb: 3 }}>
        <CardContent>
          <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} spacing={1} sx={{ mb: 1.5 }}>
            <Box><Typography variant="h6" fontWeight={800}>Execution history</Typography><Typography variant="body2" color="text.secondary">Every row opens the complete per-case report. Mobile packages stay reusable in Uploads; evidence is retained here.</Typography></Box>
            {runs.isFetching && <LinearProgress sx={{ width: 120 }} />}
          </Stack>
          {!runs.isLoading && !(runs.data ?? []).length ? <Alert severity="info">No execution runs are available yet.</Alert> : (
            <TableContainer>
              <Table size="small">
                <TableHead><TableRow><TableCell>Run</TableCell><TableCell>Target</TableCell><TableCell>Status</TableCell><TableCell>Passed</TableCell><TableCell>Failed</TableCell><TableCell>Blocked</TableCell><TableCell>Last run</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
                <TableBody>{(runs.data ?? []).map((run) => <TableRow key={run.id} hover selected={run.id === selectedRunId} onClick={() => chooseRun(run)} sx={{ cursor: "pointer" }}>
                  <TableCell><Typography variant="body2" fontWeight={700} noWrap sx={{ maxWidth: 260 }}>{run.name}</Typography></TableCell>
                  <TableCell><Typography variant="body2" noWrap sx={{ maxWidth: 290 }}>{targetLabel(run)}</Typography><Typography variant="caption" color="text.secondary">{providerLabel(run)}</Typography></TableCell>
                  <TableCell><Chip size="small" label={run.status} color={statusColor(run.status)} /></TableCell>
                  <TableCell>{run.passed_tests}</TableCell><TableCell>{run.failed_tests}</TableCell><TableCell>{run.blocked_tests}</TableCell>
                  <TableCell>{new Date(run.completed_at || run.created_at).toLocaleString()}</TableCell>
                  <TableCell align="right"><Button size="small" startIcon={<VisibilityOutlinedIcon />} onClick={(event) => { event.stopPropagation(); chooseRun(run); }}>View</Button></TableCell>
                </TableRow>)}</TableBody>
              </Table>
            </TableContainer>
          )}
        </CardContent>
      </Card>

      {selectedRun && <Card variant="outlined">
        <CardContent>
          <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2}>
            <Box>
              <Typography variant="h6" fontWeight={800}>{selectedRun.name}</Typography>
              <Typography variant="body2" color="text.secondary">{targetLabel(selectedRun)} · {providerLabel(selectedRun)} · started {new Date(selectedRun.started_at || selectedRun.created_at).toLocaleString()}</Typography>
            </Box>
            <Stack direction="row" spacing={1} alignItems="center"><Chip label={selectedRun.status} color={statusColor(selectedRun.status)} /><Button size="small" variant="outlined" startIcon={<ReplayOutlinedIcon />} disabled={!selectedRun.execution_plan_id || rerun.isPending || ["queued", "running"].includes(selectedRun.status)} onClick={() => rerun.mutate(selectedRun)}>Rerun</Button></Stack>
          </Stack>
          {rerun.isError && <Alert severity="error" sx={{ mt: 2 }}>{rerun.error instanceof Error ? rerun.error.message : "The run could not be queued again."}</Alert>}
          <Divider sx={{ my: 2 }} />
          <Grid container spacing={1.5} sx={{ mb: 2 }}>
            {[["Total", selectedRun.total_tests], ["Passed", selectedRun.passed_tests], ["Failed", selectedRun.failed_tests], ["Blocked", selectedRun.blocked_tests]].map(([label, value]) => <Grid key={String(label)} size={{ xs: 6, sm: 3 }}><Box sx={{ p: 1.25, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h6" fontWeight={800}>{value}</Typography></Box></Grid>)}
          </Grid>
          {selectedRun.results.length === 0 ? <Alert severity="info">This run has no per-case results yet. Refresh while the worker is running.</Alert> : <Stack spacing={1}>
            {selectedRun.results.map((result) => <Box key={result.id} sx={{ p: 1.25, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
              <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1}>
                <Box sx={{ minWidth: 0 }}><Typography variant="body2" fontWeight={800}>{result.test_case_key} · {result.scenario}</Typography><Typography variant="caption" color={result.status === "failed" ? "error.main" : "text.secondary"}>{result.error_message || `${result.duration_ms ?? 0} ms`}</Typography></Box>
                <Stack direction="row" spacing={1} alignItems="center"><Chip size="small" label={result.status} color={resultColor(result.status)} />{result.defects.map((defect) => <Chip key={defect.id} size="small" label={defect.defect_key} variant="outlined" color="error" />)}</Stack>
              </Stack>
              {result.evidence && <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>{typeof result.evidence.final_url === "string" && <Chip size="small" variant="outlined" label={`URL: ${result.evidence.final_url}`} />}{typeof result.evidence.current_package === "string" && <Chip size="small" variant="outlined" label={`Package: ${result.evidence.current_package}`} />}{typeof result.evidence.screenshot_asset_id === "string" && <Button size="small" startIcon={<DownloadOutlinedIcon />} onClick={() => downloadEvidence(result.evidence!.screenshot_asset_id as string, `${selectedRun.name}-launch.png`)}>Download screenshot</Button>}{typeof result.evidence.page_source_asset_id === "string" && <Button size="small" startIcon={<DownloadOutlinedIcon />} onClick={() => downloadEvidence(result.evidence!.page_source_asset_id as string, `${selectedRun.name}-page-source.xml`)}>Download page source</Button>}</Stack>}
            </Box>)}
          </Stack>}
          {evidenceIds(selectedRun).length > 0 && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 2 }}>Evidence assets are linked to this report and intentionally excluded from the general Upload Repository list.</Typography>}
        </CardContent>
      </Card>}
    </Box>
  );
}
