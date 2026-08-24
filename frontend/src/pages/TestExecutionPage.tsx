import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Box, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import Grid from "@mui/material/Grid2";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { executionsApi, testCasesApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import PageHeader from "@/components/PageHeader";
import type { ExecutionResult } from "@/types/domain";

export default function TestExecutionPage() {
  const { selectedProjectId } = useSelectedProject();
  const queryClient = useQueryClient();
  const [name, setName] = useState("Regression run");
  const [baseUrl, setBaseUrl] = useState("");
  const [browser] = useState<"chromium">("chromium");
  const [defectResult, setDefectResult] = useState<ExecutionResult | null>(null);
  const [defectTitle, setDefectTitle] = useState("");
  const [defectDescription, setDefectDescription] = useState("");
  const history = useQuery({ queryKey: ["history", selectedProjectId], queryFn: () => testCasesApi.history(selectedProjectId).then(r => r.data), enabled: Boolean(selectedProjectId) });
  const runs = useQuery({ queryKey: ["executions", selectedProjectId], queryFn: () => executionsApi.list(selectedProjectId).then(r => r.data), enabled: Boolean(selectedProjectId), refetchInterval: 4000 });
  const candidates = useMemo(() => history.data?.flatMap(run => run.test_cases).filter(tc => tc.is_automation_candidate) ?? [], [history.data]);
  const createRun = useMutation({
    mutationFn: () => executionsApi.create({ project_id: selectedProjectId, name, base_url: baseUrl, browser, test_case_ids: candidates.map(tc => tc.id) }).then(r => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["executions", selectedProjectId] }),
  });
  const createDefect = useMutation({
    mutationFn: () => executionsApi.createDefect(defectResult!.id, { title: defectTitle, description: defectDescription, severity: "major" }),
    onSuccess: () => {
      setDefectResult(null);
      setDefectTitle("");
      setDefectDescription("");
      queryClient.invalidateQueries({ queryKey: ["executions", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["dashboard", selectedProjectId] });
    },
  });

  if (!selectedProjectId) return <Alert severity="info">Create or select a project before scheduling execution.</Alert>;
  return (
    <Box>
      <PageHeader eyebrow="M4 · EXECUTION FABRIC" title="Test execution" description="Run automation candidates with Playwright and retain evidence for every result." />
      <Card variant="outlined" sx={{ mb: 3 }}><CardContent>
        <Grid container spacing={2} alignItems="center">
          <Grid size={{ xs: 12, md: 4 }}><TextField label="Run name" value={name} onChange={e => setName(e.target.value)} fullWidth /></Grid>
          <Grid size={{ xs: 12, md: 4 }}><TextField label="Application base URL" placeholder="https://staging.example.com" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} fullWidth /></Grid>
          <Grid size={{ xs: 12, md: 2 }}><FormControl fullWidth><InputLabel>Browser</InputLabel><Select label="Browser" value={browser} readOnly><MenuItem value="chromium">Chromium</MenuItem></Select></FormControl></Grid>
          <Grid size={{ xs: 12, md: 2 }}><Button variant="contained" fullWidth size="large" startIcon={<PlayArrowIcon />} disabled={!baseUrl || !candidates.length || createRun.isPending} onClick={() => createRun.mutate()}>{createRun.isPending ? "Queuing…" : "Run tests"}</Button></Grid>
        </Grid>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: "block" }}>{candidates.length} automation candidate(s). The runner only executes the supported DSL; ambiguous steps are marked blocked for human conversion.</Typography>
        {createRun.isError && <Alert severity="error" sx={{ mt: 2 }}>The execution could not be queued.</Alert>}
      </CardContent></Card>
      <Stack spacing={1.5}>
        {runs.data?.map(run => <Card key={run.id} variant="outlined"><CardContent><Box sx={{ display: "flex", justifyContent: "space-between", gap: 2, alignItems: "center" }}><Box><Typography fontWeight={700}>{run.name}</Typography><Typography variant="body2" color="text.secondary">{run.browser} · {run.base_url} · {new Date(run.created_at).toLocaleString()}</Typography></Box><Stack direction="row" spacing={1}><Chip label={run.status} color={run.status === "completed" ? "success" : run.status === "failed" ? "error" : "info"} /><Chip label={`${run.passed_tests} passed`} variant="outlined" /><Chip label={`${run.failed_tests} failed`} variant="outlined" color="error" /><Chip label={`${run.blocked_tests} blocked`} variant="outlined" color="warning" /></Stack></Box>{run.results.length > 0 && <Stack spacing={1} sx={{ mt: 2 }}>{run.results.map(result => <Box key={result.id} sx={{ p: 1.5, borderRadius: 2, bgcolor: "action.hover", display: "flex", justifyContent: "space-between", gap: 2 }}><Box><Typography variant="body2" fontWeight={700}>{result.test_case_key} · {result.scenario}</Typography><Typography variant="caption" color={result.status === "failed" ? "error.main" : "text.secondary"}>{result.error_message ?? `${result.duration_ms ?? 0} ms`}</Typography></Box><Stack direction="row" spacing={1} alignItems="center"><Chip size="small" label={result.status} color={result.status === "passed" ? "success" : result.status === "failed" ? "error" : result.status === "blocked" ? "warning" : "default"} />{result.status === "failed" && !result.defects.length && <Button size="small" color="error" onClick={() => { setDefectResult(result); setDefectTitle(`Failure: ${result.scenario}`); setDefectDescription(result.error_message ?? "Execution failed."); }}>Log defect</Button>}{result.defects.map(defect => <Chip key={defect.id} size="small" label={defect.defect_key} variant="outlined" />)}</Stack></Box>)}</Stack>}</CardContent></Card>)}
        {!runs.isLoading && !runs.data?.length && <Alert severity="info">No execution runs yet. Generate test cases and mark automation candidates first.</Alert>}
      </Stack>
      <Dialog open={Boolean(defectResult)} onClose={() => setDefectResult(null)} fullWidth maxWidth="sm"><DialogTitle>Log defect from execution evidence</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}><TextField label="Title" value={defectTitle} onChange={e => setDefectTitle(e.target.value)} fullWidth /><TextField label="Description" value={defectDescription} onChange={e => setDefectDescription(e.target.value)} multiline minRows={4} fullWidth /><Alert severity="info">The defect remains linked to the failed execution result and its evidence.</Alert></Stack></DialogContent><DialogActions><Button onClick={() => setDefectResult(null)}>Cancel</Button><Button variant="contained" color="error" disabled={!defectTitle || !defectDescription || createDefect.isPending} onClick={() => createDefect.mutate()}>Create defect</Button></DialogActions></Dialog>
    </Box>
  );
}

