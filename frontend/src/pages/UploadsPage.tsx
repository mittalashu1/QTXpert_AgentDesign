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
import { UploadedAsset } from "@/types/domain";
import { useSelectedProject } from "@/hooks/useSelectedProject";

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function categoryLabel(category: string) {
  return category.replaceAll("_", " ").replace(/\b\w/g, (match) => match.toUpperCase());
}

export default function UploadsPage() {
  const queryClient = useQueryClient();
  const { selectedProjectId, selectedProject } = useSelectedProject();
  const [category, setCategory] = useState("all");
  const [error, setError] = useState("");

  const uploadsQuery = useQuery({
    queryKey: ["uploads", selectedProjectId, category],
    queryFn: () => uploadsApi.list({
      project_id: selectedProjectId,
      ...(category === "all" ? {} : { category }),
    }).then((response) => response.data),
    enabled: Boolean(selectedProjectId),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadsApi.upload(file, {
      projectId: selectedProjectId,
      sourceModule: "test_data",
    }),
    onSuccess: async () => {
      setError("");
      await queryClient.invalidateQueries({ queryKey: ["uploads", selectedProjectId] });
      await queryClient.invalidateQueries({ queryKey: ["document-intelligence-assets", selectedProjectId] });
    },
    onError: (reason: any) => setError(reason?.response?.data?.detail || reason?.message || "Upload failed"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => uploadsApi.remove(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["uploads", selectedProjectId] });
      await queryClient.invalidateQueries({ queryKey: ["document-intelligence-assets", selectedProjectId] });
    },
    onError: (reason: any) => setError(reason?.response?.data?.detail || reason?.message || "Delete failed"),
  });

  const rows = uploadsQuery.data ?? [];
  const summary = useMemo(() => ({
    files: rows.length,
    apk: rows.filter((item) => item.category === "apk").length,
    documents: rows.filter((item) => item.category === "document").length,
    bytes: rows.reduce((total, item) => total + item.size_bytes, 0),
  }), [rows]);

  if (!selectedProjectId) return <Alert severity="info">Create or select a project from the top bar.</Alert>;

  const uploadFiles = (event: ChangeEvent<HTMLInputElement>) => {
    Array.from(event.target.files ?? []).forEach((file) => uploadMutation.mutate(file));
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
    } catch (reason: any) {
      setError(reason?.response?.data?.detail || reason?.message || "Download failed");
    }
  };

  return (
    <Stack spacing={3}>
      <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" gap={2}>
        <Box>
          <Stack direction="row" spacing={1.2} alignItems="center">
            <FolderOutlinedIcon color="primary" />
            <Typography variant="h4" fontWeight={800}>Upload Repository</Typography>
          </Stack>
          <Typography color="text.secondary" sx={{ mt: 0.5 }}>
            Files for <b>{selectedProject?.name || "the active project"}</b>. Other projects have separate repositories.
          </Typography>
        </Box>
        <Button component="label" variant="contained" startIcon={<CloudUploadOutlinedIcon />} sx={{ alignSelf: { xs: "flex-start", md: "center" } }}>
          Add files
          <input hidden multiple type="file" onChange={uploadFiles} />
        </Button>
      </Stack>

      {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
      {(uploadMutation.isPending || uploadsQuery.isLoading) && <LinearProgress />}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        {[
          ["Files", summary.files],
          ["Android APKs", summary.apk],
          ["Documents", summary.documents],
          ["Stored size", formatBytes(summary.bytes)],
        ].map(([label, value]) => (
          <Card key={String(label)} variant="outlined" sx={{ minWidth: 170, flex: 1 }}>
            <CardContent><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h5" fontWeight={800}>{value}</Typography></CardContent>
          </Card>
        ))}
      </Stack>

      <Card variant="outlined">
        <CardContent>
          <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={2} alignItems={{ sm: "center" }}>
            <Typography variant="h6" fontWeight={800}>Project files</Typography>
            <FormControl size="small" sx={{ minWidth: 190 }}>
              <InputLabel>Type</InputLabel>
              <Select value={category} label="Type" onChange={(event) => setCategory(event.target.value)}>
                <MenuItem value="all">All uploads</MenuItem>
                <MenuItem value="apk">Android APKs</MenuItem>
                <MenuItem value="document">Documents</MenuItem>
                <MenuItem value="test_data">Test data</MenuItem>
                <MenuItem value="media">Media</MenuItem>
                <MenuItem value="other">Other</MenuItem>
              </Select>
            </FormControl>
          </Stack>

          {uploadsQuery.isError && <Alert severity="error" sx={{ mt: 2 }}>Unable to load this project's repository.</Alert>}
          {!uploadsQuery.isLoading && rows.length === 0 ? (
            <Box sx={{ py: 7, textAlign: "center" }}>
              <FolderOutlinedIcon sx={{ fontSize: 48, color: "text.disabled", mb: 1 }} />
              <Typography fontWeight={700}>No files in this project yet</Typography>
              <Typography variant="body2" color="text.secondary">Files added from Document Intelligence, Test Design, Test Data and Autopilot will appear here.</Typography>
            </Box>
          ) : (
            <TableContainer sx={{ mt: 2 }}>
              <Table size="small">
                <TableHead><TableRow><TableCell>File</TableCell><TableCell>Type</TableCell><TableCell>Source</TableCell><TableCell>Size</TableCell><TableCell>Uploaded</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
                <TableBody>
                  {rows.map((asset) => (
                    <TableRow key={asset.id} hover>
                      <TableCell sx={{ maxWidth: 370 }}><Typography variant="body2" fontWeight={700} noWrap>{asset.filename}</Typography><Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace" }}>{asset.sha256.slice(0, 12)}…</Typography></TableCell>
                      <TableCell><Chip size="small" variant="outlined" label={categoryLabel(asset.category)} /></TableCell>
                      <TableCell>{categoryLabel(asset.source_module)}</TableCell>
                      <TableCell>{formatBytes(asset.size_bytes)}</TableCell>
                      <TableCell>{new Date(asset.created_at).toLocaleString()}</TableCell>
                      <TableCell align="right"><Button size="small" startIcon={<DownloadOutlinedIcon />} onClick={() => download(asset)}>Download</Button><Button size="small" color="error" startIcon={<DeleteOutlineOutlinedIcon />} disabled={deleteMutation.isPending} onClick={() => { if (window.confirm(`Delete ${asset.filename} from ${selectedProject?.name || "this project"}?`)) deleteMutation.mutate(asset.id); }}>Delete</Button></TableCell>
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
