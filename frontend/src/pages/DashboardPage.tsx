import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Box, Button, Card, CardContent, Chip, Grid, LinearProgress, Stack, Typography } from "@mui/material";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import ArrowForwardOutlinedIcon from "@mui/icons-material/ArrowForwardOutlined";
import { useNavigate } from "react-router-dom";
import { testCasesApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import ProjectSelector from "@/components/ProjectSelector";

function StatCard({ label, value, detail }: { label: string; value: string | number; detail: string }) {
  return <Card sx={{ borderRadius: 3, height: "100%" }}><CardContent><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="h4" sx={{ fontWeight: 800, mt: 0.5 }}>{value}</Typography><Typography variant="caption" color="text.secondary">{detail}</Typography></CardContent></Card>;
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { selectedProjectId, selectedProject } = useSelectedProject();
  const { data: runs } = useQuery({
    queryKey: ["history", selectedProjectId],
    queryFn: () => testCasesApi.history(selectedProjectId).then((res) => res.data),
    enabled: Boolean(selectedProjectId),
    refetchInterval: 10000,
  });

  const metrics = useMemo(() => {
    const allRuns = runs ?? [];
    const cases = allRuns.flatMap((run) => run.test_cases);
    const completed = allRuns.filter((run) => run.status === "completed").length;
    const automation = cases.filter((tc) => tc.is_automation_candidate).length;
    const coverage = cases.length ? Math.round((new Set(cases.map((tc) => tc.requirement_traceability).filter(Boolean)).size / Math.max(1, cases.length)) * 100) : 0;
    const confidence = Math.min(99, Math.round((completed ? 55 : 0) + Math.min(25, coverage / 4) + (cases.length ? Math.min(20, automation / cases.length * 20) : 0)));
    return { allRuns, cases, completed, automation, coverage, confidence };
  }, [runs]);

  return <Stack spacing={3}>
    <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }} gap={2}>
      <Box><Typography variant="h5" sx={{ fontWeight: 800 }}>Release intelligence</Typography><Typography color="text.secondary">{selectedProject ? selectedProject.name : "Select a project to map requirements to coverage"}</Typography></Box>
      <Stack direction="row" spacing={1}><ProjectSelector /><Button variant="contained" startIcon={<AutoAwesomeOutlinedIcon />} onClick={() => navigate("/generate")} disabled={!selectedProjectId}>Create AI plan</Button></Stack>
    </Stack>
    <Card sx={{ borderRadius: 3, background: "linear-gradient(120deg, #101828 0%, #243b53 100%)", color: "white" }}><CardContent sx={{ p: { xs: 2.5, md: 4 } }}><Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" gap={3}><Box><Chip label="AI test command center" size="small" sx={{ bgcolor: "rgba(255,255,255,.14)", color: "white", mb: 1 }} /><Typography variant="h4" sx={{ fontWeight: 800, maxWidth: 620 }}>Turn every requirement into an executable release plan.</Typography><Typography sx={{ mt: 1, color: "rgba(255,255,255,.75)", maxWidth: 620 }}>Generate smoke, feature, regression, or deep-regression coverage, then inspect the evidence before your team ships.</Typography><Button sx={{ mt: 2 }} variant="contained" color="secondary" endIcon={<ArrowForwardOutlinedIcon />} onClick={() => navigate("/generate")} disabled={!selectedProjectId}>Plan the next release</Button></Box><Box sx={{ minWidth: 220, alignSelf: "center" }}><Typography variant="body2" sx={{ color: "rgba(255,255,255,.7)" }}>Coverage confidence</Typography><Typography variant="h2" sx={{ fontWeight: 900 }}>{metrics.confidence}%</Typography><LinearProgress variant="determinate" value={metrics.confidence} sx={{ mt: 1, bgcolor: "rgba(255,255,255,.18)", "& .MuiLinearProgress-bar": { bgcolor: "#7dd3fc" } }} /><Typography variant="caption" sx={{ color: "rgba(255,255,255,.7)" }}>Evidence from generated and traceable cases</Typography></Box></Stack></CardContent></Card>
    <Grid container spacing={2}><Grid item xs={12} sm={6} md={3}><StatCard label="AI plans" value={metrics.allRuns.length} detail={`${metrics.completed} completed`} /></Grid><Grid item xs={12} sm={6} md={3}><StatCard label="Generated cases" value={metrics.cases.length} detail="Across this project" /></Grid><Grid item xs={12} sm={6} md={3}><StatCard label="Automation-ready" value={metrics.automation} detail="Candidates with executable intent" /></Grid><Grid item xs={12} sm={6} md={3}><StatCard label="Traceability" value={`${metrics.coverage}%`} detail="Cases linked to requirements" /></Grid></Grid>
    <Card sx={{ borderRadius: 3 }}><CardContent><Typography variant="h6" sx={{ mb: 2, fontWeight: 700 }}>Recent AI plans</Typography>{metrics.allRuns.length === 0 ? <Typography color="text.secondary">No plans yet. Upload a requirement, choose a release profile, and let QTXpert build the first coverage map.</Typography> : <Stack spacing={1.5}>{metrics.allRuns.slice(0, 6).map((run) => <Box key={run.id} sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 2, borderBottom: "1px solid", borderColor: "divider", pb: 1.5 }}><Box><Typography variant="body2" sx={{ fontWeight: 700 }}>Run {run.id.slice(0, 8)}</Typography><Typography variant="caption" color="text.secondary">{run.llm_provider} / {run.llm_model} · {run.test_cases.length} cases</Typography></Box><Chip size="small" label={run.status.replaceAll("_", " ")} color={run.status === "completed" ? "success" : run.status === "failed" ? "error" : "warning"} /></Box>)}</Stack>}</CardContent></Card>
  </Stack>;
}
