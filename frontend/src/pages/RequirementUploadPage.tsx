import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
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
  Tooltip,
  Typography,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import HubOutlinedIcon from "@mui/icons-material/HubOutlined";
import RuleOutlinedIcon from "@mui/icons-material/RuleOutlined";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import { documentIntelligenceApi, uploadsApi } from "@/services/api";
import { DocumentAnalysisRun, DocumentFinding, DocumentFindingStatus, DocumentProfile, UploadedAsset } from "@/types/domain";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import ProjectSelector from "@/components/ProjectSelector";

const EXTRACTABLE_EXTENSIONS = new Set([
  "pdf", "docx", "pptx", "txt", "md", "json", "csv", "xlsx", "xls", "xml", "yaml", "yml", "html", "htm",
]);
const EXCLUDED_PROJECT_ASSETS = new Set(["apk", "ipa", "mp4", "mov", "webm"]);

const profileLabels: Record<DocumentProfile, string> = {
  general: "General enterprise",
  banking: "Banking & financial services",
  retail: "Retail / e-commerce",
  saas: "SaaS",
  government: "Government / public sector",
};

const severityColor = (severity: string): "error" | "warning" | "info" | "default" => {
  if (severity === "critical") return "error";
  if (severity === "high") return "warning";
  if (severity === "medium") return "info";
  return "default";
};

const readinessColor = (status?: string): "error" | "warning" | "success" | "info" => {
  if (!status || status.includes("not_ready")) return "error";
  if (status === "needs_refinement") return "warning";
  if (status === "ready_with_risk") return "warning";
  if (status === "ready_for_test_design") return "success";
  return "info";
};

const pretty = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

export default function RequirementUploadPage() {
  const { selectedProjectId } = useSelectedProject();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState(0);
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [profile, setProfile] = useState<DocumentProfile>("general");
  const [additionalContext, setAdditionalContext] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setSelectedAssetIds([]);
    setMessage("");
    setError("");
  }, [selectedProjectId]);

  const uploadsQuery = useQuery({
    queryKey: ["document-intelligence-assets", selectedProjectId],
    queryFn: () => uploadsApi.list({ project_id: selectedProjectId }).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
  });

  const latestRunQuery = useQuery({
    queryKey: ["document-intelligence-latest", selectedProjectId],
    queryFn: () => documentIntelligenceApi.latest(selectedProjectId).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
    refetchInterval: 2500,
  });

  const projectAssets = useMemo(
    () => (uploadsQuery.data || []).filter((asset) => !EXCLUDED_PROJECT_ASSETS.has(asset.extension.toLowerCase())),
    [uploadsQuery.data]
  );
  const analyzableAssets = useMemo(
    () => projectAssets.filter((asset) => EXTRACTABLE_EXTENSIONS.has(asset.extension.toLowerCase())),
    [projectAssets]
  );

  const uploadMutation = useMutation({
    mutationFn: async (files: File[]) => {
      const uploaded: UploadedAsset[] = [];
      for (const file of files) {
        const response = await uploadsApi.upload(file, {
          projectId: selectedProjectId,
          sourceModule: "document_intelligence",
        });
        uploaded.push(response.data);
      }
      return uploaded;
    },
    onSuccess: (assets) => {
      queryClient.invalidateQueries({ queryKey: ["document-intelligence-assets", selectedProjectId] });
      setSelectedAssetIds((current) => Array.from(new Set([
        ...current,
        ...assets.filter((asset) => EXTRACTABLE_EXTENSIONS.has(asset.extension.toLowerCase())).map((asset) => asset.id),
      ])));
      setMessage(`${assets.length} document${assets.length === 1 ? "" : "s"} added to the project repository.`);
      setError("");
    },
    onError: (err: any) => setError(err?.response?.data?.detail || err?.message || "Document upload failed"),
  });

  const analyzeMutation = useMutation({
    mutationFn: () => documentIntelligenceApi.analyze({
      project_id: selectedProjectId,
      asset_ids: selectedAssetIds,
      profile,
      additional_context: additionalContext,
    }),
    onSuccess: () => {
      setMessage("AI documentation review started. QTXpert is correlating the selected project documents.");
      setError("");
      queryClient.invalidateQueries({ queryKey: ["document-intelligence-latest", selectedProjectId] });
      setTab(0);
    },
    onError: (err: any) => setError(err?.response?.data?.detail || err?.message || "Document analysis could not start"),
  });

  const reviewMutation = useMutation({
    mutationFn: ({ finding, status }: { finding: DocumentFinding; status: DocumentFindingStatus }) =>
      documentIntelligenceApi.reviewFinding(finding.id, {
        status,
        suggested_refinement: finding.suggested_refinement,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["document-intelligence-latest", selectedProjectId] }),
    onError: (err: any) => setError(err?.response?.data?.detail || "Finding update failed"),
  });

  const publishMutation = useMutation({
    mutationFn: (runId: string) => documentIntelligenceApi.publish(runId),
    onSuccess: (response) => {
      setMessage(response.data.message);
      setError("");
      queryClient.invalidateQueries({ queryKey: ["document-intelligence-latest", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["requirements", selectedProjectId] });
    },
    onError: (err: any) => setError(err?.response?.data?.detail || err?.message || "Could not publish the intelligence baseline"),
  });

  const run = latestRunQuery.data;
  const isRunning = Boolean(run && ["queued", "extracting", "analyzing"].includes(run.status));

  const handleFiles = (files: FileList | null) => {
    if (!files || !selectedProjectId) return;
    uploadMutation.mutate(Array.from(files));
  };

  const onFileInput = (event: ChangeEvent<HTMLInputElement>) => {
    handleFiles(event.target.files);
    event.target.value = "";
  };

  const toggleAsset = (assetId: string) => {
    setSelectedAssetIds((current) => current.includes(assetId)
      ? current.filter((id) => id !== assetId)
      : [...current, assetId]);
  };

  const selectAll = () => setSelectedAssetIds(analyzableAssets.map((asset) => asset.id));

  return (
    <Stack spacing={3}>
      <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} spacing={2}>
        <Box>
          <Stack direction="row" spacing={1.25} alignItems="center">
            <AutoAwesomeIcon color="primary" />
            <Typography variant="h4" fontWeight={800}>AI Document Intelligence</Typography>
          </Stack>
          <Typography color="text.secondary" sx={{ mt: 0.75, maxWidth: 950 }}>
            QTXpert reviews the complete development and testing documentation baseline, finds gaps and contradictions, measures testability, proposes refinements and creates a trusted input for Test Design.
          </Typography>
        </Box>
        <ProjectSelector />
      </Stack>

      {!selectedProjectId && <Alert severity="info">Select or create a project to review its documentation baseline.</Alert>}
      {message && <Alert severity="success" onClose={() => setMessage("")}>{message}</Alert>}
      {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}

      {selectedProjectId && (
        <>
          <Paper variant="outlined" sx={{ p: { xs: 2, md: 3 }, borderRadius: 3 }}>
            <Grid container spacing={2.5} alignItems="stretch">
              <Grid item xs={12} lg={7}>
                <Stack spacing={2}>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                    <FormControl size="small" sx={{ minWidth: 260 }}>
                      <InputLabel id="document-profile-label">Analysis profile</InputLabel>
                      <Select
                        labelId="document-profile-label"
                        label="Analysis profile"
                        value={profile}
                        onChange={(event) => setProfile(event.target.value as DocumentProfile)}
                      >
                        {(Object.keys(profileLabels) as DocumentProfile[]).map((item) => (
                          <MenuItem key={item} value={item}>{profileLabels[item]}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                    <Button variant="outlined" onClick={selectAll} disabled={!analyzableAssets.length}>Select all analyzable</Button>
                    <Chip label={`${selectedAssetIds.length} selected`} color={selectedAssetIds.length ? "primary" : "default"} variant="outlined" />
                  </Stack>
                  <TextField
                    label="Optional project / change context"
                    multiline
                    minRows={2}
                    maxRows={5}
                    value={additionalContext}
                    onChange={(event) => setAdditionalContext(event.target.value)}
                    placeholder="Example: This is a change to the existing retail-banking transfer journey. Existing OTP and cooling-period rules should remain unless explicitly changed."
                    helperText="Use context for scope and intent only. Do not paste production credentials or secrets."
                  />
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
                    <Button
                      variant="contained"
                      size="large"
                      startIcon={analyzeMutation.isPending || isRunning ? <CircularProgress size={18} color="inherit" /> : <AutoAwesomeIcon />}
                      disabled={!selectedAssetIds.length || analyzeMutation.isPending || isRunning}
                      onClick={() => analyzeMutation.mutate()}
                    >
                      {isRunning ? "AI review in progress…" : "Run AI Documentation Review"}
                    </Button>
                    <Typography variant="caption" color="text.secondary">
                      Cross-document consistency + existing-system comparison + QA testability review
                    </Typography>
                  </Stack>
                  {isRunning && <LinearProgress />}
                </Stack>
              </Grid>
              <Grid item xs={12} lg={5}>
                <Box
                  onDragOver={(event) => { event.preventDefault(); setIsDragOver(true); }}
                  onDragLeave={() => setIsDragOver(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setIsDragOver(false);
                    handleFiles(event.dataTransfer.files);
                  }}
                  sx={{
                    height: "100%",
                    minHeight: 180,
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    textAlign: "center",
                    border: "2px dashed",
                    borderColor: isDragOver ? "primary.main" : "divider",
                    bgcolor: isDragOver ? "action.hover" : "background.default",
                    borderRadius: 3,
                    p: 2.5,
                  }}
                >
                  <UploadFileOutlinedIcon sx={{ fontSize: 42, color: "primary.main" }} />
                  <Typography fontWeight={700} sx={{ mt: 1 }}>Add project documentation</Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 420, my: 1 }}>
                    BRD, PRD, FSD, SRS, Jira/CSV/JSON, API/OpenAPI, XLS/XLSX, PPTX, XML/YAML, test plans, test cases and other development/testing artifacts.
                  </Typography>
                  <Button component="label" variant="outlined" disabled={uploadMutation.isPending}>
                    {uploadMutation.isPending ? "Uploading…" : "Browse documents"}
                    <input hidden multiple type="file" onChange={onFileInput} accept=".pdf,.docx,.pptx,.txt,.md,.json,.csv,.xlsx,.xls,.xml,.yaml,.yml,.html,.htm" />
                  </Button>
                </Box>
              </Grid>
            </Grid>
          </Paper>

          {run?.status === "failed" && <Alert severity="error">Latest Document Intelligence run failed: {run.error_message || "Unknown analysis error"}</Alert>}

          {run?.status === "completed" && <ReadinessSummary run={run} onPublish={() => publishMutation.mutate(run.id)} publishing={publishMutation.isPending} />}

          <Card variant="outlined" sx={{ borderRadius: 3 }}>
            <Tabs value={tab} onChange={(_, value) => setTab(value)} variant="scrollable" scrollButtons="auto" sx={{ px: 2, borderBottom: "1px solid", borderColor: "divider" }}>
              <Tab icon={<FactCheckOutlinedIcon />} iconPosition="start" label="Overview" />
              <Tab icon={<DescriptionOutlinedIcon />} iconPosition="start" label={`Documents (${projectAssets.length})`} />
              <Tab icon={<WarningAmberOutlinedIcon />} iconPosition="start" label={`AI Findings (${run?.findings?.length || 0})`} />
              <Tab icon={<HubOutlinedIcon />} iconPosition="start" label="Knowledge & Traceability" />
              <Tab icon={<RuleOutlinedIcon />} iconPosition="start" label="Refinements" />
            </Tabs>
            <CardContent sx={{ p: { xs: 2, md: 3 } }}>
              {tab === 0 && <OverviewTab run={run} projectAssets={projectAssets} />}
              {tab === 1 && (
                <DocumentsTab
                  assets={projectAssets}
                  run={run}
                  selectedAssetIds={selectedAssetIds}
                  onToggle={toggleAsset}
                />
              )}
              {tab === 2 && <FindingsTab run={run} onReview={(finding, status) => reviewMutation.mutate({ finding, status })} />}
              {tab === 3 && <KnowledgeTab run={run} />}
              {tab === 4 && <RefinementsTab run={run} onReview={(finding, status) => reviewMutation.mutate({ finding, status })} />}
            </CardContent>
          </Card>
        </>
      )}
    </Stack>
  );
}

function ReadinessSummary({ run, onPublish, publishing }: { run: DocumentAnalysisRun; onPublish: () => void; publishing: boolean }) {
  const scores = run.scores || {};
  const critical = run.findings.filter((finding) => finding.severity === "critical" && finding.status !== "resolved" && finding.status !== "rejected").length;
  const high = run.findings.filter((finding) => finding.severity === "high" && finding.status !== "resolved" && finding.status !== "rejected").length;
  return (
    <Stack spacing={2}>
      <Grid container spacing={2}>
        <Grid item xs={12} sm={6} lg={3}>
          <ScoreCard label="Documentation readiness" score={run.readiness_score} highlight status={pretty(run.readiness_status)} />
        </Grid>
        <Grid item xs={6} sm={3} lg><ScoreCard label="Completeness" score={scores.completeness ?? 0} /></Grid>
        <Grid item xs={6} sm={3} lg><ScoreCard label="Testability" score={scores.testability ?? 0} /></Grid>
        <Grid item xs={6} sm={3} lg><ScoreCard label="Consistency" score={scores.consistency ?? 0} /></Grid>
        <Grid item xs={6} sm={3} lg><ScoreCard label="Traceability" score={scores.traceability ?? 0} /></Grid>
      </Grid>
      <Alert severity={readinessColor(run.readiness_status)}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} justifyContent="space-between" alignItems={{ md: "center" }}>
          <Box>
            <b>{pretty(run.readiness_status)}</b> · {critical} critical and {high} high unresolved documentation finding(s).
            {run.summary ? ` ${run.summary}` : ""}
          </Box>
          <Button
            variant={run.published_requirement_id ? "outlined" : "contained"}
            color={run.readiness_status === "not_ready_for_test_design" ? "warning" : "primary"}
            disabled={publishing}
            onClick={onPublish}
            startIcon={publishing ? <CircularProgress size={16} color="inherit" /> : <CheckCircleOutlineIcon />}
          >
            {run.published_requirement_id ? "Refresh Test Design baseline" : "Send intelligence to Test Design"}
          </Button>
        </Stack>
      </Alert>
    </Stack>
  );
}

function ScoreCard({ label, score, highlight, status }: { label: string; score: number; highlight?: boolean; status?: string }) {
  const normalized = Math.max(0, Math.min(100, Math.round(score || 0)));
  return (
    <Card variant="outlined" sx={{ height: "100%", borderColor: highlight ? "primary.main" : "divider" }}>
      <CardContent>
        <Typography variant="caption" color="text.secondary">{label}</Typography>
        <Typography variant="h4" fontWeight={800} sx={{ mt: 0.5 }}>{normalized}<Typography component="span" variant="body2" color="text.secondary">/100</Typography></Typography>
        <LinearProgress variant="determinate" value={normalized} sx={{ mt: 1.25, height: 6, borderRadius: 3 }} />
        {status && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>{status}</Typography>}
      </CardContent>
    </Card>
  );
}

function OverviewTab({ run, projectAssets }: { run?: DocumentAnalysisRun | null; projectAssets: UploadedAsset[] }) {
  if (!run) {
    return <Alert severity="info">Select the relevant project documents and run the AI Documentation Review. QTXpert will classify them, correlate them and assess completeness, consistency and testability.</Alert>;
  }
  if (run.status !== "completed") {
    return <Stack spacing={2}><Typography variant="h6" fontWeight={800}>Reviewing project documentation</Typography><Typography color="text.secondary">Current stage: {pretty(run.status)}</Typography><LinearProgress /></Stack>;
  }
  const missing = run.missing_documents || [];
  const recs = run.recommendations || [];
  const selectedFiles = new Set(run.asset_ids);
  return (
    <Grid container spacing={3}>
      <Grid item xs={12} lg={7}>
        <Stack spacing={2.5}>
          <Box>
            <Typography variant="h6" fontWeight={800}>AI assessment</Typography>
            <Typography color="text.secondary" sx={{ mt: 1 }}>{run.summary}</Typography>
          </Box>
          <Divider />
          <Box>
            <Typography fontWeight={800}>Documentation map</Typography>
            <Grid container spacing={1.5} sx={{ mt: 0.5 }}>
              {(run.document_inventory || []).map((item) => (
                <Grid item xs={12} md={6} key={item.asset_id}>
                  <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                    <Stack direction="row" justifyContent="space-between" spacing={1}>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography variant="body2" fontWeight={700} noWrap>{item.filename}</Typography>
                        <Typography variant="caption" color="text.secondary">{item.document_type}</Typography>
                      </Box>
                      <Chip size="small" label={item.status} color={item.status === "critical" ? "error" : item.status === "attention" ? "warning" : "success"} variant="outlined" />
                    </Stack>
                    <Typography variant="caption" color="text.secondary">Quality {item.quality_score}% · Testability {item.testability_score}% · {item.issue_count} issue(s)</Typography>
                  </Paper>
                </Grid>
              ))}
            </Grid>
          </Box>
          {recs.length > 0 && <Box><Typography fontWeight={800}>Recommended actions</Typography><Stack spacing={1} sx={{ mt: 1 }}>{recs.slice(0, 8).map((item, index) => <Typography variant="body2" key={`${item}-${index}`}>{index + 1}. {item}</Typography>)}</Stack></Box>}
        </Stack>
      </Grid>
      <Grid item xs={12} lg={5}>
        <Stack spacing={2}>
          <Card variant="outlined"><CardContent><Typography fontWeight={800}>Baseline coverage</Typography><Typography variant="h4" fontWeight={800} sx={{ mt: 1 }}>{selectedFiles.size}<Typography variant="body2" component="span" color="text.secondary"> / {projectAssets.length} project assets</Typography></Typography><Typography variant="caption" color="text.secondary">Documents included in the latest analysis.</Typography></CardContent></Card>
          <Card variant="outlined"><CardContent><Typography fontWeight={800}>Potentially missing documentation</Typography>{missing.length === 0 ? <Typography color="text.secondary" variant="body2" sx={{ mt: 1 }}>No missing document category was identified by this review.</Typography> : <Stack spacing={1.2} sx={{ mt: 1.5 }}>{missing.map((item, index) => <Box key={`${item.document_type}-${index}`}><Stack direction="row" spacing={1} alignItems="center"><Chip size="small" label={item.priority.toUpperCase()} color={item.priority === "high" ? "warning" : "default"} /><Typography variant="body2" fontWeight={700}>{item.document_type}</Typography></Stack><Typography variant="caption" color="text.secondary">{item.reason}</Typography></Box>)}</Stack>}</CardContent></Card>
        </Stack>
      </Grid>
    </Grid>
  );
}

function DocumentsTab({ assets, run, selectedAssetIds, onToggle }: { assets: UploadedAsset[]; run?: DocumentAnalysisRun | null; selectedAssetIds: string[]; onToggle: (id: string) => void }) {
  const inventory = new Map((run?.document_inventory || []).map((item) => [item.asset_id, item]));
  if (assets.length === 0) return <Alert severity="info">No project documents are available yet. Upload development/testing artifacts above or through Test Data → Uploads.</Alert>;
  return (
    <TableContainer>
      <Table size="small">
        <TableHead><TableRow><TableCell padding="checkbox" /><TableCell>Document</TableCell><TableCell>Detected type</TableCell><TableCell>Quality</TableCell><TableCell>Testability</TableCell><TableCell>Issues</TableCell><TableCell>Repository source</TableCell></TableRow></TableHead>
        <TableBody>
          {assets.map((asset) => {
            const info = inventory.get(asset.id);
            const supported = EXTRACTABLE_EXTENSIONS.has(asset.extension.toLowerCase());
            return (
              <TableRow hover key={asset.id}>
                <TableCell padding="checkbox"><Tooltip title={supported ? "Include in next AI review" : "Stored in repository; text extraction is not available for this format yet"}><span><Checkbox checked={selectedAssetIds.includes(asset.id)} onChange={() => onToggle(asset.id)} disabled={!supported} /></span></Tooltip></TableCell>
                <TableCell><Typography variant="body2" fontWeight={700}>{asset.filename}</Typography><Typography variant="caption" color="text.secondary">{asset.extension.toUpperCase()} · {(asset.size_bytes / 1024 / 1024).toFixed(2)} MB</Typography></TableCell>
                <TableCell>{info?.document_type || (supported ? "Pending AI classification" : "Stored asset")}</TableCell>
                <TableCell>{info ? `${info.quality_score}%` : "—"}</TableCell>
                <TableCell>{info ? `${info.testability_score}%` : "—"}</TableCell>
                <TableCell>{info ? <Chip size="small" label={info.issue_count} color={info.issue_count ? "warning" : "success"} variant="outlined" /> : "—"}</TableCell>
                <TableCell><Chip size="small" label={asset.source_module.replaceAll("_", " ")} variant="outlined" /></TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function FindingsTab({ run, onReview }: { run?: DocumentAnalysisRun | null; onReview: (finding: DocumentFinding, status: DocumentFindingStatus) => void }) {
  if (!run || run.status !== "completed") return <Alert severity="info">AI findings will appear after the documentation review completes.</Alert>;
  if (!run.findings.length) return <Alert severity="success">No material documentation gaps were identified in this run.</Alert>;
  const order = { critical: 0, high: 1, medium: 2, low: 3 } as Record<string, number>;
  const findings = [...run.findings].sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
  return (
    <Stack spacing={1.25}>
      {findings.map((finding) => (
        <Accordion key={finding.id} variant="outlined" disableGutters sx={{ borderRadius: "8px !important", "&:before": { display: "none" } }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1.25} alignItems={{ md: "center" }} sx={{ width: "100%", pr: 1 }}>
              <Chip size="small" label={finding.severity.toUpperCase()} color={severityColor(finding.severity)} />
              <Typography variant="body2" fontWeight={800} sx={{ flex: 1 }}>{finding.finding_key} · {finding.title}</Typography>
              <Chip size="small" label={pretty(finding.category)} variant="outlined" />
              <Chip size="small" label={pretty(finding.status)} color={finding.status === "resolved" ? "success" : "default"} variant="outlined" />
            </Stack>
          </AccordionSummary>
          <AccordionDetails>
            <Grid container spacing={2}>
              <Grid item xs={12} lg={7}>
                <Typography variant="body2">{finding.description}</Typography>
                {finding.testing_impact && <Box sx={{ mt: 1.5 }}><Typography variant="caption" color="text.secondary">Testing impact</Typography><Typography variant="body2" fontWeight={600}>{finding.testing_impact}</Typography></Box>}
                {finding.evidence && finding.evidence.length > 0 && <Box sx={{ mt: 1.5 }}><Typography variant="caption" color="text.secondary">Evidence</Typography><Stack spacing={1} sx={{ mt: 0.5 }}>{finding.evidence.map((item, index) => <Paper key={index} variant="outlined" sx={{ p: 1.25, bgcolor: "action.hover" }}><Typography variant="caption" fontWeight={700}>{item.filename || "Project baseline"}</Typography><Typography variant="body2">{item.excerpt || item.reason}</Typography>{item.reason && item.excerpt && <Typography variant="caption" color="text.secondary">{item.reason}</Typography>}</Paper>)}</Stack></Box>}
              </Grid>
              <Grid item xs={12} lg={5}>
                <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                  <Typography variant="caption" color="text.secondary">AI recommended refinement</Typography>
                  <Typography variant="body2" sx={{ mt: 0.5 }}>{finding.suggested_refinement || "No automatic rewrite is proposed. Clarification is required."}</Typography>
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>Confidence: {Math.round(finding.confidence * 100)}%</Typography>
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.5 }}>
                    <Button size="small" variant="outlined" onClick={() => onReview(finding, "accepted")}>Accept suggestion</Button>
                    <Button size="small" variant="outlined" color="warning" onClick={() => onReview(finding, "needs_clarification")}>Needs clarification</Button>
                    <Button size="small" variant="text" onClick={() => onReview(finding, "resolved")}>Mark resolved</Button>
                    <Button size="small" variant="text" color="inherit" onClick={() => onReview(finding, "rejected")}>Reject</Button>
                  </Stack>
                </Paper>
              </Grid>
            </Grid>
          </AccordionDetails>
        </Accordion>
      ))}
    </Stack>
  );
}

function KnowledgeTab({ run }: { run?: DocumentAnalysisRun | null }) {
  if (!run || run.status !== "completed") return <Alert severity="info">The project requirement knowledge model will appear after analysis.</Alert>;
  const model = run.knowledge_model || {};
  const sections = [
    ["Business rules", "business_rules"],
    ["Functional requirements", "functional_requirements"],
    ["Actors / roles", "actors"],
    ["User journeys", "user_journeys"],
    ["Acceptance criteria", "acceptance_criteria"],
    ["Integrations", "integrations"],
    ["Validation rules", "validation_rules"],
    ["Security controls", "security_controls"],
    ["Data rules", "data_rules"],
    ["NFRs", "non_functional_requirements"],
    ["Regulatory requirements", "regulatory_requirements"],
    ["Error / recovery rules", "error_recovery_rules"],
    ["Open questions", "open_questions"],
  ] as const;
  return (
    <Stack spacing={2}>
      <Alert severity="info">This normalized knowledge model is the bridge between Document Intelligence and Test Design. Publishing the baseline makes these vetted elements available to downstream test generation.</Alert>
      <Grid container spacing={2}>
        {sections.map(([label, key]) => {
          const items = Array.isArray(model[key]) ? model[key] : [];
          return <Grid item xs={12} md={6} lg={4} key={key}><Card variant="outlined" sx={{ height: "100%" }}><CardContent><Stack direction="row" justifyContent="space-between"><Typography fontWeight={800}>{label}</Typography><Chip size="small" label={items.length} /></Stack>{items.length ? <Stack spacing={0.75} sx={{ mt: 1.25 }}>{items.slice(0, 8).map((item, index) => <Typography key={index} variant="body2">• {item}</Typography>)}{items.length > 8 && <Typography variant="caption" color="text.secondary">+ {items.length - 8} more</Typography>}</Stack> : <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>None identified.</Typography>}</CardContent></Card></Grid>;
        })}
      </Grid>
    </Stack>
  );
}

function RefinementsTab({ run, onReview }: { run?: DocumentAnalysisRun | null; onReview: (finding: DocumentFinding, status: DocumentFindingStatus) => void }) {
  if (!run || run.status !== "completed") return <Alert severity="info">AI refinements will appear after analysis.</Alert>;
  const refinements = run.findings.filter((finding) => finding.suggested_refinement);
  if (!refinements.length) return <Alert severity="info">No automated wording refinements were proposed. Review the AI Findings tab for clarification gaps.</Alert>;
  return (
    <Stack spacing={2}>
      <Alert severity="warning">QTXpert never silently rewrites project requirements. Every AI refinement remains a proposal until a human accepts, rejects or resolves it.</Alert>
      {refinements.map((finding) => (
        <Paper key={finding.id} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
          <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1}>
            <Box><Stack direction="row" spacing={1} alignItems="center"><Chip size="small" label={finding.severity.toUpperCase()} color={severityColor(finding.severity)} /><Typography fontWeight={800}>{finding.title}</Typography></Stack><Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>{finding.original_text || finding.description}</Typography></Box>
            <Chip label={pretty(finding.status)} size="small" variant="outlined" />
          </Stack>
          <Box sx={{ mt: 2, p: 1.5, bgcolor: "action.hover", borderRadius: 2 }}><Typography variant="caption" color="primary.main" fontWeight={800}>AI SUGGESTED WORDING / ACTION</Typography><Typography variant="body2" sx={{ mt: 0.5 }}>{finding.suggested_refinement}</Typography></Box>
          <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}><Button size="small" variant="contained" onClick={() => onReview(finding, "accepted")}>Accept</Button><Button size="small" variant="outlined" color="warning" onClick={() => onReview(finding, "needs_clarification")}>Ask for clarification</Button><Button size="small" variant="text" onClick={() => onReview(finding, "rejected")}>Reject</Button></Stack>
        </Paper>
      ))}
    </Stack>
  );
}
