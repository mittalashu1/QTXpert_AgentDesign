import { Box, Typography } from "@mui/material";
import type { ReactNode } from "react";

export default function PageHeader({ eyebrow, title, description, actions }: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: { xs: "flex-start", md: "center" }, gap: 2, mb: 3 }}>
      <Box>
        <Typography variant="overline" color="primary.main" sx={{ fontWeight: 700, letterSpacing: ".14em" }}>{eyebrow}</Typography>
        <Typography variant="h4" sx={{ mt: -0.5 }}>{title}</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.75 }}>{description}</Typography>
      </Box>
      {actions}
    </Box>
  );
}

