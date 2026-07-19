import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  CardContent,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { settingsApi } from "@/services/api";

const PROVIDERS = [
  { value: "azure_openai", label: "Azure OpenAI (default)" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic Claude" },
  { value: "gemini", label: "Google Gemini" },
  { value: "bedrock", label: "AWS Bedrock" },
];

export default function ApiConfigurationPage() {
  const [provider, setProvider] = useState("azure_openai");
  const [model, setModel] = useState("gpt-4o");
  const [name, setName] = useState("Default configuration");

  const testMutation = useMutation({
    mutationFn: () => settingsApi.testProvider(provider).then((res) => res.data),
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      settingsApi.createConfiguration({
        name,
        llm_provider: provider,
        llm_model: model,
        is_active: true,
      }),
  });

  return (
    <Stack spacing={3}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>
        API Configuration
      </Typography>

      <Card sx={{ borderRadius: 3, maxWidth: 560 }}>
        <CardContent>
          <Stack spacing={2}>
            <TextField label="Configuration name" value={name} onChange={(e) => setName(e.target.value)} />
            <TextField select label="LLM Provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
              {PROVIDERS.map((p) => (
                <MenuItem key={p.value} value={p.value}>
                  {p.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField label="Model / deployment name" value={model} onChange={(e) => setModel(e.target.value)} />

            <Stack direction="row" spacing={2}>
              <Button variant="outlined" onClick={() => testMutation.mutate()}>
                Test connection
              </Button>
              <Button variant="contained" onClick={() => saveMutation.mutate()}>
                Save configuration
              </Button>
            </Stack>

            {testMutation.data && (
              <Alert severity={testMutation.data.healthy ? "success" : "error"}>
                {testMutation.data.healthy
                  ? `${provider} is reachable and responding.`
                  : testMutation.data.detail || `${provider} could not be reached.`}
              </Alert>
            )}
            {saveMutation.isSuccess && (
              <Alert severity="success">Configuration saved.</Alert>
            )}
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  );
}
