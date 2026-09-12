import { createTheme, ThemeOptions } from "@mui/material/styles";

/**
 * QTXpert.ai design tokens.
 * Palette: deep slate/navy (#0F1B2D, #16283F) for surfaces, a precise
 * signal-teal (#0FB5AE) for primary actions/automation cues, and a
 * calibrated amber (#E8A03D) reserved for risk/priority signals only -
 * so color itself carries meaning instead of decorating the UI.
 */
const shared: ThemeOptions = {
  typography: {
    fontFamily: '"Inter", "IBM Plex Sans", "Segoe UI", sans-serif',
    // The workspace is evidence-dense by design. Keep hierarchy clear without
    // making every label compete with the data on screen.
    fontSize: 14,
    h1: { fontSize: "2rem", lineHeight: 1.15, fontWeight: 650, letterSpacing: "-0.025em" },
    h2: { fontSize: "1.7rem", lineHeight: 1.2, fontWeight: 650, letterSpacing: "-0.02em" },
    h3: { fontSize: "1.45rem", lineHeight: 1.2, fontWeight: 650, letterSpacing: "-0.015em" },
    h4: { fontSize: "1.3rem", lineHeight: 1.25, fontWeight: 650, letterSpacing: "-0.01em" },
    h5: { fontSize: "1.12rem", lineHeight: 1.3, fontWeight: 650 },
    h6: { fontSize: ".98rem", lineHeight: 1.35, fontWeight: 650 },
    subtitle1: { fontSize: ".95rem", lineHeight: 1.4 },
    subtitle2: { fontSize: ".84rem", lineHeight: 1.4 },
    body1: { fontSize: ".88rem", lineHeight: 1.48 },
    body2: { fontSize: ".8rem", lineHeight: 1.45 },
    button: { textTransform: "none", fontWeight: 650, fontSize: ".8rem" },
    caption: { fontFamily: '"IBM Plex Mono", monospace', fontSize: ".69rem", lineHeight: 1.45 },
  },
  shape: { borderRadius: 10 },
};

/**
 * A restrained glass treatment for the workspace shell. The material is kept
 * on navigation and containers only; content remains opaque and high contrast
 * so the interface stays useful for dense QA evidence and reduced-transparency
 * accessibility settings.
 */
const components = (mode: "light" | "dark"): ThemeOptions["components"] => {
  const dark = mode === "dark";
  return {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundImage: dark
            ? "radial-gradient(circle at 12% -8%, rgba(18, 199, 192, .10), transparent 32%), radial-gradient(circle at 92% 8%, rgba(232, 160, 61, .06), transparent 24%)"
            : "radial-gradient(circle at 12% -8%, rgba(14, 124, 119, .06), transparent 32%), radial-gradient(circle at 92% 8%, rgba(232, 160, 61, .045), transparent 24%)",
          backgroundAttachment: "fixed",
        },
        // Keep long content usable while preserving readable line lengths.
        ".qtxpert-workspace-main": {
          "& .MuiTypography-root": { maxWidth: "100%" },
          "& .MuiTableCell-root": { verticalAlign: "top" },
        },
        "*, *::before, *::after": {
          scrollbarColor: dark ? "#2A4658 transparent" : "#B8C8CE transparent",
          scrollbarWidth: "thin",
        },
        "@media (prefers-reduced-motion: reduce)": {
          "*, *::before, *::after": {
            animationDuration: "0.01ms !important",
            animationIterationCount: "1 !important",
            transitionDuration: "0.01ms !important",
            scrollBehavior: "auto !important",
          },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: dark ? "rgba(17, 30, 46, .82)" : "rgba(255, 255, 255, .80)",
          backdropFilter: "blur(18px) saturate(140%)",
          WebkitBackdropFilter: "blur(18px) saturate(140%)",
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: dark ? "rgba(17, 30, 46, .88)" : "rgba(255, 255, 255, .86)",
          backdropFilter: "blur(18px) saturate(130%)",
          WebkitBackdropFilter: "blur(18px) saturate(130%)",
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 10,
          backgroundImage: "none",
          boxShadow: dark ? "0 4px 14px rgba(0, 0, 0, .16)" : "0 2px 10px rgba(15, 27, 45, .035)",
          transition: "border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease",
        },
      },
    },
    MuiCardContent: {
      styleOverrides: {
        root: {
          padding: 14,
          "&:last-child": { paddingBottom: 14 },
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          minHeight: 34,
          padding: "6px 12px",
          transition: "transform 160ms ease, box-shadow 160ms ease, background-color 160ms ease",
        },
        contained: {
          boxShadow: "none",
          "&:hover": {
            boxShadow: dark ? "0 8px 18px rgba(18, 199, 192, .20)" : "0 8px 18px rgba(14, 124, 119, .18)",
            transform: "translateY(-1px)",
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 999,
          height: 24,
          fontSize: ".72rem",
          "& .MuiChip-label": { paddingLeft: 9, paddingRight: 9 },
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: { padding: 7 },
        sizeSmall: { padding: 5 },
      },
    },
    MuiToolbar: {
      styleOverrides: {
        root: { minHeight: "56px !important" },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: { minHeight: 40, paddingTop: 7, paddingBottom: 7 },
      },
    },
    MuiListItemIcon: {
      styleOverrides: {
        root: { minWidth: 34 },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { padding: "8px 10px", fontSize: ".76rem", lineHeight: 1.4 },
        head: { fontWeight: 700, fontSize: ".72rem" },
      },
    },
    MuiTabs: {
      styleOverrides: {
        root: { minHeight: 40 },
        flexContainer: { minHeight: 40 },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: { minHeight: 40, padding: "8px 12px", fontSize: ".76rem", textTransform: "none", fontWeight: 650 },
      },
    },
    MuiTextField: {
      defaultProps: { size: "small" },
    },
    MuiInputBase: {
      styleOverrides: {
        root: { fontSize: ".82rem" },
        input: { paddingTop: 10, paddingBottom: 10 },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: { fontSize: ".78rem" },
      },
    },
    MuiFormHelperText: {
      styleOverrides: {
        root: { fontSize: ".68rem", lineHeight: 1.35, marginTop: 4 },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          paddingTop: 8,
          paddingBottom: 8,
          fontSize: ".8rem",
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: { maxWidth: 360, padding: "8px 10px", fontSize: ".74rem", lineHeight: 1.45 },
      },
    },
  };
};

export const lightTheme = createTheme({
  ...shared,
  components: components("light"),
  palette: {
    mode: "light",
    primary: { main: "#0E7C77", contrastText: "#FFFFFF" },
    secondary: { main: "#E8A03D" },
    background: { default: "#F5F7F8", paper: "#FFFFFF" },
    text: { primary: "#12202E", secondary: "#4C5F70" },
    divider: "#D9E1E5",
    error: { main: "#C0392B" },
    warning: { main: "#E8A03D" },
    success: { main: "#1E8E5A" },
  },
});

export const darkTheme = createTheme({
  ...shared,
  components: components("dark"),
  palette: {
    mode: "dark",
    primary: { main: "#12C7C0", contrastText: "#06120F" },
    secondary: { main: "#E8A03D" },
    background: { default: "#0B141F", paper: "#111E2E" },
    text: { primary: "#E7EEF2", secondary: "#8FA3B3" },
    divider: "#1F3040",
    error: { main: "#E5605A" },
    warning: { main: "#E8A03D" },
    success: { main: "#33B37B" },
  },
});


