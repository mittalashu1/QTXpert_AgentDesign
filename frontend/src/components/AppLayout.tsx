import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { AppBar, Avatar, Box, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Menu, MenuItem, Toolbar, Tooltip, Typography } from "@mui/material";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import ArchitectureOutlinedIcon from "@mui/icons-material/ArchitectureOutlined";
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline";
import AssessmentOutlinedIcon from "@mui/icons-material/AssessmentOutlined";
import DarkModeOutlinedIcon from "@mui/icons-material/DarkModeOutlined";
import LightModeOutlinedIcon from "@mui/icons-material/LightModeOutlined";
import { useAuth } from "@/contexts/AuthContext";
import { useThemeMode } from "@/contexts/ThemeModeContext";
import ProjectSelector from "@/components/ProjectSelector";

const drawerWidth = 248;
const navigation = [
  { to: "/", label: "Dashboard", icon: <DashboardOutlinedIcon />, end: true },
  { to: "/documents", label: "Document analysis", icon: <DescriptionOutlinedIcon /> },
  { to: "/design", label: "Test design", icon: <ArchitectureOutlinedIcon /> },
  { to: "/execution", label: "Test execution", icon: <PlayCircleOutlineIcon /> },
  { to: "/reports", label: "Test reports", icon: <AssessmentOutlinedIcon /> },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { mode, toggleMode } = useThemeMode();
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="fixed" elevation={0} sx={{ zIndex: (t) => t.zIndex.drawer + 1, borderBottom: "1px solid", borderColor: "divider", bgcolor: "background.paper", color: "text.primary" }}>
        <Toolbar sx={{ gap: 3 }}>
          <Typography variant="h6" sx={{ fontWeight: 800, minWidth: drawerWidth - 40 }}>QTXpert<Box component="span" sx={{ color: "primary.main" }}>AI</Box></Typography>
          <Box sx={{ flex: 1, maxWidth: 420 }}><ProjectSelector /></Box>
          <Tooltip title={mode === "dark" ? "Use light theme" : "Use dark theme"}><IconButton onClick={toggleMode}>{mode === "dark" ? <LightModeOutlinedIcon /> : <DarkModeOutlinedIcon />}</IconButton></Tooltip>
          <IconButton onClick={(e) => setAnchorEl(e.currentTarget)}><Avatar sx={{ width: 34, height: 34, bgcolor: "primary.main", fontSize: 14 }}>{user?.full_name?.charAt(0).toUpperCase() ?? "U"}</Avatar></IconButton>
          <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
            <MenuItem onClick={() => { setAnchorEl(null); navigate("/profile"); }}>Profile</MenuItem>
            {user?.role === "admin" && <MenuItem onClick={() => { setAnchorEl(null); navigate("/administration/users"); }}>Administration</MenuItem>}
            <Divider />
            <MenuItem onClick={() => { setAnchorEl(null); logout(); navigate("/login"); }}>Sign out</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Drawer variant="permanent" sx={{ width: drawerWidth, flexShrink: 0, "& .MuiDrawer-paper": { width: drawerWidth, boxSizing: "border-box", borderRightColor: "divider", bgcolor: "background.paper" } }}>
        <Toolbar />
        <Box sx={{ px: 1.5, py: 2 }}>
          <Typography variant="caption" color="text.secondary" sx={{ px: 1.5, fontWeight: 700, letterSpacing: ".12em" }}>QUALITY WORKSPACE</Typography>
          <List sx={{ mt: 1 }}>
            {navigation.map((item) => <ListItemButton key={item.to} component={NavLink} to={item.to} end={item.end} sx={{ borderRadius: 2, mb: .5, "&.active": { bgcolor: "primary.main", color: "primary.contrastText", "& .MuiListItemIcon-root": { color: "inherit" } } }}><ListItemIcon sx={{ minWidth: 38, color: "text.secondary" }}>{item.icon}</ListItemIcon><ListItemText primary={item.label} primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} /></ListItemButton>)}
          </List>
        </Box>
        <Box sx={{ mt: "auto", p: 2 }}><Box sx={{ p: 1.5, borderRadius: 2, bgcolor: "action.hover" }}><Typography variant="caption" color="primary.main" sx={{ fontWeight: 700 }}>M4 FOUNDATION</Typography><Typography variant="body2" sx={{ mt: .5, fontWeight: 600 }}>Playwright-first execution</Typography><Typography variant="caption" color="text.secondary">Unsupported natural-language steps are blocked, never reported as false passes.</Typography></Box></Box>
      </Drawer>
      <Box component="main" sx={{ ml: `${drawerWidth}px`, p: { xs: 2, md: 4 }, minHeight: "100vh" }}><Toolbar /><Outlet /></Box>
    </Box>
  );
}

