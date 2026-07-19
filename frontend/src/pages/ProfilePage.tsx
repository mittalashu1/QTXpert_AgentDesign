import { Avatar, Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { useAuth } from "@/contexts/AuthContext";

export default function ProfilePage() {
  const { user } = useAuth();
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
    </Stack>
  );
}
