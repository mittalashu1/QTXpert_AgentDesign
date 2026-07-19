import { Card, CardContent, Stack, Typography } from "@mui/material";

const STAGES = [
  { title: "1. Normalize requirements", detail: "Merges and de-duplicates all raw input documents into a single requirements corpus." },
  { title: "2. Extract structure", detail: "Identifies business rules, actors, user journeys, acceptance criteria, integrations, dependencies, validation rules, and regulatory/non-functional requirements." },
  { title: "3. Requirement summary", detail: "Produces a concise executive summary for the dashboard." },
  { title: "4. Functional breakdown", detail: "Splits requirements into independently testable functional units." },
  { title: "5. Test scenarios", detail: "Generates high-level scenarios per functional unit across all required test types." },
  { title: "6. Detailed test cases", detail: "Expands each scenario into fully specified test cases with steps, data, and traceability." },
  { title: "7. Risk analysis", detail: "Assesses coverage gaps and high-risk areas across the generated suite." },
];

export default function PromptLibraryPage() {
  return (
    <Stack spacing={3}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>
        Prompt Library
      </Typography>
      <Typography color="text.secondary">
        The AI Test Design Agent runs these stages in sequence for every generation request.
      </Typography>
      <Stack spacing={2}>
        {STAGES.map((stage) => (
          <Card key={stage.title} sx={{ borderRadius: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {stage.title}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {stage.detail}
              </Typography>
            </CardContent>
          </Card>
        ))}
      </Stack>
    </Stack>
  );
}
