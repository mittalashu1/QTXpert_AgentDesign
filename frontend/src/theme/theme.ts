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

export const lightTheme = createTheme({
  ...shared,
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
