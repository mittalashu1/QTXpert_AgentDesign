import { ChangeEvent, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert, Box, Button, Card, CardContent, Chip, Divider, FormControl,
  FormHelperText, InputLabel, LinearProgress, MenuItem, Select, Stack,
  TextField, Typography,
} from "@mui/material";
import AddOutlinedIcon from "@mui/icons-material/AddOutlined";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import DeleteOutlineOutlinedIcon from "@mui/icons-material/DeleteOutlineOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import SaveOutlinedIcon from "@mui/icons-material/SaveOutlined";
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import { requirementsApi, testCasesApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import ProjectSelector from "@/components/ProjectSelector";
import { EXPORT_FORMATS, GenerationRun, TestCase } from "@/types/domain";

const ACTIVE_STATUSES = ["pending", "normalizing", "analyzing", "generating_scenarios", "generating_test_cases", "risk_analysis"];
const PROGRESS: Record<string, number> = { pending: 5, normalizing: 15, analyzing: 35, generating_scenarios: 55, generating_test_cases: 75, risk_analysis: 90, completed: 100, failed: 100 };
const FILE_EXTENSIONS = ".pdf,.docx,.txt,.md,.json,.csv";
type SourceKind = "file" | "link";
type InputSource = { id: string; label: string; description: string; kind: SourceKind; accept?: string; placeholder?: string };

const SOURCES: InputSource[] = [
  { id: "app", label: "App / APK", description: "Upload a product package", kind: "file", accept: ".apk,.ipa,.zip" },
  { id: "document", label: "Documents", description: "PDF, DOCX, TXT, CSV", kind: "file", accept: FILE_EXTENSIONS },
  { id: "video", label: "Video walkthrough", description: "MP4, MOV, WEBM", kind: "file", accept: ".mp4,.mov,.webm" },
  { id: "jira", label: "Jira", description: "Paste a story or export URL", kind: "link", placeholder: "https://company.atlassian.net/browse/QA-123" },
  { id: "confluence", label: "Confluence", description: "Paste a requirements page", kind: "link", placeholder: "https://company.atlassian.net/wiki/..." },
  { id: "website", label: "Website URL", description: "Explore a live product", kind: "link", placeholder: "https://your-product.example" },
];

function EditableCase({ testCase, onChange }: { testCase: TestCase; onChange: (next: TestCase) => void }) {
  return <Card variant="outlined" sx={{ borderRadius: 2 }}><CardContent>
    <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{testCase.test_case_key}</Typography>
      <Stack direction="row" spacing={0.5}><Chip size="small" label={testCase.test_type.replace(/_/g, " ")} /><Chip size="small" color={testCase.priority === "high" || testCase.priority === "critical" ? "error" : "warning"} label={testCase.priority} /></Stack>
    </Stack>
    <Stack spacing={1.25}>
      <TextField label="Scenario" value={testCase.scenario} onChange={(e) => onChange({ ...testCase, scenario: e.target.value })} fullWidth />
      <TextField label="Objective" value={testCase.objective} onChange={(e) => onChange({ ...testCase, objective: e.target.value })} fullWidth multiline minRows={2} />
      <TextField label="Preconditions" value={testCase.preconditions ?? ""} onChange={(e) => onChange({ ...testCase, preconditions: e.target.value })} fullWidth multiline minRows={2} />
      <TextField label="Steps (one per line)" value={testCase.steps.join("\n")} onChange={(e) => onChange({ ...testCase, steps: e.target.value.split("\n").filter(Boolean) })} fullWidth multiline minRows={3} />
      <TextField label="Expected result" value={testCase.expected_result} onChange={(e) => onChange({ ...testCase, expected_result: e.target.value })} fullWidth multiline minRows={2} />
    </Stack>
  </CardContent></Card>;
}

export default function GenerateTestCasesPage() {
  const { selectedProjectId } = useSelectedProject();
  const [selectedSource, setSelectedSource] = useState("document");
  const [sourceUrl, setSourceUrl] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [prompt, setPrompt] = useState("");
  const [coverage, setCoverage] = useState("balanced");
  const [result, setResult] = useState<GenerationRun | null>(null);
  const [draftCases, setDraftCases] = useState<TestCase[]>([]);
  const [saved, setSaved] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const source = SOURCES.find((item) => item.id === selectedSource) ?? SOURCES[1];
  const { data: liveRun } = useQuery({
    queryKey: ["generation-run", result?.id],
    queryFn: () => testCasesApi.getRun(result!.id).then((res) => res.data),
    enabled: Boolean(result?.id),
    refetchInterval: (query) => ACTIVE_STATUSES.includes(((query.state.data as GenerationRun | undefined)?.status ?? result?.status) ?? "") ? 2500 : false,
  });
  const run = liveRun ?? result;
  const isActive = Boolean(run && ACTIVE_STATUSES.includes(run.status));
  const inputSummary = useMemo(() => [...files.map((file) => file.name), ...(source.kind === "link" && sourceUrl.trim() ? [sourceUrl.trim()] : [])], [files, source.kind, sourceUrl]);

  const generationMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProjectId) throw new Error("Create or select a project before generating test cases.");
      if (!files.length && !sourceUrl.trim() && !prompt.trim()) throw new Error("Add a file, link, or prompt first.");
      setMessage("Uploading your sources and preparing generation…");
      const requirementIds: string[] = [];
      for (const file of files) requirementIds.push((await requirementsApi.upload(selectedProjectId, file)).data.id);
      const context = [prompt.trim() ? `User guidance:\n${prompt.trim()}` : "", sourceUrl.trim() ? `${source.label} source: ${sourceUrl.trim()}` : "", `Coverage preference: ${coverage}`, inputSummary.length ? `Inputs: ${inputSummary.join(", ")}` : ""].filter(Boolean).join("\n\n");
      if (context) requirementIds.push((await requirementsApi.submitDirectPrompt(selectedProjectId, `${source.label} test design`, context)).data.id);
      const profile = coverage === "quick" ? "smoke" : coverage === "thorough" ? "regression" : "feature";
      return testCasesApi.generate(selectedProjectId, requirementIds, undefined, profile).then((res) => res.data);
    },
    onSuccess: (next) => { setResult(next); setDraftCases(next.test_cases ?? []); setSaved(false); setMessage("Generation started. Live progress will appear here."); setError(null); },
    onError: (reason) => { setError((reason as any)?.response?.data?.detail || (reason as Error).message || "Generation failed."); setMessage(null); },
  });
  const exportMutation = useMutation({
    mutationFn: async (format: string) => {
      if (!run?.id) throw new Error("Generate a suite before exporting.");
      const response = await testCasesApi.export(run.id, format); const info = EXPORT_FORMATS.find((item) => item.value === format); const url = window.URL.createObjectURL(new Blob([response.data])); const link = document.createElement("a"); link.href = url; link.download = `qtxpert-${run.id.slice(0, 8)}-${info?.value ?? format}`; link.click(); window.URL.revokeObjectURL(url);
    },
    onSuccess: (_, format) => setMessage(`Downloaded ${format.toUpperCase()} test cases.`),
    onError: (reason) => setError((reason as any)?.response?.data?.detail || "Export failed."),
  });
  const onFiles = (event: ChangeEvent<HTMLInputElement>) => { setFiles((current) => [...current, ...Array.from(event.target.files ?? [])]); event.target.value = ""; };
  const startNewChat = () => { setResult(null); setDraftCases([]); setFiles([]); setSourceUrl(""); setPrompt(""); setSaved(false); setError(null); setMessage("Started a new test-design chat."); };
  const saveSuite = () => { if (!run) return; localStorage.setItem("qtxpert-saved-suite", JSON.stringify({ runId: run.id, cases: draftCases, savedAt: new Date().toISOString() })); setSaved(true); setMessage("Suite saved to your QTXpert workspace and history."); };
  const updateCase = (index: number, next: TestCase) => setDraftCases((current) => current.map((item, idx) => idx === index ? next : item));

  if (run) return <Stack spacing={3}>
    <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} spacing={1}><Box><Typography variant="h5" sx={{ fontWeight: 700 }}>Interactive test suite</Typography><Typography color="text.secondary">{run.status === "completed" ? `${draftCases.length} editable test cases` : `Working: ${run.status.replaceAll("_", " ")}`}</Typography></Box><Stack direction="row" spacing={1} flexWrap="wrap"><Button startIcon={<RefreshOutlinedIcon />} onClick={() => setResult(null)}>Edit inputs</Button><Button startIcon={<SaveOutlinedIcon />} variant={saved ? "outlined" : "contained"} onClick={saveSuite} disabled={run.status !== "completed"}>{saved ? "Saved" : "Save suite"}</Button><Button onClick={startNewChat}>＋ New chat</Button></Stack></Stack>
    {isActive && <LinearProgress variant="determinate" value={PROGRESS[run.status] ?? 10} />}{run.error_message && <Alert severity={run.status === "failed" ? "error" : "warning"}>{run.error_message}</Alert>}
    {run.status === "completed" && <Card><CardContent><Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} spacing={1}><Box><Typography variant="h6">Review and improve</Typography><Typography variant="body2" color="text.secondary">Every field is editable. Changes stay in this saved suite.</Typography></Box><Stack direction="row" spacing={1}>{["excel", "csv", "json"].map((format) => <Button key={format} size="small" variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={() => exportMutation.mutate(format)} disabled={exportMutation.isPending}>{format === "excel" ? "Excel" : format.toUpperCase()}</Button>)}</Stack></Stack></CardContent></Card>}
    <Stack spacing={2}>{draftCases.map((testCase, index) => <EditableCase key={testCase.id || index} testCase={testCase} onChange={(next) => updateCase(index, next)} />)}</Stack>{!isActive && !draftCases.length && run.status !== "failed" && <Alert severity="info">The provider returned no test cases. Edit the inputs and run again.</Alert>}{message && <Alert severity="success" onClose={() => setMessage(null)}>{message}</Alert>}{error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
  </Stack>;

  return <Stack spacing={3}>
    <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} spacing={1}><Box><Typography variant="h5" sx={{ fontWeight: 700 }}>Test design workspace</Typography><Typography color="text.secondary">Bring every source and instruction together on one page.</Typography></Box><Stack direction="row" spacing={1}><Button onClick={startNewChat}>＋ New chat</Button><ProjectSelector /></Stack></Stack>
    <Card sx={{ borderRadius: 3 }}><CardContent><Stack spacing={3}><Box><Typography variant="h6">Start a test-design chat</Typography><Typography variant="body2" color="text.secondary">Upload an app, requirements, or video; paste links; and describe what matters. QTXpert sends these inputs to the authenticated generation service.</Typography></Box>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} flexWrap="wrap">{SOURCES.map((item) => <Button key={item.id} variant={selectedSource === item.id ? "contained" : "outlined"} startIcon={item.kind === "file" ? <CloudUploadOutlinedIcon /> : <AddOutlinedIcon />} onClick={() => { setSelectedSource(item.id); if (item.kind === "file") fileInputRef.current?.click(); }} sx={{ justifyContent: "flex-start", textTransform: "none", minWidth: 180 }}><Box sx={{ textAlign: "left" }}><Typography variant="body2" sx={{ fontWeight: 700 }}>{item.label}</Typography><Typography variant="caption" sx={{ opacity: 0.75 }}>{item.description}</Typography></Box></Button>)}</Stack>
      <input ref={fileInputRef} hidden type="file" multiple accept={source.accept ?? FILE_EXTENSIONS} onChange={onFiles} />{source.kind === "link" && <TextField label={`${source.label} link`} value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder={source.placeholder} fullWidth helperText="The link is sent as context with your prompt." />}
      <Box onClick={() => fileInputRef.current?.click()} sx={{ border: "1px dashed", borderColor: "primary.main", borderRadius: 2, p: 2, cursor: "pointer", bgcolor: "action.hover" }}><Typography sx={{ fontWeight: 600 }}>Drop files here or click to browse</Typography><Typography variant="caption" color="text.secondary">Supported requirement files: {FILE_EXTENSIONS}</Typography></Box>{files.length > 0 && <Stack spacing={1}>{files.map((file, index) => <Stack key={`${file.name}-${index}`} direction="row" alignItems="center" spacing={1}><Chip label={file.name} onDelete={() => setFiles((current) => current.filter((_, idx) => idx !== index))} deleteIcon={<DeleteOutlineOutlinedIcon />} /><Typography variant="caption" color="text.secondary">{Math.ceil(file.size / 1024)} KB</Typography></Stack>)}</Stack>}
      <Divider /><TextField label="What should we test?" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Example: Cover checkout, payment failures, permissions, accessibility, and mobile edge cases." fullWidth multiline minRows={4} helperText="Optional when you upload a source; required when you only provide instructions." />
      <FormControl sx={{ maxWidth: 260 }}><InputLabel id="coverage-label">Coverage</InputLabel><Select labelId="coverage-label" label="Coverage" value={coverage} onChange={(e) => setCoverage(e.target.value)}><MenuItem value="quick">Quick</MenuItem><MenuItem value="balanced">Balanced</MenuItem><MenuItem value="thorough">Thorough</MenuItem></Select><FormHelperText>Controls breadth of scenarios.</FormHelperText></FormControl>
      {message && <Alert severity="info">{message}</Alert>}{error && <Alert severity="error">{error}</Alert>}<Button variant="contained" size="large" startIcon={<AutoAwesomeOutlinedIcon />} onClick={() => generationMutation.mutate()} disabled={generationMutation.isPending || !selectedProjectId} sx={{ alignSelf: "flex-start" }}>{generationMutation.isPending ? "Preparing generation…" : "Analyze and generate test cases"}</Button>
    </Stack></CardContent></Card><Typography variant="caption" color="text.secondary">Signed-in workspace • generation runs are stored in History • exports are available after completion</Typography>
  </Stack>;
}

