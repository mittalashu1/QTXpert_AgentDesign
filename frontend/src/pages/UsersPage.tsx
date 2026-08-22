import { useEffect, useState } from "react";
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  MenuItem, Stack, TextField, Typography,
} from "@mui/material";
import { usersApi } from "@/services/api";
import { User, UserRole } from "@/types/domain";
import { useAuth } from "@/contexts/AuthContext";

const roles: UserRole[] = ["admin", "qa_lead", "qa_engineer", "business_analyst", "automation_engineer", "viewer"];
const blank = { email: "", full_name: "", password: "", role: "qa_engineer" as UserRole };

export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [form, setForm] = useState(blank);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [resetting, setResetting] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState("");

  const load = () => usersApi.list().then((r) => setUsers(r.data)).catch(() => setError("Unable to load users."));
  useEffect(() => { load(); }, []);
  const message = (e: unknown) => (e as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Request failed.";

  const save = async () => {
    try {
      if (editing) await usersApi.update(editing.id, { full_name: form.full_name, role: form.role });
      else await usersApi.create(form);
      setOpen(false); setEditing(null); setForm(blank); setError(""); load();
    } catch (e) { setError(message(e)); }
  };
  const toggle = async (target: User) => {
    try { await usersApi.update(target.id, { is_active: !target.is_active }); setError(""); load(); }
    catch (e) { setError(message(e)); }
  };
  const reset = async () => {
    if (!resetting) return;
    try { await usersApi.resetPassword(resetting.id, newPassword); setResetting(null); setNewPassword(""); setError(""); }
    catch (e) { setError(message(e)); }
  };
  const openEdit = (target: User) => { setEditing(target); setForm({ email: target.email, full_name: target.full_name, password: "", role: target.role }); setOpen(true); };

  return <Stack spacing={3}>
    <Box display="flex" justifyContent="space-between" alignItems="center"><Typography variant="h5" fontWeight={700}>Administration · Users</Typography><Button variant="contained" onClick={() => { setEditing(null); setForm(blank); setOpen(true); }}>Add user</Button></Box>
    {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
    <Stack spacing={1}>
      {users.map((target) => <Box key={target.id} sx={{ p: 2, border: "1px solid", borderColor: "divider", borderRadius: 2, display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
        <Box sx={{ flexGrow: 1 }}><Typography fontWeight={600}>{target.full_name}</Typography><Typography variant="body2" color="text.secondary">{target.email}</Typography></Box>
        <Chip size="small" label={target.role.replaceAll("_", " ")} /><Chip size="small" color={target.is_active ? "success" : "default"} label={target.is_active ? "Active" : "Inactive"} />
        <Button size="small" onClick={() => openEdit(target)}>Edit</Button><Button size="small" onClick={() => setResetting(target)}>Reset password</Button>
        <Button size="small" color={target.is_active ? "warning" : "success"} disabled={target.id === currentUser?.id} onClick={() => toggle(target)}>{target.is_active ? "Deactivate" : "Activate"}</Button>
      </Box>)}
    </Stack>
    <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm"><DialogTitle>{editing ? "Edit user" : "Add user"}</DialogTitle><DialogContent><Stack spacing={2} sx={{ mt: 1 }}>
      <TextField label="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
      <TextField label="Email" type="email" disabled={Boolean(editing)} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      {!editing && <TextField label="Temporary password" type="password" helperText="At least 12 characters" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />}
      <TextField select label="Role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as UserRole })}>{roles.map((role) => <MenuItem key={role} value={role}>{role.replaceAll("_", " ")}</MenuItem>)}</TextField>
    </Stack></DialogContent><DialogActions><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="contained" onClick={save}>{editing ? "Save" : "Create"}</Button></DialogActions></Dialog>
    <Dialog open={Boolean(resetting)} onClose={() => setResetting(null)}><DialogTitle>Reset password</DialogTitle><DialogContent><TextField autoFocus fullWidth sx={{ mt: 1 }} label="New temporary password" type="password" helperText="At least 12 characters" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} /></DialogContent><DialogActions><Button onClick={() => setResetting(null)}>Cancel</Button><Button variant="contained" onClick={reset}>Reset password</Button></DialogActions></Dialog>
  </Stack>;
}
