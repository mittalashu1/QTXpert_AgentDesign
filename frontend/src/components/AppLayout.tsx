import { useEffect, useMemo, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AppBar, Avatar, Badge, Box, Button, Chip, Collapse, Dialog, DialogContent, DialogTitle, Divider, Drawer, IconButton, InputAdornment, List, ListItemButton, ListItemIcon, ListItemText, Menu, MenuItem, Stack, TextField, Toolbar, Tooltip, Typography, useMediaQuery, useTheme } from "@mui/material";
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
import SearchOutlinedIcon from "@mui/icons-material/SearchOutlined";
import NotificationsNoneOutlinedIcon from "@mui/icons-material/NotificationsNoneOutlined";
import BugReportOutlinedIcon from "@mui/icons-material/BugReportOutlined";
import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import CheckCircleOutlineOutlinedIcon from "@mui/icons-material/CheckCircleOutlineOutlined";
import { useAuth } from "@/contexts/AuthContext";
import { useThemeMode } from "@/contexts/ThemeModeContext";
import ProjectSelector from "@/components/ProjectSelector";
import { dashboardApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import type { DashboardSummary } from "@/types/domain";
import { qtxpertColors, qtxpertEffects } from "@/theme/theme";

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

interface WorkspaceNotice {
  key: string;
  title: string;
  detail: string;
  count: number;
  route: string;
  icon: ReactNode;
}

const searchablePages = [
  ...navigation,
  { to: "/test-data/uploads", label: "Test data repository", icon: <CloudUploadOutlinedIcon /> },
  { to: "/test-data/documents", label: "Document repository", icon: <DescriptionOutlinedIcon /> },
];

function buildWorkspaceNotices(data?: DashboardSummary): WorkspaceNotice[] {
  if (!data) return [];
  const notices: WorkspaceNotice[] = [];
  if (data.autopilot?.waiting_for_input_jobs) {
    notices.push({
      key: "autopilot-inputs",
      title: "Autopilot needs input",
      detail: "Review the saved checkpoint to continue.",
      count: data.autopilot.waiting_for_input_jobs,
      route: "/autopilot",
      icon: <AutoAwesomeIcon fontSize="small" />,
    });
  }
  if (data.open_defects > 0) {
    notices.push({
      key: "open-defects",
      title: "Open defects",
      detail: "Review the recorded issues in reports.",
      count: data.open_defects,
      route: "/reports",
      icon: <BugReportOutlinedIcon fontSize="small" />,
    });
  }
  const failedRuns = data.recent_runs.filter((run) => run.failed_tests > 0).length;
  if (failedRuns > 0) {
    notices.push({
      key: "failed-runs",
      title: "Recent runs with failures",
      detail: "Open execution results to review the latest failures.",
      count: failedRuns,
      route: "/execution",
      icon: <WarningAmberOutlinedIcon fontSize="small" />,
    });
  }
  if (data.autopilot?.deferred_tests) {
    notices.push({
      key: "deferred-tests",
      title: "Checks awaiting setup",
      detail: "Review prerequisites or approvals in Autopilot.",
      count: data.autopilot.deferred_tests,
      route: "/autopilot",
      icon: <WarningAmberOutlinedIcon fontSize="small" />,
    });
  }
  return notices;
}

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const { mode, toggleMode } = useThemeMode();
  const { selectedProjectId, selectedProject } = useSelectedProject();
  const theme = useTheme();
  const wideViewport = useMediaQuery(theme.breakpoints.up("md"));
  const fullHeader = useMediaQuery(theme.breakpoints.up("lg"));
  const showProfileDetails = useMediaQuery("(min-width: 840px)");
  const [profileAnchorEl, setProfileAnchorEl] = useState<null | HTMLElement>(null);
  const [noticeAnchorEl, setNoticeAnchorEl] = useState<null | HTMLElement>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [navHovered, setNavHovered] = useState(false);
  const [testDataOpen, setTestDataOpen] = useState(location.pathname.startsWith("/test-data"));
  const canViewCosts = user?.role === "admin" && user.email.trim().toLowerCase() === COST_ADMIN_EMAIL;
  const attentionQuery = useQuery({
    queryKey: ["dashboard", selectedProjectId],
    queryFn: () => dashboardApi.summary(selectedProjectId).then((response) => response.data),
    enabled: Boolean(selectedProjectId && selectedProject),
    staleTime: 60_000,
    refetchInterval: false,
    refetchOnWindowFocus: true,
  });
  const workspaceNotices = useMemo(() => buildWorkspaceNotices(attentionQuery.data), [attentionQuery.data]);
  const filteredPages = useMemo(() => {
    const query = searchValue.trim().toLowerCase();
    const pages = canViewCosts
      ? [...searchablePages, { to: "/cost-center", label: "Cost center", icon: <AccountBalanceWalletOutlinedIcon /> }]
      : searchablePages;
    return query ? pages.filter((page) => page.label.toLowerCase().includes(query)) : pages;
  }, [canViewCosts, searchValue]);
  const userRoleLabel = user?.role.replaceAll("_", " ") || "Team member";
  // The desktop shell keeps a quiet icon rail and reveals the full navigation
  // on hover/focus. This preserves room for dense test lists while keeping all
  // destinations one gesture away.
  const navExpanded = !wideViewport || navHovered;
  const drawerRootWidth = wideViewport ? compactDrawerWidth : drawerWidth;
  const drawerPaperWidth = navExpanded ? drawerWidth : compactDrawerWidth;

  useEffect(() => {
    if (location.pathname.startsWith("/test-data")) setTestDataOpen(true);
  }, [location.pathname]);

  useEffect(() => {
    const handleSearchShortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", handleSearchShortcut);
    return () => window.removeEventListener("keydown", handleSearchShortcut);
  }, []);

  const openPage = (path: string) => {
    setSearchOpen(false);
    setSearchValue("");
    navigate(path);
  };

  const navSx = {
    borderRadius: 1.5,
    mb: 0.5,
    position: "relative",
    transition: "background-color 160ms ease, color 160ms ease, transform 160ms ease",
    "&:hover": {
      bgcolor: "action.hover",
      backgroundImage: mode === "dark"
        ? "linear-gradient(120deg, rgba(167,139,250,.16), rgba(255,255,255,.035))"
        : "linear-gradient(120deg, rgba(237,229,255,.76), rgba(255,255,255,.42))",
    },
    "&.active": {
      bgcolor: "action.selected",
      backgroundImage: mode === "dark"
        ? "linear-gradient(120deg, rgba(167,139,250,.22), rgba(255,255,255,.045))"
        : "linear-gradient(120deg, rgba(237,229,255,.92), rgba(255,255,255,.58))",
      color: "primary.main",
      borderLeft: "3px solid",
      borderColor: "primary.main",
      boxShadow: mode === "dark" ? "none" : qtxpertEffects.cardShadow,
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
          backgroundColor: mode === "dark" ? "rgba(38,35,49,.76)" : "rgba(255,255,255,.76)",
          backgroundImage: mode === "dark" ? qtxpertEffects.glassSheenDark : qtxpertEffects.glassSheenLight,
          color: "text.primary",
          backdropFilter: "blur(22px) saturate(160%)",
          WebkitBackdropFilter: "blur(22px) saturate(160%)",
          boxShadow: (theme) => theme.palette.mode === "dark"
            ? "0 1px 0 rgba(255,255,255,.08)"
            : qtxpertEffects.cardShadow,
        }}
      >
        <Toolbar sx={{ gap: { xs: 0.6, sm: 1.1, md: 1.5 }, px: { xs: 1, sm: 1.5, md: 2 }, minWidth: 0 }}>
          <Box
            component="img"
            src="/qtxpert-logo.svg"
            alt="QTXpert"
            sx={{ display: "block", width: { xs: 98, sm: navExpanded ? 132 : 116 }, height: "auto", maxHeight: 34, flexShrink: 0 }}
          />
          <Box sx={{ minWidth: 0, flex: { xs: "1 1 150px", sm: "0 1 340px" }, maxWidth: { sm: 380 } }}><ProjectSelector topLevel /></Box>
          <Box sx={{ flex: 1, minWidth: 0 }} />
          <Tooltip title="Search pages and tools · Ctrl/⌘ K">
            <Button
              variant="outlined"
              onClick={() => setSearchOpen(true)}
              aria-label="Search pages and tools"
              startIcon={<SearchOutlinedIcon fontSize="small" />}
              sx={{
                minWidth: { xs: 34, sm: 36, lg: 228 },
                width: { xs: 36, lg: "auto" },
                px: { xs: 0.6, lg: 1.2 },
                justifyContent: { xs: "center", lg: "flex-start" },
                color: "text.secondary",
                borderColor: "divider",
                bgcolor: mode === "dark" ? "background.paper" : qtxpertColors.searchBackground,
                "& .MuiButton-startIcon": { mx: { xs: 0, lg: 0.5 } },
              }}
            >
              {fullHeader && <Typography variant="body2" sx={{ flex: 1, textAlign: "left", whiteSpace: "nowrap" }}>Search pages &amp; tools</Typography>}
            </Button>
          </Tooltip>
          <Tooltip title={workspaceNotices.length ? `${workspaceNotices.length} project attention items` : "Project notifications"}>
            <IconButton
              onClick={(event) => setNoticeAnchorEl(event.currentTarget)}
              aria-label={`Project notifications, ${workspaceNotices.length} items`}
              sx={{ border: "1px solid", borderColor: "divider", bgcolor: "background.paper" }}
            >
              <Badge badgeContent={workspaceNotices.length} color="error" max={9}>
                <NotificationsNoneOutlinedIcon />
              </Badge>
            </IconButton>
          </Tooltip>
          <Menu
            anchorEl={noticeAnchorEl}
            open={Boolean(noticeAnchorEl)}
            onClose={() => setNoticeAnchorEl(null)}
            PaperProps={{ sx: { width: 340, maxWidth: "calc(100vw - 24px)", borderRadius: 2.5, p: 0.5, backdropFilter: "blur(20px)" } }}
          >
            <Box sx={{ px: 1.5, py: 1 }}>
              <Typography variant="subtitle2" fontWeight={800}>Project attention</Typography>
              <Typography variant="caption" color="text.secondary" noWrap>{selectedProject?.name || "Select a project"}</Typography>
            </Box>
            <Divider />
            {attentionQuery.isFetching ? (
              <MenuItem disabled>Loading project signals…</MenuItem>
            ) : attentionQuery.isError ? (
              <MenuItem disabled>Project signals are temporarily unavailable.</MenuItem>
            ) : workspaceNotices.length ? workspaceNotices.map((notice) => (
              <MenuItem key={notice.key} onClick={() => { setNoticeAnchorEl(null); openPage(notice.route); }} sx={{ alignItems: "flex-start", gap: 1, py: 1 }}>
                <ListItemIcon sx={{ minWidth: 28, mt: 0.25 }}>{notice.icon}</ListItemIcon>
                <ListItemText
                  primary={notice.title}
                  secondary={notice.detail}
                  primaryTypographyProps={{ variant: "body2", fontWeight: 700, noWrap: true }}
                  secondaryTypographyProps={{ variant: "caption", color: "text.secondary", sx: { whiteSpace: "normal" } }}
                />
                <Chip size="small" label={notice.count} color="warning" variant="outlined" />
              </MenuItem>
            )) : (
              <Box sx={{ display: "flex", alignItems: "center", gap: 1, px: 1.5, py: 2 }}>
                <CheckCircleOutlineOutlinedIcon color="success" fontSize="small" />
                <Typography variant="body2" color="text.secondary">No open attention items for this project.</Typography>
              </Box>
            )}
          </Menu>
          <Tooltip title={mode === "dark" ? "Use light theme" : "Use dark theme"}>
            <IconButton onClick={toggleMode} aria-label={mode === "dark" ? "Use light theme" : "Use dark theme"} sx={{ border: "1px solid", borderColor: "divider", bgcolor: "background.paper" }}>
              {mode === "dark" ? <LightModeOutlinedIcon /> : <DarkModeOutlinedIcon />}
            </IconButton>
          </Tooltip>
          <Tooltip title="Account and profile">
            <Button
              onClick={(event) => setProfileAnchorEl(event.currentTarget)}
              aria-label={`Account menu for ${user?.full_name || "user"}`}
              endIcon={showProfileDetails ? <ExpandMoreIcon fontSize="small" /> : undefined}
              sx={{ minWidth: 0, px: { xs: 0.2, sm: 0.6 }, color: "text.primary", borderRadius: 2.5, textAlign: "left" }}
            >
                <Avatar sx={{ width: 36, height: 36, mr: showProfileDetails ? 1 : 0, color: "#fff", background: `linear-gradient(140deg, ${qtxpertColors.lavender}, ${qtxpertColors.primary})` }}>
                {user?.full_name?.charAt(0).toUpperCase() ?? "U"}
              </Avatar>
              {showProfileDetails && <Stack sx={{ alignItems: "flex-start", minWidth: 90, maxWidth: 140 }}>
                <Typography variant="body2" fontWeight={800} noWrap sx={{ maxWidth: "100%" }}>{user?.full_name || "Workspace user"}</Typography>
                <Typography variant="caption" color="text.secondary" noWrap sx={{ textTransform: "capitalize", maxWidth: "100%" }}>{userRoleLabel}</Typography>
              </Stack>}
            </Button>
          </Tooltip>
          <Menu anchorEl={profileAnchorEl} open={Boolean(profileAnchorEl)} onClose={() => setProfileAnchorEl(null)}>
            <Box sx={{ px: 2, py: 1.25, minWidth: 180 }}>
              <Typography variant="body2" fontWeight={800}>{user?.full_name || "Workspace user"}</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ textTransform: "capitalize" }}>{userRoleLabel}</Typography>
            </Box>
            <Divider />
            <MenuItem onClick={() => { setProfileAnchorEl(null); navigate("/profile"); }}>Profile</MenuItem>
            {user?.role === "admin" && <MenuItem onClick={() => { setProfileAnchorEl(null); navigate("/administration/users"); }}>Administration</MenuItem>}
            <Divider />
            <MenuItem onClick={() => { setProfileAnchorEl(null); logout(); navigate("/login"); }}>Sign out</MenuItem>
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
            backgroundColor: "background.paper",
            backgroundImage: mode === "dark" ? qtxpertEffects.glassSheenDark : qtxpertEffects.glassSheenLight,
            overflowX: "hidden",
            transition: "width 180ms ease, box-shadow 180ms ease",
            backdropFilter: "blur(20px) saturate(155%)",
            WebkitBackdropFilter: "blur(20px) saturate(155%)",
            boxShadow: navExpanded && wideViewport
              ? (theme) => theme.palette.mode === "dark"
                ? "8px 0 24px rgba(0,0,0,.18)"
                : qtxpertEffects.cardShadow
              : "none",
            // Keep the header above the rail so the wordmark is never clipped.
            zIndex: (theme) => theme.zIndex.drawer,
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
            <ListItemButton onClick={() => setTestDataOpen((open) => !open)} title={!navExpanded ? "Repositories" : undefined} sx={{ borderRadius: 1.5, mb: 0.5, bgcolor: location.pathname.startsWith("/test-data") ? "action.selected" : undefined, color: location.pathname.startsWith("/test-data") ? "primary.main" : undefined, justifyContent: navExpanded ? undefined : "center", px: navExpanded ? undefined : 1 }}>
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
      <Box component="main" className="qtxpert-workspace-main" sx={{ ml: `${drawerRootWidth}px`, p: { xs: 1.5, md: 2.25 }, minHeight: "100vh", minWidth: 0, bgcolor: "transparent", transition: "margin-left 180ms ease" }}>
        <Toolbar />
        <Outlet />
      </Box>
      <Dialog open={searchOpen} onClose={() => { setSearchOpen(false); setSearchValue(""); }} fullWidth maxWidth="sm">
        <DialogTitle sx={{ pb: 1 }}>Find a page or tool</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            value={searchValue}
            onChange={(event) => setSearchValue(event.target.value)}
            placeholder="Search dashboard, Autopilot, reports…"
            inputProps={{ "aria-label": "Search QTXpert pages and tools" }}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchOutlinedIcon fontSize="small" /></InputAdornment> }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && filteredPages[0]) openPage(filteredPages[0].to);
            }}
          />
          <List dense sx={{ mt: 1, maxHeight: 360, overflowY: "auto" }}>
            {filteredPages.length ? filteredPages.map((page) => (
              <ListItemButton key={page.to} onClick={() => openPage(page.to)} sx={{ borderRadius: 1.5 }}>
                <ListItemIcon sx={{ minWidth: 38, color: "primary.main" }}>{page.icon}</ListItemIcon>
                <ListItemText primary={page.label} secondary={page.to} primaryTypographyProps={{ fontWeight: 700 }} />
              </ListItemButton>
            )) : <Typography variant="body2" color="text.secondary" sx={{ px: 2, py: 2 }}>No matching page or tool.</Typography>}
          </List>
        </DialogContent>
      </Dialog>
    </Box>
  );
}
