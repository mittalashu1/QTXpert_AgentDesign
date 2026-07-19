import { Card, CardActionArea, CardContent, Stack, Typography } from "@mui/material";
import { useNavigate } from "react-router-dom";

export default function SettingsPage() {
  const navigate = useNavigate();

  return (
    <Stack spacing={3}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>
        Settings
      </Typography>
      <Card sx={{ borderRadius: 3, maxWidth: 480 }}>
        <CardActionArea onClick={() => navigate("/settings/api-configuration")}>
          <CardContent>
            <Typography variant="h6">API Configuration</Typography>
            <Typography variant="body2" color="text.secondary">
              Choose the active LLM provider and model, and test connectivity.
            </Typography>
          </CardContent>
        </CardActionArea>
      </Card>
    </Stack>
  );
}
