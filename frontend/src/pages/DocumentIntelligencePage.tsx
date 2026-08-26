import { ChangeEvent, useEffect, useMemo, useState } from "react";
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
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import { documentIntelligenceApi, uploadsApi } from "@/services/api";
import { DocumentAnalysisRun, DocumentFinding, DocumentFindingStatus, DocumentProfile, UploadedAsset } from "@/types/domain";
import { useSelectedProject } from "@/hooks/useSelectedProject";

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

export default function DocumentIntelligencePage() {
  const { selectedProjectId, selectedProject } = useSelectedProject();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState(0);
  const [profile, setProfile] = useState<DocumentProfile>("general");
  const [changeContext, setChangeContext] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!selectedProjectId) return;
    setChangeContext(localStorage.getItem(`qtxpert-document-context:${selectedProjectId}`) || "");
    setMessage("");
    setError("");
    setTab(0);
  }, [selectedProjectId]);

  useEffect(() => {
    if (selectedProjectId) localStorage.setItem(`qtxpert-document-context:${selectedProjectId}`, changeContext);
  }, [selectedProjectId, changeContext]);

  const uploadsQuery = useQuery({
    queryKey: ["document-intelligence-assets", selectedProjectId],
    queryFn: () => uploadsApi.list({ project_id: selectedProjectId }).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
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

  const projectAssets = useMemo(
    () => (uploadsQuery.data || []).filter((asset) => !EXCLUDED.has(asset.extension.toLowerCase())),
    [uploadsQuery.data]
  );
  const analyzableAssets = useMemo(
    () => projectAssets.filter((asset) => EXTRACTABLE_EXTENSIONS.has(asset.extension.toLowerCase())),
    [projectAssets]
  );

  const uploadMutation = useMutation({
    mutationFn: async (files: File[]) => {
      const results: UploadedAsset[] = [];
      for (const file of files) {
        const response = await uploadsApi.upload(file, {
          projectId: selectedProjectId,
          sourceModule: "document_intelligence",
        });
        results.push(response.data);
      }
      return results;
    },
    onSuccess: async (assets) => {
      await queryClient.invalidateQueries({ queryKey: ["document-intelligence-assets", selectedProjectId] });
      setMessage(`${assets.length} document${assets.length === 1 ? "" : "s"} added to ${selectedProject?.name || "this project"}.`);
      setError("");
    },
    onError: (reason: any) => setError(reason?.response?.data?.detail || reason?.message || "Document upload failed"),
  });

  const analyzeMutation = useMutation({
    mutationFn: () => documentIntelligenceApi.analyze({
      project_id: selectedProjectId,
      // Every analyzable document in the active project is deliberately included.
      asset_ids: analyzableAssets.map((asset) => asset.id),
      profile,
      additional_context: changeContext,
    }),
    onSuccess: async () => {
      setMessage("AI documentation review started.");
      setError("");
      await queryClient.invalidateQueries({ queryKey: ["document-intelligence-latest", selectedProjectId] });
      setTab(0);
    },
    onError: (reason: any) => setError(reason?.response?.data?.detail || reason?.message || "Document analysis could not start"),
  });

  const reviewMutation = useMutation({
    mutationFn: ({ finding, status }: { finding: DocumentFinding; status: DocumentFindingStatus }) =>
      documentIntelligenceApi.reviewFinding(finding.id, {
        status,
        suggested_refinement: finding.suggested_refinement,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["document-intelligence-latest", selectedProjectId] }),
    onError: (reason: any) => setError(reason?.response?.data?.detail || "Finding update failed"),
  });

  const publishMutation = useMutation({
    mutationFn: (runId: string) => documentIntelligenceApi.publish(runId),
    onSuccess: (response) => {
      setMessage(response.data.message);
      queryClient.invalidateQueries({ queryKey: ["requirements", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["document-intelligence-latest", selectedProjectId] });
    },
    onError: (reason: any) => setError(reason?.response?.data?.detail || "Could not publish the intelligence baseline"),
  });

  const run = latestRunQuery.data;
  const running = Boolean(run && ["queued", "extracting", "analyzing"].includes(run.status));
  const scores = run?.scores || {};
  const unresolved = (run?.findings || []).filter((finding) => !["resolved", "rejected"].includes(finding.status));
  const critical = unresolved.filter((finding) => finding.severity === "critical").length;
  const high = unresolved.filter((finding) => finding.severity === "high").length;

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

  const handleFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (files.length) uploadMutation.mutate(files);
    event.target.value = "";
  };

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
            <Grid item xs={12} lg={7}>
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
            <Grid item xs={12} sm={6} lg={3}>
              <FormControl fullWidth size="small">
                <InputLabel>Analysis profile</InputLabel>
                <Select label="Analysis profile" value={profile} onChange={(event) => setProfile(event.target.value as DocumentProfile)}>
                  {(Object.keys(profileLabels) as DocumentProfile[]).map((item) => <MenuItem key={item} value={item}>{profileLabels[item]}</MenuItem>)}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={6} lg={2}>
              <Button component="label" variant="outlined" startIcon={<UploadFileOutlinedIcon />} fullWidth disabled={uploadMutation.isPending}>
                Add documents
                <input hidden multiple type="file" onChange={handleFiles} accept=".pdf,.docx,.pptx,.txt,.md,.json,.csv,.xlsx,.xls,.xml,.yaml,.yml,.html,.htm" />
              </Button>
            </Grid>
          </Grid>
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
              {analyzableAssets.length} project document{analyzableAssets.length === 1 ? "" : "s"} included automatically · existing requirements and test baseline are also considered
            </Typography>
          </Stack>
          {(running || uploadMutation.isPending) && <LinearProgress sx={{ mt: 2 }} />}
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
              <Button size="small" variant="contained" startIcon={<CheckCircleOutlineIcon />} disabled={publishMutation.isPending} onClick={() => publishMutation.mutate(run.id)}>
                {run.published_requirement_id ? "Refresh Test Design baseline" : "Send to Test Design"}
              </Button>
            </Stack>
          </Alert>
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
          {tab === 0 && <CoverageTable run={run} rows={coverageRows} context={changeContext} />}
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
  if (!assets.length) return <Alert severity="info">No documents are stored for this project yet.</Alert>;
  return (
    <TableContainer>
      <Table size="small">
        <TableHead><TableRow><TableCell>Document</TableCell><TableCell>Type</TableCell><TableCell>Quality</TableCell><TableCell>Testability</TableCell><TableCell>Change fit</TableCell><TableCell>Issues</TableCell><TableCell>Source</TableCell></TableRow></TableHead>
        <TableBody>
          {assets.map((asset) => {
            const item = inventory.get(asset.id);
            const fit = item ? Math.round((item.quality_score + item.testability_score) / 2) : null;
            return <TableRow key={asset.id} hover><TableCell><Typography variant="body2" fontWeight={700}>{asset.filename}</Typography><Typography variant="caption" color="text.secondary">{asset.extension.toUpperCase()}</Typography></TableCell><TableCell>{item?.document_type || "Pending review"}</TableCell><TableCell>{item ? `${item.quality_score}%` : "—"}</TableCell><TableCell>{item ? `${item.testability_score}%` : "—"}</TableCell><TableCell>{fit === null ? "—" : `${fit}%`}</TableCell><TableCell>{item?.issue_count ?? "—"}</TableCell><TableCell>{pretty(asset.source_module)}</TableCell></TableRow>;
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
