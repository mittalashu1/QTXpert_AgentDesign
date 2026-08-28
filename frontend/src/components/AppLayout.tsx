import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { AppBar, Avatar, Box, Chip, Collapse, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Menu, MenuItem, Toolbar, Tooltip, Typography } from "@mui/material";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import ArchitectureOutlinedIcon from "@mui/icons-material/ArchitectureOutlined";
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline";
import AssessmentOutlinedIcon from "@mui/icons-material/AssessmentOutlined";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import StorageOutlinedIcon from "@mui/icons-material/StorageOutlined";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import AccountBalanceWalletOutlinedIcon from "@mui/icons-material/AccountBalanceWalletOutlined";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import DarkModeOutlinedIcon from "@mui/icons-material/DarkModeOutlined";
import LightModeOutlinedIcon from "@mui/icons-material/LightModeOutlined";
import { useAuth } from "@/contexts/AuthContext";
import { useThemeMode } from "@/contexts/ThemeModeContext";
import ProjectSelector from "@/components/ProjectSelector";

const drawerWidth = 248;
const COST_ADMIN_EMAIL = "admin@qtxpert.com";
const navigation = [
  { to: "/", label: "Dashboard", icon: <DashboardOutlinedIcon />, end: true },
  { to: "/autopilot", label: "Autopilot", icon: <AutoAwesomeIcon />, badge: "NEW" },
  { to: "/documents", label: "Document Intelligence", icon: <DescriptionOutlinedIcon />, badge: "AI" },
  { to: "/design", label: "Test design", icon: <ArchitectureOutlinedIcon /> },
  { to: "/execution", label: "Test execution", icon: <PlayCircleOutlineIcon /> },
  { to: "/reports", label: "Test reports", icon: <AssessmentOutlinedIcon /> },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const { mode, toggleMode } = useThemeMode();
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [testDataOpen, setTestDataOpen] = useState(location.pathname.startsWith("/test-data"));
  const canViewCosts = user?.role === "admin" && user.email.trim().toLowerCase() === COST_ADMIN_EMAIL;

  useEffect(() => {
    if (location.pathname.startsWith("/test-data")) setTestDataOpen(true);
  }, [location.pathname]);

  const navSx = {
    borderRadius: 2,
    mb: 0.5,
    "&.active": {
      bgcolor: "primary.main",
      color: "primary.contrastText",
      "& .MuiListItemIcon-root": { color: "inherit" },
    },
  } as const;

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="fixed" elevation={0} sx={{ zIndex: (theme) => theme.zIndex.drawer + 1, borderBottom: "1px solid", borderColor: "divider", bgcolor: "background.paper", color: "text.primary" }}>
        <Toolbar sx={{ gap: 3 }}>
          <Typography variant="h6" sx={{ fontWeight: 800, minWidth: drawerWidth - 40 }}>QTXpert<Box component="span" sx={{ color: "primary.main" }}>AI</Box></Typography>
          <Box sx={{ flex: 1, maxWidth: 440 }}><ProjectSelector topLevel /></Box>
          <Tooltip title={mode === "dark" ? "Use light theme" : "Use dark theme"}><IconButton onClick={toggleMode}>{mode === "dark" ? <LightModeOutlinedIcon /> : <DarkModeOutlinedIcon />}</IconButton></Tooltip>
          <IconButton onClick={(event) => setAnchorEl(event.currentTarget)}><Avatar sx={{ width: 34, height: 34, bgcolor: "primary.main", fontSize: 14 }}>{user?.full_name?.charAt(0).toUpperCase() ?? "U"}</Avatar></IconButton>
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
            {navigation.map((item) => (
              <ListItemButton key={item.to} component={NavLink} to={item.to} end={item.end} sx={navSx}>
                <ListItemIcon sx={{ minWidth: 38, color: "text.secondary" }}>{item.icon}</ListItemIcon>
                <ListItemText primary={item.label} primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
                {item.badge && <Chip label={item.badge} size="small" sx={{ height: 20, fontSize: 10, fontWeight: 800 }} />}
              </ListItemButton>
            ))}
            <ListItemButton onClick={() => setTestDataOpen((open) => !open)} sx={{ borderRadius: 2, mb: 0.5, bgcolor: location.pathname.startsWith("/test-data") ? "action.selected" : undefined }}>
              <ListItemIcon sx={{ minWidth: 38, color: "text.secondary" }}><StorageOutlinedIcon /></ListItemIcon>
              <ListItemText primary="Test Data" primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
              {testDataOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
            </ListItemButton>
            <Collapse in={testDataOpen} timeout="auto" unmountOnExit>
              <List disablePadding>
                <ListItemButton component={NavLink} to="/test-data/uploads" sx={{ ...navSx, pl: 4.6 }}>
                  <ListItemIcon sx={{ minWidth: 34, color: "text.secondary" }}><CloudUploadOutlinedIcon fontSize="small" /></ListItemIcon>
                  <ListItemText primary="Uploads" primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
                </ListItemButton>
              </List>
            </Collapse>
            {canViewCosts && <>
              <Divider sx={{ my: 1.25 }} />
              <ListItemButton component={NavLink} to="/cost-center" sx={navSx}>
                <ListItemIcon sx={{ minWidth: 38, color: "text.secondary" }}><AccountBalanceWalletOutlinedIcon /></ListItemIcon>
                <ListItemText primary="Cost Center" primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
                <Chip label="ADMIN" size="small" sx={{ height: 20, fontSize: 9, fontWeight: 800 }} />
              </ListItemButton>
            </>}
          </List>
        </Box>
      </Drawer>
      <Box component="main" sx={{ ml: `${drawerWidth}px`, p: { xs: 2, md: 4 }, minHeight: "100vh" }}><Toolbar /><Outlet /></Box>
    </Box>
  );
}

