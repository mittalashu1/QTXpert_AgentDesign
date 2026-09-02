import { ChangeEvent, DragEvent, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import { uploadsApi } from "@/services/api";
import { UploadedAsset } from "@/types/domain";
import { useRepositoryAssets } from "@/components/repositoryAssets";

const DOCUMENT_EXTENSIONS = new Set([
  "pdf", "docx", "pptx", "txt", "md", "json", "csv", "xlsx", "xls", "xml", "yaml", "yml", "html", "htm",
]);
const DOCUMENT_ACCEPT = ".pdf,.docx,.pptx,.txt,.md,.json,.csv,.xlsx,.xls,.xml,.yaml,.yml,.html,.htm";
const DOCUMENT_MAX_UPLOAD_MB = 25;

export interface RepositoryDocumentsPickerProps {
  projectId: string | null | undefined;
  selectedIds: string[];
  onSelectionChange: (ids: string[]) => void;
  sourceModule?: string;
  title?: string;
  description?: string;
  compact?: boolean;
  allowUpload?: boolean;
  maxSelected?: number;
  onOpenRepository?: () => void;
  /** Optional shared query data when the parent already loaded this project repository. */
  assets?: UploadedAsset[];
  assetsLoading?: boolean;
  assetsError?: boolean;
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function displaySource(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function errorMessage(reason: unknown, fallback: string) {
  const candidate = reason as { response?: { data?: { detail?: unknown } }; message?: unknown };
  if (typeof candidate?.response?.data?.detail === "string") return candidate.response.data.detail;
  if (reason instanceof Error && reason.message) return reason.message;
  return fallback;
}

export default function RepositoryDocumentsPicker({
  projectId,
  selectedIds,
  onSelectionChange,
  sourceModule = "repository_documents",
  title = "Existing project documents",
  description = "Select documents already stored in the project repository, or add a new document once for reuse across QTXpert.",
  compact = false,
  allowUpload = true,
  maxSelected = 20,
  onOpenRepository,
  assets: providedAssets,
  assetsLoading,
  assetsError,
}: RepositoryDocumentsPickerProps) {
  const queryClient = useQueryClient();
  const [isDragOver, setIsDragOver] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const documentsQuery = useRepositoryAssets({
    projectId,
    categories: ["document"],
    cacheKey: "repository-documents",
    enabled: providedAssets === undefined,
  });

  const documents = useMemo(
    () => (providedAssets ?? documentsQuery.assets).filter((asset) => asset.category === "document" && asset.source_module !== "test_data" && asset.status === "ready"),
    [documentsQuery.assets, providedAssets],
  );
  const documentsLoading = providedAssets === undefined ? documentsQuery.isLoading || documentsQuery.isFetching : Boolean(assetsLoading);
  const documentsError = providedAssets === undefined ? documentsQuery.isError : Boolean(assetsError);
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const uploadMutation = useMutation({
    mutationFn: async (files: File[]) => {
      if (!projectId) throw new Error("Select a project before uploading documents.");
      const uploaded: UploadedAsset[] = [];
      for (const file of files) {
        uploaded.push((await uploadsApi.upload(file, {
          projectId,
          sourceModule,
          category: "document",
        })).data);
      }
      return uploaded;
    },
    onSuccess: async (assets) => {
      const nextIds = [...selectedIds, ...assets.map((asset) => asset.id)].slice(0, maxSelected);
      onSelectionChange(Array.from(new Set(nextIds)));
      setMessage(`${assets.length} document${assets.length === 1 ? "" : "s"} added to the project repository.`);
      setError("");
      await queryClient.invalidateQueries({ queryKey: ["repository-documents", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["uploads", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["document-intelligence-assets", projectId] });
    },
    onError: (reason) => setError(errorMessage(reason, "Document upload failed.")),
  });

  if (!projectId) return null;

  const addFiles = (incoming: File[]) => {
    const valid = incoming.filter((file) => DOCUMENT_EXTENSIONS.has(file.name.split(".").pop()?.toLowerCase() || ""));
    const invalid = incoming.filter((file) => !valid.includes(file));
    const oversized = valid.filter((file) => file.size > DOCUMENT_MAX_UPLOAD_MB * 1024 * 1024);
    const accepted = valid.filter((file) => !oversized.includes(file));
    const messages: string[] = [];
    if (invalid.length) messages.push(`Skipped ${invalid.map((file) => file.name).join(", ")}; unsupported document type.`);
    if (oversized.length) messages.push(`Skipped ${oversized.map((file) => file.name).join(", ")}; documents may be up to ${DOCUMENT_MAX_UPLOAD_MB} MB.`);
    if (messages.length) setError(messages.join(" ")); else setError("");
    if (accepted.length) uploadMutation.mutate(accepted);
  };

  const handleInput = (event: ChangeEvent<HTMLInputElement>) => {
    addFiles(Array.from(event.target.files || []));
    event.target.value = "";
  };
  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragOver(false);
    addFiles(Array.from(event.dataTransfer.files || []));
  };
  const toggle = (id: string) => {
    if (selectedSet.has(id)) onSelectionChange(selectedIds.filter((selectedId) => selectedId !== id));
    else if (selectedIds.length < maxSelected) onSelectionChange([...selectedIds, id]);
  };

  return (
    <Card variant="outlined" sx={{ borderRadius: 3 }}>
      <CardContent sx={{ p: compact ? 1.75 : { xs: 2, md: 2.5 } }}>
        <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" spacing={1.5} alignItems={{ sm: "center" }}>
          <Box>
            <Stack direction="row" spacing={1} alignItems="center">
              <DescriptionOutlinedIcon color="primary" fontSize="small" />
              <Typography variant="subtitle1" fontWeight={800}>{title}</Typography>
              <Chip size="small" variant="outlined" label={`${documents.length} stored`} />
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{description}</Typography>
          </Box>
          <Stack direction="row" spacing={1} alignItems="center">
            {selectedIds.length > 0 && <Chip size="small" color="primary" variant="outlined" label={`${selectedIds.length} selected`} />}
            {onOpenRepository && <Button size="small" startIcon={<FolderOutlinedIcon />} onClick={onOpenRepository}>Open repository</Button>}
            {allowUpload && <Button component="label" size="small" variant="outlined" startIcon={uploadMutation.isPending ? <CircularProgress size={14} /> : <CloudUploadOutlinedIcon />} disabled={uploadMutation.isPending}>
              Add document
              <input hidden multiple type="file" accept={DOCUMENT_ACCEPT} onChange={handleInput} />
            </Button>}
          </Stack>
        </Stack>
        {message && <Alert severity="success" sx={{ mt: 1.5 }} onClose={() => setMessage("")}>{message}</Alert>}
        {error && <Alert severity="error" sx={{ mt: 1.5 }} onClose={() => setError("")}>{error}</Alert>}
        {allowUpload && <Box
          onDragOver={(event) => { event.preventDefault(); setIsDragOver(true); }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDrop}
          sx={{ mt: 1.5, px: 1.25, py: 1, border: "1px dashed", borderColor: isDragOver ? "primary.main" : "divider", borderRadius: 2, bgcolor: isDragOver ? "action.hover" : "transparent" }}
        >
          <Typography variant="caption" color="text.secondary">Drop a document here or use Add document · up to {DOCUMENT_MAX_UPLOAD_MB} MB · stored once in the project repository.</Typography>
        </Box>}
        <Divider sx={{ my: 1.5 }} />
        {documentsLoading ? <LinearDocumentPlaceholder /> : documentsError ? <Alert severity="warning">Stored documents could not be loaded. Retry the page or open the repository.</Alert> : documents.length === 0 ? (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 1 }}>
            <FolderOutlinedIcon color="disabled" fontSize="small" />
            <Typography variant="body2" color="text.secondary">No reusable documents are stored for this project yet.</Typography>
          </Stack>
        ) : (
          <TableContainer sx={{ maxHeight: compact ? 260 : 360 }}>
            <Table size="small" stickyHeader>
              <TableHead><TableRow><TableCell padding="checkbox" /><TableCell>Document</TableCell><TableCell>Size</TableCell><TableCell>Uploaded</TableCell><TableCell>Source</TableCell></TableRow></TableHead>
              <TableBody>
                {documents.map((asset) => {
                  const checked = selectedSet.has(asset.id);
                  const disabled = !checked && selectedIds.length >= maxSelected;
                  return <TableRow key={asset.id} hover selected={checked}>
                    <TableCell padding="checkbox"><Tooltip title={disabled ? `Select up to ${maxSelected} documents` : checked ? "Remove from this run" : "Attach to this run"}><span><Checkbox checked={checked} disabled={disabled} onChange={() => toggle(asset.id)} inputProps={{ "aria-label": `Attach ${asset.filename}` }} /></span></Tooltip></TableCell>
                    <TableCell sx={{ minWidth: 180 }}><Typography variant="body2" fontWeight={700} noWrap>{asset.filename}</Typography><Typography variant="caption" color="text.secondary">{asset.extension.toUpperCase()} · SHA {asset.sha256.slice(0, 10)}…</Typography></TableCell>
                    <TableCell>{formatBytes(asset.size_bytes)}</TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{new Date(asset.created_at).toLocaleString()}</TableCell>
                    <TableCell><Chip size="small" variant="outlined" label={displaySource(asset.source_module)} /></TableCell>
                  </TableRow>;
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </CardContent>
    </Card>
  );
}

function LinearDocumentPlaceholder() {
  return <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 1 }}><CircularProgress size={16} /><Typography variant="body2" color="text.secondary">Checking the project repository…</Typography></Stack>;
}
