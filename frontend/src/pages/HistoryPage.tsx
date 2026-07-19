import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Box,
  Card,
  CardContent,
  Chip,
  Collapse,
  Stack,
  Typography,
} from "@mui/material";
import { testCasesApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import ProjectSelector from "@/components/ProjectSelector";
import TestCaseCard from "@/components/TestCaseCard";

const STATUS_COLOR: Record<string, "success" | "error" | "warning"> = {
  completed: "success",
  failed: "error",
};

export default function HistoryPage() {
  const { selectedProjectId } = useSelectedProject();
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);

  const { data: runs } = useQuery({
    queryKey: ["history", selectedProjectId],
    queryFn: () => testCasesApi.history(selectedProjectId).then((res) => res.data),
    enabled: Boolean(selectedProjectId),
  });

  return (
    <Stack spacing={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          History
        </Typography>
        <ProjectSelector />
      </Stack>

      {!runs || runs.length === 0 ? (
        <Typography color="text.secondary">No generation runs for this project yet.</Typography>
      ) : (
        <Stack spacing={2}>
          {runs.map((run) => (
            <Card key={run.id} sx={{ borderRadius: 3 }}>
              <CardContent>
                <Box
                  sx={{ display: "flex", justifyContent: "space-between", cursor: "pointer" }}
                  onClick={() => setExpandedRunId(expandedRunId === run.id ? null : run.id)}
                >
                  <Box>
                    <Typography sx={{ fontWeight: 600 }}>Run {run.id.slice(0, 8)}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(run.created_at).toLocaleString()} - {run.llm_provider}/{run.llm_model} -{" "}
                      {run.test_cases.length} test cases
                    </Typography>
                  </Box>
                  <Chip
                    size="small"
                    label={run.status}
                    color={STATUS_COLOR[run.status] ?? "warning"}
                  />
                </Box>
                <Collapse in={expandedRunId === run.id}>
                  <Stack spacing={2} sx={{ mt: 2 }}>
                    {run.error_message && (
                      <Typography color="error.main" variant="body2">
                        {run.error_message}
                      </Typography>
                    )}
                    {run.test_cases.map((tc) => (
                      <TestCaseCard key={tc.id} testCase={tc} />
                    ))}
                  </Stack>
                </Collapse>
              </CardContent>
            </Card>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
