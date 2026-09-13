import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { AppBar, Avatar, Box, Chip, Collapse, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Menu, MenuItem, Toolbar, Tooltip, Typography, useMediaQuery, useTheme } from "@mui/material";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import ArchitectureOutlinedIcon from "@mui/icons-material/ArchitectureOutlined";
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline";
import AssessmentOutlinedIcon from "@mui/icons-material/AssessmentOutlined";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import StorageOutlinedIcon from "@mui/icons-material/StorageOutlined";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import AccountBalanceWalletOutlinedIcon from "@mui/icons-material/AccountBalanceWalletOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import DarkModeOutlinedIcon from "@mui/icons-material/DarkModeOutlined";
import LightModeOutlinedIcon from "@mui/icons-material/LightModeOutlined";
import { useAuth } from "@/contexts/AuthContext";
import { useThemeMode } from "@/contexts/ThemeModeContext";
import ProjectSelector from "@/components/ProjectSelector";

const drawerWidth = 224;
const compactDrawerWidth = 60;
const COST_ADMIN_EMAIL = "admin@qtxpert.com";
const navigation = [
  { to: "/", label: "Dashboard", icon: <DashboardOutlinedIcon />, end: true },
  { to: "/autopilot", label: "Autopilot", icon: <AutoAwesomeIcon />, badge: "NEW" },
  { to: "/documents", label: "Document Intelligence", icon: <DescriptionOutlinedIcon />, badge: "AI" },
  { to: "/design", label: "Test design", icon: <ArchitectureOutlinedIcon /> },
  { to: "/execution", label: "Test execution", icon: <PlayCircleOutlineIcon /> },
  { to: "/reports", label: "Test reports", icon: <AssessmentOutlinedIcon /> },
  { to: "/settings", label: "Settings", icon: <SettingsOutlinedIcon /> },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const { mode, toggleMode } = useThemeMode();
  const theme = useTheme();
  const wideViewport = useMediaQuery(theme.breakpoints.up("md"));
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [navHovered, setNavHovered] = useState(false);
  const [testDataOpen, setTestDataOpen] = useState(location.pathname.startsWith("/test-data"));
  const canViewCosts = user?.role === "admin" && user.email.trim().toLowerCase() === COST_ADMIN_EMAIL;
  // The desktop shell keeps a quiet icon rail and reveals the full navigation
  // on hover/focus. This preserves room for dense test lists while keeping all
  // destinations one gesture away.
  const navExpanded = !wideViewport || navHovered;
  const drawerRootWidth = wideViewport ? compactDrawerWidth : drawerWidth;
  const drawerPaperWidth = navExpanded ? drawerWidth : compactDrawerWidth;

  useEffect(() => {
    if (location.pathname.startsWith("/test-data")) setTestDataOpen(true);
  }, [location.pathname]);

  const navSx = {
    borderRadius: 1.5,
    mb: 0.5,
    position: "relative",
    transition: "background-color 160ms ease, color 160ms ease, transform 160ms ease",
    "&:hover": {
      bgcolor: mode === "dark" ? "rgba(165, 173, 255, .12)" : "rgba(109, 99, 242, .08)",
    },
    "&.active": {
      bgcolor: mode === "dark" ? "rgba(165, 173, 255, .14)" : "rgba(109, 99, 242, .10)",
      color: "primary.main",
      borderLeft: "3px solid",
      borderColor: "primary.main",
      boxShadow: mode === "dark"
        ? "0 8px 20px rgba(109, 99, 242, .10)"
        : "0 8px 20px rgba(109, 99, 242, .08)",
      "& .MuiListItemIcon-root": { color: "inherit" },
    },
  } as const;

  return (
    <Box className="qtxpert-workspace-shell" sx={{ minHeight: "100vh", bgcolor: "transparent" }}>
      <AppBar
        position="fixed"
        elevation={0}
        sx={{
          zIndex: (theme) => theme.zIndex.drawer + 1,
          borderBottom: "1px solid",
          borderColor: "divider",
          backgroundColor: (theme) => theme.palette.mode === "dark" ? "rgba(12, 13, 26, .72)" : "rgba(255, 255, 255, .76)",
          color: "text.primary",
          backdropFilter: "blur(18px) saturate(140%)",
          WebkitBackdropFilter: "blur(18px) saturate(140%)",
        }}
      >
        <Toolbar sx={{ gap: 1.75, px: { xs: 1.5, md: 2 } }}>
          <Box
            component="img"
            src="/qtxpert-logo.svg"
            alt="QTXpert"
            sx={{ display: "block", width: navExpanded ? 132 : 116, height: "auto", maxHeight: 34, flexShrink: 0 }}
          />
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
      <Drawer
        variant="permanent"
        onMouseEnter={() => { if (wideViewport) setNavHovered(true); }}
        onMouseLeave={() => { if (wideViewport) setNavHovered(false); }}
        onFocus={() => { if (wideViewport) setNavHovered(true); }}
        sx={{
          width: drawerRootWidth,
          flexShrink: 0,
          overflow: "visible",
          transition: "width 180ms ease",
          "& .MuiDrawer-paper": {
            width: drawerPaperWidth,
            boxSizing: "border-box",
            borderRight: "1px solid",
            borderRightColor: "divider",
            backgroundColor: (theme) => theme.palette.mode === "dark" ? "rgba(12, 13, 26, .80)" : "rgba(255, 255, 255, .82)",
            overflowX: "hidden",
            transition: "width 180ms ease, box-shadow 180ms ease",
            backdropFilter: "blur(18px) saturate(135%)",
            WebkitBackdropFilter: "blur(18px) saturate(135%)",
            boxShadow: navExpanded && wideViewport
              ? (theme) => theme.palette.mode === "dark"
                ? "8px 0 30px rgba(0, 0, 0, .28)"
                : "8px 0 30px rgba(91, 69, 224, .10)"
              : "none",
            // Keep the header above the rail so the wordmark is never clipped.\n            zIndex: (theme) => theme.zIndex.drawer,
          },
        }}
      >
        <Toolbar />
        <Box sx={{ px: navExpanded ? 1 : 0.5, py: 1.5 }}>
          {!navExpanded && <Tooltip title="Open workspace navigation" placement="right"><Box aria-hidden sx={{ height: 22 }} /></Tooltip>}
          {navExpanded && <Typography variant="caption" color="text.secondary" sx={{ px: 1.5, fontWeight: 700, letterSpacing: ".12em", whiteSpace: "nowrap" }}>QUALITY WORKSPACE</Typography>}
          <List sx={{ mt: 1 }}>
            {navigation.map((item) => (
              <ListItemButton key={item.to} component={NavLink} to={item.to} end={item.end} title={!navExpanded ? item.label : undefined} sx={{ ...navSx, justifyContent: navExpanded ? undefined : "center", px: navExpanded ? undefined : 1 }}>
                <ListItemIcon sx={{ minWidth: navExpanded ? 38 : "auto", color: "text.secondary", justifyContent: "center" }}>{item.icon}</ListItemIcon>
                {navExpanded && <ListItemText primary={item.label} primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />}
                {navExpanded && item.badge && <Chip label={item.badge} size="small" sx={{ height: 20, fontSize: 10, fontWeight: 800 }} />}
              </ListItemButton>
            ))}
            <ListItemButton onClick={() => setTestDataOpen((open) => !open)} title={!navExpanded ? "Repositories" : undefined} sx={{ borderRadius: 1.5, mb: 0.5, bgcolor: location.pathname.startsWith("/test-data") ? (mode === "dark" ? "rgba(165, 173, 255, .14)" : "rgba(109, 99, 242, .10)") : undefined, color: location.pathname.startsWith("/test-data") ? "primary.main" : undefined, justifyContent: navExpanded ? undefined : "center", px: navExpanded ? undefined : 1 }}>
              <ListItemIcon sx={{ minWidth: navExpanded ? 38 : "auto", color: "text.secondary", justifyContent: "center" }}><StorageOutlinedIcon /></ListItemIcon>
              {navExpanded && <ListItemText primary="Repositories" primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />}
              {navExpanded && (testDataOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />)}
            </ListItemButton>
            <Collapse in={testDataOpen && navExpanded} timeout="auto" unmountOnExit>
              <List disablePadding>
                <ListItemButton component={NavLink} to="/test-data/uploads" sx={{ ...navSx, pl: 4.6 }}>
                  <ListItemIcon sx={{ minWidth: 34, color: "text.secondary" }}><CloudUploadOutlinedIcon fontSize="small" /></ListItemIcon>
                  <ListItemText primary="Test data" primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
                </ListItemButton>
                <ListItemButton component={NavLink} to="/test-data/documents" sx={{ ...navSx, pl: 4.6 }}>
                  <ListItemIcon sx={{ minWidth: 34, color: "text.secondary" }}><DescriptionOutlinedIcon fontSize="small" /></ListItemIcon>
                  <ListItemText primary="Documents" primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
                </ListItemButton>
              </List>
            </Collapse>
            {canViewCosts && <>
              <Divider sx={{ my: 1.25 }} />
              <ListItemButton component={NavLink} to="/cost-center" title={!navExpanded ? "Cost Center" : undefined} sx={{ ...navSx, justifyContent: navExpanded ? undefined : "center", px: navExpanded ? undefined : 1 }}>
                <ListItemIcon sx={{ minWidth: navExpanded ? 38 : "auto", color: "text.secondary", justifyContent: "center" }}><AccountBalanceWalletOutlinedIcon /></ListItemIcon>
                {navExpanded && <ListItemText primary="Cost Center" primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />}
                {navExpanded && <Chip label="ADMIN" size="small" sx={{ height: 20, fontSize: 9, fontWeight: 800 }} />}
              </ListItemButton>
            </>}
          </List>
        </Box>
      </Drawer>
      <Box component="main" className="qtxpert-workspace-main" sx={{ ml: `${drawerRootWidth}px`, p: { xs: 1.5, md: 2.25 }, minHeight: "100vh", minWidth: 0, bgcolor: "transparent", transition: "margin-left 180ms ease" }}><Toolbar /><Outlet /></Box>
    </Box>
  );
}
