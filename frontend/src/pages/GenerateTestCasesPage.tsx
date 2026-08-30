import { ChangeEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Card,
  CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Divider,
  FormControl, FormHelperText, IconButton, InputLabel, LinearProgress, Menu,
  MenuItem, Select, Stack, TextField, Tooltip, Typography,
} from "@mui/material";
import AddOutlinedIcon from "@mui/icons-material/AddOutlined";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import CheckOutlinedIcon from "@mui/icons-material/CheckOutlined";
import CloseOutlinedIcon from "@mui/icons-material/CloseOutlined";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import DeleteOutlineOutlinedIcon from "@mui/icons-material/DeleteOutlineOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import ExpandMoreOutlinedIcon from "@mui/icons-material/ExpandMoreOutlined";
import ArrowBackOutlinedIcon from "@mui/icons-material/ArrowBackOutlined";
import MoreVertOutlinedIcon from "@mui/icons-material/MoreVertOutlined";
import SaveOutlinedIcon from "@mui/icons-material/SaveOutlined";
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import Grid from "@mui/material/Grid2";
import { useNavigate, useSearchParams } from "react-router-dom";
import { requirementsApi, testCasesApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import ProjectSelector from "@/components/ProjectSelector";
import RepositoryDocumentsPicker from "@/components/RepositoryDocumentsPicker";
import { EXPORT_FORMATS, GenerationRun, GenerationRunSummary, TestCase } from "@/types/domain";

const ACTIVE_STATUSES = ["pending", "normalizing", "analyzing", "generating_scenarios", "generating_test_cases", "risk_analysis"];
const PROGRESS: Record<string, number> = { pending: 5, normalizing: 15, analyzing: 35, generating_scenarios: 55, generating_test_cases: 75, risk_analysis: 90, completed: 100, failed: 100 };
const FILE_EXTENSIONS = ".pdf,.docx,.txt,.md,.json,.csv";
// Keep the client hint aligned with the backend defaults. Documents remain
// intentionally small; mobile packages use the larger Autopilot allowance.
const DOCUMENT_MAX_UPLOAD_MB = 25;
const MOBILE_PACKAGE_MAX_UPLOAD_MB = 250;
const LOCAL_CHAT_STORAGE_KEY = "qtxpert-saved-chats";
const RUN_RAIL_RENDER_LIMIT = 100;
const MAX_TITLE_WORDS = 20;
type SourceKind = "file" | "link";
type InputSource = { id: string; label: string; description: string; kind: SourceKind; accept?: string; placeholder?: string };
type RunRailEntry = GenerationRun | GenerationRunSummary;

function apiErrorMessage(reason: unknown, fallback: string): string {
  const detail = (reason as AxiosError<{ detail?: string }>)?.response?.data?.detail;
  return detail || (reason instanceof Error ? reason.message : fallback);
}

const SOURCES: InputSource[] = [
  { id: "app", label: "App / APK / IPA", description: "Upload a product package (up to 250 MB)", kind: "file", accept: ".apk,.ipa,.zip" },
  { id: "document", label: "Documents", description: "PDF, DOCX, TXT, CSV", kind: "file", accept: FILE_EXTENSIONS },
  { id: "video", label: "Video walkthrough", description: "MP4, MOV, WEBM", kind: "file", accept: ".mp4,.mov,.webm" },
  { id: "jira", label: "Jira", description: "Paste a story or export URL", kind: "link", placeholder: "https://company.atlassian.net/browse/QA-123" },
  { id: "confluence", label: "Confluence", description: "Paste a requirements page", kind: "link", placeholder: "https://company.atlassian.net/wiki/..." },
  { id: "website", label: "Website URL", description: "Explore a live product", kind: "link", placeholder: "https://your-product.example" },
];

function EditableCase({ testCase, onChange }: { testCase: TestCase; onChange: (next: TestCase) => void }) {
  return <Accordion variant="outlined" disableGutters sx={{ borderRadius: 1.75, minWidth: 0, "&:before": { display: "none" } }}>
    <AccordionSummary expandIcon={<ExpandMoreOutlinedIcon />} sx={{ px: 1.25, py: 0.35, minHeight: 62, "& .MuiAccordionSummary-content": { my: 0.45, minWidth: 0 } }}>
      <Stack spacing={0.6} sx={{ minWidth: 0, pr: 1 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={{ xs: 0.25, sm: 1 }} alignItems={{ xs: "flex-start", sm: "center" }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 800, whiteSpace: "nowrap" }}>{testCase.test_case_key}</Typography>
          <Typography variant="body2" sx={{ fontWeight: 600, display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2, overflow: "hidden", lineHeight: 1.25, maxWidth: "100%" }}>
            {testCase.scenario || "Untitled scenario"}
          </Typography>
        </Stack>
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
          <Chip size="small" label={testCase.test_type.replace(/_/g, " ")} sx={{ height: 20, "& .MuiChip-label": { px: 0.8, fontSize: ".68rem" } }} />
          <Chip size="small" color={testCase.priority === "high" || testCase.priority === "critical" ? "error" : "warning"} label={testCase.priority} sx={{ height: 20, "& .MuiChip-label": { px: 0.8, fontSize: ".68rem" } }} />
          <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center", fontSize: ".68rem" }}>Edit details</Typography>
        </Stack>
      </Stack>
    </AccordionSummary>
    <AccordionDetails sx={{ px: 1.25, pb: 1.5 }}>
      <Stack spacing={1.25}>
        <TextField label="Scenario" value={testCase.scenario} onChange={(e) => onChange({ ...testCase, scenario: e.target.value })} fullWidth />
        <TextField label="Objective" value={testCase.objective} onChange={(e) => onChange({ ...testCase, objective: e.target.value })} fullWidth multiline minRows={2} />
        <TextField label="Preconditions" value={testCase.preconditions ?? ""} onChange={(e) => onChange({ ...testCase, preconditions: e.target.value })} fullWidth multiline minRows={2} />
        <TextField label="Steps (one per line)" value={testCase.steps.join("\n")} onChange={(e) => onChange({ ...testCase, steps: e.target.value.split("\n").filter(Boolean) })} fullWidth multiline minRows={3} />
        <TextField label="Expected result" value={testCase.expected_result} onChange={(e) => onChange({ ...testCase, expected_result: e.target.value })} fullWidth multiline minRows={2} />
      </Stack>
    </AccordionDetails>
  </Accordion>;
}

function readSavedChats(): GenerationRun[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(LOCAL_CHAT_STORAGE_KEY) || "[]");
    return Array.isArray(parsed)
      ? parsed.filter((item) => item && typeof item === "object" && typeof item.id === "string")
      : [];
  } catch {
    return [];
  }
}

function normalizeHeading(value: unknown) {
  if (typeof value !== "string") return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  return normalized.split(/[.!?](?:\s|$)/)[0]?.trim() || normalized;
}

function compactTitle(value: unknown, maxWords = MAX_TITLE_WORDS) {
  const heading = normalizeHeading(value);
  if (!heading) return null;
  const words = heading.split(/\s+/);
  return words.length > maxWords ? `${words.slice(0, maxWords).join(" ")}…` : heading;
}

function fullRunTitle(run: RunRailEntry) {
  const fullRun = "test_cases" in run ? run : null;
  const summaryRun = "test_case_count" in run ? run : null;
  const candidates: unknown[] = [
    run.title,
    run.requirement_summary,
    summaryRun?.first_scenario,
    fullRun?.test_scenarios?.[0]?.["title"],
    fullRun?.test_scenarios?.[0]?.["scenario"],
    fullRun?.functional_breakdown?.[0]?.["title"],
    fullRun?.functional_breakdown?.[0]?.["name"],
    fullRun?.test_cases?.[0]?.scenario,
  ];
  const heading = candidates.map((candidate) => normalizeHeading(candidate)).find(Boolean);
  if (heading) return heading;
  const profile = normalizeHeading(run.generation_profile?.replaceAll("_", " ")) || "feature";
  const date = run.created_at ? new Date(run.created_at).toLocaleDateString() : "";
  return `Test set • ${profile}${date ? ` • ${date}` : ""}`;
}

function runTitle(run: RunRailEntry) {
  return compactTitle(fullRunTitle(run)) || "Test run";
}

function runCaseCount(run: RunRailEntry) {
  return "test_case_count" in run ? run.test_case_count : run.test_cases?.length ?? 0;
}

function testCaseTypeLabel(value: string) {
  const normalized = value.replace(/[_-]+/g, " ").trim();
  return normalized ? normalized.replace(/\b\w/g, (character) => character.toUpperCase()) : "Functional";
}

function inputHeading(source: InputSource, files: File[], sourceUrl: string, prompt: string) {
  const queryHeading = compactTitle(prompt);
  if (queryHeading) return queryHeading;
  const fileNames = files
    .map((file) => file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim())
    .filter(Boolean);
  if (fileNames.length === 1) return compactTitle(fileNames[0]) || fileNames[0];
  if (fileNames.length > 1) return compactTitle(`${fileNames[0]} + ${fileNames.length - 1} more`) || `${fileNames[0]} + ${fileNames.length - 1} more`;
  if (sourceUrl.trim()) {
    try {
      const parsed = new URL(sourceUrl.trim());
      const path = parsed.pathname.split("/").filter(Boolean).pop();
      return compactTitle(path ? `${parsed.hostname} • ${path}` : parsed.hostname) || source.label;
    } catch {
      return compactTitle(sourceUrl) || source.label;
    }
  }
  return `${source.label} test design`;
}

function RunRail({ runs, activeId, openingId, renamingId, onSelect, onRename, onDelete, onNew }: {
  runs: RunRailEntry[];
  activeId?: string;
  openingId?: string | null;
  renamingId?: string | null;
  onSelect: (run: RunRailEntry) => void | Promise<void>;
  onRename: (run: RunRailEntry, title: string) => Promise<void>;
  onDelete: (run: RunRailEntry) => Promise<void>;
  onNew: () => void;
}) {
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [menuAnchorEl, setMenuAnchorEl] = useState<HTMLElement | null>(null);
  const [menuRun, setMenuRun] = useState<RunRailEntry | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<RunRailEntry | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const visibleRuns = runs.filter((run) => fullRunTitle(run).toLowerCase().includes(search.toLowerCase()));
  const displayedRuns = visibleRuns.slice(0, RUN_RAIL_RENDER_LIMIT);

  const beginRename = (run: RunRailEntry) => {
    setEditingId(run.id);
    setEditingTitle(fullRunTitle(run));
  };
  const finishRename = async (run: RunRailEntry) => {
    const title = compactTitle(editingTitle);
    if (!title) return;
    await onRename(run, title);
    setEditingId(null);
    setEditingTitle("");
  };
  const closeMenu = () => {
    setMenuAnchorEl(null);
    setMenuRun(null);
  };
  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      await onDelete(deleteTarget);
      setDeleteTarget(null);
    } catch {
      // The parent surfaces the API error in the workspace; keep the dialog open
      // so the user can read it and choose what to do next.
    } finally {
      setDeleteBusy(false);
    }
  };

  return <Card variant="outlined" sx={{ width: { xs: "100%", lg: 280 }, flexShrink: 0, position: { lg: "sticky" }, top: 16, borderRadius: 3 }}>
    <CardContent sx={{ p: 1.25, "&:last-child": { pb: 1.25 } }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Box><Typography variant="subtitle1" sx={{ fontWeight: 800 }}>Test runs</Typography><Typography sx={{ fontSize: ".7rem" }} color="text.secondary">Revisit and improve saved suites</Typography></Box>
        <Button size="small" startIcon={<AddOutlinedIcon />} onClick={onNew} sx={{ textTransform: "none", whiteSpace: "nowrap", minWidth: 0 }}>New</Button>
      </Stack>
      <TextField size="small" fullWidth value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search runs" sx={{ mb: 1 }} />
      <Stack spacing={0.6} sx={{ maxHeight: { lg: "calc(100vh - 235px)" }, overflowY: "auto", pr: 0.25, minHeight: 0, "& > .MuiCard-root": { flexShrink: 0 } }}>
        {displayedRuns.map((run) => {
          const title = runTitle(run);
          const fullTitle = fullRunTitle(run);
          const selected = activeId === run.id;
          const status = run.status || "completed";
          const opening = openingId === run.id;
          const editing = editingId === run.id;
          const renaming = renamingId === run.id;
          return <Card key={run.id} variant="outlined" onClick={() => { if (!opening && !editing) void onSelect(run); }} sx={{ cursor: opening ? "progress" : editing ? "default" : "pointer", flexShrink: 0, minHeight: 50, opacity: opening || renaming ? 0.7 : 1, borderColor: selected ? "primary.main" : "divider", bgcolor: selected ? "action.selected" : "background.paper", transition: "border-color .15s, background-color .15s, opacity .15s", "&:hover": { borderColor: "primary.main" } }}>
            <CardContent sx={{ px: 1, py: 0.7, "&:last-child": { pb: 0.7 } }}>
              {editing ? <Stack direction="row" spacing={0.25} alignItems="center">
                <TextField
                  variant="standard"
                  value={editingTitle}
                  onChange={(event) => setEditingTitle(event.target.value)}
                  onClick={(event) => event.stopPropagation()}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") { event.preventDefault(); void finishRename(run); }
                    if (event.key === "Escape") { setEditingId(null); setEditingTitle(""); }
                  }}
                  autoFocus
                  fullWidth
                  inputProps={{ maxLength: 500, style: { fontSize: "0.76rem", fontWeight: 650 } }}
                />
                <IconButton size="small" disabled={renaming || !editingTitle.trim()} onClick={(event) => { event.stopPropagation(); void finishRename(run); }} aria-label="Save test run name"><CheckOutlinedIcon sx={{ fontSize: 16 }} /></IconButton>
                <IconButton size="small" disabled={renaming} onClick={(event) => { event.stopPropagation(); setEditingId(null); setEditingTitle(""); }} aria-label="Cancel rename"><CloseOutlinedIcon sx={{ fontSize: 16 }} /></IconButton>
              </Stack> : <Stack direction="row" spacing={0.25} alignItems="center" sx={{ minWidth: 0 }}>
                <Tooltip title={fullTitle} placement="top" enterDelay={500}><Typography noWrap sx={{ flex: 1, minWidth: 0, fontSize: ".76rem", lineHeight: 1.25, fontWeight: 700 }}>{title}</Typography></Tooltip>
                <Tooltip title={`Actions for ${title}`}><IconButton size="small" onClick={(event) => { event.stopPropagation(); setMenuAnchorEl(event.currentTarget); setMenuRun(run); }} aria-label={`Actions for ${title}`} sx={{ p: 0.35 }}><MoreVertOutlinedIcon sx={{ fontSize: 17 }} /></IconButton></Tooltip>
              </Stack>}
              <Stack direction="row" spacing={0.65} alignItems="center" sx={{ mt: 0.35 }}>
                <Chip size="small" label={opening ? "loading…" : renaming ? "saving…" : status.replaceAll("_", " ")} color={status === "completed" ? "success" : status === "failed" ? "error" : "default"} sx={{ height: 19, "& .MuiChip-label": { px: 0.7, fontSize: ".61rem", lineHeight: 1 } }} />
                <Typography color="text.secondary" sx={{ fontSize: ".67rem", whiteSpace: "nowrap" }}>{runCaseCount(run)} cases</Typography>
              </Stack>
            </CardContent>
          </Card>;
        })}
        {visibleRuns.length > displayedRuns.length && <Typography variant="caption" color="text.secondary" sx={{ px: 0.5, py: 1 }}>Showing the first {RUN_RAIL_RENDER_LIMIT} of {visibleRuns.length} runs. Use search to find older suites.</Typography>}
        {!visibleRuns.length && <Typography variant="body2" color="text.secondary" sx={{ p: 1 }}>No saved runs yet. Start a new test to create one.</Typography>}
      </Stack>
      <Menu anchorEl={menuAnchorEl} open={Boolean(menuAnchorEl) && Boolean(menuRun)} onClose={closeMenu}>
        <MenuItem onClick={() => { if (menuRun) beginRename(menuRun); closeMenu(); }} disabled={Boolean(menuRun && renamingId === menuRun.id)}>
          <EditOutlinedIcon sx={{ mr: 1, fontSize: 18 }} />Edit name
        </MenuItem>
        <MenuItem
          disabled={Boolean(menuRun && ACTIVE_STATUSES.includes(menuRun.status))}
          onClick={() => { if (menuRun) setDeleteTarget(menuRun); closeMenu(); }}
          sx={{ color: "error.main" }}
        >
          <DeleteOutlineOutlinedIcon sx={{ mr: 1, fontSize: 18 }} />Delete test set
        </MenuItem>
      </Menu>
      <Dialog open={Boolean(deleteTarget)} onClose={() => { if (!deleteBusy) setDeleteTarget(null); }} maxWidth="xs" fullWidth>
        <DialogTitle>Delete test set?</DialogTitle>
        <DialogContent>
          <Typography>
            Delete “{deleteTarget ? runTitle(deleteTarget) : "this test set"}” and its generated test cases?
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
            This cannot be undone. Test sets with recorded execution results are retained for audit history.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)} disabled={deleteBusy}>Cancel</Button>
          <Button color="error" variant="contained" onClick={() => void confirmDelete()} disabled={deleteBusy}>
            {deleteBusy ? "Deleting…" : "Delete test set"}
          </Button>
        </DialogActions>
      </Dialog>
    </CardContent>
  </Card>;
}

export default function GenerateTestCasesPage() {
  const navigate = useNavigate();
  const { selectedProjectId } = useSelectedProject();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const focusedRunId = searchParams.get("run");
  const historyQuery = useQuery<GenerationRunSummary[]>({
    queryKey: ["generation-history-summaries", selectedProjectId],
    queryFn: () => testCasesApi.historySummaries(selectedProjectId!, 500).then((res) => res.data),
    enabled: Boolean(selectedProjectId),
  });
  const { data: historyRunSummaries = [] } = historyQuery;
  const [localRuns, setLocalRuns] = useState<GenerationRun[]>(() => readSavedChats());
  const allRuns = useMemo<RunRailEntry[]>(
    () => {
      const projectLocalRuns = localRuns.filter((localRun) => !selectedProjectId || localRun.project_id === selectedProjectId);
      const serverIds = new Set(historyRunSummaries.map((serverRun) => serverRun.id));
      const visibleLocalRuns = projectLocalRuns.filter((localRun) => !serverIds.has(localRun.id));
      return [...visibleLocalRuns, ...historyRunSummaries]
        .sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());
    },
    [historyRunSummaries, localRuns, selectedProjectId],
  );
  const [selectedSource, setSelectedSource] = useState("document");
  const [sourceUrl, setSourceUrl] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [selectedDocumentAssetIds, setSelectedDocumentAssetIds] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [coverage, setCoverage] = useState("balanced");
  const [result, setResult] = useState<GenerationRun | null>(null);
  const [draftCases, setDraftCases] = useState<TestCase[]>([]);
  const [saved, setSaved] = useState(false);
  const [localPreview, setLocalPreview] = useState(false);
  const [openingRunId, setOpeningRunId] = useState<string | null>(null);
  const [renamingRunId, setRenamingRunId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [caseSearch, setCaseSearch] = useState("");
  const [caseTypeFilter, setCaseTypeFilter] = useState("all");
  const [expandedCaseGroups, setExpandedCaseGroups] = useState<Record<string, boolean>>({});
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const source = SOURCES.find((item) => item.id === selectedSource) ?? SOURCES[1];
  useEffect(() => {
    setSelectedDocumentAssetIds([]);
  }, [selectedProjectId]);
  const { data: liveRun } = useQuery({
    queryKey: ["generation-run", result?.id],
    queryFn: () => testCasesApi.getRun(result!.id).then((res) => res.data),
    enabled: Boolean(result?.id && !result.id.startsWith("local-")),
    refetchInterval: (query) => ACTIVE_STATUSES.includes(((query.state.data as GenerationRun | undefined)?.status ?? result?.status) ?? "") ? 1500 : false,
  });
  const run = liveRun ?? result;
  const isActive = Boolean(run && ACTIVE_STATUSES.includes(run.status));
  useEffect(() => {
    if (liveRun?.test_cases?.length) { setDraftCases(liveRun.test_cases); setLocalPreview(false); }
  }, [liveRun]);
  const inputSummary = useMemo(() => [
    ...files.map((file) => file.name),
    ...(source.kind === "link" && sourceUrl.trim() ? [sourceUrl.trim()] : []),
    ...(selectedDocumentAssetIds.length ? [`${selectedDocumentAssetIds.length} repository document${selectedDocumentAssetIds.length === 1 ? "" : "s"}`] : []),
  ], [files, selectedDocumentAssetIds.length, source.kind, sourceUrl]);

  const generationMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProjectId) throw new Error("Create or select a project before generating test cases.");
      if (!files.length && !sourceUrl.trim() && !prompt.trim() && !selectedDocumentAssetIds.length) throw new Error("Add a file, link, repository document, or prompt first.");
      setMessage("Checking repository documents and preparing generation…");
      const requirementIds: string[] = [];
      for (const assetId of selectedDocumentAssetIds) {
        requirementIds.push((await requirementsApi.reuseUpload(selectedProjectId, assetId)).data.id);
      }
      for (const file of files) requirementIds.push((await requirementsApi.upload(selectedProjectId, file)).data.id);
      const context = [prompt.trim() ? `User guidance:\n${prompt.trim()}` : "", sourceUrl.trim() ? `${source.label} source: ${sourceUrl.trim()}` : "", selectedDocumentAssetIds.length ? `Supporting repository documents attached: ${selectedDocumentAssetIds.length}` : "", `Coverage preference: ${coverage}`, inputSummary.length ? `Inputs: ${inputSummary.join(", ")}` : ""].filter(Boolean).join("\n\n");
      if (context) requirementIds.push((await requirementsApi.submitDirectPrompt(selectedProjectId, `${source.label} test design`, context)).data.id);
      const profile = coverage === "quick" ? "smoke" : coverage === "thorough" ? "regression" : "feature";
      const testSetTitle = inputHeading(source, files, sourceUrl, prompt);
      return testCasesApi.generate(selectedProjectId, requirementIds, undefined, profile, testSetTitle).then((res) => res.data);
    },
    onSuccess: (next) => {
      const hasServerCases = Boolean(next.test_cases?.length);
      setResult({ ...next, title: next.title || inputHeading(source, files, sourceUrl, prompt) });
      setDraftCases(next.test_cases ?? []);
      setLocalPreview(false);
      setSaved(false);
      setMessage(hasServerCases ? "Generation started. Live progress will appear here." : "Generation is running against your supplied inputs. Real test cases will appear when analysis completes.");
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["generation-history-summaries", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["repository-documents", selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ["uploads", selectedProjectId] });
    },
    onError: (reason) => { setError(apiErrorMessage(reason, "Generation failed.")); setMessage(null); },
  });
  const exportMutation = useMutation({
    mutationFn: async (format: string) => {
      if (!run?.id) throw new Error("Generate a suite before exporting.");
      let blob: Blob;
      if (localPreview) {
        if (format === "json") blob = new Blob([JSON.stringify(draftCases, null, 2)], { type: "application/json" });
        else {
          const header = "Key,Scenario,Objective,Priority,Severity,Steps,Expected result";
          const rows = draftCases.map((item) => [item.test_case_key, item.scenario, item.objective, item.priority, item.severity, item.steps.join(" | "), item.expected_result].map((value) => `"${String(value).replace(/"/g, '""')}"`).join(","));
          blob = new Blob([[header, ...rows].join("\n")], { type: "text/csv;charset=utf-8" });
        }
      } else {
        const response = await testCasesApi.export(run.id, format);
        blob = new Blob([response.data]);
      }
      const info = EXPORT_FORMATS.find((item) => item.value === format);
      const extension = localPreview && format === "excel" ? "csv" : (info?.value ?? format);
      const url = window.URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `qtxpert-${run.id.slice(0, 8)}-${extension}`; link.click(); window.URL.revokeObjectURL(url);
    },
    onSuccess: (_, format) => setMessage(`Downloaded ${format.toUpperCase()} test cases.`),
    onError: (reason) => setError(apiErrorMessage(reason, "Export failed.")),
  });
  const allowedExtensions = (source.accept ?? FILE_EXTENSIONS).split(",").map((extension) => extension.trim().toLowerCase());
  const addFiles = (incoming: File[]) => {
    const valid = incoming.filter((file) => allowedExtensions.includes(`.${file.name.split(".").pop()?.toLowerCase() ?? ""}`));
    const invalid = incoming.filter((file) => !valid.includes(file));
    const maxUploadMb = source.id === "app" ? MOBILE_PACKAGE_MAX_UPLOAD_MB : DOCUMENT_MAX_UPLOAD_MB;
    const maxUploadBytes = maxUploadMb * 1024 * 1024;
    const oversized = valid.filter((file) => file.size > maxUploadBytes);
    const accepted = valid.filter((file) => !oversized.includes(file));
    const messages: string[] = [];
    if (invalid.length) messages.push(`Skipped ${invalid.map((file) => file.name).join(", ")}. Allowed for ${source.label}: ${source.accept ?? FILE_EXTENSIONS}.`);
    if (oversized.length) messages.push(`Skipped ${oversized.map((file) => file.name).join(", ")}. ${source.id === "app" ? "APK/IPA packages" : "Files"} may be up to ${maxUploadMb} MB.`);
    setError(messages.length ? messages.join(" ") : null);
    if (accepted.length) setFiles((current) => [...current, ...accepted]);
  };
  const onFiles = (event: ChangeEvent<HTMLInputElement>) => { addFiles(Array.from(event.target.files ?? [])); event.target.value = ""; };
  const chooseSource = (item: InputSource) => {
    setSelectedSource(item.id);
    if (item.kind === "file") {
      const input = fileInputRef.current;
      if (input) { input.accept = item.accept ?? FILE_EXTENSIONS; input.multiple = item.id !== "app"; input.value = ""; }
      input?.click();
    }
  };
  const saveChatSnapshot = (sourceRun: GenerationRun, cases: TestCase[]) => {
    const isLocal = sourceRun.id.startsWith("local-");
    if (!isLocal) return null;
    const snapshot: GenerationRun = {
      ...sourceRun,
      id: sourceRun.id,
      status: cases.length ? "completed" : sourceRun.status,
      requirement_summary: sourceRun.requirement_summary || "Saved test chat",
      created_at: sourceRun.created_at,
      test_cases: cases,
    };
    const next = [snapshot, ...localRuns.filter((item) => item.id !== snapshot.id)];
    setLocalRuns(next);
    localStorage.setItem(LOCAL_CHAT_STORAGE_KEY, JSON.stringify(next));
    return snapshot;
  };
  const exitRunView = () => {
    setSearchParams({}, { replace: true });
    setResult(null);
    setDraftCases([]);
    setFiles([]);
    setSelectedDocumentAssetIds([]);
    setSourceUrl("");
    setPrompt("");
    setSaved(false);
    setLocalPreview(false);
    setOpeningRunId(null);
    setRenamingRunId(null);
    setMessage(null);
    setError(null);
  };
  const startNewChat = () => {
    const savedChat = run?.id.startsWith("local-") ? saveChatSnapshot(run, draftCases) : null;
    exitRunView();
    setSelectedSource("document");
    setMessage(savedChat ? "Saved the current chat to Test runs. Add a source or describe a new flow to begin." : "Started a new test-design chat. Add a source or describe the flow to begin.");
  };
  const openRun = async (historyRun: RunRailEntry) => {
    setError(null);
    setSearchParams({ run: historyRun.id }, { replace: true });
    if ("test_cases" in historyRun) {
      setResult(historyRun); setDraftCases(historyRun.test_cases ?? []); setLocalPreview(historyRun.id.startsWith("local-")); setSaved(historyRun.id.startsWith("local-"));
      setMessage(historyRun.id.startsWith("local-") ? "Reopened a saved chat. Edit any field to continue improving it." : "Reopened this test run. Edit any field to improve the suite.");
      return;
    }
    setOpeningRunId(historyRun.id);
    try {
      const fullRun = await queryClient.fetchQuery({
        queryKey: ["generation-run", historyRun.id],
        queryFn: () => testCasesApi.getRun(historyRun.id).then((response) => response.data),
        staleTime: 30_000,
      });
      setResult(fullRun);
      setDraftCases(fullRun.test_cases ?? []);
      setLocalPreview(false);
      setSaved(false);
      setMessage("Reopened this test run. Edit any field to improve the suite.");
    } catch (reason) {
      setError(apiErrorMessage(reason, "Could not load this test run."));
    } finally {
      setOpeningRunId(null);
    }
  };
  useEffect(() => {
    if (!focusedRunId || run?.id === focusedRunId || openingRunId === focusedRunId) return;
    const target = allRuns.find((item) => item.id === focusedRunId);
    if (target) {
      void openRun(target);
      return;
    }
    if (historyQuery.isFetched && !allRuns.length) setSearchParams({}, { replace: true });
  }, [allRuns, focusedRunId, historyQuery.isFetched, openingRunId, run?.id]);
  const renameRun = async (historyRun: RunRailEntry, title: string) => {
    setRenamingRunId(historyRun.id);
    setError(null);
    try {
      if (historyRun.id.startsWith("local-")) {
        const next = localRuns.map((item) => item.id === historyRun.id ? { ...item, title } : item);
        setLocalRuns(next);
        localStorage.setItem(LOCAL_CHAT_STORAGE_KEY, JSON.stringify(next));
        if (result?.id === historyRun.id) setResult({ ...result, title });
      } else {
        const updated = (await testCasesApi.updateRunTitle(historyRun.id, title)).data;
        queryClient.setQueryData(["generation-run", historyRun.id], updated);
        if (result?.id === historyRun.id) setResult(updated);
        await queryClient.invalidateQueries({ queryKey: ["generation-history-summaries", selectedProjectId] });
      }
      setMessage("Test run name updated.");
    } catch (reason) {
      setError(apiErrorMessage(reason, "Could not rename this test run."));
      throw reason;
    } finally {
      setRenamingRunId(null);
    }
  };
  const deleteRun = async (historyRun: RunRailEntry) => {
    setError(null);
    try {
      if (historyRun.id.startsWith("local-")) {
        const next = localRuns.filter((item) => item.id !== historyRun.id);
        setLocalRuns(next);
        localStorage.setItem(LOCAL_CHAT_STORAGE_KEY, JSON.stringify(next));
      } else {
        await testCasesApi.deleteRun(historyRun.id);
        queryClient.removeQueries({ queryKey: ["generation-run", historyRun.id] });
        await queryClient.invalidateQueries({ queryKey: ["generation-history-summaries", selectedProjectId] });
      }
      if (run?.id === historyRun.id) exitRunView();
      setMessage("Test set deleted.");
    } catch (reason) {
      setError(apiErrorMessage(reason, "Could not delete this test set."));
      throw reason;
    }
  };
  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!run) throw new Error("Open a generated test set before saving edits.");
      if (localPreview) {
        return saveChatSnapshot(run, draftCases) ?? { ...run, test_cases: draftCases };
      }
      return testCasesApi.updateRun(run.id, draftCases).then((response) => response.data);
    },
    onSuccess: (updatedRun) => {
      setResult(updatedRun);
      setDraftCases(updatedRun.test_cases ?? draftCases);
      setSaved(true);
      setMessage("Changes saved to this test set. No new generation run was created.");
      if (!updatedRun.id.startsWith("local-")) {
        queryClient.setQueryData(["generation-run", updatedRun.id], updatedRun);
        queryClient.invalidateQueries({ queryKey: ["generation-history-summaries", selectedProjectId] });
      }
      setError(null);
    },
    onError: (reason) => setError(apiErrorMessage(reason, "Could not save the test set.")),
  });
  const saveSuite = () => { if (run) saveMutation.mutate(); };
  const updateCase = (index: number, next: TestCase) => {
    setSaved(false);
    setDraftCases((current) => current.map((item, idx) => idx === index ? next : item));
  };

  const testTypeOptions = useMemo(
    () => [...new Set(draftCases.map((testCase) => testCase.test_type || "functional"))].sort(),
    [draftCases],
  );
  const filteredDraftCases = useMemo(() => {
    const search = caseSearch.trim().toLowerCase();
    return draftCases
      .map((testCase, index) => ({ testCase, index }))
      .filter(({ testCase }) => {
        const matchesType = caseTypeFilter === "all" || (testCase.test_type || "functional") === caseTypeFilter;
        const matchesSearch = !search || `${testCase.test_case_key} ${testCase.scenario} ${testCase.objective} ${testCase.test_type}`.toLowerCase().includes(search);
        return matchesType && matchesSearch;
      });
  }, [caseSearch, caseTypeFilter, draftCases]);
  const draftCaseGroups = useMemo(() => {
    const groups = new Map<string, Array<{ testCase: TestCase; index: number }>>();
    filteredDraftCases.forEach((item) => {
      const key = item.testCase.test_type || "functional";
      const current = groups.get(key) ?? [];
      current.push(item);
      groups.set(key, current);
    });
    return [...groups.entries()];
  }, [filteredDraftCases]);
  const automationCandidateCount = draftCases.filter((testCase) => testCase.is_automation_candidate).length;
  const highRiskCount = draftCases.filter((testCase) => testCase.risk_level === "high" || ["critical", "blocker"].includes(testCase.severity)).length;

  const workspace = (content: ReactNode) => <Stack direction={{ xs: "column", lg: "row" }} spacing={2} alignItems="flex-start"><RunRail runs={allRuns} activeId={run?.id} openingId={openingRunId} renamingId={renamingRunId} onSelect={openRun} onRename={renameRun} onDelete={deleteRun} onNew={startNewChat} /><Box sx={{ flex: 1, minWidth: 0, width: "100%" }}>{content}</Box></Stack>;

  if (run) return workspace(<Stack spacing={2}>
    <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} spacing={1}><Box sx={{ minWidth: 0 }}><Button size="small" startIcon={<ArrowBackOutlinedIcon />} onClick={exitRunView} sx={{ mb: 0.5, textTransform: "none" }}>Back to Test design</Button><Typography variant="h5" sx={{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis" }}>{runTitle(run)}</Typography><Typography color="text.secondary">{run.status === "completed" ? `${draftCases.length} editable test cases` : draftCases.length ? `${draftCases.length} test cases ready • generating more` : `Working: ${run.status.replaceAll("_", " ")}`}</Typography></Box><Stack direction="row" spacing={1} flexWrap="wrap"><Button startIcon={<RefreshOutlinedIcon />} onClick={() => setResult(null)}>Edit inputs</Button><Button startIcon={<SaveOutlinedIcon />} variant={saved ? "outlined" : "contained"} onClick={saveSuite} disabled={saveMutation.isPending || (run.status !== "completed" && !localPreview)}>{saveMutation.isPending ? "Saving…" : saved ? "Saved" : "Save suite"}</Button></Stack></Stack>
    {isActive && <LinearProgress variant="determinate" value={PROGRESS[run.status] ?? 10} />}
    {isActive && <Alert severity="info">{draftCases.length ? `${draftCases.length} real test cases are ready to review below. Additional coverage is still generating.` : "Analyzing your inputs. The first completed test-case batch will appear here automatically."}</Alert>}
    {run.error_message && <Alert severity={run.status === "failed" ? "error" : "warning"}>{run.error_message}</Alert>}
    {(run.status === "completed" || localPreview) && <>
      <Card variant="outlined"><CardContent><Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} spacing={1}><Box><Typography variant="h6">Review and improve</Typography><Typography variant="body2" color="text.secondary">Every field is editable. Grouped sections make the suite easy to scan before you save it.</Typography></Box><Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>{["excel", "csv", "json"].map((format) => <Button key={format} size="small" variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={() => exportMutation.mutate(format)} disabled={exportMutation.isPending}>{format === "excel" ? "Excel" : format.toUpperCase()}</Button>)}</Stack></Stack></CardContent></Card>
      <Grid container spacing={1.25}>
        {[["Total cases", draftCases.length, "Generated scenarios"], ["Automation candidates", automationCandidateCount, "Ready for execution review"], ["High-risk cases", highRiskCount, "Critical or blocker severity"], ["Coverage groups", testTypeOptions.length, "Functional areas represented"]].map(([label, value, helper]) => <Grid key={String(label)} size={{ xs: 6, sm: 3 }}><Card variant="outlined" sx={{ height: "100%" }}><CardContent sx={{ p: 1.5, "&:last-child": { pb: 1.5 } }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h5" sx={{ fontWeight: 800, mt: 0.35 }}>{value}</Typography><Typography variant="caption" color="text.secondary">{helper}</Typography></CardContent></Card></Grid>)}
      </Grid>
      <Card variant="outlined"><CardContent sx={{ p: 1.5, "&:last-child": { pb: 1.5 } }}><Stack direction={{ xs: "column", sm: "row" }} spacing={1.25} alignItems={{ sm: "center" }}><TextField size="small" label="Search cases" value={caseSearch} onChange={(event) => setCaseSearch(event.target.value)} placeholder="Key, scenario or objective" sx={{ minWidth: { sm: 260 } }} /><FormControl size="small" sx={{ minWidth: { sm: 190 } }}><InputLabel id="design-case-type-filter">Coverage group</InputLabel><Select labelId="design-case-type-filter" label="Coverage group" value={caseTypeFilter} onChange={(event) => setCaseTypeFilter(event.target.value)}><MenuItem value="all">All groups</MenuItem>{testTypeOptions.map((type) => <MenuItem key={type} value={type}>{testCaseTypeLabel(type)}</MenuItem>)}</Select></FormControl><Chip size="small" variant="outlined" label={`${filteredDraftCases.length} of ${draftCases.length} visible`} /><Box sx={{ flex: 1 }} /><Typography variant="caption" color="text.secondary">Expand a group to edit its cases.</Typography></Stack></CardContent></Card>
      <Stack spacing={1.25} sx={{ maxHeight: { lg: "calc(100vh - 430px)" }, overflowY: { lg: "auto" }, pr: { lg: 1 } }}>
        {draftCaseGroups.map(([group, items]) => <Accordion key={group} expanded={expandedCaseGroups[group] ?? true} onChange={(_, expanded) => setExpandedCaseGroups((current) => ({ ...current, [group]: expanded }))} disableGutters variant="outlined" sx={{ borderRadius: 2, "&:before": { display: "none" } }}>
          <AccordionSummary expandIcon={<ExpandMoreOutlinedIcon />} sx={{ px: 1.5, minHeight: 52, "& .MuiAccordionSummary-content": { my: 0.8 } }}><Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}><Typography sx={{ fontWeight: 800 }}>{testCaseTypeLabel(group)}</Typography><Chip size="small" label={`${items.length} ${items.length === 1 ? "case" : "cases"}`} /></Stack></AccordionSummary>
          <AccordionDetails sx={{ p: 1.25, pt: 0.25 }}><Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "repeat(2, minmax(0, 1fr))", xl: "repeat(3, minmax(0, 1fr))" }, gap: 1.1, alignItems: "start" }}>{items.map(({ testCase, index }) => <EditableCase key={testCase.id || index} testCase={testCase} onChange={(next) => updateCase(index, next)} />)}</Box></AccordionDetails>
        </Accordion>)}
        {!draftCaseGroups.length && <Alert severity="info">No test cases match the current search or coverage group.</Alert>}
      </Stack>
    </>}
    {!isActive && !draftCases.length && run.status !== "failed" && <Alert severity="info">The provider returned no test cases. Edit the inputs and run again.</Alert>}{message && <Alert severity="success" onClose={() => setMessage(null)}>{message}</Alert>}{error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
  </Stack>);

  return workspace(<Stack spacing={3}>
    <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} spacing={1}><Box><Typography variant="h5" sx={{ fontWeight: 700 }}>Test design workspace</Typography><Typography color="text.secondary">Bring every source and instruction together on one page.</Typography></Box><Stack direction="row" spacing={1}><Button onClick={startNewChat}>＋ New chat</Button><ProjectSelector /></Stack></Stack>
    <Card sx={{ borderRadius: 3 }}><CardContent><Stack spacing={3}><Box><Typography variant="h6">Start a test-design chat</Typography><Typography variant="body2" color="text.secondary">Upload an app, requirements, or video; paste links; and describe what matters. QTXpert sends these inputs to the authenticated generation service.</Typography></Box>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} flexWrap="wrap">{SOURCES.map((item) => <Button key={item.id} variant={selectedSource === item.id ? "contained" : "outlined"} startIcon={item.kind === "file" ? <CloudUploadOutlinedIcon /> : <AddOutlinedIcon />} onClick={() => chooseSource(item)} sx={{ justifyContent: "flex-start", textTransform: "none", minWidth: 180 }}><Box sx={{ textAlign: "left" }}><Typography variant="body2" sx={{ fontWeight: 700 }}>{item.label}</Typography><Typography variant="caption" sx={{ opacity: 0.75 }}>{item.description}</Typography></Box></Button>)}</Stack>
      <input ref={fileInputRef} hidden type="file" multiple accept={source.accept ?? FILE_EXTENSIONS} onChange={onFiles} />{source.kind === "link" && <TextField label={`${source.label} link`} value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder={source.placeholder} fullWidth helperText="The link is sent as context with your prompt." />}
      <Box onClick={() => fileInputRef.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); addFiles(Array.from(event.dataTransfer.files)); }} sx={{ border: "1px dashed", borderColor: "primary.main", borderRadius: 2, p: 2, cursor: "pointer", bgcolor: "action.hover" }}><Typography sx={{ fontWeight: 600 }}>Drop files here or click to browse</Typography><Typography variant="caption" color="text.secondary">Allowed for {source.label}: {source.accept ?? FILE_EXTENSIONS} • up to {source.id === "app" ? MOBILE_PACKAGE_MAX_UPLOAD_MB : DOCUMENT_MAX_UPLOAD_MB} MB</Typography></Box>{files.length > 0 && <Stack spacing={1}>{files.map((file, index) => <Stack key={`${file.name}-${index}`} direction="row" alignItems="center" spacing={1}><Chip label={file.name} onDelete={() => setFiles((current) => current.filter((_, idx) => idx !== index))} deleteIcon={<DeleteOutlineOutlinedIcon />} /><Typography variant="caption" color="text.secondary">{Math.ceil(file.size / 1024)} KB</Typography></Stack>)}</Stack>}
      <RepositoryDocumentsPicker
        projectId={selectedProjectId}
        selectedIds={selectedDocumentAssetIds}
        onSelectionChange={setSelectedDocumentAssetIds}
        sourceModule="test_design"
        title="Existing project documents (optional)"
        description="Reuse documents already in this project repository. They stay stored once and can be attached to future Test Design runs."
        compact
        onOpenRepository={() => navigate("/test-data/documents")}
      />
      <Divider /><TextField label="What should we test?" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Example: Cover checkout, payment failures, permissions, accessibility, and mobile edge cases." fullWidth multiline minRows={4} helperText="Optional when you upload a source; required when you only provide instructions." />
      <FormControl sx={{ maxWidth: 260 }}><InputLabel id="coverage-label">Coverage</InputLabel><Select labelId="coverage-label" label="Coverage" value={coverage} onChange={(e) => setCoverage(e.target.value)}><MenuItem value="quick">Quick</MenuItem><MenuItem value="balanced">Balanced</MenuItem><MenuItem value="thorough">Thorough</MenuItem></Select><FormHelperText>Controls breadth of scenarios.</FormHelperText></FormControl>
      {message && <Alert severity="info">{message}</Alert>}{error && <Alert severity="error">{error}</Alert>}<Button variant="contained" size="large" startIcon={<AutoAwesomeOutlinedIcon />} onClick={() => generationMutation.mutate()} disabled={generationMutation.isPending || !selectedProjectId} sx={{ alignSelf: "flex-start" }}>{generationMutation.isPending ? "Preparing generation…" : "Analyze and generate test cases"}</Button>
    </Stack></CardContent></Card><Typography variant="caption" color="text.secondary">Signed-in workspace • generation runs are stored in Test runs • exports are available after completion</Typography>
  </Stack>);
}

