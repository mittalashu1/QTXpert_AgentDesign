import { createTheme, ThemeOptions } from "@mui/material/styles";

type ThemeMode = "light" | "dark";

/**
 * QTXpert workspace tokens.
 *
 * These values intentionally match the public QTXpert site: a quiet ink
 * canvas, violet-to-cyan brand accents, restrained glass surfaces, and
 * semantic status colors that remain reserved for test state.
 */
const shared: ThemeOptions = {
  typography: {
    fontFamily: '"Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    fontSize: 14,
    h1: {
      fontFamily: '"Sora", "Inter", "Segoe UI", sans-serif',
      fontSize: "2rem",
      lineHeight: 1.12,
      fontWeight: 700,
      letterSpacing: "-0.04em",
    },
    h2: {
      fontFamily: '"Sora", "Inter", "Segoe UI", sans-serif',
      fontSize: "1.7rem",
      lineHeight: 1.16,
      fontWeight: 700,
      letterSpacing: "-0.035em",
    },
    h3: {
      fontFamily: '"Sora", "Inter", "Segoe UI", sans-serif',
      fontSize: "1.45rem",
      lineHeight: 1.2,
      fontWeight: 700,
      letterSpacing: "-0.025em",
    },
    h4: {
      fontFamily: '"Sora", "Inter", "Segoe UI", sans-serif',
      fontSize: "1.3rem",
      lineHeight: 1.24,
      fontWeight: 700,
      letterSpacing: "-0.02em",
    },
    h5: {
      fontFamily: '"Sora", "Inter", "Segoe UI", sans-serif',
      fontSize: "1.12rem",
      lineHeight: 1.3,
      fontWeight: 700,
    },
    h6: {
      fontFamily: '"Sora", "Inter", "Segoe UI", sans-serif',
      fontSize: ".98rem",
      lineHeight: 1.35,
      fontWeight: 700,
    },
    subtitle1: { fontSize: ".95rem", lineHeight: 1.42 },
    subtitle2: { fontSize: ".84rem", lineHeight: 1.42 },
    body1: { fontSize: ".88rem", lineHeight: 1.5 },
    body2: { fontSize: ".8rem", lineHeight: 1.46 },
    button: { textTransform: "none", fontWeight: 700, fontSize: ".8rem" },
    caption: {
      fontFamily: '"IBM Plex Mono", "SFMono-Regular", Consolas, monospace',
      fontSize: ".69rem",
      lineHeight: 1.45,
    },
  },
  shape: { borderRadius: 10 },
};

const components = (mode: ThemeMode): ThemeOptions["components"] => {
  const dark = mode === "dark";
  const brand = dark ? "#8B87FB" : "#5B45E0";
  const brandSoft = dark ? "rgba(165, 173, 255, .14)" : "rgba(109, 99, 242, .10)";
  const surface = dark ? "rgba(18, 19, 34, .74)" : "rgba(255, 255, 255, .82)";
  const surfaceStrong = dark ? "rgba(18, 19, 34, .94)" : "rgba(255, 255, 255, .96)";

  return {
    MuiCssBaseline: {
      styleOverrides: {
        html: {
          colorScheme: mode,
          scrollBehavior: "smooth",
        },
        body: {
          minHeight: "100vh",
          overflowX: "hidden",
          backgroundColor: dark ? "#06070F" : "#F8F9FF",
          backgroundImage: dark
            ? 'linear-gradient(180deg, rgba(6, 7, 15, .68), rgba(6, 7, 15, .91)), url("/qtxpert-workspace-atmosphere.svg")'
            : 'linear-gradient(180deg, rgba(248, 249, 255, .84), rgba(248, 249, 255, .96)), url("/qtxpert-workspace-atmosphere.svg")',
          backgroundAttachment: "fixed",
          backgroundPosition: "center top",
          backgroundRepeat: "no-repeat",
          backgroundSize: "cover",
          transition: "background-color 220ms ease, color 220ms ease",
        },
        "body::before": {
          content: '""',
          position: "fixed",
          inset: 0,
          pointerEvents: "none",
          zIndex: -1,
          background: dark
            ? "radial-gradient(50% 44% at 8% 0%, rgba(109, 99, 242, .16), transparent 68%), radial-gradient(42% 40% at 92% 4%, rgba(34, 211, 238, .10), transparent 72%)"
            : "radial-gradient(50% 44% at 8% 0%, rgba(109, 99, 242, .10), transparent 68%), radial-gradient(42% 40% at 92% 4%, rgba(34, 211, 238, .08), transparent 72%)",
        },
        "::selection": {
          background: dark ? "rgba(165, 173, 255, .28)" : "rgba(109, 99, 242, .18)",
        },
        ".qtxpert-workspace-main": {
          minWidth: 0,
          "& .MuiTypography-root": { maxWidth: "100%" },
          "& .MuiTableCell-root": { verticalAlign: "top" },
        },
        ".qtxpert-workspace-shell": {
          minHeight: "100vh",
        },
        "*, *::before, *::after": {
          scrollbarColor: dark ? "#3A326D transparent" : "#C5C7F2 transparent",
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
          backgroundColor: dark ? "rgba(12, 13, 26, .72)" : "rgba(255, 255, 255, .76)",
          borderBottom: "1px solid " + (dark ? "rgba(255, 255, 255, .08)" : "rgba(15, 23, 42, .08)"),
          backdropFilter: "blur(18px) saturate(140%)",
          WebkitBackdropFilter: "blur(18px) saturate(140%)",
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: dark ? "rgba(12, 13, 26, .80)" : "rgba(255, 255, 255, .82)",
          borderRightColor: dark ? "rgba(255, 255, 255, .08)" : "rgba(15, 23, 42, .08)",
          backdropFilter: "blur(18px) saturate(135%)",
          WebkitBackdropFilter: "blur(18px) saturate(135%)",
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 14,
          backgroundColor: surface,
          backgroundImage: "none",
          borderColor: dark ? "rgba(255, 255, 255, .08)" : "rgba(15, 23, 42, .09)",
          boxShadow: dark
            ? "0 12px 34px rgba(0, 0, 0, .18), 0 1px 0 rgba(255, 255, 255, .04) inset"
            : "0 12px 30px rgba(91, 69, 224, .06), 0 1px 0 rgba(255, 255, 255, .72) inset",
          transition: "border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease",
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
    MuiDialog: {
      styleOverrides: {
        paper: {
          backgroundColor: surfaceStrong,
          border: "1px solid " + (dark ? "rgba(255, 255, 255, .09)" : "rgba(15, 23, 42, .10)"),
          boxShadow: dark
            ? "0 28px 80px rgba(0, 0, 0, .45)"
            : "0 28px 80px rgba(15, 23, 42, .16)",
        },
      },
    },
    MuiButton: {
      defaultProps: {
        disableElevation: true,
      },
      styleOverrides: {
        root: {
          minHeight: 34,
          padding: "6px 12px",
          borderRadius: 9,
          transition: "transform 160ms ease, box-shadow 160ms ease, background-color 160ms ease, border-color 160ms ease",
        },
        containedPrimary: {
          color: "#FFFFFF",
          background: "linear-gradient(135deg, #6D63F2 0%, #5B45E0 100%)",
          boxShadow: "0 10px 26px rgba(109, 99, 242, .28)",
          "&:hover": {
            background: "linear-gradient(135deg, #7A70F5 0%, #624CE5 100%)",
            boxShadow: "0 14px 34px rgba(109, 99, 242, .40)",
            transform: "translateY(-1px)",
          },
          "&.Mui-disabled": {
            color: "rgba(255, 255, 255, .70)",
            background: dark ? "rgba(109, 99, 242, .30)" : "rgba(109, 99, 242, .42)",
          },
        },
        outlined: {
          borderColor: dark ? "rgba(165, 173, 255, .30)" : "rgba(91, 69, 224, .26)",
          "&:hover": {
            borderColor: brand,
            backgroundColor: brandSoft,
          },
        },
        text: {
          "&:hover": {
            backgroundColor: brandSoft,
          },
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          padding: 7,
          borderRadius: 9,
          transition: "background-color 160ms ease, color 160ms ease, transform 160ms ease",
          "&:hover": {
            backgroundColor: brandSoft,
            color: brand,
          },
        },
        sizeSmall: { padding: 5 },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 999,
          height: 24,
          fontSize: ".72rem",
          fontWeight: 650,
          "& .MuiChip-label": { paddingLeft: 9, paddingRight: 9 },
        },
        outlinedPrimary: {
          borderColor: dark ? "rgba(165, 173, 255, .34)" : "rgba(91, 69, 224, .28)",
        },
      },
    },
    MuiToolbar: {
      styleOverrides: {
        root: { minHeight: "56px !important" },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          minHeight: 40,
          paddingTop: 7,
          paddingBottom: 7,
          borderRadius: 10,
          transition: "background-color 160ms ease, color 160ms ease, transform 160ms ease",
          "&:hover": { backgroundColor: brandSoft },
          "&.active": {
            color: brand,
            backgroundColor: brandSoft,
            boxShadow: dark
              ? "inset 3px 0 0 #8B87FB, 0 8px 20px rgba(109, 99, 242, .10)"
              : "inset 3px 0 0 #5B45E0, 0 8px 20px rgba(109, 99, 242, .08)",
          },
        },
      },
    },
    MuiListItemIcon: {
      styleOverrides: {
        root: {
          minWidth: 34,
          color: dark ? "#98A2B3" : "#667085",
        },
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
        root: {
          minHeight: 40,
          padding: "8px 12px",
          fontSize: ".76rem",
          textTransform: "none",
          fontWeight: 700,
          "&.Mui-selected": { color: brand },
        },
        indicator: {
          background: "linear-gradient(90deg, #6D63F2, #22D3EE)",
          height: 2,
        },
      },
    },
    MuiTextField: {
      defaultProps: { size: "small" },
    },
    MuiInputBase: {
      styleOverrides: {
        root: {
          fontSize: ".82rem",
          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: brand,
            borderWidth: 1,
          },
        },
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
        tooltip: {
          maxWidth: 360,
          padding: "8px 10px",
          fontSize: ".74rem",
          lineHeight: 1.45,
          borderRadius: 8,
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
    primary: { main: "#5B45E0", light: "#8B87FB", dark: "#4632C6", contrastText: "#FFFFFF" },
    secondary: { main: "#22D3EE", light: "#67E8F9", dark: "#0891B2", contrastText: "#06131A" },
    background: { default: "#F8F9FF", paper: "#FFFFFF" },
    text: { primary: "#182033", secondary: "#667085" },
    divider: "rgba(15, 23, 42, .10)",
    error: { main: "#E11D48" },
    warning: { main: "#F59E0B" },
    info: { main: "#0EA5E9" },
    success: { main: "#10B981" },
  },
});

export const darkTheme = createTheme({
  ...shared,
  components: components("dark"),
  palette: {
    mode: "dark",
    primary: { main: "#8B87FB", light: "#C5C9FF", dark: "#6D63F2", contrastText: "#FFFFFF" },
    secondary: { main: "#22D3EE", light: "#67E8F9", dark: "#0891B2", contrastText: "#06131A" },
    background: { default: "#06070F", paper: "#121322" },
    text: { primary: "#F1F3F8", secondary: "#98A2B3" },
    divider: "rgba(255, 255, 255, .08)",
    error: { main: "#FB7185" },
    warning: { main: "#FBBF24" },
    info: { main: "#38BDF8" },
    success: { main: "#34D399" },
  },
});
