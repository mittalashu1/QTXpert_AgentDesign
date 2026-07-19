import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  LinearProgress,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import { requirementsApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import ProjectSelector from "@/components/ProjectSelector";

export default function RequirementUploadPage() {
  const { selectedProjectId } = useSelectedProject();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState(0);
  const [isDragOver, setIsDragOver] = useState(false);
  const [promptTitle, setPromptTitle] = useState("");
  const [promptContent, setPromptContent] = useState("");

  const { data: requirements } = useQuery({
    queryKey: ["requirements", selectedProjectId],
    queryFn: () => requirementsApi.listForProject(selectedProjectId).then((res) => res.data),
    enabled: Boolean(selectedProjectId),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => requirementsApi.upload(selectedProjectId, file),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["requirements", selectedProjectId] }),
  });

  const promptMutation = useMutation({
    mutationFn: () =>
      requirementsApi.submitDirectPrompt(selectedProjectId, promptTitle, promptContent),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["requirements", selectedProjectId] });
      setPromptTitle("");
      setPromptContent("");
    },
  });

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || !selectedProjectId) return;
      Array.from(files).forEach((file) => uploadMutation.mutate(file));
    },
    [selectedProjectId, uploadMutation]
  );

  return (
    <Stack spacing={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Requirement Upload
        </Typography>
        <ProjectSelector />
      </Stack>

      {!selectedProjectId && (
        <Alert severity="info">Select or create a project above before uploading requirements.</Alert>
      )}

      <Card sx={{ borderRadius: 3 }}>
        <CardContent>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
            <Tab label="Upload BRD / Jira export" />
            <Tab label="Direct prompt" />
          </Tabs>

          {tab === 0 && (
            <Box
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragOver(true);
              }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDragOver(false);
                handleFiles(e.dataTransfer.files);
              }}
              sx={{
                border: "2px dashed",
                borderColor: isDragOver ? "primary.main" : "divider",
                borderRadius: 3,
                py: 6,
                textAlign: "center",
                bgcolor: isDragOver ? "action.hover" : "transparent",
                transition: "all 0.15s ease",
              }}
            >
              <UploadFileOutlinedIcon sx={{ fontSize: 40, color: "text.secondary", mb: 1 }} />
              <Typography sx={{ mb: 1 }}>Drag and drop files here, or</Typography>
              <Button variant="contained" component="label" disabled={!selectedProjectId}>
                Browse files
                <input
                  type="file"
                  hidden
                  multiple
                  accept=".pdf,.docx,.txt,.md,.json,.csv"
                  onChange={(e) => handleFiles(e.target.files)}
                />
              </Button>
              <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 1 }}>
                Supported: PDF, DOCX, TXT, Markdown, Jira JSON/CSV export
              </Typography>
              {uploadMutation.isPending && <LinearProgress sx={{ mt: 2 }} />}
              {uploadMutation.isError && (
                <Alert severity="error" sx={{ mt: 2 }}>
                  Upload failed. Please check the file type and try again.
                </Alert>
              )}
            </Box>
          )}

          {tab === 1 && (
            <Stack spacing={2}>
              <TextField
                label="Title"
                value={promptTitle}
                onChange={(e) => setPromptTitle(e.target.value)}
                fullWidth
              />
              <TextField
                label="Requirement text (Markdown supported)"
                value={promptContent}
                onChange={(e) => setPromptContent(e.target.value)}
                multiline
                minRows={10}
                fullWidth
              />
              <Button
                variant="contained"
                disabled={!selectedProjectId || !promptTitle || !promptContent}
                onClick={() => promptMutation.mutate()}
                sx={{ alignSelf: "flex-start" }}
              >
                Submit requirement
              </Button>
            </Stack>
          )}
        </CardContent>
      </Card>

      <Card sx={{ borderRadius: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Project requirements
          </Typography>
          {!requirements || requirements.length === 0 ? (
            <Typography color="text.secondary">No requirements added yet.</Typography>
          ) : (
            <Stack spacing={1.5}>
              {requirements.map((req) => (
                <Box
                  key={req.id}
                  sx={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    borderBottom: "1px solid",
                    borderColor: "divider",
                    pb: 1.5,
                  }}
                >
                  <Typography variant="body2">{req.title}</Typography>
                  <Chip size="small" label={req.source.replace("_", " ")} />
                </Box>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>
    </Stack>
  );
}
