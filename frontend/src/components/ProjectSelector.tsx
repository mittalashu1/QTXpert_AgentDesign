import { useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { useCreateProject } from "@/hooks/useProjects";
import { useSelectedProject } from "@/hooks/useSelectedProject";

export default function ProjectSelector({ topLevel = false }: { topLevel?: boolean }) {
  const { projects, selectedProjectId, selectProject } = useSelectedProject();
  const createProject = useCreateProject();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  // Project selection is a workspace-level control. Legacy page-level
  // ProjectSelector instances intentionally render nothing.
  if (!topLevel) return null;

  const handleCreate = async () => {
    if (!name.trim()) return;
    const project = await createProject.mutateAsync({ name, description });
    selectProject(project.id);
  };

  const dialog = (
    <CreateProjectDialog
      open={dialogOpen}
      name={name}
      description={description}
      busy={createProject.isPending}
      onNameChange={setName}
      onDescriptionChange={setDescription}
      onClose={() => setDialogOpen(false)}
      onCreate={handleCreate}
    />
  );

  if (projects.length === 0) {
    return (
      <Stack direction="row" spacing={2} alignItems="center">
        <Typography color="text.secondary">No projects yet.</Typography>
        <Button startIcon={<AddIcon />} variant="outlined" onClick={() => setDialogOpen(true)}>
          Create project
        </Button>
        {dialog}
      </Stack>
    );
  }

  return (
    <Stack direction="row" spacing={1.5} alignItems="center">
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
      <Button size="small" startIcon={<AddIcon />} onClick={() => setDialogOpen(true)}>
        New project
      </Button>
      {dialog}
    </Stack>
  );
}

function CreateProjectDialog({
  open,
  name,
  description,
  busy,
  onNameChange,
  onDescriptionChange,
  onClose,
  onCreate,
}: {
  open: boolean;
  name: string;
  description: string;
  busy: boolean;
  onNameChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onClose: () => void;
  onCreate: () => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>New project</DialogTitle>
      <DialogContent>
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          <TextField label="Project name" value={name} onChange={(event) => onNameChange(event.target.value)} autoFocus fullWidth />
          <TextField label="Description (optional)" value={description} onChange={(event) => onDescriptionChange(event.target.value)} multiline minRows={2} fullWidth />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={onCreate} disabled={!name.trim() || busy}>
          {busy ? "Creating…" : "Create"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
