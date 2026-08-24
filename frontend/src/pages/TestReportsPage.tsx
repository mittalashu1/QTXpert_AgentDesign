import { useQuery } from "@tanstack/react-query";
import { Alert, Box, Card, CardContent, Chip, LinearProgress, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import Grid from "@mui/material/Grid2";
import { dashboardApi, executionsApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import PageHeader from "@/components/PageHeader";

export default function TestReportsPage() {
  const { selectedProjectId } = useSelectedProject();
  const summary = useQuery({ queryKey: ["dashboard", selectedProjectId], queryFn: () => dashboardApi.summary(selectedProjectId).then(r => r.data), enabled: Boolean(selectedProjectId) });
  const runs = useQuery({ queryKey: ["executions", selectedProjectId], queryFn: () => executionsApi.list(selectedProjectId).then(r => r.data), enabled: Boolean(selectedProjectId) });
  if (!selectedProjectId) return <Alert severity="info">Select a project to view reports.</Alert>;
  return <Box>
    <PageHeader eyebrow="QUALITY INTELLIGENCE" title="Test reports" description="Traceable execution trends, evidence, and defect signals." />
    <Grid container spacing={2} sx={{ mb: 3 }}>
      {[["Pass rate", `${summary.data?.pass_rate ?? 0}%`], ["Execution runs", summary.data?.execution_runs ?? 0], ["Open defects", summary.data?.open_defects ?? 0], ["Automation candidates", summary.data?.automation_candidates ?? 0]].map(([label, value]) => <Grid key={String(label)} size={{ xs: 12, sm: 6, md: 3 }}><Card variant="outlined"><CardContent><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="h4" sx={{ mt: 1 }}>{value}</Typography></CardContent></Card></Grid>)}
    </Grid>
    <Card variant="outlined"><CardContent><Typography variant="h6" sx={{ mb: 2 }}>Execution history</Typography>{runs.isLoading && <LinearProgress />}<Table><TableHead><TableRow><TableCell>Run</TableCell><TableCell>Status</TableCell><TableCell>Browser</TableCell><TableCell>Passed</TableCell><TableCell>Failed</TableCell><TableCell>Blocked</TableCell><TableCell>Created</TableCell></TableRow></TableHead><TableBody>{runs.data?.map(run => <TableRow key={run.id}><TableCell>{run.name}</TableCell><TableCell><Chip size="small" label={run.status} /></TableCell><TableCell>{run.browser}</TableCell><TableCell>{run.passed_tests}</TableCell><TableCell>{run.failed_tests}</TableCell><TableCell>{run.blocked_tests}</TableCell><TableCell>{new Date(run.created_at).toLocaleString()}</TableCell></TableRow>)}</TableBody></Table></CardContent></Card>
  </Box>;
}

