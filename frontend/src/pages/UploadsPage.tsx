import { ChangeEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControl,
  InputLabel,
  LinearProgress,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import DeleteOutlineOutlinedIcon from "@mui/icons-material/DeleteOutlineOutlined";
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import { uploadsApi } from "@/services/api";
import { isReusableProjectDocument, UploadedAsset } from "@/types/domain";
import { useSelectedProject } from "@/hooks/useSelectedProject";

export type RepositoryMode = "test_data" | "documents";

interface UploadsPageProps {
  mode?: RepositoryMode;
}

const DOCUMENT_EXTENSIONS = new Set([
  "pdf", "docx", "pptx", "txt", "md", "json", "csv", "xlsx", "xls", "xml", "yaml", "yml", "html", "htm",
]);
const TEST_DATA_EXTENSIONS = new Set(["csv", "json", "xlsx", "xls", "xml", "yaml", "yml", "txt"]);
const MOBILE_EXTENSIONS = new Set(["apk", "ipa"]);
const DOCUMENT_ACCEPT = ".pdf,.docx,.pptx,.txt,.md,.json,.csv,.xlsx,.xls,.xml,.yaml,.yml,.html,.htm,.apk,.ipa";
const TEST_DATA_ACCEPT = ".csv,.json,.xlsx,.xls,.xml,.yaml,.yml,.txt";
const DOCUMENT_MAX_UPLOAD_MB = 25;
const MOBILE_PACKAGE_MAX_UPLOAD_MB = 250;

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function categoryLabel(category: string) {
  return category.replaceAll("_", " ").replace(/\b\w/g, (match) => match.toUpperCase());
}

function isExecutionEvidence(asset: UploadedAsset) {
  return ["autopilot_evidence", "execution_evidence"].includes(asset.category)
    || ["autopilot_evidence", "execution_report"].includes(asset.source_module);
}

function errorMessage(reason: unknown, fallback: string) {
  const candidate = reason as { response?: { data?: { detail?: unknown } }; message?: unknown };
  if (typeof candidate?.response?.data?.detail === "string") return candidate.response.data.detail;
  if (reason instanceof Error && reason.message) return reason.message;
  return fallback;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

export default function UploadsPage({ mode = "test_data" }: UploadsPageProps) {
  const isDocumentRepository = mode === "documents";
  const queryClient = useQueryClient();
  const { selectedProjectId, selectedProject } = useSelectedProject();
  const [category, setCategory] = useState(isDocumentRepository ? "all" : "test_data");
  const [error, setError] = useState("");

  const uploadsQuery = useQuery({
    queryKey: ["uploads", selectedProjectId, isDocumentRepository ? "repository-documents" : "test-data"],
    queryFn: () => uploadsApi.list({
      project_id: selectedProjectId,
      // Fetch metadata for the active project; each view applies its own
      // category/source boundary so legacy test-data uploads remain visible
      // after the repository split.
    }).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => {
      const extension = file.name.split(".").pop()?.toLowerCase() || "";
      return uploadsApi.upload(file, {
        projectId: selectedProjectId,
        sourceModule: isDocumentRepository ? "repository_documents" : "test_data",
        // Documents are explicitly classified so spreadsheets and markup do
        // not silently land in the separate test-data repository. App builds
        // keep their APK/IPA category for Autopilot and Test Execution.
        category: isDocumentRepository ? (MOBILE_EXTENSIONS.has(extension) ? undefined : "document") : "test_data",
      });
    },
    onSuccess: async () => {
      setError("");
      await queryClient.invalidateQueries({ queryKey: ["uploads", selectedProjectId] });
      await queryClient.invalidateQueries({ queryKey: ["repository-documents", selectedProjectId] });
      await queryClient.invalidateQueries({ queryKey: ["document-intelligence-assets", selectedProjectId] });
    },
    onError: (reason) => setError(errorMessage(reason, "Upload failed")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => uploadsApi.remove(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["uploads", selectedProjectId] });
      await queryClient.invalidateQueries({ queryKey: ["repository-documents", selectedProjectId] });
      await queryClient.invalidateQueries({ queryKey: ["document-intelligence-assets", selectedProjectId] });
    },
    onError: (reason) => setError(errorMessage(reason, "Delete failed")),
  });

  const rows = useMemo(() => {
    const assets = (uploadsQuery.data ?? []).filter((asset) => {
      if (isExecutionEvidence(asset)) return false;
      if (isDocumentRepository) return ["document", "apk", "ipa"].includes(asset.category) && asset.source_module !== "test_data";
      return asset.category === "test_data" || asset.source_module === "test_data";
    });
    if (category === "all" || (!isDocumentRepository && category === "test_data")) return assets;
    if (isDocumentRepository && category === "document") return assets.filter(isReusableProjectDocument);
    return assets.filter((asset) => asset.category === category);
  }, [category, isDocumentRepository, uploadsQuery.data]);

  const summary = useMemo(() => ({
    files: rows.length,
    documents: rows.filter(isReusableProjectDocument).length,
    mobile: rows.filter((item) => MOBILE_EXTENSIONS.has(item.category) || MOBILE_EXTENSIONS.has(item.extension.toLowerCase())).length,
    bytes: rows.reduce((total, item) => total + item.size_bytes, 0),
  }), [rows]);

  if (!selectedProjectId) return <Alert severity="info">Create or select a project from the top bar.</Alert>;

  const uploadFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const incoming = Array.from(event.target.files ?? []);
    const acceptedExtensions = isDocumentRepository ? new Set([...DOCUMENT_EXTENSIONS, ...MOBILE_EXTENSIONS]) : TEST_DATA_EXTENSIONS;
    const valid = incoming.filter((file) => acceptedExtensions.has(file.name.split(".").pop()?.toLowerCase() || ""));
    const invalid = incoming.filter((file) => !valid.includes(file));
    const oversized = valid.filter((file) => {
      const extension = file.name.split(".").pop()?.toLowerCase() || "";
      const maxMb = isDocumentRepository && MOBILE_EXTENSIONS.has(extension) ? MOBILE_PACKAGE_MAX_UPLOAD_MB : DOCUMENT_MAX_UPLOAD_MB;
      return file.size > maxMb * 1024 * 1024;
    });
    const allowed = valid.filter((file) => !oversized.includes(file));
    const messages: string[] = [];
    if (invalid.length) messages.push(`Skipped ${invalid.map((file) => file.name).join(", ")}. Unsupported file type for this repository.`);
    if (oversized.length) messages.push(`Skipped ${oversized.map((file) => file.name).join(", ")}. Documents allow ${DOCUMENT_MAX_UPLOAD_MB} MB; APK/IPA packages allow ${MOBILE_PACKAGE_MAX_UPLOAD_MB} MB.`);
    setError(messages.join(" "));
    allowed.forEach((file) => uploadMutation.mutate(file));
    event.target.value = "";
  };

  const download = async (asset: UploadedAsset) => {
    try {
      const response = await uploadsApi.download(asset.id);
      const url = window.URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = asset.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (reason) {
      setError(errorMessage(reason, "Download failed"));
    }
  };

  const title = isDocumentRepository ? "Document repository" : "Test data repository";
  const description = isDocumentRepository
    ? "Reusable requirements, contracts, plans and mobile builds for this project. Upload once, then attach the same asset from Autopilot, Document Intelligence or Test Design."
    : "Structured fixtures and datasets kept separate from project documents and application builds.";

  return (
    <Stack spacing={3}>
      <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" gap={2}>
        <Box>
          <Stack direction="row" spacing={1.2} alignItems="center">
            <FolderOutlinedIcon color="primary" />
            <Typography variant="h4" fontWeight={800}>{title}</Typography>
          </Stack>
          <Typography color="text.secondary" sx={{ mt: 0.5 }}>
            {description} Files belong to <b>{selectedProject?.name || "the active project"}</b> only.
          </Typography>
        </Box>
        <Button component="label" variant="contained" startIcon={<CloudUploadOutlinedIcon />} sx={{ alignSelf: { xs: "flex-start", md: "center" } }} disabled={uploadMutation.isPending}>
          Add {isDocumentRepository ? "documents or app builds" : "test data"}
          <input hidden multiple type="file" accept={isDocumentRepository ? DOCUMENT_ACCEPT : TEST_DATA_ACCEPT} onChange={uploadFiles} />
        </Button>
      </Stack>

      {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
      <Alert severity="info">
        {isDocumentRepository
          ? "This is the single source of truth for reusable documents and app builds. Analysis and Test Design read the stored asset; execution evidence remains with Test reports."
          : "Test data is stored separately from documents and mobile builds. Execution evidence and reports are kept in Test reports."}
      </Alert>
      {(uploadMutation.isPending || uploadsQuery.isLoading) && <LinearProgress />}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        {[
          [isDocumentRepository ? "Repository files" : "Test data files", summary.files],
          [isDocumentRepository ? "Documents" : "Structured fixtures", summary.documents || (isDocumentRepository ? 0 : summary.files)],
          [isDocumentRepository ? "Mobile builds" : "Stored size", isDocumentRepository ? summary.mobile : formatBytes(summary.bytes)],
          ...(isDocumentRepository ? [["Stored size", formatBytes(summary.bytes)] as [string, string]] : []),
        ].map(([label, value]) => (
          <Card key={String(label)} variant="outlined" sx={{ minWidth: 170, flex: 1 }}>
            <CardContent><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h5" fontWeight={800}>{value}</Typography></CardContent>
          </Card>
        ))}
      </Stack>

      <Card variant="outlined">
        <CardContent>
          <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={2} alignItems={{ sm: "center" }}>
            <Box>
              <Typography variant="h6" fontWeight={800}>Project {isDocumentRepository ? "documents and builds" : "test data"}</Typography>
              <Typography variant="body2" color="text.secondary">Every stored asset has a stable ID, checksum, source, storage backend, size and upload history.</Typography>
            </Box>
            <FormControl size="small" sx={{ minWidth: 190 }}>
              <InputLabel>Type</InputLabel>
              <Select value={category} label="Type" onChange={(event) => setCategory(event.target.value)}>
                <MenuItem value="all">All {isDocumentRepository ? "repository files" : "test data"}</MenuItem>
                {isDocumentRepository ? <>
                  <MenuItem value="document">Documents</MenuItem>
                  <MenuItem value="apk">Android APKs</MenuItem>
                  <MenuItem value="ipa">iOS IPAs</MenuItem>
                </> : <MenuItem value="test_data">Test data</MenuItem>}
              </Select>
            </FormControl>
          </Stack>

          {uploadsQuery.isError && <Alert severity="error" sx={{ mt: 2 }}>Unable to load this project's repository.</Alert>}
          {!uploadsQuery.isLoading && rows.length === 0 ? (
            <Box sx={{ py: 7, textAlign: "center" }}>
              <FolderOutlinedIcon sx={{ fontSize: 48, color: "text.disabled", mb: 1 }} />
              <Typography fontWeight={700}>No {isDocumentRepository ? "documents or app builds" : "test data files"} in this project yet</Typography>
              <Typography variant="body2" color="text.secondary">Use Add files above. Stored assets can be reused by the relevant QTXpert modules.</Typography>
            </Box>
          ) : (
            <TableContainer sx={{ mt: 2 }}>
              <Table size="small" stickyHeader>
                <TableHead><TableRow><TableCell>File</TableCell><TableCell>Type</TableCell><TableCell>Source</TableCell><TableCell>Size</TableCell><TableCell>Uploaded</TableCell><TableCell>Updated</TableCell><TableCell>Storage</TableCell><TableCell>Status</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
                <TableBody>
                  {rows.map((asset) => (
                    <TableRow key={asset.id} hover>
                      <TableCell sx={{ maxWidth: 330 }}><Typography variant="body2" fontWeight={700} noWrap>{asset.filename}</Typography><Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace" }}>{asset.extension.toUpperCase()} · SHA {asset.sha256.slice(0, 12)}…</Typography></TableCell>
                      <TableCell><Chip size="small" variant="outlined" label={categoryLabel(isDocumentRepository ? asset.category : "test_data")} /></TableCell>
                      <TableCell><Chip size="small" variant="outlined" label={categoryLabel(asset.source_module)} /></TableCell>
                      <TableCell>{formatBytes(asset.size_bytes)}</TableCell>
                      <TableCell sx={{ whiteSpace: "nowrap" }}>{formatDate(asset.created_at)}</TableCell>
                      <TableCell sx={{ whiteSpace: "nowrap" }}>{formatDate(asset.updated_at)}</TableCell>
                      <TableCell><Chip size="small" label={categoryLabel(asset.storage_backend)} /></TableCell>
                      <TableCell><Chip size="small" color={asset.status === "ready" ? "success" : "warning"} variant="outlined" label={categoryLabel(asset.status)} /></TableCell>
                      <TableCell align="right" sx={{ whiteSpace: "nowrap" }}><Button size="small" startIcon={<DownloadOutlinedIcon />} onClick={() => download(asset)}>Download</Button><Button size="small" color="error" startIcon={<DeleteOutlineOutlinedIcon />} disabled={deleteMutation.isPending} onClick={() => { if (window.confirm(`Delete ${asset.filename} from ${selectedProject?.name || "this project"}?`)) deleteMutation.mutate(asset.id); }}>Delete</Button></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </CardContent>
      </Card>
    </Stack>
  );
}

export function DocumentsRepositoryPage() {
  return <UploadsPage mode="documents" />;
}
