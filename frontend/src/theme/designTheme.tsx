import { createTheme, GlobalStyles, ThemeProvider } from "@mui/material";
import type { ReactNode } from "react";
import { darkTheme, lightTheme } from "@/theme/theme";

export type DesignMode = "light" | "dark";

/**
 * Semantic tokens for the Design workspace.
 *
 * These tokens intentionally keep the product surface quiet: charcoal text,
 * green for healthy/active work, neutral gray for unknown states, amber for
 * warnings, and muted coral for attention. Individual screens consume the
 * MUI semantic palette built from these values instead of introducing their
 * own visual language.
 */
export const designTokens = {
  light: {
    page: "#F4F6F4",
    surface: "#FFFFFF",
    surfaceSubtle: "#F8FAF9",
    surfaceMuted: "#EEF2EF",
    primary: "#1F7850",
    primaryHover: "#185F3F",
    primarySoft: "#E6F2EA",
    primarySoftStrong: "#D3E9DA",
    healthy: "#2F9364",
    healthySoft: "#EAF6EF",
    neutral: "#68756D",
    neutralSoft: "#EEF1EF",
    warning: "#AC741B",
    warningSoft: "#FFF4DE",
    attention: "#BE665F",
    attentionSoft: "#FCECEA",
    text: "#27332C",
    textSecondary: "#5C6A61",
    textMuted: "#7C8981",
    border: "#D8E1DA",
    borderStrong: "#C6D3C9",
    focus: "#237C53",
    heroGradient: "linear-gradient(180deg, rgba(255,255,255,.98) 0%, rgba(247,250,248,.98) 100%)",
    heroAccentGradient: "radial-gradient(circle at 42% 38%, rgba(255,255,255,.96), rgba(231,242,235,.72) 40%, rgba(204,230,213,.56) 72%, transparent 78%)",
    heroOrbGradient: "radial-gradient(circle at 30% 22%, rgba(255,255,255,.98), rgba(231,242,235,.82) 44%, rgba(190,220,200,.66) 74%, rgba(255,255,255,.34))",
    heroShadow: "inset 0 2px 12px rgba(255,255,255,.96), inset -9px -12px 22px rgba(31,120,80,.12), 0 0 0 10px rgba(255,255,255,.42), 0 0 0 23px rgba(191,222,201,.22), 0 18px 42px rgba(39,75,54,.12)",
    cardShadow: "0 2px 12px rgba(39,51,44,.06)",
    cardHoverShadow: "0 7px 22px rgba(39,51,44,.10)",
    atmosphere: "linear-gradient(180deg, rgba(245,249,246,.92), rgba(244,246,244,0))",
    surfaceTranslucent: "rgba(255,255,255,.92)",
  },
  dark: {
    page: "#1E2621",
    surface: "#27322B",
    surfaceSubtle: "#2E3A32",
    surfaceMuted: "#354239",
    primary: "#81C79C",
    primaryHover: "#A2DDB7",
    primarySoft: "rgba(129,199,156,.18)",
    primarySoftStrong: "rgba(129,199,156,.28)",
    healthy: "#86D2A4",
    healthySoft: "rgba(134,210,164,.18)",
    neutral: "#B6C2B9",
    neutralSoft: "rgba(182,194,185,.16)",
    warning: "#E2B46A",
    warningSoft: "rgba(226,180,106,.18)",
    attention: "#E19A92",
    attentionSoft: "rgba(225,154,146,.18)",
    text: "#F1F6F2",
    textSecondary: "#C4D1C7",
    textMuted: "#9AABA0",
    border: "rgba(220,236,225,.16)",
    borderStrong: "rgba(220,236,225,.28)",
    focus: "#9BDBB1",
    heroGradient: "linear-gradient(180deg, rgba(43,56,47,.98) 0%, rgba(39,50,43,.98) 100%)",
    heroAccentGradient: "radial-gradient(circle at 42% 38%, rgba(255,255,255,.14), rgba(129,199,156,.16) 40%, rgba(129,199,156,.08) 72%, transparent 78%)",
    heroOrbGradient: "radial-gradient(circle at 30% 22%, rgba(255,255,255,.22), rgba(129,199,156,.26) 44%, rgba(129,199,156,.12) 74%, rgba(255,255,255,.08))",
    heroShadow: "inset 0 2px 12px rgba(255,255,255,.08), inset -9px -12px 22px rgba(129,199,156,.10), 0 0 0 10px rgba(255,255,255,.04), 0 0 0 23px rgba(129,199,156,.08), 0 18px 42px rgba(0,0,0,.18)",
    cardShadow: "0 8px 24px rgba(0,0,0,.16)",
    cardHoverShadow: "0 10px 28px rgba(0,0,0,.22)",
    atmosphere: "linear-gradient(180deg, rgba(46,58,50,.88), rgba(30,38,33,0))",
    surfaceTranslucent: "rgba(39,50,43,.92)",
  },
} as const;

export const designEffects = {
  cardShadow: designTokens.light.cardShadow,
  cardHoverShadow: designTokens.light.cardHoverShadow,
  atmosphere: designTokens.light.atmosphere,
  heroGradient: designTokens.light.heroGradient,
  heroAccentGradient: designTokens.light.heroAccentGradient,
  heroOrbGradient: designTokens.light.heroOrbGradient,
  heroShadow: designTokens.light.heroShadow,
} as const;

function createDesignTheme(mode: DesignMode) {
  const colors = designTokens[mode];
  const baseTheme = mode === "dark" ? darkTheme : lightTheme;

  return createTheme(baseTheme, {
    shape: { borderRadius: 10 },
    palette: {
      mode,
      primary: { main: colors.primary, light: colors.primarySoftStrong, dark: colors.primaryHover, contrastText: "#FFFFFF" },
      secondary: { main: colors.neutral, light: colors.neutralSoft, dark: colors.textSecondary, contrastText: colors.text },
      background: { default: colors.page, paper: colors.surface },
      text: { primary: colors.text, secondary: colors.textSecondary, disabled: colors.textMuted },
      divider: colors.border,
      action: { hover: colors.surfaceSubtle, selected: colors.primarySoft, disabled: colors.textMuted },
      error: { main: colors.attention, light: colors.attentionSoft, dark: colors.attention },
      warning: { main: colors.warning, light: colors.warningSoft, dark: colors.warning },
      info: { main: colors.neutral, light: colors.neutralSoft, dark: colors.textSecondary },
      success: { main: colors.healthy, light: colors.healthySoft, dark: colors.healthy },
    },
    components: {
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 14,
            backgroundColor: colors.surface,
            backgroundImage: "none",
            borderColor: colors.border,
            boxShadow: colors.cardShadow,
            "&:hover": { boxShadow: colors.cardHoverShadow },
          },
        },
      },
      MuiCardContent: {
        styleOverrides: {
          root: { padding: 16, "&:last-child": { paddingBottom: 16 } },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: { backgroundImage: "none" },
          outlined: { borderColor: colors.border, boxShadow: "none" },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: { backgroundColor: colors.surface, border: `1px solid ${colors.border}`, boxShadow: colors.cardHoverShadow },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: { minHeight: 36, borderRadius: 9, fontWeight: 700 },
          containedPrimary: {
            color: "#FFFFFF",
            background: colors.primary,
            boxShadow: "0 3px 10px rgba(31,120,80,.16)",
            "&:hover": { background: colors.primaryHover, boxShadow: "0 5px 14px rgba(31,120,80,.20)" },
            "&.Mui-disabled": { color: mode === "dark" ? "rgba(255,255,255,.68)" : "#FFFFFF", background: mode === "dark" ? "rgba(129,199,156,.28)" : "rgba(31,120,80,.38)" },
          },
          outlined: {
            color: colors.textSecondary,
            borderColor: colors.borderStrong,
            backgroundColor: colors.surface,
            "&:hover": { color: colors.primary, borderColor: colors.primary, backgroundColor: colors.primarySoft },
          },
          outlinedPrimary: { color: colors.primary, borderColor: colors.primary, backgroundColor: colors.surface },
          text: { color: colors.textSecondary, "&:hover": { color: colors.primary, backgroundColor: colors.primarySoft } },
        },
      },
      MuiIconButton: {
        styleOverrides: {
          root: { borderRadius: 9, "&:hover": { backgroundColor: colors.primarySoft, color: colors.primary } },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { borderRadius: 999, fontWeight: 700 },
          outlined: { borderColor: colors.borderStrong, color: colors.textSecondary },
          outlinedPrimary: { borderColor: colors.primary, color: colors.primary },
        },
      },
      MuiTabs: {
        styleOverrides: {
          indicator: { backgroundColor: colors.primary, height: 2 },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: { color: colors.textSecondary, "&.Mui-selected": { color: colors.primary } },
        },
      },
      MuiInputBase: {
        styleOverrides: {
          root: {
            "&.Mui-focused .MuiOutlinedInput-notchedOutline": { borderColor: colors.focus, borderWidth: 1 },
          },
        },
      },
      MuiLinearProgress: {
        styleOverrides: {
          root: { backgroundColor: colors.primarySoft, borderRadius: 999 },
          bar: { backgroundColor: colors.primary, borderRadius: 999 },
        },
      },
      MuiAlert: {
        styleOverrides: {
          standardSuccess: { backgroundColor: colors.healthySoft, color: colors.healthy },
          standardWarning: { backgroundColor: colors.warningSoft, color: colors.warning },
          standardError: { backgroundColor: colors.attentionSoft, color: colors.attention },
          standardInfo: { backgroundColor: colors.neutralSoft, color: colors.textSecondary },
        },
      },
    },
  });
}

export const designLightTheme = createDesignTheme("light");
export const designDarkTheme = createDesignTheme("dark");

const designRoutePaths = ["/autopilot", "/documents", "/design"];

export function isDesignModulePath(pathname: string) {
  return designRoutePaths.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

export function DesignModuleTheme({ mode, children }: { mode: DesignMode; children: ReactNode }) {
  const colors = designTokens[mode];
  const theme = mode === "dark" ? designDarkTheme : designLightTheme;
  const vars: Record<string, string> = {
    "--design-page": colors.page,
    "--design-surface": colors.surface,
    "--design-surface-subtle": colors.surfaceSubtle,
    "--design-surface-muted": colors.surfaceMuted,
    "--design-surface-translucent": colors.surfaceTranslucent,
    "--design-primary-soft": colors.primarySoft,
    "--design-healthy-soft": colors.healthySoft,
    "--design-border": colors.border,
    "--design-border-strong": colors.borderStrong,
    "--design-card-shadow": colors.cardShadow,
    "--design-primary-line": colors.primarySoftStrong,
    "--design-atmosphere": colors.atmosphere,
    "--design-hero-gradient": colors.heroGradient,
    "--design-hero-accent-gradient": colors.heroAccentGradient,
    "--design-hero-orb-gradient": colors.heroOrbGradient,
    "--design-hero-shadow": colors.heroShadow,
  };

  return (
    <ThemeProvider theme={theme}>
      <GlobalStyles
        styles={{
          ".design-module": {
            ...vars,
            minHeight: "calc(100vh - 56px)",
            color: colors.text,
            backgroundColor: colors.page,
            "& .MuiPaper-root": { backgroundImage: "none" },
            "& .qtxpert-page-header": {
              backgroundColor: colors.surface,
              backgroundImage: "none",
              borderColor: colors.border,
              boxShadow: colors.cardShadow,
              backdropFilter: "none",
              WebkitBackdropFilter: "none",
              "&::before": { background: colors.primary },
            },
            "& .autopilot-glass": {
              background: colors.surface,
              backgroundImage: "none",
              borderColor: colors.border,
              boxShadow: colors.cardShadow,
              backdropFilter: "none",
              WebkitBackdropFilter: "none",
            },
          },
        }}
      />
      <div className="design-module">{children}</div>
    </ThemeProvider>
  );
}
