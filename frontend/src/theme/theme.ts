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
  glassSurfaceLight: "rgba(255,255,255,.68)",
  glassSurfaceStrongLight: "rgba(255,255,255,.84)",
  glassSurfaceDark: "rgba(48,45,58,.78)",
  glassSurfaceStrongDark: "rgba(48,45,58,.90)",
  glassSheenLight: "linear-gradient(145deg, rgba(255,255,255,.92) 0%, rgba(255,255,255,.66) 48%, rgba(239,233,255,.52) 100%)",
  glassSheenDark: "linear-gradient(145deg, rgba(255,255,255,.075) 0%, rgba(167,139,250,.035) 52%, rgba(48,45,58,.18) 100%)",
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
  const surface = dark ? qtxpertEffects.glassSurfaceDark : qtxpertEffects.glassSurfaceLight;
  const surfaceStrong = dark ? qtxpertEffects.glassSurfaceStrongDark : qtxpertEffects.glassSurfaceStrongLight;
  const border = dark ? "rgba(255,255,255,.12)" : qtxpertColors.border;
  const glassEdge = dark ? "rgba(255,255,255,.16)" : "rgba(255,255,255,.92)";
  const glassSheen = dark ? qtxpertEffects.glassSheenDark : qtxpertEffects.glassSheenLight;
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
          isolation: "isolate",
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
          backgroundColor: dark ? "rgba(38,35,49,.76)" : "rgba(255,255,255,.76)",
          backgroundImage: glassSheen,
          borderBottom: `1px solid ${border}`,
          backdropFilter: "blur(22px) saturate(160%)",
          WebkitBackdropFilter: "blur(22px) saturate(160%)",
          boxShadow: dark ? "0 8px 28px rgba(0,0,0,.16)" : "0 8px 28px rgba(79,57,135,.055)",
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: surface,
          backgroundImage: glassSheen,
          borderRightColor: border,
          backdropFilter: "blur(20px) saturate(155%)",
          WebkitBackdropFilter: "blur(20px) saturate(155%)",
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 18,
          backgroundColor: surface,
          backgroundImage: glassSheen,
          backgroundClip: "padding-box",
          border: `1px solid ${glassEdge}`,
          backdropFilter: "blur(18px) saturate(150%)",
          WebkitBackdropFilter: "blur(18px) saturate(150%)",
          boxShadow: dark
            ? "inset 0 1px 0 rgba(255,255,255,.08), 0 12px 32px rgba(0,0,0,.20)"
            : "inset 0 1px 0 rgba(255,255,255,.96), 0 10px 32px rgba(70,50,120,.065)",
          transition: "border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease",
          "&:hover": {
            borderColor: dark ? "rgba(203,185,255,.34)" : "rgba(167,139,250,.40)",
            boxShadow: dark ? "inset 0 1px 0 rgba(255,255,255,.09), 0 16px 38px rgba(0,0,0,.24)" : "inset 0 1px 0 rgba(255,255,255,.98), 0 14px 36px rgba(117,70,232,.10)",
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
          backgroundColor: surface,
          backgroundImage: glassSheen,
          backdropFilter: "blur(16px) saturate(145%)",
          WebkitBackdropFilter: "blur(16px) saturate(145%)",
        },
        outlined: {
          borderColor: dark ? "rgba(255,255,255,.14)" : "rgba(255,255,255,.92)",
          boxShadow: dark ? "inset 0 1px 0 rgba(255,255,255,.06)" : "inset 0 1px 0 rgba(255,255,255,.94), 0 6px 20px rgba(70,50,120,.035)",
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          backgroundColor: surfaceStrong,
          backgroundImage: glassSheen,
          border: `1px solid ${border}`,
          backdropFilter: "blur(22px) saturate(160%)",
          WebkitBackdropFilter: "blur(22px) saturate(160%)",
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
          background: "linear-gradient(135deg, #8258EE 0%, #6E41DE 62%, #5E36C9 100%)",
          boxShadow: "inset 0 1px 0 rgba(255,255,255,.32), 0 7px 18px rgba(117,70,232,.22)",
          "&:hover": {
            background: "linear-gradient(135deg, #8D68F2 0%, #7549E3 62%, #633BD2 100%)",
            boxShadow: "inset 0 1px 0 rgba(255,255,255,.36), 0 10px 22px rgba(117,70,232,.27)",
            transform: "translateY(-1px)",
          },
          "&.Mui-disabled": {
            color: dark ? "rgba(255,255,255,.70)" : "#FFFFFF",
            background: dark ? "rgba(167,139,250,.30)" : "rgba(117,70,232,.40)",
          },
        },
        outlined: {
          color: dark ? "#E3D7FF" : qtxpertColors.primary,
          borderColor: dark ? "rgba(167,139,250,.34)" : "#DDD0FF",
          backgroundColor: dark ? "rgba(167,139,250,.12)" : "rgba(243,237,255,.68)",
          backdropFilter: "blur(10px) saturate(135%)",
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
          transition: "background-color 160ms ease, color 160ms ease, transform 160ms ease, box-shadow 160ms ease",
          "&:focus-visible": { outline: "2px solid", outlineColor: brand, outlineOffset: 2 },
          "&:hover": {
            backgroundColor: brandSoft,
            color: brand,
            boxShadow: dark ? "0 4px 14px rgba(0,0,0,.20)" : "0 4px 14px rgba(117,70,232,.10)",
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
        root: { padding: "8px 10px", fontSize: ".8rem", lineHeight: 1.4, borderColor: border },
        head: { fontWeight: 700, fontSize: ".75rem", color: dark ? "#F3EEFF" : qtxpertColors.textPrimary, backgroundColor: dark ? "rgba(167,139,250,.12)" : "rgba(117,70,232,.06)" },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          transition: "background-color 140ms ease",
          "&:hover": { backgroundColor: dark ? "rgba(167,139,250,.075)" : "rgba(117,70,232,.035)" },
          "&:last-child td, &:last-child th": { borderBottom: 0 },
        },
      },
    },
    MuiAccordion: {
      styleOverrides: {
        root: {
          borderRadius: "14px !important",
          backgroundColor: surface,
          backgroundImage: glassSheen,
          border: `1px solid ${border}`,
          backdropFilter: "blur(16px) saturate(145%)",
          WebkitBackdropFilter: "blur(16px) saturate(145%)",
          boxShadow: dark ? "inset 0 1px 0 rgba(255,255,255,.06)" : "inset 0 1px 0 rgba(255,255,255,.9)",
          "&:before": { display: "none" },
          "&.Mui-expanded": { margin: 0 },
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        root: { minHeight: 40, backgroundColor: "transparent" },
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
          borderRadius: "10px 10px 0 0",
          "&.Mui-selected": { color: brand, backgroundColor: brandSoft },
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
          backgroundColor: dark ? "rgba(255,255,255,.045)" : "rgba(255,255,255,.60)",
          backgroundImage: glassSheen,
          backdropFilter: "blur(12px) saturate(135%)",
          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: brand,
            borderWidth: 1,
          },
          "& .MuiOutlinedInput-notchedOutline": { borderColor: dark ? "rgba(255,255,255,.16)" : "rgba(108,88,154,.20)" },
          "&:hover .MuiOutlinedInput-notchedOutline": { borderColor: dark ? "rgba(203,185,255,.44)" : "rgba(117,70,232,.42)" },
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
    background: { default: qtxpertColors.mainBackground, paper: qtxpertEffects.glassSurfaceLight },
    text: { primary: qtxpertColors.textPrimary, secondary: qtxpertColors.textSecondary, disabled: qtxpertColors.textMuted },
    divider: qtxpertColors.border,
    action: { hover: "rgba(247,243,255,.74)", selected: "rgba(240,232,255,.82)", disabled: qtxpertColors.textMuted },
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
    background: { default: "#24212E", paper: qtxpertEffects.glassSurfaceDark },
    text: { primary: "#F8FAFF", secondary: "#D0CBD9", disabled: "#85879A" },
    divider: "rgba(255,255,255,.12)",
    action: { hover: "rgba(167,139,250,.16)", selected: "rgba(167,139,250,.20)", disabled: "#85879A" },
    error: { main: "#F07886", light: "rgba(229,87,104,.20)", dark: qtxpertColors.error },
    warning: { main: "#F0A675", light: "rgba(232,138,82,.20)", dark: qtxpertColors.warning },
    info: { main: "#9CC4E9", light: "rgba(130,181,232,.18)", dark: "#648DB8" },
    success: { main: "#53C69E", light: "rgba(22,164,123,.18)", dark: qtxpertColors.success },
  },
});
