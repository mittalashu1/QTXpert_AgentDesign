import { useQuery } from "@tanstack/react-query";
import { Box, Card, CardContent, Grid, Stack, Typography } from "@mui/material";
import { testCasesApi } from "@/services/api";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import ProjectSelector from "@/components/ProjectSelector";

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Card sx={{ borderRadius: 3, height: "100%" }}>
      <CardContent>
        <Typography variant="body2" color="text.secondary">
          {label}
        </Typography>
        <Typography variant="h4" sx={{ fontWeight: 700, mt: 0.5 }}>
          {value}
        </Typography>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const { selectedProjectId, selectedProject } = useSelectedProject();

  const { data: runs } = useQuery({
    queryKey: ["history", selectedProjectId],
    queryFn: () => testCasesApi.history(selectedProjectId).then((res) => res.data),
    enabled: Boolean(selectedProjectId),
  });

  const totalTestCases = runs?.reduce((sum, run) => sum + run.test_cases.length, 0) ?? 0;
  const automationCandidates =
    runs?.reduce(
      (sum, run) => sum + run.test_cases.filter((tc) => tc.is_automation_candidate).length,
      0
    ) ?? 0;
  const automationPct = totalTestCases > 0 ? Math.round((automationCandidates / totalTestCases) * 100) : 0;
  const avgProcessingTime =
    runs && runs.length > 0
      ? (
          runs.reduce((sum, run) => sum + (run.processing_time_seconds ?? 0), 0) / runs.length
        ).toFixed(1)
      : "0.0";

  return (
    <Stack spacing={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Dashboard
          </Typography>
          <Typography color="text.secondary">
            {selectedProject ? selectedProject.name : "Select or create a project to get started"}
          </Typography>
        </Box>
        <ProjectSelector />
      </Stack>

      <Grid container spacing={2}>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard label="Recent runs" value={runs?.length ?? 0} />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard label="Generated test cases" value={totalTestCases} />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard label="Automation %" value={`${automationPct}%`} />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard label="Avg. processing time" value={`${avgProcessingTime}s`} />
        </Grid>
      </Grid>

      <Card sx={{ borderRadius: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Recent requests
          </Typography>
          {!runs || runs.length === 0 ? (
            <Typography color="text.secondary">
              No generation runs yet - upload a requirement and generate your first test cases.
            </Typography>
          ) : (
            <Stack spacing={1.5}>
              {runs.slice(0, 5).map((run) => (
                <Box
                  key={run.id}
                  sx={{
                    display: "flex",
                    justifyContent: "space-between",
                    borderBottom: "1px solid",
                    borderColor: "divider",
                    pb: 1.5,
                  }}
                >
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      Run {run.id.slice(0, 8)}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {run.llm_provider} / {run.llm_model} - {run.test_cases.length} test cases
                    </Typography>
                  </Box>
                  <Typography
                    variant="body2"
                    sx={{
                      color:
                        run.status === "completed"
                          ? "success.main"
                          : run.status === "failed"
                          ? "error.main"
                          : "warning.main",
                      fontWeight: 600,
                    }}
                  >
                    {run.status}
                  </Typography>
                </Box>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>
    </Stack>
  );
}
