import { Box, IconButton, Stack, Tooltip, Typography } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import type { ReactNode } from "react";

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
    <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: { xs: "flex-start", md: "center" }, gap: 1.5, mb: 2 }}>
      <Box>
        <Typography variant="overline" color="primary.main" sx={{ fontWeight: 700, letterSpacing: ".12em", lineHeight: 1.2 }}>{eyebrow}</Typography>
        <Typography variant="h4" sx={{ mt: -0.25 }}>{title}</Typography>
        <Stack direction="row" spacing={0.25} alignItems="center" sx={{ mt: 0.35 }}>
          <Typography variant="body2" color="text.secondary">{conciseDescription}</Typography>
          {conciseDescription !== description && <Tooltip title={description} placement="right"><IconButton size="small" aria-label={`More about ${title}`} sx={{ p: 0.35 }}><InfoOutlinedIcon sx={{ fontSize: 15 }} /></IconButton></Tooltip>}
        </Stack>
      </Box>
      {actions}
    </Box>
  );
}

