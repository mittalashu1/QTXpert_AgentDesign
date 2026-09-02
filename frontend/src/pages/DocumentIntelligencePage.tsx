import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControl,
  Grid,
  InputLabel,
  LinearProgress,
  MenuItem,
  Select,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import AssessmentOutlinedIcon from "@mui/icons-material/AssessmentOutlined";
import { useNavigate } from "react-router-dom";
import { documentIntelligenceApi } from "@/services/api";
import { DocumentAnalysisRun, DocumentFinding, DocumentFindingStatus, DocumentProfile, DocumentTraceability, UploadedAsset } from "@/types/domain";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import RepositoryDocumentsPicker from "@/components/RepositoryDocumentsPicker";
import { useRepositoryAssets } from "@/components/repositoryAssets";

const EXTRACTABLE_EXTENSIONS = new Set([
  "pdf", "docx", "pptx", "txt", "md", "json", "csv", "xlsx", "xls", "xml", "yaml", "yml", "html", "htm",
]);
const EXCLUDED = new Set(["apk", "ipa", "mp4", "mov", "webm"]);

const profileLabels: Record<DocumentProfile, string> = {
  general: "General enterprise",
  banking: "Banking & financial services",
  retail: "Retail / e-commerce",
  saas: "SaaS",
  government: "Government / public sector",
};

const areaLabels: Record<string, string> = {
  completeness: "Requirement completeness",
  clarity: "Clarity & ambiguity",
  consistency: "Cross-document consistency",
  testability: "Testability",
  traceability: "Traceability",
  acceptance_criteria: "Acceptance criteria",
  nfr_coverage: "NFR coverage",
  integration_detail: "Integration detail",
};

const areaCategories: Record<string, string[]> = {
  completeness: ["missing_requirement", "incomplete_requirement", "missing_business_rule", "missing_dependency", "missing_document"],
  clarity: ["ambiguity", "non_testable", "unresolved_tbd"],
  consistency: ["contradiction", "cross_document_conflict", "existing_system_conflict", "obsolete_requirement"],
  testability: ["non_testable", "missing_validation", "missing_boundary", "missing_error_handling", "missing_recovery"],
  traceability: ["broken_traceability", "change_impact_gap"],
  acceptance_criteria: ["missing_acceptance_criteria"],
  nfr_coverage: ["missing_nfr", "missing_security_control", "missing_regulatory", "missing_audit_logging"],
  integration_detail: ["missing_integration", "missing_api_contract", "missing_data_mapping", "missing_role_permission"],
};

function pretty(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function scoreStatus(score: number) {
  if (score >= 85) return { label: "Strong", color: "success" as const };
  if (score >= 70) return { label: "Adequate", color: "info" as const };
  if (score >= 50) return { label: "Partial", color: "warning" as const };
  return { label: "Gap", color: "error" as const };
}

function findingColor(severity: string): "error" | "warning" | "info" | "default" {
  if (severity === "critical") return "error";
  if (severity === "high") return "warning";
  if (severity === "medium") return "info";
  return "default";
}

function readableError(reason: unknown, fallback: string): string {
  if (typeof reason === "object" && reason !== null) {
    const candidate = reason as {
      response?: { data?: { detail?: unknown } };
      message?: unknown;
    };
    const detail = candidate.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (typeof candidate.message === "string" && candidate.message.trim()) return candidate.message;
  }
  return fallback;
}

function redactContextForStorage(value: string) {
  return value
    .replace(/(["']?\b(?:password|passcode|token|secret|otp|api[_ -]?key|access[_ -]?key|client[_ -]?secret|refresh[_ -]?token)\b["']?)\s*[:=]\s*(["']?)[^,;\n"']+\2/gi, "$1: [REDACTED]")
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]{12,}/gi, "Bearer [REDACTED]")
    .slice(0, 8000);
}

export default function DocumentIntelligencePage() {
  const navigate = useNavigate();
  const { selectedProjectId } = useSelectedProject();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState(0);
  const [profile, setProfile] = useState<DocumentProfile>("general");
  const [changeContext, setChangeContext] = useState("");
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!selectedProjectId) return;
    const storedContext = localStorage.getItem(`qtxpert-document-context:${selectedProjectId}`) || "";
    const safeContext = redactContextForStorage(storedContext);
    setChangeContext(safeContext);
    if (safeContext !== storedContext) localStorage.setItem(`qtxpert-document-context:${selectedProjectId}`, safeContext);
    setMessage("");
    setError("");
    setTab(0);
    setSelectedAssetIds([]);
  }, [selectedProjectId]);

  useEffect(() => {
    if (selectedProjectId) localStorage.setItem(`qtxpert-document-context:${selectedProjectId}`, redactContextForStorage(changeContext));
  }, [selectedProjectId, changeContext]);

  const uploadsQuery = useRepositoryAssets({
    projectId: selectedProjectId,
    categories: ["document"],
    cacheKey: "document-intelligence-assets",
  });

  const latestRunQuery = useQuery({
    queryKey: ["document-intelligence-latest", selectedProjectId],
    queryFn: () => documentIntelligenceApi.latest(selectedProjectId).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
    refetchInterval: (query) => {
      const status = (query.state.data as DocumentAnalysisRun | null | undefined)?.status;
      return status && ["queued", "extracting", "analyzing"].includes(status) ? 2500 : false;
    },
  });

  const traceabilityQuery = useQuery<DocumentTraceability | null>({
    queryKey: ["document-intelligence-traceability", latestRunQuery.data?.id],
    queryFn: () => latestRunQuery.data?.id
      ? documentIntelligenceApi.traceability(latestRunQuery.data.id).then((response) => response.data)
      : Promise.resolve(null),
    enabled: Boolean(latestRunQuery.data?.id && latestRunQuery.data?.status === "completed"),
    refetchInterval: (query) => {
      const value = query.state.data;
      return value && (value.active_execution_count > 0 || value.generation_runs.some((item) => ["pending", "normalizing", "analyzing", "generating_scenarios", "generating_test_cases", "risk_analysis"].includes(item.status))) ? 4000 : false;
    },
  });

  const projectAssets = useMemo(
    // Test data and application builds have their own repositories. Document
    // Intelligence should only review assets classified as documents.
    () => uploadsQuery.assets.filter((asset) => asset.category === "document" && asset.source_module !== "test_data" && !EXCLUDED.has(asset.extension.toLowerCase())),
    [uploadsQuery.assets]
  );
  const analyzableAssets = useMemo(
    () => projectAssets.filter((asset) => EXTRACTABLE_EXTENSIONS.has(asset.extension.toLowerCase())),
    [projectAssets]
  );

  const analyzeMutation = useMutation({
    mutationFn: () => documentIntelligenceApi.analyze({
      project_id: selectedProjectId,
      // Empty selection means review every extractable repository document;
      // an explicit selection keeps a focused review reproducible.
      asset_ids: selectedAssetIds.length ? selectedAssetIds : analyzableAssets.map((asset) => asset.id),
      profile,
      additional_context: changeContext,
    }),
    onSuccess: async () => {
      setMessage("AI documentation review started.");
      setError("");
      await queryClient.invalidateQueries({ queryKey: ["document-intelligence-latest", selectedProjectId] });
      setTab(0);
    },
    onError: (reason: unknown) => setError(readableError(reason, "Document analysis could not start")),
  });

  const reviewMutation = useMutation({
    mutationFn: ({ finding, status }: { finding: DocumentFinding; status: DocumentFindingStatus }) =>
      documentIntelligenceApi.reviewFinding(finding.id, {
        status,
        suggested_refinement: finding.suggested_refinement,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document-intelligence-latest", selectedProjectId] });
      if (run?.id) queryClient.invalidateQueries({ queryKey: ["document-intelligence-traceability", run.id] });
    },
    onError: (reason: unknown) => setError(readableError(reason, "Finding update failed")),
  });

  const publishMutation = useMutation({
    mutationFn: (runId: string) => documentIntelligenceApi.publish(runId),
    onSuccess: (response, runId) => {
      setMessage(response.data.message);
      queryClient.invalidateQueries({ queryKey: ["requirements", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["document-intelligence-latest", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["document-intelligence-traceability", runId] });
    },
    onError: (reason: unknown) => setError(readableError(reason, "Could not publish the intelligence baseline")),
  });

  const generateTestsMutation = useMutation({
    mutationFn: (runId: string) => documentIntelligenceApi.generateTests(runId, {
      generation_profile: "feature",
      test_set_title: "Document Intelligence test design",
    }),
    onSuccess: async (response) => {
      setMessage(response.data.message);
      await queryClient.invalidateQueries({ queryKey: ["document-intelligence-traceability", run?.id] });
      await queryClient.invalidateQueries({ queryKey: ["requirements", selectedProjectId] });
      navigate(`/design?run=${response.data.generation_run_id}`);
    },
    onError: (reason: unknown) => setError(readableError(reason, "Test Design generation could not start")),
  });

  const run = latestRunQuery.data;
  const running = Boolean(run && ["queued", "extracting", "analyzing"].includes(run.status));
  const scores = useMemo(() => run?.scores || {}, [run?.scores]);
  const unresolved = (run?.findings || []).filter((finding) => !["resolved", "rejected"].includes(finding.status));
  const critical = unresolved.filter((finding) => finding.severity === "critical").length;
  const high = unresolved.filter((finding) => finding.severity === "high").length;
  const traceability = traceabilityQuery.data;

  const coverageRows = useMemo(() => Object.keys(areaLabels).map((key) => {
    const score = Math.max(0, Math.min(100, Math.round(scores[key] || 0)));
    const related = unresolved.find((finding) => (areaCategories[key] || []).includes(finding.category));
    return {
      key,
      area: areaLabels[key],
      score,
      status: scoreStatus(score),
      improvement: related?.suggested_refinement || related?.title || (score >= 85 ? "No material gap identified." : "Review the supporting documentation for this area."),
    };
  }), [scores, unresolved]);

  if (!selectedProjectId) return <Alert severity="info">Create or select a project from the top bar.</Alert>;

  return (
    <Stack spacing={2.5}>
      <Box>
        <Stack direction="row" spacing={1} alignItems="center">
          <AutoAwesomeIcon color="primary" />
          <Typography variant="h4" fontWeight={800}>Document Intelligence</Typography>
          <Chip size="small" label="AI" color="primary" variant="outlined" />
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          Validate whether the current project documentation is complete and testable for the intended change.
        </Typography>
      </Box>

      {message && <Alert severity="success" onClose={() => setMessage("")}>{message}</Alert>}
      {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Grid container spacing={2} alignItems="flex-start">
            <Grid item xs={12} lg={8}>
              <TextField
                label="Change / scope context"
                value={changeContext}
                onChange={(event) => setChangeContext(event.target.value)}
                placeholder="Describe what is changing, the target journey/module, and any existing behaviour that must remain unchanged."
                multiline
                minRows={3}
                fullWidth
              />
            </Grid>
            <Grid item xs={12} sm={6} lg={4}>
              <FormControl fullWidth size="small">
                <InputLabel>Analysis profile</InputLabel>
                <Select label="Analysis profile" value={profile} onChange={(event) => setProfile(event.target.value as DocumentProfile)}>
                  {(Object.keys(profileLabels) as DocumentProfile[]).map((item) => <MenuItem key={item} value={item}>{profileLabels[item]}</MenuItem>)}
                </Select>
              </FormControl>
            </Grid>
          </Grid>
          <RepositoryDocumentsPicker
            projectId={selectedProjectId}
            selectedIds={selectedAssetIds}
            onSelectionChange={setSelectedAssetIds}
            sourceModule="document_intelligence"
            title="Choose repository documents (optional)"
            description="Upload a new document or select existing files from this project repository. Leave the selection empty to review every stored document."
            compact
            assets={projectAssets}
            assetsLoading={uploadsQuery.isLoading || uploadsQuery.isFetching}
            assetsError={uploadsQuery.isError}
            onOpenRepository={() => navigate("/test-data/documents")}
          />
          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }} sx={{ mt: 2 }}>
            <Button
              variant="contained"
              startIcon={running || analyzeMutation.isPending ? <CircularProgress size={18} color="inherit" /> : <AutoAwesomeIcon />}
              disabled={!analyzableAssets.length || running || analyzeMutation.isPending}
              onClick={() => analyzeMutation.mutate()}
            >
              {running ? "Reviewing documentation…" : "Run AI review"}
            </Button>
            <Typography variant="caption" color="text.secondary">
              {selectedAssetIds.length ? `${selectedAssetIds.length} selected document${selectedAssetIds.length === 1 ? "" : "s"}` : `${analyzableAssets.length} stored document${analyzableAssets.length === 1 ? "" : "s"} available`} for review · upload once, reuse from the repository
            </Typography>
          </Stack>
          {(running || analyzeMutation.isPending) && <LinearProgress sx={{ mt: 2 }} />}
        </CardContent>
      </Card>

      {run?.status === "failed" && <Alert severity="error">{run.error_message || "The latest review failed."}</Alert>}

      {run?.status === "completed" && (
        <>
          <Grid container spacing={1.5}>
            {[
              ["Change fulfilment", `${Math.round(run.readiness_score)}%`],
              ["Testability", `${Math.round(scores.testability || 0)}%`],
              ["Documents reviewed", run.document_inventory?.length || 0],
              ["Critical / high gaps", `${critical} / ${high}`],
            ].map(([label, value]) => (
              <Grid item xs={6} lg={3} key={String(label)}>
                <Card variant="outlined"><CardContent><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h4" fontWeight={800}>{value}</Typography></CardContent></Card>
              </Grid>
            ))}
          </Grid>
          <Alert severity={run.readiness_score >= 85 ? "success" : run.readiness_score >= 70 ? "info" : run.readiness_score >= 50 ? "warning" : "error"}>
            <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }} justifyContent="space-between">
              <Box><b>{pretty(run.readiness_status)}</b>{run.summary ? ` · ${run.summary}` : ""}</Box>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                <Button size="small" variant="outlined" startIcon={<CheckCircleOutlineIcon />} disabled={publishMutation.isPending} onClick={() => publishMutation.mutate(run.id)}>
                  {run.published_requirement_id ? "Refresh baseline" : "Publish baseline"}
                </Button>
                <Button size="small" variant="contained" startIcon={generateTestsMutation.isPending ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRoundedIcon />} disabled={generateTestsMutation.isPending || traceability?.generation_runs.some((item) => ["pending", "normalizing", "analyzing", "generating_scenarios", "generating_test_cases", "risk_analysis"].includes(item.status))} onClick={() => generateTestsMutation.mutate(run.id)}>
                  Generate Test Design
                </Button>
              </Stack>
            </Stack>
          </Alert>
          <Card variant="outlined" sx={{ borderRadius: 3 }}>
            <CardContent>
              <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }} justifyContent="space-between">
                <Box>
                  <Typography variant="h6" fontWeight={800}>Downstream delivery</Typography>
                  <Typography variant="body2" color="text.secondary">Trace this static document baseline into Test Design, Test Execution and runtime reporting.</Typography>
                </Box>
                <Chip size="small" label={`Last analysis: ${new Date(run.updated_at).toLocaleString()}`} variant="outlined" />
              </Stack>
              {traceabilityQuery.isLoading && <LinearProgress sx={{ mt: 2 }} />}
              {traceability && <>
                <Grid container spacing={1.25} sx={{ mt: 1 }}>
                  {[
                    ["Open findings", traceability.open_finding_count, traceability.critical_finding_count ? `${traceability.critical_finding_count} critical` : "Review before sign-off"],
                    ["Test Design cases", traceability.generated_test_case_count, `${traceability.generation_runs.length} linked run${traceability.generation_runs.length === 1 ? "" : "s"}`],
                    ["Execution plans", traceability.execution_plan_count, `${traceability.execution_run_count} run${traceability.execution_run_count === 1 ? "" : "s"}`],
                    ["Runtime results", traceability.executed_test_count, traceability.active_execution_count ? `${traceability.active_execution_count} run${traceability.active_execution_count === 1 ? "" : "s"} in progress` : traceability.executed_test_count ? `${traceability.passed_count} passed · ${traceability.failed_count} failed` : traceability.pending_test_count ? `${traceability.pending_test_count} result${traceability.pending_test_count === 1 ? "" : "s"} pending` : "Pending execution"],
                  ].map(([label, value, detail]) => <Grid item xs={6} md={3} key={String(label)}><Box sx={{ p: 1.5, bgcolor: "action.hover", borderRadius: 2, height: "100%" }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h5" fontWeight={800}>{value}</Typography><Typography variant="caption" color="text.secondary">{detail}</Typography></Box></Grid>)}
                </Grid>
                <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mt: 1.5 }}>
                  {traceability.generation_runs[0] && <Button size="small" variant="outlined" startIcon={<PlayArrowRoundedIcon />} onClick={() => navigate(`/design?run=${traceability.generation_runs[0].id}`)}>Open Test Design</Button>}
                  <Button size="small" variant="outlined" startIcon={<AutoAwesomeIcon />} onClick={() => navigate(`/autopilot?document_run=${run.id}`)}>Open Autopilot with baseline</Button>
                  <Button size="small" variant="outlined" startIcon={<AccountTreeOutlinedIcon />} onClick={() => navigate("/execution")}>Open Test Execution</Button>
                  <Button size="small" variant="outlined" startIcon={<AssessmentOutlinedIcon />} onClick={() => navigate("/reports")}>Open Test Reports</Button>
                </Stack>
                {traceability.next_actions.length > 0 && <Alert severity="info" sx={{ mt: 1.5 }}><Typography variant="body2" fontWeight={700}>Next actions</Typography>{traceability.next_actions.slice(0, 4).map((action) => <Typography variant="body2" key={action}>• {action}</Typography>)}</Alert>}
              </>}
              {!traceabilityQuery.isLoading && !traceability && <Alert severity="info" sx={{ mt: 1.5 }}>Downstream traceability will appear when this analysis is available.</Alert>}
            </CardContent>
          </Card>
        </>
      )}

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <Tabs value={tab} onChange={(_, value) => setTab(value)} variant="scrollable" scrollButtons="auto" sx={{ px: 2, borderBottom: "1px solid", borderColor: "divider" }}>
          <Tab label="Coverage" />
          <Tab label={`Documents (${projectAssets.length})`} />
          <Tab label={`Findings (${run?.findings?.length || 0})`} />
          <Tab label="Refinements" />
        </Tabs>
        <CardContent>
          {tab === 0 && <CoverageTable run={run} rows={coverageRows} context={changeContext || run?.additional_context || ""} />}
          {tab === 1 && <DocumentsTable assets={projectAssets} run={run} />}
          {tab === 2 && <FindingsTable run={run} onReview={(finding, status) => reviewMutation.mutate({ finding, status })} />}
          {tab === 3 && <RefinementsTable run={run} onReview={(finding, status) => reviewMutation.mutate({ finding, status })} />}
        </CardContent>
      </Card>
    </Stack>
  );
}

function CoverageTable({ run, rows, context }: { run?: DocumentAnalysisRun | null; rows: Array<{ key: string; area: string; score: number; status: { label: string; color: "success" | "info" | "warning" | "error" }; improvement: string }>; context: string }) {
  if (!run || run.status !== "completed") return <Alert severity="info">Run the AI review to produce documentation coverage and improvement areas.</Alert>;
  return (
    <Stack spacing={2}>
      {context.trim() && <Typography variant="body2" color="text.secondary"><b>Change context:</b> {context}</Typography>}
      <TableContainer>
        <Table size="small">
          <TableHead><TableRow><TableCell>Assessment area</TableCell><TableCell width={150}>Fulfilment</TableCell><TableCell width={130}>Status</TableCell><TableCell>Improvement / gap</TableCell></TableRow></TableHead>
          <TableBody>
            {rows.map((row) => <TableRow key={row.key} hover><TableCell sx={{ fontWeight: 700 }}>{row.area}</TableCell><TableCell>{row.score}%</TableCell><TableCell><Chip size="small" color={row.status.color} label={row.status.label} variant="outlined" /></TableCell><TableCell>{row.improvement}</TableCell></TableRow>)}
            <TableRow sx={{ bgcolor: "action.hover" }}><TableCell sx={{ fontWeight: 800 }}>Overall documentation readiness for change</TableCell><TableCell sx={{ fontWeight: 800 }}>{Math.round(run.readiness_score)}%</TableCell><TableCell><Chip size="small" color={scoreStatus(run.readiness_score).color} label={scoreStatus(run.readiness_score).label} /></TableCell><TableCell>{run.recommendations?.[0] || "Review unresolved findings before finalising the test baseline."}</TableCell></TableRow>
          </TableBody>
        </Table>
      </TableContainer>
    </Stack>
  );
}

function DocumentsTable({ assets, run }: { assets: UploadedAsset[]; run?: DocumentAnalysisRun | null }) {
  const inventory = new Map((run?.document_inventory || []).map((item) => [item.asset_id, item]));
  if (!assets.length) return <Alert severity="info">No documents are stored for this project yet. Upload one or open the Document repository to add it.</Alert>;
  return (
    <TableContainer>
      <Table size="small">
        <TableHead><TableRow><TableCell>Document</TableCell><TableCell>Type</TableCell><TableCell>Quality</TableCell><TableCell>Testability</TableCell><TableCell>Change fit</TableCell><TableCell>Issues</TableCell><TableCell>Source</TableCell><TableCell>Size</TableCell><TableCell>Uploaded</TableCell><TableCell>Storage</TableCell><TableCell>Status</TableCell></TableRow></TableHead>
        <TableBody>
          {assets.map((asset) => {
            const item = inventory.get(asset.id);
            const fit = item ? Math.round((item.quality_score + item.testability_score) / 2) : null;
            const formatBytes = (value: number) => value < 1024 * 1024 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`;
            const uploaded = new Date(asset.created_at);
            const uploadedLabel = Number.isNaN(uploaded.getTime()) ? "—" : uploaded.toLocaleString();
            return <TableRow key={asset.id} hover><TableCell><Typography variant="body2" fontWeight={700}>{asset.filename}</Typography><Typography variant="caption" color="text.secondary">{asset.extension.toUpperCase()} · SHA {asset.sha256.slice(0, 10)}…</Typography></TableCell><TableCell>{item?.document_type || "Pending review"}</TableCell><TableCell>{item ? `${item.quality_score}%` : "—"}</TableCell><TableCell>{item ? `${item.testability_score}%` : "—"}</TableCell><TableCell>{fit === null ? "—" : `${fit}%`}</TableCell><TableCell>{item?.issue_count ?? "—"}</TableCell><TableCell>{pretty(asset.source_module)}</TableCell><TableCell>{formatBytes(asset.size_bytes)}</TableCell><TableCell sx={{ whiteSpace: "nowrap" }}>{uploadedLabel}</TableCell><TableCell><Chip size="small" variant="outlined" label={pretty(asset.storage_backend)} /></TableCell><TableCell><Chip size="small" color={asset.status === "ready" ? "success" : "warning"} variant="outlined" label={pretty(asset.status)} /></TableCell></TableRow>;
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function FindingsTable({ run, onReview }: { run?: DocumentAnalysisRun | null; onReview: (finding: DocumentFinding, status: DocumentFindingStatus) => void }) {
  if (!run || run.status !== "completed") return <Alert severity="info">Findings will appear after the AI review completes.</Alert>;
  if (!run.findings.length) return <Alert severity="success">No material documentation gaps were identified.</Alert>;
  const order = { critical: 0, high: 1, medium: 2, low: 3 } as Record<string, number>;
  const findings = [...run.findings].sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
  return (
    <TableContainer>
      <Table size="small">
        <TableHead><TableRow><TableCell>ID</TableCell><TableCell>Severity</TableCell><TableCell>Area / finding</TableCell><TableCell>Testing impact</TableCell><TableCell>Recommendation</TableCell><TableCell>Confidence</TableCell><TableCell>Review</TableCell></TableRow></TableHead>
        <TableBody>
          {findings.map((finding) => <TableRow key={finding.id} hover><TableCell>{finding.finding_key}</TableCell><TableCell><Chip size="small" color={findingColor(finding.severity)} label={finding.severity.toUpperCase()} /></TableCell><TableCell sx={{ minWidth: 240 }}><Typography variant="body2" fontWeight={700}>{finding.title}</Typography><Typography variant="caption" color="text.secondary">{pretty(finding.category)}</Typography></TableCell><TableCell sx={{ minWidth: 220 }}>{finding.testing_impact || finding.description}</TableCell><TableCell sx={{ minWidth: 240 }}>{finding.suggested_refinement || "Clarify and document the expected behaviour."}</TableCell><TableCell>{Math.round(finding.confidence * 100)}%</TableCell><TableCell><Stack direction="row" spacing={0.5}><Button size="small" onClick={() => onReview(finding, "accepted")}>Accept</Button><Button size="small" onClick={() => onReview(finding, "needs_clarification")}>Clarify</Button><Button size="small" onClick={() => onReview(finding, "resolved")}>Resolve</Button></Stack></TableCell></TableRow>)}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function RefinementsTable({ run, onReview }: { run?: DocumentAnalysisRun | null; onReview: (finding: DocumentFinding, status: DocumentFindingStatus) => void }) {
  const findings = (run?.findings || []).filter((finding) => finding.suggested_refinement);
  if (!run || run.status !== "completed") return <Alert severity="info">AI refinements will appear after the review completes.</Alert>;
  if (!findings.length) return <Alert severity="success">No AI refinements are currently proposed.</Alert>;
  return (
    <TableContainer>
      <Table size="small">
        <TableHead><TableRow><TableCell>Finding</TableCell><TableCell>Current wording / issue</TableCell><TableCell>AI refinement</TableCell><TableCell>Status</TableCell><TableCell>Action</TableCell></TableRow></TableHead>
        <TableBody>
          {findings.map((finding) => <TableRow key={finding.id} hover><TableCell sx={{ minWidth: 220 }}><Typography variant="body2" fontWeight={700}>{finding.finding_key} · {finding.title}</Typography></TableCell><TableCell sx={{ minWidth: 260 }}>{finding.original_text || finding.description}</TableCell><TableCell sx={{ minWidth: 300 }}>{finding.suggested_refinement}</TableCell><TableCell><Chip size="small" label={pretty(finding.status)} variant="outlined" /></TableCell><TableCell><Stack direction="row" spacing={0.5}><Button size="small" onClick={() => onReview(finding, "accepted")}>Accept</Button><Button size="small" onClick={() => onReview(finding, "rejected")}>Reject</Button></Stack></TableCell></TableRow>)}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
