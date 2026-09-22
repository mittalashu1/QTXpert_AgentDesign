import { Box, IconButton, Stack, Tooltip, Typography } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import type { ReactNode } from "react";
import { qtxpertEffects } from "@/theme/theme";

export default function PageHeader({ eyebrow, title, description, actions }: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  const conciseDescription = description.length > 125
    ? `${description.slice(0, 122).replace(/\s+\S*$/, "")}…`
    : description;
  return (
    <Box
      component="header"
      className="qtxpert-page-header"
      sx={(theme) => ({
        position: "relative",
        isolation: "isolate",
        display: "flex",
        flexDirection: { xs: "column", sm: "row" },
        justifyContent: "space-between",
        alignItems: { xs: "stretch", sm: "center" },
        gap: 1.25,
        mb: 1.5,
        p: { xs: 1.25, sm: 1.5 },
        border: "1px solid",
        borderColor: theme.palette.mode === "dark" ? "rgba(255,255,255,.14)" : "rgba(255,255,255,.92)",
        borderRadius: 2.5,
        backgroundColor: theme.palette.mode === "dark" ? qtxpertEffects.glassSurfaceDark : qtxpertEffects.glassSurfaceLight,
        backgroundImage: theme.palette.mode === "dark" ? qtxpertEffects.glassSheenDark : qtxpertEffects.heroGradient,
        backdropFilter: "blur(18px) saturate(150%)",
        WebkitBackdropFilter: "blur(18px) saturate(150%)",
        boxShadow: theme.palette.mode === "dark"
          ? "inset 0 1px 0 rgba(255,255,255,.07), 0 8px 24px rgba(0,0,0,.14)"
          : "inset 0 1px 0 rgba(255,255,255,.96), 0 8px 24px rgba(70,50,120,.045)",
        "&::before": {
          content: "\"\"",
          position: "absolute",
          zIndex: -1,
          top: 12,
          bottom: 12,
          left: 0,
          width: 3,
          borderRadius: 3,
          background: `linear-gradient(180deg, ${theme.palette.primary.light}, ${theme.palette.primary.main})`,
        },
        "& > *": { minWidth: 0 },
      })}
    >
      <Box sx={{ minWidth: 0, pl: 0.25 }}>
        <Typography variant="overline" color="primary.main" sx={{ fontWeight: 750, letterSpacing: ".1em", lineHeight: 1.2 }}>{eyebrow}</Typography>
        <Typography variant="h4" sx={{ mt: -0.2, fontWeight: 750 }}>{title}</Typography>
        <Stack direction="row" spacing={0.25} alignItems="center" sx={{ mt: 0.25 }}>
          <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.45 }}>{conciseDescription}</Typography>
          {conciseDescription !== description && <Tooltip title={description} placement="right"><IconButton size="small" aria-label={`More about ${title}`} sx={{ p: 0.35 }}><InfoOutlinedIcon sx={{ fontSize: 15 }} /></IconButton></Tooltip>}
        </Stack>
      </Box>
      {actions}
    </Box>
  );
}


