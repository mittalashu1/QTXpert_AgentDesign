import { useState } from "react";
import { Alert, Avatar, Button, Card, CardContent, Chip, Stack, TextField, Typography } from "@mui/material";
import { useAuth } from "@/contexts/AuthContext";
import { authApi } from "@/services/api";

export default function ProfilePage() {
  const { user } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState("");
  if (!user) return null;

  return (
    <Stack spacing={3}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>
        Profile
      </Typography>
      <Card sx={{ borderRadius: 3, maxWidth: 480 }}>
        <CardContent>
          <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
            <Avatar sx={{ width: 56, height: 56, bgcolor: "primary.main" }}>
              {user.full_name.charAt(0).toUpperCase()}
            </Avatar>
            <div>
              <Typography variant="h6">{user.full_name}</Typography>
              <Typography variant="body2" color="text.secondary">
                {user.email}
              </Typography>
            </div>
          </Stack>
          <Chip label={user.role.replace("_", " ")} />
        </CardContent>
      </Card>
      <Card sx={{ borderRadius: 3, maxWidth: 480 }}>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>Change password</Typography>
          <Stack spacing={2}>
            {message && <Alert severity={message.startsWith("Password changed") ? "success" : "error"}>{message}</Alert>}
            <TextField label="Current password" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
            <TextField label="New password" type="password" helperText="At least 12 characters" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            <Button variant="contained" onClick={async () => {
              try { await authApi.changePassword(currentPassword, newPassword); setCurrentPassword(""); setNewPassword(""); setMessage("Password changed. Please sign in again."); }
              catch (e) { setMessage((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Unable to change password."); }
            }}>Change password</Button>
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  );
}
