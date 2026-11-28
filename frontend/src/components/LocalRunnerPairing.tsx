import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography,
} from "@mui/material";
import { localRunnersApi } from "@/services/api";
import { API_BASE_URL } from "@/services/apiClient";

const RUNNER_COMMAND = String.raw`.\tools\local_runner\.venv\Scripts\python.exe .\tools\local_runner\agent.py`;
export const LOCAL_RUNNER_START_COMMAND = `${RUNNER_COMMAND} run`;

export default function LocalRunnerPairing({ projectId, projectName }: { projectId: string; projectName?: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  const enrollment = useMutation({
    mutationFn: () => localRunnersApi.createEnrollment(projectId).then((response) => response.data),
    gcTime: 0,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["paired-runners", projectId] });
    },
  });
  const apiUrl = new URL(API_BASE_URL, window.location.origin).href.replace(/\/$/, "");
  const details = enrollment.data;
  const command = details ? `${RUNNER_COMMAND} pair --api-url "${apiUrl}" --token "${details.enrollment_token}"` : "";

  const close = () => {
    enrollment.reset();
    setCopyStatus("");
    setOpen(false);
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopyStatus("Pairing command copied.");
    } catch {
      setCopyStatus("Select and copy the command from the field.");
    }
  };

  return <>
    <Button size="small" variant="outlined" onClick={() => setOpen(true)}>Pair this laptop</Button>
    <Dialog open={open} onClose={close} fullWidth maxWidth="sm">
      <DialogTitle>Pair this laptop with {projectName || "the selected project"}</DialogTitle>
      <DialogContent>
        <Stack spacing={1.5}>
          <Typography variant="body2">
            A Windows runner lets QTXpert use this laptop’s USB phone or emulator for Android tests. Connect the device, allow USB debugging and start Appium on the laptop.
          </Typography>
          {details ? <>
            <Typography variant="body2">
              Run this one-time command from the QTXpert repository in PowerShell within {Math.floor(details.expires_in_seconds / 60)} minutes.
            </Typography>
            <TextField
              label="PowerShell pairing command"
              value={command}
              multiline
              fullWidth
              slotProps={{ input: { readOnly: true } }}
            />
            <Button size="small" onClick={() => void copy()} sx={{ alignSelf: "flex-start" }}>Copy pairing command</Button>
            {copyStatus && <Typography role="status" variant="body2">{copyStatus}</Typography>}
            <Typography variant="body2">
              Then run <code>{LOCAL_RUNNER_START_COMMAND}</code> and refresh the Android device list.
            </Typography>
          </> : enrollment.isError && <Alert severity="error">Could not create a pairing command. Try again.</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>Close</Button>
        {!command && <Button variant="contained" disabled={enrollment.isPending} onClick={() => enrollment.mutate()}>
          {enrollment.isPending ? "Creating…" : "Create pairing command"}
        </Button>}
      </DialogActions>
    </Dialog>
  </>;
}
