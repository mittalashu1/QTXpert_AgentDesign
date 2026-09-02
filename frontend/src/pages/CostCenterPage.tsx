import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, FormControl, InputLabel, Link as MuiLink, MenuItem,
  Select, Stack, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import AccountBalanceWalletOutlinedIcon from "@mui/icons-material/AccountBalanceWalletOutlined";
import OpenInNewOutlinedIcon from "@mui/icons-material/OpenInNewOutlined";
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import { apiClient } from "@/services/apiClient";
import PageHeader from "@/components/PageHeader";

type AICostBreakdown = {
  provider: string;
  model: string;
  tier: string;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  unpriced_requests: number;
};

type AzureActualCost = {
  configured: boolean;
  connected: boolean;
  actual_cost: number | null;
  currency: string | null;
  last_synced_at: string | null;
  scope: string | null;
  resource_name: string | null;
  error: string | null;
};

type CostSurface = {
  key: string;
  category: string;
  service: string;
  configured: boolean | null;
  coverage: "actual" | "estimated" | "manual" | "not_configured";
  actual_cost: number | null;
  estimated_cost_usd: number | null;
  currency: string | null;
  billing_source: string;
  note: string;
  action: string | null;
  portal_url: string | null;
  pricing_url: string | null;
  limits_url: string | null;
  limits: string[];
  account_plan: string | null;
  live_usage: Record<string, string | number | boolean | null> | null;
  last_verified_at: string | null;
  provider_error: string | null;
};

type CostCatalogInfo = {
  status: "fresh" | "partial" | "due" | "unavailable";
  last_refreshed_at: string | null;
  next_refresh_at: string | null;
  error: string | null;
};

type CostSummary = {
  period_days: number;
  since: string;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  unpriced_requests: number;
  by_model: AICostBreakdown[];
  azure: AzureActualCost;
  variance_usd: number | null;
  cost_surfaces: CostSurface[];
  untracked_surface_count: number;
  catalog?: CostCatalogInfo;
};

function money(value: number | null | undefined, currency = "USD") {
  if (value == null) return "Not available";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

const coverageLabel: Record<CostSurface["coverage"], string> = {
  actual: "Actual connected",
  estimated: "Estimated only",
  manual: "No billing feed",
  not_configured: "Not configured",
};

const coverageColor: Record<CostSurface["coverage"], "success" | "info" | "warning" | "default"> = {
  actual: "success",
  estimated: "info",
  manual: "warning",
  not_configured: "default",
};

function dateTime(value: string | null | undefined) {
  if (!value) return "Not available";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Not available" : parsed.toLocaleString();
}

function bytes(value: number) {
  if (!Number.isFinite(value)) return String(value);
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value;
  let index = -1;
  do {
    amount /= 1024;
    index += 1;
  } while (amount >= 1024 && index < units.length - 1);
  return `${amount.toFixed(amount >= 10 ? 0 : 1)} ${units[index]}`;
}

function usageLines(usage: CostSurface["live_usage"]) {
  if (!usage) return [];
  return Object.entries(usage)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => {
      const label = key.replaceAll("_", " ");
      const rendered = key.includes("bytes") && typeof value === "number" ? bytes(value) : String(value);
      return `${label}: ${rendered}`;
    });
}

export default function CostCenterPage() {
  const [days, setDays] = useState(30);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["admin-cost-center", days],
    queryFn: () => apiClient.get<CostSummary>("/admin/ai-costs", { params: { days } }).then((response) => response.data),
    staleTime: 60_000,
  });
  const data = query.data;
  const number = useMemo(() => new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }), []);
  const azureValue = data?.azure.connected ? money(data.azure.actual_cost, data.azure.currency || "USD") : "Not connected";
  const variance = data?.variance_usd == null ? "Not available" : money(data.variance_usd, "USD");
  const catalog = data?.catalog ?? { status: "unavailable" as const, last_refreshed_at: null, next_refresh_at: null, error: "Catalog metadata is not available from this backend revision." };

  const refreshCatalog = async () => {
    setRefreshing(true);
    setRefreshMessage(null);
    try {
      const response = await apiClient.post<CostCatalogInfo>("/admin/cost-catalog/refresh");
      await query.refetch();
      setRefreshMessage(
        response.data.status === "partial"
          ? "Catalog refreshed; one or more provider checks failed, so the last known values remain visible."
          : response.data.status === "unavailable"
            ? "The catalog refresh was unavailable; the last safe snapshot remains visible."
            : "Provider limits and usage refreshed.",
      );
    } catch {
      setRefreshMessage("The refresh could not reach one or more providers; the last safe snapshot remains visible.");
    } finally {
      setRefreshing(false);
    }
  };

  return <Box>
    <PageHeader
      eyebrow="OWNER · FINOPS"
      title="Cost Center"
      description="Actual spend, QTXpert usage estimates and every known platform cost surface that is not yet connected to a billing feed."
      actions={
        <Stack direction="row" spacing={1} alignItems="center">
          <Button
            size="small"
            variant="outlined"
            startIcon={refreshing ? <CircularProgress size={16} /> : <RefreshOutlinedIcon />}
            onClick={refreshCatalog}
            disabled={refreshing || query.isFetching}
          >
            Refresh catalog
          </Button>
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel id="cost-period-label">Period</InputLabel>
            <Select labelId="cost-period-label" label="Period" value={days} onChange={(event) => setDays(Number(event.target.value))}>
              <MenuItem value={7}>Last 7 days</MenuItem>
              <MenuItem value={30}>Last 30 days</MenuItem>
              <MenuItem value={90}>Last 90 days</MenuItem>
              <MenuItem value={365}>Last 365 days</MenuItem>
            </Select>
          </FormControl>
        </Stack>
      }
    />

    {query.isLoading && <Alert severity="info" sx={{ mb: 2 }}>Loading cost coverage…</Alert>}
    {query.isError && <Alert severity="error" sx={{ mb: 2 }}>Cost data is temporarily unavailable.</Alert>}
    {refreshMessage && <Alert severity={refreshMessage.startsWith("Provider") ? "success" : "warning"} sx={{ mb: 2 }}>{refreshMessage}</Alert>}

    {data && <Stack spacing={2.5}>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}><Card variant="outlined"><CardContent><Typography variant="caption" color="text.secondary">Azure actual</Typography><Typography variant="h4" sx={{ mt: .5 }}>{azureValue}</Typography><Typography variant="caption" color="text.secondary">{data.azure.connected ? "Azure Cost Management" : "Actual billing feed unavailable"}</Typography></CardContent></Card></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}><Card variant="outlined"><CardContent><Typography variant="caption" color="text.secondary">QTXpert AI estimate</Typography><Typography variant="h4" sx={{ mt: .5 }}>{money(data.estimated_cost_usd)}</Typography><Typography variant="caption" color="text.secondary">{data.unpriced_requests ? `${data.unpriced_requests} unpriced request(s)` : "Token-metered estimate"}</Typography></CardContent></Card></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}><Card variant="outlined"><CardContent><Typography variant="caption" color="text.secondary">Azure vs estimate</Typography><Typography variant="h4" sx={{ mt: .5 }}>{variance}</Typography><Typography variant="caption" color="text.secondary">Available only when Azure actual cost is in USD</Typography></CardContent></Card></Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}><Card variant="outlined"><CardContent><Typography variant="caption" color="text.secondary">Unconnected billing surfaces</Typography><Typography variant="h4" sx={{ mt: .5 }}>{data.untracked_surface_count}</Typography><Typography variant="caption" color="text.secondary">Manual reconciliation required</Typography></CardContent></Card></Grid>
      </Grid>

      {!data.azure.connected && data.azure.configured && <Alert severity="warning">{data.azure.error || "Azure Cost Management is configured but actual cost could not be retrieved."}</Alert>}
      {!data.azure.configured && <Alert severity="info">Azure Cost Management is not connected. Cost Center deliberately shows “Not connected” instead of a misleading $0 actual bill.</Alert>}
      {!!data.unpriced_requests && <Alert severity="warning">{data.unpriced_requests} AI request(s) do not have a configured model rate, so the QTXpert estimate is incomplete.</Alert>}
      <Alert severity={catalog.status === "partial" || catalog.status === "unavailable" ? "warning" : "info"}>
        <strong>Provider catalog:</strong>{" "}
        {catalog.last_refreshed_at ? `last refreshed ${dateTime(catalog.last_refreshed_at)}` : "not refreshed yet"}.{" "}
        {catalog.next_refresh_at ? `Automatic refresh is due ${dateTime(catalog.next_refresh_at)}.` : "Automatic refresh is enabled monthly."}{" "}
        {catalog.error || "Use Refresh catalog to request an immediate provider check."}
      </Alert>

      <Card variant="outlined">
        <CardContent>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}><AccountBalanceWalletOutlinedIcon color="primary" /><Typography variant="h6" fontWeight={800}>Ecosystem cost coverage</Typography></Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>A missing amount is not treated as zero. It means QTXpert does not currently receive an authoritative billing value for that service.</Typography>
          <TableContainer sx={{ overflowX: "auto" }}>
            <Table size="small" sx={{ minWidth: 1180 }}>
              <TableHead><TableRow><TableCell>Area</TableCell><TableCell>Service</TableCell><TableCell>Coverage</TableCell><TableCell align="right">Cost</TableCell><TableCell>Billing source</TableCell><TableCell>Account limits &amp; live usage</TableCell><TableCell>What to do</TableCell></TableRow></TableHead>
              <TableBody>
                {data.cost_surfaces.map((surface) => {
                  const amount = surface.actual_cost != null
                    ? money(surface.actual_cost, surface.currency || "USD")
                    : surface.estimated_cost_usd != null
                      ? `${money(surface.estimated_cost_usd)} est.`
                      : "Not available";
                  return <TableRow key={surface.key} hover>
                    <TableCell><Typography variant="body2" color="text.secondary">{surface.category}</Typography></TableCell>
                    <TableCell sx={{ minWidth: 230 }}>
                      <Typography variant="body2" fontWeight={700}>
                        {surface.portal_url ? <MuiLink href={surface.portal_url} target="_blank" rel="noreferrer" underline="hover" color="inherit">{surface.service} <OpenInNewOutlinedIcon sx={{ fontSize: 13, verticalAlign: "text-top" }} /></MuiLink> : surface.service}
                      </Typography>
                      {surface.account_plan && <Chip size="small" sx={{ mt: .5, mr: .5 }} label={`Plan: ${surface.account_plan}`} variant="outlined" />}
                      {surface.pricing_url && <MuiLink href={surface.pricing_url} target="_blank" rel="noreferrer" underline="hover" variant="caption">Pricing</MuiLink>}
                      <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>{surface.note}</Typography>
                    </TableCell>
                    <TableCell><Chip size="small" label={coverageLabel[surface.coverage]} color={coverageColor[surface.coverage]} variant="outlined" /></TableCell>
                    <TableCell align="right" sx={{ whiteSpace: "nowrap" }}><Typography fontWeight={700}>{amount}</Typography></TableCell>
                    <TableCell sx={{ minWidth: 180 }}><Typography variant="body2">{surface.billing_source}</Typography></TableCell>
                    <TableCell sx={{ minWidth: 300 }}>
                      <Stack spacing={0.35}>
                        {(surface.limits ?? []).map((limit) => <Typography key={limit} variant="caption" color="text.secondary">• {limit}</Typography>)}
                        {surface.limits_url && <MuiLink href={surface.limits_url} target="_blank" rel="noreferrer" underline="hover" variant="caption">View documented limits</MuiLink>}
                        {usageLines(surface.live_usage).map((line) => <Typography key={line} variant="caption" color="success.main">Live · {line}</Typography>)}
                        {surface.provider_error && <Typography variant="caption" color="error.main">Live check: {surface.provider_error}</Typography>}
                        {surface.last_verified_at && <Typography variant="caption" color="text.secondary">Verified {dateTime(surface.last_verified_at)}</Typography>}
                      </Stack>
                    </TableCell>
                    <TableCell sx={{ minWidth: 220 }}><Typography variant="body2" color="text.secondary">{surface.action || "No action required."}</Typography></TableCell>
                  </TableRow>;
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>

      <Card variant="outlined"><CardContent>
        <Typography variant="h6" fontWeight={800}>AI metering detail</Typography>
        <Stack direction="row" spacing={3} sx={{ mt: 1.5, mb: 2, flexWrap: "wrap", rowGap: 1 }}>
          <Box><Typography variant="caption" color="text.secondary">Requests</Typography><Typography fontWeight={700}>{number.format(data.request_count)}</Typography></Box>
          <Box><Typography variant="caption" color="text.secondary">Input tokens</Typography><Typography fontWeight={700}>{number.format(data.input_tokens)}</Typography></Box>
          <Box><Typography variant="caption" color="text.secondary">Output tokens</Typography><Typography fontWeight={700}>{number.format(data.output_tokens)}</Typography></Box>
        </Stack>
        {data.by_model.length ? <TableContainer><Table size="small"><TableHead><TableRow><TableCell>Provider</TableCell><TableCell>Model</TableCell><TableCell>Tier</TableCell><TableCell align="right">Requests</TableCell><TableCell align="right">Estimated cost</TableCell></TableRow></TableHead><TableBody>{data.by_model.map((item) => <TableRow key={`${item.provider}:${item.model}:${item.tier}`}><TableCell>{item.provider}</TableCell><TableCell>{item.model}</TableCell><TableCell>{item.tier}</TableCell><TableCell align="right">{number.format(item.request_count)}</TableCell><TableCell align="right">{money(item.estimated_cost_usd)}</TableCell></TableRow>)}</TableBody></Table></TableContainer> : <Typography color="text.secondary">No metered AI requests in this period.</Typography>}
      </CardContent></Card>

      <Box sx={{ px: 0.5, pb: 1 }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.6 }}>
          <Box component="span" sx={{ fontWeight: 800 }}>Cost semantics:</Box>{" "}
          Actual provider charges are shown only where QTXpert has an authoritative billing feed. Account limits and live usage are refreshed monthly when a scoped provider connector is configured; links remain available for manual verification. A missing amount is never treated as zero.
        </Typography>
      </Box>
    </Stack>}
  </Box>;
}
