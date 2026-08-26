import { useQuery } from "@tanstack/react-query";
import { Alert, Box, Button, Card, CardContent, Chip, LinearProgress, Stack, Typography } from "@mui/material";
import Grid from "@mui/material/Grid2";
import { useNavigate } from "react-router-dom";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import ArchitectureOutlinedIcon from "@mui/icons-material/ArchitectureOutlined";
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline";
import { dashboardApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import { useAuth } from "@/contexts/AuthContext";
import PageHeader from "@/components/PageHeader";

function formatMoney(value: number | null | undefined, currency = "USD") {
  if (value == null) return "—";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { selectedProjectId, selectedProject } = useSelectedProject();
  const summary = useQuery({ queryKey: ["dashboard", selectedProjectId], queryFn: () => dashboardApi.summary(selectedProjectId).then(r => r.data), enabled: Boolean(selectedProjectId) });
  const aiCosts = useQuery({ queryKey: ["dashboard-ai-costs"], queryFn: () => dashboardApi.aiCosts().then(r => r.data), enabled: isAdmin, staleTime: 60_000 });
  const number = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
  if (!selectedProjectId && !isAdmin) return <Alert severity="info">Create or select a project to open its quality dashboard.</Alert>;
  const metrics = [
    ["Requirements", summary.data?.requirements ?? 0],
    ["Test cases", summary.data?.test_cases ?? 0],
    ["Execution runs", summary.data?.execution_runs ?? 0],
    ["Pass rate", `${summary.data?.pass_rate ?? 0}%`],
    ["Open defects", summary.data?.open_defects ?? 0],
    ["Automation-ready", summary.data?.automation_candidates ?? 0],
  ];
  const azure = aiCosts.data?.azure;
  const azureValue = azure?.connected ? formatMoney(azure.actual_cost, azure.currency || "USD") : azure?.configured ? "Unavailable" : "Not connected";
  const meteredValue = formatMoney(aiCosts.data?.estimated_cost_usd ?? 0, "USD");
  const varianceValue = aiCosts.data?.variance_usd == null ? "—" : formatMoney(aiCosts.data.variance_usd, "USD");

  return <Box>
    <PageHeader eyebrow={isAdmin ? "ADMIN · TEST MANAGEMENT" : "TEST MANAGEMENT"} title={selectedProject?.name ?? "Admin dashboard"} description={isAdmin ? "Workspace quality activity and reconciled AI usage for administrators." : "A live view of requirement coverage, designed tests, execution, and defects."} actions={<Button variant="contained" onClick={() => navigate("/documents")}>Analyze a document</Button>} />
    {isAdmin && <Card variant="outlined" sx={{ mb: 2 }}>
      <CardContent>
        <Typography variant="overline" color="primary.main" sx={{ fontWeight: 700, letterSpacing: ".12em" }}>ADMIN · AI SPEND</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Actual Azure billing and QTXpert-metered model usage for the last {aiCosts.data?.period_days ?? 30} days.</Typography>
        <Grid container spacing={1.5}>
          <Grid size={{ xs: 12, md: 4 }}><Box sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">Azure actual cost</Typography><Typography variant="h5" sx={{ mt: 0.25 }}>{aiCosts.isLoading ? "Loading…" : azureValue}</Typography><Typography variant="caption" color="text.secondary">{azure?.connected ? `${azure.resource_name || "Azure OpenAI"}${azure.last_synced_at ? ` · synced ${new Date(azure.last_synced_at).toLocaleString()}` : ""}` : "Azure Cost Management"}</Typography></Box></Grid>
          <Grid size={{ xs: 12, md: 4 }}><Box sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">QTXpert metered estimate</Typography><Typography variant="h5" sx={{ mt: 0.25 }}>{aiCosts.isLoading ? "Loading…" : meteredValue}</Typography><Typography variant="caption" color="text.secondary">{aiCosts.data?.unpriced_requests ? `Partial · ${aiCosts.data.unpriced_requests} unpriced request(s)` : "Based on recorded token rates"}</Typography></Box></Grid>
          <Grid size={{ xs: 12, md: 4 }}><Box sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="text.secondary">Variance</Typography><Typography variant="h5" sx={{ mt: 0.25 }}>{aiCosts.isLoading ? "Loading…" : varianceValue}</Typography><Typography variant="caption" color="text.secondary">Azure actual minus QTXpert estimate</Typography></Box></Grid>
        </Grid>
        <Stack direction="row" spacing={3} sx={{ mt: 2, flexWrap: "wrap", rowGap: 1 }}>
          <Box><Typography variant="caption" color="text.secondary">Requests</Typography><Typography fontWeight={700}>{number.format(aiCosts.data?.request_count ?? 0)}</Typography></Box>
          <Box><Typography variant="caption" color="text.secondary">Input tokens</Typography><Typography fontWeight={700}>{number.format(aiCosts.data?.input_tokens ?? 0)}</Typography></Box>
          <Box><Typography variant="caption" color="text.secondary">Output tokens</Typography><Typography fontWeight={700}>{number.format(aiCosts.data?.output_tokens ?? 0)}</Typography></Box>
        </Stack>
        {aiCosts.isError && <Alert severity="warning" sx={{ mt: 2 }}>AI cost data is temporarily unavailable.</Alert>}
        {!aiCosts.isLoading && azure && !azure.configured && <Alert severity="info" sx={{ mt: 2 }}>Azure Cost Management is not connected. QTXpert will not display a misleading $0 as the Azure bill; configure the Azure cost credentials on the backend to show actual spend.</Alert>}
        {!aiCosts.isLoading && azure?.configured && !azure.connected && <Alert severity="warning" sx={{ mt: 2 }}>{azure.error || "Azure Cost Management could not be reached."}</Alert>}
        {!!aiCosts.data?.unpriced_requests && <Alert severity="warning" sx={{ mt: 2 }}>{aiCosts.data.unpriced_requests} QTXpert request(s) have no configured model rate, so the metered estimate is incomplete.</Alert>}
        {!!aiCosts.data?.by_model.length && <Stack spacing={1} sx={{ mt: 2 }}>
          <Typography variant="subtitle2">QTXpert metered cost by model</Typography>
          {aiCosts.data.by_model.map((item) => <Box key={`${item.provider}:${item.model}:${item.tier}`} sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 2, p: 1.25, bgcolor: "action.hover", borderRadius: 2, flexWrap: "wrap" }}>
            <Box><Typography fontWeight={700}>{item.model}</Typography><Typography variant="caption" color="text.secondary">{item.provider} · {item.tier} · {number.format(item.request_count)} requests{item.unpriced_requests ? ` · ${item.unpriced_requests} unpriced` : ""}</Typography></Box>
            <Typography fontWeight={700}>{formatMoney(item.estimated_cost_usd, "USD")}</Typography>
          </Box>)}
        </Stack>}
      </CardContent>
    </Card>}
    {selectedProjectId && <>
      {summary.isLoading && <LinearProgress sx={{ mb: 2 }} />}
      <Grid container spacing={2}>{metrics.map(([label, value]) => <Grid key={String(label)} size={{ xs: 12, sm: 6, md: 4 }}><Card variant="outlined"><CardContent><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="h3" sx={{ mt: 1 }}>{value}</Typography></CardContent></Card></Grid>)}</Grid>
      <Grid container spacing={2} sx={{ mt: 1 }}>
        <Grid size={{ xs: 12, md: 7 }}><Card variant="outlined"><CardContent><Typography variant="h6">Recent execution</Typography><Stack spacing={1.25} sx={{ mt: 2 }}>{summary.data?.recent_runs.map(run => <Box key={run.id} sx={{ display: "flex", justifyContent: "space-between", p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Box><Typography fontWeight={700}>{run.name}</Typography><Typography variant="caption" color="text.secondary">{new Date(run.created_at).toLocaleString()}</Typography></Box><Chip label={run.status} size="small" /></Box>)}{!summary.data?.recent_runs.length && <Typography color="text.secondary">No execution activity yet.</Typography>}</Stack></CardContent></Card></Grid>
        <Grid size={{ xs: 12, md: 5 }}><Card variant="outlined"><CardContent><Typography variant="h6">Continue your quality flow</Typography><Stack spacing={1.5} sx={{ mt: 2 }}><Button startIcon={<DescriptionOutlinedIcon />} variant="outlined" onClick={() => navigate("/documents")}>Document analysis</Button><Button startIcon={<ArchitectureOutlinedIcon />} variant="outlined" onClick={() => navigate("/design")}>Design test cases</Button><Button startIcon={<PlayCircleOutlineIcon />} variant="outlined" onClick={() => navigate("/execution")}>Execute automation</Button></Stack></CardContent></Card></Grid>
      </Grid>
    </>}
  </Box>;
}
