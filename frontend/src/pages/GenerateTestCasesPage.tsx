import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Box, Button, Card, CardContent, Checkbox, FormControlLabel, LinearProgress, MenuItem, Stack, TextField, Typography } from "@mui/material";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import { requirementsApi, testCasesApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import ProjectSelector from "@/components/ProjectSelector";
import TestCaseCard from "@/components/TestCaseCard";
import { EXPORT_FORMATS, GenerationRun } from "@/types/domain";

const ACTIVE_STATUSES = ["pending", "normalizing", "analyzing", "generating_scenarios", "generating_test_cases", "risk_analysis"];
const PROGRESS: Record<string, number> = { pending: 5, normalizing: 15, analyzing: 35, generating_scenarios: 55, generating_test_cases: 75, risk_analysis: 90, completed: 100, failed: 100 };

export default function GenerateTestCasesPage() {
  const { selectedProjectId } = useSelectedProject();
  const [selectedRequirementIds, setSelectedRequirementIds] = useState<string[]>([]);
  const [exportFormat, setExportFormat] = useState("excel");
  const [result, setResult] = useState<GenerationRun | null>(null);
  const { data: requirements } = useQuery({ queryKey: ["requirements", selectedProjectId], queryFn: () => requirementsApi.listForProject(selectedProjectId).then((res) => res.data), enabled: Boolean(selectedProjectId) });
  const generateMutation = useMutation({ mutationFn: () => testCasesApi.generate(selectedProjectId, selectedRequirementIds), onSuccess: (res) => setResult(res.data) });
  const { data: liveRun } = useQuery({ queryKey: ["generation-run", result?.id], queryFn: () => testCasesApi.getRun(result!.id).then((res) => res.data), enabled: Boolean(result?.id), refetchInterval: (query) => ACTIVE_STATUSES.includes(((query.state.data as GenerationRun | undefined)?.status ?? result?.status) ?? "") ? 2500 : false });
  const run = liveRun ?? result;
  const isActive = Boolean(run && ACTIVE_STATUSES.includes(run.status));
  const exportMutation = useMutation({ mutationFn: () => testCasesApi.export(run!.id, exportFormat), onSuccess: (res) => { const format = EXPORT_FORMATS.find((f) => f.value === exportFormat); const url = window.URL.createObjectURL(new Blob([res.data])); const link = document.createElement("a"); link.href = url; link.download = `testcases-${run!.id.slice(0, 8)}-${format?.value ?? "export"}`; link.click(); window.URL.revokeObjectURL(url); } });
  const toggleRequirement = (id: string) => setSelectedRequirementIds((prev) => prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id]);

  return <Stack spacing={3}>
    <Stack direction="row" justifyContent="space-between" alignItems="center"><Typography variant="h5" sx={{ fontWeight: 700 }}>Generate Test Cases</Typography><ProjectSelector /></Stack>
    <Card sx={{ borderRadius: 3 }}><CardContent>
      <Typography variant="h6" sx={{ mb: 1 }}>Select requirements</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Leave all unchecked to generate from every requirement in this project.</Typography>
      {!requirements || requirements.length === 0 ? <Alert severity="info">Upload or submit a requirement first.</Alert> : <Stack>{requirements.map((req) => <FormControlLabel key={req.id} control={<Checkbox checked={selectedRequirementIds.includes(req.id)} onChange={() => toggleRequirement(req.id)} />} label={req.title} />)}</Stack>}
      <Button variant="contained" size="large" startIcon={<AutoAwesomeOutlinedIcon />} sx={{ mt: 2 }} disabled={!selectedProjectId || generateMutation.isPending || isActive} onClick={() => generateMutation.mutate()}>{generateMutation.isPending ? "Starting…" : isActive ? "Generation in progress" : "Generate test cases"}</Button>
      {(generateMutation.isPending || isActive) && <Box sx={{ mt: 2 }}><LinearProgress variant="determinate" value={run ? PROGRESS[run.status] : 5} /><Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>{generateMutation.isPending ? "Starting generation…" : `Working: ${run!.status.replaceAll("_", " ")} (${PROGRESS[run!.status]}%)`}</Typography></Box>}
      {generateMutation.isError && <Alert severity="error" sx={{ mt: 2 }}>{(generateMutation.error as any)?.response?.data?.detail || (generateMutation.error as Error)?.message || "Generation failed. Check the AI provider configuration."}</Alert>}
      {run?.status === "failed" && <Alert severity="error" sx={{ mt: 2 }}>{run.error_message || "Generation failed with no further detail."}</Alert>}
      {run?.status === "completed" && run.error_message && <Alert severity="warning" sx={{ mt: 2 }}>{run.error_message}</Alert>}
    </CardContent></Card>
    {run && <Card sx={{ borderRadius: 3 }}><CardContent>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}><Box><Typography variant="h6">Results</Typography><Typography variant="body2" color="text.secondary">{run.test_cases.length} test cases via {run.llm_provider} / {run.llm_model}{run.processing_time_seconds ? ` • ${run.processing_time_seconds.toFixed(1)}s` : ""}</Typography></Box><Stack direction="row" spacing={1}><TextField select size="small" label="Export as" value={exportFormat} onChange={(e) => setExportFormat(e.target.value)} sx={{ minWidth: 180 }}>{EXPORT_FORMATS.map((f) => <MenuItem key={f.value} value={f.value}>{f.label}</MenuItem>)}</TextField><Button variant="outlined" disabled={run.status !== "completed"} onClick={() => exportMutation.mutate()}>Export</Button></Stack></Stack>
      {run.requirement_summary && <Alert severity="info" sx={{ mb: 2 }}>{run.requirement_summary}</Alert>}<Stack spacing={2}>{run.test_cases.map((tc) => <TestCaseCard key={tc.id} testCase={tc} />)}</Stack>
    </CardContent></Card>}
  </Stack>;
}

