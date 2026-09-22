import { createTheme, ThemeOptions } from "@mui/material/styles";

type ThemeMode = "light" | "dark";

export const qtxpertColors = {
  mainBackground: "#F8FAFF",
  secondaryBackground: "#F5F3FF",
  cardBackground: "#FFFFFF",
  primary: "#7546E8",
  primaryHover: "#6335D5",
  lavender: "#A78BFA",
  lightLavender: "#EDE5FF",
  softLilac: "#F3EDFF",
  iconLilac: "#F0E8FF",
  mint: "#DDF8EC",
  success: "#16A47B",
  successButton: "#E5F8EF",
  successCard: "#F0FCF6",
  successText: "#16845F",
  peach: "#FFF0E8",
  warning: "#E88A52",
  warningCard: "#FFF6EE",
  warningText: "#B96B22",
  softCoral: "#FFE7EB",
  error: "#E55768",
  errorCard: "#FFF0F2",
  errorText: "#D94F63",
  paleSkyBlue: "#EAF3FF",
  chartPurple: "#8264D8",
  chartGreen: "#39B894",
  chartPeach: "#F5A66B",
  chartCoral: "#E76F82",
  chartLilac: "#B39AF3",
  chartBlue: "#82B5E8",
  textPrimary: "#29263D",
  textBody: "#475467",
  textSecondary: "#667085",
  textMuted: "#85879A",
  border: "#E8E6F2",
  searchBackground: "#F8F9FE",
} as const;

export const qtxpertEffects = {
  atmosphere:
    "radial-gradient(ellipse at 12% 8%, rgba(196,181,253,0.38) 0%, transparent 42%), radial-gradient(ellipse at 88% 12%, rgba(221,214,254,0.34) 0%, transparent 40%), radial-gradient(ellipse at 85% 88%, rgba(167,243,208,0.21) 0%, transparent 38%), radial-gradient(ellipse at 58% 52%, rgba(255,255,255,0.46) 0%, transparent 54%), linear-gradient(138deg, rgba(255,255,255,0.12), transparent 40%, rgba(237,229,255,0.24) 76%, rgba(255,255,255,0.16))",
  heroGradient:
    "linear-gradient(110deg, rgba(255,255,255,0.56) 0%, rgba(248,241,255,0.42) 28%, rgba(238,233,255,0.36) 58%, rgba(234,244,255,0.34) 82%, rgba(255,255,255,0.52) 100%)",
  glassBackground: "rgba(255,255,255,0.48)",
  glassBorder: "rgba(255,255,255,0.94)",
  glassSurfaceLight: "rgba(255,255,255,0.68)",
  glassSurfaceStrongLight: "rgba(255,255,255,0.82)",
  glassSurfaceDark: "rgba(48,45,58,0.78)",
  glassSurfaceStrongDark: "rgba(52,49,64,0.88)",
  glassSheenLight:
    "linear-gradient(120deg, rgba(255,255,255,0.82) 0%, rgba(248,241,255,0.58) 38%, rgba(234,244,255,0.48) 72%, rgba(255,255,255,0.72) 100%)",
  glassSheenDark:
    "linear-gradient(120deg, rgba(69,62,87,0.82) 0%, rgba(52,49,64,0.76) 42%, rgba(43,42,55,0.82) 100%)",
  glassShadow:
    "inset 0 1px 0 rgba(255,255,255,0.98), inset 0 -1px 0 rgba(117,70,232,0.10), 0 18px 48px rgba(117,70,232,0.14)",
  cardShadow: "0 4px 20px rgba(70,50,120,0.035)",
  cardHoverShadow: "0 8px 28px rgba(117,70,232,0.08)",
} as const;

/**
 * QTXpert workspace tokens.
 *
 * Shared QTXpert visual tokens keep the application on its approved light,
 * pastel-purple glass theme while retaining a neutral dark-mode option.
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
  shape: { borderRadius: 12 },
};

const components = (mode: ThemeMode): ThemeOptions["components"] => {
  const dark = mode === "dark";
  const brand = dark ? qtxpertColors.lavender : qtxpertColors.primary;
  const brandSoft = dark ? "rgba(167,139,250,.16)" : qtxpertColors.lightLavender;
  const surface = dark ? "#302D3A" : qtxpertColors.cardBackground;
  const surfaceStrong = dark ? "#343140" : qtxpertColors.cardBackground;
  const border = dark ? "rgba(255,255,255,.12)" : qtxpertColors.border;
  const darkBackground = "#24212E";

  return {
    MuiCssBaseline: {
      styleOverrides: {
        "@font-face": [
          {
            fontFamily: "Inter",
            fontStyle: "normal",
            fontWeight: "400 700",
            fontDisplay: "swap",
            src: 'url("/fonts/inter-latin.woff2") format("woff2")',
          },
          {
            fontFamily: "Sora",
            fontStyle: "normal",
            fontWeight: "400 800",
            fontDisplay: "swap",
            src: 'url("/fonts/sora-latin.woff2") format("woff2")',
          },
        ],
        html: {
          colorScheme: mode,
          scrollBehavior: "smooth",
        },
        body: {
          minHeight: "100vh",
          overflowX: "hidden",
          color: dark ? "#F8FAFF" : qtxpertColors.textPrimary,
          backgroundColor: dark ? darkBackground : qtxpertColors.mainBackground,
          backgroundImage: dark
            ? "radial-gradient(ellipse at 12% 8%, rgba(167,139,250,.14) 0%, transparent 42%), radial-gradient(ellipse at 88% 12%, rgba(196,181,253,.10) 0%, transparent 40%)"
            : `${qtxpertEffects.atmosphere}, url("/qtxpert-workspace-atmosphere.svg")`,
          backgroundAttachment: "fixed",
          backgroundPosition: "center top",
          backgroundRepeat: "no-repeat",
          backgroundSize: "cover",
          transition: "background-color 220ms ease, color 220ms ease",
        },
        "::selection": {
          background: dark ? "rgba(167,139,250,.28)" : "rgba(117,70,232,.16)",
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
          scrollbarColor: dark ? "#766791 transparent" : "#D8D0ED transparent",
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
          backgroundColor: dark ? "rgba(48,45,58,.90)" : "rgba(255,255,255,.90)",
          borderBottom: `1px solid ${border}`,
          backdropFilter: "blur(18px) saturate(125%)",
          WebkitBackdropFilter: "blur(18px) saturate(125%)",
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: dark ? "#302D3A" : qtxpertColors.cardBackground,
          borderRightColor: border,
          backdropFilter: "blur(14px) saturate(115%)",
          WebkitBackdropFilter: "blur(14px) saturate(115%)",
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 18,
          backgroundColor: surface,
          backgroundImage: "none",
          borderColor: border,
          boxShadow: dark
            ? "0 8px 24px rgba(0,0,0,.18)"
            : qtxpertEffects.cardShadow,
          transition: "border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease",
          "&:hover": {
            boxShadow: dark ? "0 10px 26px rgba(0,0,0,.22)" : qtxpertEffects.cardHoverShadow,
          },
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
        outlined: {
          borderColor: border,
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          backgroundColor: surfaceStrong,
          border: `1px solid ${border}`,
          boxShadow: dark
            ? "0 20px 56px rgba(0,0,0,.30)"
            : "0 20px 56px rgba(70,50,120,.10)",
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
          borderRadius: 12,
          transition: "transform 160ms ease, box-shadow 160ms ease, background-color 160ms ease, border-color 160ms ease",
        },
        containedPrimary: {
          color: "#FFFFFF",
          background: qtxpertColors.primary,
          boxShadow: "0 4px 12px rgba(117,70,232,.16)",
          "&:hover": {
            background: qtxpertColors.primaryHover,
            boxShadow: "0 6px 16px rgba(117,70,232,.18)",
          },
          "&.Mui-disabled": {
            color: dark ? "rgba(255,255,255,.70)" : "#FFFFFF",
            background: dark ? "rgba(167,139,250,.30)" : "rgba(117,70,232,.40)",
          },
        },
        outlined: {
          color: dark ? "#E3D7FF" : qtxpertColors.primary,
          borderColor: dark ? "rgba(167,139,250,.34)" : "#DDD0FF",
          backgroundColor: dark ? "rgba(167,139,250,.10)" : qtxpertColors.softLilac,
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
          borderColor: dark ? "rgba(167,139,250,.34)" : "#DDD0FF",
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
          color: dark ? "#D0CBD9" : qtxpertColors.textSecondary,
          transition: "background-color 160ms ease, color 160ms ease, transform 160ms ease",
          "&:hover": { backgroundColor: dark ? brandSoft : "#F7F3FF" },
          "&.active": {
            color: brand,
            backgroundColor: dark ? brandSoft : "#F0E8FF",
            boxShadow: dark ? "inset 3px 0 0 #A78BFA" : "inset 3px 0 0 #7546E8",
          },
        },
      },
    },
    MuiListItemIcon: {
      styleOverrides: {
        root: {
          minWidth: 34,
          color: dark ? "#C4C0D0" : "#77718F",
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { padding: "8px 10px", fontSize: ".8rem", lineHeight: 1.4 },
        head: { fontWeight: 700, fontSize: ".75rem" },
      },
    },
    MuiTabs: {
      styleOverrides: {
        root: { minHeight: 40 },
        flexContainer: { minHeight: 40 },
        indicator: {
          background: `linear-gradient(90deg, ${qtxpertColors.lavender}, ${qtxpertColors.primary})`,
          height: 2,
        },
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
        root: { fontSize: ".75rem", lineHeight: 1.4, marginTop: 4 },
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
        standardSuccess: { backgroundColor: dark ? "rgba(22,164,123,.16)" : qtxpertColors.successCard, color: dark ? "#8FE0C1" : qtxpertColors.successText },
        standardWarning: { backgroundColor: dark ? "rgba(232,138,82,.16)" : qtxpertColors.warningCard, color: dark ? "#F3B58F" : qtxpertColors.warningText },
        standardError: { backgroundColor: dark ? "rgba(229,87,104,.16)" : qtxpertColors.errorCard, color: dark ? "#F3A1AA" : qtxpertColors.errorText },
        standardInfo: { backgroundColor: dark ? "rgba(130,181,232,.14)" : qtxpertColors.paleSkyBlue, color: dark ? "#B8D6F4" : "#55779D" },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          maxWidth: 360,
          padding: "8px 10px",
          fontSize: ".78rem",
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
    primary: { main: qtxpertColors.primary, light: qtxpertColors.lavender, dark: qtxpertColors.primaryHover, contrastText: "#FFFFFF" },
    secondary: { main: qtxpertColors.lavender, light: qtxpertColors.lightLavender, dark: qtxpertColors.primary, contrastText: qtxpertColors.textPrimary },
    background: { default: qtxpertColors.mainBackground, paper: qtxpertColors.cardBackground },
    text: { primary: qtxpertColors.textPrimary, secondary: qtxpertColors.textSecondary, disabled: qtxpertColors.textMuted },
    divider: qtxpertColors.border,
    action: { hover: "#F7F3FF", selected: "#F0E8FF", disabled: qtxpertColors.textMuted },
    error: { main: qtxpertColors.error, light: qtxpertColors.errorCard, dark: qtxpertColors.errorText },
    warning: { main: qtxpertColors.warning, light: qtxpertColors.warningCard, dark: qtxpertColors.warningText },
    info: { main: "#648DB8", light: qtxpertColors.paleSkyBlue, dark: "#55779D" },
    success: { main: qtxpertColors.success, light: qtxpertColors.successButton, dark: qtxpertColors.successText },
  },
});

export const darkTheme = createTheme({
  ...shared,
  components: components("dark"),
  palette: {
    mode: "dark",
    primary: { main: qtxpertColors.lavender, light: "#CBB9FF", dark: qtxpertColors.primary, contrastText: "#FFFFFF" },
    secondary: { main: "#CBB9FF", light: "#EDE5FF", dark: qtxpertColors.lavender, contrastText: "#29263D" },
    background: { default: "#24212E", paper: "#302D3A" },
    text: { primary: "#F8FAFF", secondary: "#D0CBD9", disabled: "#85879A" },
    divider: "rgba(255,255,255,.12)",
    action: { hover: "rgba(167,139,250,.16)", selected: "rgba(167,139,250,.20)", disabled: "#85879A" },
    error: { main: "#F07886", light: "rgba(229,87,104,.20)", dark: qtxpertColors.error },
    warning: { main: "#F0A675", light: "rgba(232,138,82,.20)", dark: qtxpertColors.warning },
    info: { main: "#9CC4E9", light: "rgba(130,181,232,.18)", dark: "#648DB8" },
    success: { main: "#53C69E", light: "rgba(22,164,123,.18)", dark: qtxpertColors.success },
  },
});

