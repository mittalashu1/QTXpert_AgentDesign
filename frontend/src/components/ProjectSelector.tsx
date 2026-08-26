import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import { useAuth } from "@/contexts/AuthContext";
import { useCreateProject, useUpdateProject } from "@/hooks/useProjects";
import { useSelectedProject } from "@/hooks/useSelectedProject";

export default function ProjectSelector({ topLevel = false }: { topLevel?: boolean }) {
  const { user } = useAuth();
  const { projects, selectedProjectId, selectedProject, selectProject } = useSelectedProject();
  const createProject = useCreateProject();
  const updateProject = useUpdateProject();
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const isAdmin = user?.role === "admin";

  useEffect(() => {
    if (!selectedProject) return;
    setEditName(selectedProject.name);
    setEditDescription(selectedProject.description ?? "");
  }, [selectedProject]);

  if (!topLevel) return null;

  const handleCreate = async () => {
    if (!name.trim()) return;
    const project = await createProject.mutateAsync({ name: name.trim(), description });
    selectProject(project.id);
  };

  const handleUpdate = async () => {
    if (!selectedProject || !editName.trim()) return;
    await updateProject.mutateAsync({
      id: selectedProject.id,
      name: editName.trim(),
      description: editDescription,
    });
    setEditOpen(false);
  };

  const createDialog = (
    <ProjectDialog
      open={createOpen}
      title="New project"
      confirmLabel="Create"
      busyLabel="Creating…"
      name={name}
      description={description}
      busy={createProject.isPending}
      onNameChange={setName}
      onDescriptionChange={setDescription}
      onClose={() => setCreateOpen(false)}
      onConfirm={handleCreate}
    />
  );

  const editDialog = selectedProject && isAdmin ? (
    <ProjectDialog
      open={editOpen}
      title="Edit project"
      confirmLabel="Save"
      busyLabel="Saving…"
      name={editName}
      description={editDescription}
      busy={updateProject.isPending}
      onNameChange={setEditName}
      onDescriptionChange={setEditDescription}
      onClose={() => setEditOpen(false)}
      onConfirm={handleUpdate}
    />
  ) : null;

  if (projects.length === 0) {
    return (
      <Stack direction="row" spacing={2} alignItems="center">
        <Typography color="text.secondary">No projects yet.</Typography>
        <Button startIcon={<AddIcon />} variant="outlined" onClick={() => setCreateOpen(true)}>
          Create project
        </Button>
        {createDialog}
      </Stack>
    );
  }

  return (
    <Stack direction="row" spacing={1} alignItems="center">
      <TextField
        select
        size="small"
        label="Project"
        value={selectedProjectId}
        onChange={(event) => selectProject(event.target.value)}
        sx={{ minWidth: 260 }}
      >
        {projects.map((project) => (
          <MenuItem key={project.id} value={project.id}>
            {project.name}
          </MenuItem>
        ))}
      </TextField>
      {isAdmin && selectedProject && (
        <Tooltip title="Edit project name">
          <IconButton size="small" onClick={() => setEditOpen(true)} aria-label="Edit project">
            <EditOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
      <Button size="small" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
        New project
      </Button>
      {createDialog}
      {editDialog}
    </Stack>
  );
}

function ProjectDialog({
  open,
  title,
  confirmLabel,
  busyLabel,
  name,
  description,
  busy,
  onNameChange,
  onDescriptionChange,
  onClose,
  onConfirm,
}: {
  open: boolean;
  title: string;
  confirmLabel: string;
  busyLabel: string;
  name: string;
  description: string;
  busy: boolean;
  onNameChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onClose: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          <TextField label="Project name" value={name} onChange={(event) => onNameChange(event.target.value)} autoFocus fullWidth />
          <TextField label="Description (optional)" value={description} onChange={(event) => onDescriptionChange(event.target.value)} multiline minRows={2} fullWidth />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={onConfirm} disabled={!name.trim() || busy}>
          {busy ? busyLabel : confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
