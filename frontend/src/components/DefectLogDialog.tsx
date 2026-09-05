import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import BugReportOutlinedIcon from "@mui/icons-material/BugReportOutlined";

export type DefectSubmission = {
  title: string;
  description: string;
  severity: "blocker" | "critical" | "major" | "minor" | "trivial";
  integration_provider: "local" | "jira";
};

type DefectLogDialogProps = {
  open: boolean;
  testKey: string;
  testTitle: string;
  sourceLabel: string;
  failure: string;
  defaultDescription: string;
  evidenceLabels?: string[];
  busy?: boolean;
  error?: string;
  onClose: () => void;
  onSubmit: (payload: DefectSubmission) => void;
};

/**
 * Local-first defect capture shared by Test Reports and Autopilot.
 *
 * The dialog makes the source failure and evidence visible before the user
 * saves. Choosing Jira creates an evidence-linked local draft only; a future
 * authenticated connector can submit the same normalized payload.
 */
export default function DefectLogDialog({
  open,
  testKey,
  testTitle,
  sourceLabel,
  failure,
  defaultDescription,
  evidenceLabels = [],
  busy = false,
  error = "",
  onClose,
  onSubmit,
}: DefectLogDialogProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState<DefectSubmission["severity"]>("major");
  const [integrationProvider, setIntegrationProvider] = useState<DefectSubmission["integration_provider"]>("local");

  useEffect(() => {
    if (!open) return;
    setTitle(testTitle ? `${testKey}: ${testTitle}` : testKey);
    setDescription(defaultDescription);
    setSeverity("major");
    setIntegrationProvider("local");
  }, [defaultDescription, open, testKey, testTitle]);

  const submit = () => {
    if (!title.trim() || !description.trim()) return;
    onSubmit({
      title: title.trim(),
      description: description.trim(),
      severity,
      integration_provider: integrationProvider,
    });
  };

  return (
    <Dialog open={open} onClose={() => !busy && onClose()} fullWidth maxWidth="sm">
      <DialogTitle>
        <Stack direction="row" spacing={1} alignItems="center">
          <BugReportOutlinedIcon color="error" />
          <span>Log defect</span>
        </Stack>
      </DialogTitle>
      <DialogContent dividers>
        <Stack spacing={1.5}>
          <Alert severity="info">
            This defect is pre-populated from the failed {sourceLabel}. Execution metadata and opaque evidence asset references will be retained; secrets and raw evidence bytes are never copied into the issue record.
          </Alert>
          <BoxlessSummary label="Test" value={`${testKey}${testTitle ? ` · ${testTitle}` : ""}`} />
          <BoxlessSummary label="Observed failure" value={failure || "Failure details were not returned by the runner."} />
          {evidenceLabels.length > 0 && <BoxlessSummary label="Evidence to attach" value={evidenceLabels.join(" · ")} />}
          <TextField autoFocus fullWidth label="Defect title" value={title} onChange={(event) => setTitle(event.target.value)} inputProps={{ maxLength: 500 }} />
          <TextField fullWidth multiline minRows={5} label="Description" value={description} onChange={(event) => setDescription(event.target.value)} inputProps={{ maxLength: 10000 }} helperText={`${description.length.toLocaleString()} / 10,000 characters`} />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel id="defect-severity-label">Severity</InputLabel>
              <Select labelId="defect-severity-label" label="Severity" value={severity} onChange={(event) => setSeverity(event.target.value as DefectSubmission["severity"])}>
                {(["blocker", "critical", "major", "minor", "trivial"] as const).map((value) => <MenuItem key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel id="defect-destination-label">Destination</InputLabel>
              <Select labelId="defect-destination-label" label="Destination" value={integrationProvider} onChange={(event) => setIntegrationProvider(event.target.value as DefectSubmission["integration_provider"])}>
                <MenuItem value="local">QTXpert defect log</MenuItem>
                <MenuItem value="jira">Jira draft (integration pending)</MenuItem>
              </Select>
            </FormControl>
          </Stack>
          {integrationProvider === "jira" && <Alert severity="warning">Jira is a draft boundary in this release. QTXpert will save the defect locally with a ready-to-submit issue payload; it will not create a remote issue until Jira OAuth/write access is configured.</Alert>}
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" color="error" onClick={submit} disabled={busy || !title.trim() || !description.trim()}>{busy ? "Saving…" : "Save defect"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function BoxlessSummary({ label, value }: { label: string; value: string }) {
  return <Stack spacing={0.25}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="body2" sx={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{value}</Typography></Stack>;
}
