import { useQuery } from "@tanstack/react-query";
import { Alert, Box, Button, Card, CardContent, Chip, LinearProgress, Stack, Typography } from "@mui/material";
import Grid from "@mui/material/Grid2";
import { useNavigate } from "react-router-dom";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import ArchitectureOutlinedIcon from "@mui/icons-material/ArchitectureOutlined";
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline";
import { dashboardApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import PageHeader from "@/components/PageHeader";

export default function DashboardPage() {
  const navigate = useNavigate();
  const { selectedProjectId, selectedProject } = useSelectedProject();
  const summary = useQuery({ queryKey: ["dashboard", selectedProjectId], queryFn: () => dashboardApi.summary(selectedProjectId).then(r => r.data), enabled: Boolean(selectedProjectId) });
  if (!selectedProjectId) return <Alert severity="info">Create or select a project to open its quality dashboard.</Alert>;
  const metrics = [
    ["Requirements", summary.data?.requirements ?? 0],
    ["Test cases", summary.data?.test_cases ?? 0],
    ["Execution runs", summary.data?.execution_runs ?? 0],
    ["Pass rate", `${summary.data?.pass_rate ?? 0}%`],
    ["Open defects", summary.data?.open_defects ?? 0],
    ["Automation-ready", summary.data?.automation_candidates ?? 0],
  ];
  return <Box>
    <PageHeader eyebrow="TEST MANAGEMENT" title={selectedProject?.name ?? "Quality dashboard"} description="A live view of requirement coverage, designed tests, execution, and defects." actions={<Button variant="contained" onClick={() => navigate("/documents")}>Analyze a document</Button>} />
    {summary.isLoading && <LinearProgress sx={{ mb: 2 }} />}
    <Grid container spacing={2}>{metrics.map(([label, value]) => <Grid key={String(label)} size={{ xs: 12, sm: 6, md: 4 }}><Card variant="outlined"><CardContent><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="h3" sx={{ mt: 1 }}>{value}</Typography></CardContent></Card></Grid>)}</Grid>
    <Grid container spacing={2} sx={{ mt: 1 }}>
      <Grid size={{ xs: 12, md: 7 }}><Card variant="outlined"><CardContent><Typography variant="h6">Recent execution</Typography><Stack spacing={1.25} sx={{ mt: 2 }}>{summary.data?.recent_runs.map(run => <Box key={run.id} sx={{ display: "flex", justifyContent: "space-between", p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Box><Typography fontWeight={700}>{run.name}</Typography><Typography variant="caption" color="text.secondary">{new Date(run.created_at).toLocaleString()}</Typography></Box><Chip label={run.status} size="small" /></Box>)}{!summary.data?.recent_runs.length && <Typography color="text.secondary">No execution activity yet.</Typography>}</Stack></CardContent></Card></Grid>
      <Grid size={{ xs: 12, md: 5 }}><Card variant="outlined"><CardContent><Typography variant="h6">Continue your quality flow</Typography><Stack spacing={1.5} sx={{ mt: 2 }}><Button startIcon={<DescriptionOutlinedIcon />} variant="outlined" onClick={() => navigate("/documents")}>Document analysis</Button><Button startIcon={<ArchitectureOutlinedIcon />} variant="outlined" onClick={() => navigate("/design")}>Design test cases</Button><Button startIcon={<PlayCircleOutlineIcon />} variant="outlined" onClick={() => navigate("/execution")}>Execute automation</Button></Stack></CardContent></Card></Grid>
    </Grid>
  </Box>;
}

