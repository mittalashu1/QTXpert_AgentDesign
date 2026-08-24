import { Accordion, AccordionDetails, AccordionSummary, Box, Chip, Stack, Typography } from "@mui/material";
import ExpandMoreOutlinedIcon from "@mui/icons-material/ExpandMoreOutlined";
import { TestCase } from "@/types/domain";

const PRIORITY_COLOR: Record<string, "error" | "warning" | "info" | "default"> = {
  critical: "error",
  high: "warning",
  medium: "info",
  low: "default",
};

const RISK_COLOR: Record<string, "error" | "warning" | "success"> = {
  high: "error",
  medium: "warning",
  low: "success",
};

export default function TestCaseCard({ testCase }: { testCase: TestCase }) {
  return (
    <Accordion variant="outlined" disableGutters sx={{ borderRadius: 2, "&:before": { display: "none" } }}>
      <AccordionSummary expandIcon={<ExpandMoreOutlinedIcon />} sx={{ px: 2, py: 0.5 }}>
        <Stack spacing={0.6} sx={{ minWidth: 0, pr: 1 }}>
          <Typography variant="caption" color="text.secondary">
            {testCase.test_case_key}
            {testCase.requirement_traceability ? ` \u2022 ${testCase.requirement_traceability}` : ""}
          </Typography>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={{ xs: 0.25, sm: 1 }} alignItems={{ xs: "flex-start", sm: "center" }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: { xs: "calc(100vw - 120px)", sm: 680 } }}>
              {testCase.scenario || "Untitled scenario"}
            </Typography>
            <Typography variant="caption" color="text.secondary">Expand for details</Typography>
          </Stack>
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={testCase.test_type.replace(/_/g, " ")} />
            <Chip size="small" color={PRIORITY_COLOR[testCase.priority]} label={testCase.priority} />
            <Chip size="small" color={RISK_COLOR[testCase.risk_level]} label={`${testCase.risk_level} risk`} />
            {testCase.is_automation_candidate && <Chip size="small" color="primary" label="Automatable" />}
          </Stack>
        </Stack>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 2, pb: 2 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {testCase.objective}
        </Typography>

        {testCase.preconditions && (
          <Typography variant="body2" sx={{ mb: 1 }}>
            <strong>Preconditions:</strong> {testCase.preconditions}
          </Typography>
        )}

        <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
          Steps
        </Typography>
        <Box component="ol" sx={{ m: 0, pl: 2.5 }}>
          {testCase.steps.map((step, idx) => (
            <Typography component="li" variant="body2" key={idx}>
              {step}
            </Typography>
          ))}
        </Box>

        <Typography variant="body2" sx={{ mt: 1 }}>
          <strong>Expected result:</strong> {testCase.expected_result}
        </Typography>
        {testCase.post_conditions && (
          <Typography variant="body2">
            <strong>Post-conditions:</strong> {testCase.post_conditions}
          </Typography>
        )}
      </AccordionDetails>
    </Accordion>
  );
}

