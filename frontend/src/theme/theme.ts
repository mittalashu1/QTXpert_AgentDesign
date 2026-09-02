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
    fontFamily: '"IBM Plex Sans", "Inter", "Segoe UI", sans-serif',
    h1: { fontWeight: 600, letterSpacing: "-0.01em" },
    h2: { fontWeight: 600, letterSpacing: "-0.01em" },
    h3: { fontWeight: 600 },
    h4: { fontWeight: 600 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
    button: { textTransform: "none", fontWeight: 600 },
    caption: { fontFamily: '"IBM Plex Mono", monospace' },
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
            ? "radial-gradient(circle at 12% -8%, rgba(18, 199, 192, .12), transparent 34%), radial-gradient(circle at 92% 8%, rgba(232, 160, 61, .08), transparent 26%)"
            : "radial-gradient(circle at 12% -8%, rgba(14, 124, 119, .10), transparent 34%), radial-gradient(circle at 92% 8%, rgba(232, 160, 61, .08), transparent 26%)",
          backgroundAttachment: "fixed",
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
          borderRadius: 16,
          backgroundImage: "none",
          boxShadow: dark ? "0 16px 34px rgba(0, 0, 0, .18)" : "0 16px 34px rgba(15, 27, 45, .055)",
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
          borderRadius: 11,
          minHeight: 38,
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
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 12,
        },
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
