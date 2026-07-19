import { Box, Chip, Stack, Typography } from "@mui/material";
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
    <Box sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, p: 2 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
        <Box>
          <Typography variant="caption" color="text.secondary">
            {testCase.test_case_key}
            {testCase.requirement_traceability ? ` \u2022 ${testCase.requirement_traceability}` : ""}
          </Typography>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {testCase.scenario}
          </Typography>
        </Box>
        <Stack direction="row" spacing={0.5}>
          <Chip size="small" label={testCase.test_type.replace(/_/g, " ")} />
          <Chip size="small" color={PRIORITY_COLOR[testCase.priority]} label={testCase.priority} />
          <Chip size="small" color={RISK_COLOR[testCase.risk_level]} label={`${testCase.risk_level} risk`} />
          {testCase.is_automation_candidate && (
            <Chip size="small" color="primary" label="Automatable" />
          )}
        </Stack>
      </Stack>

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
    </Box>
  );
}
