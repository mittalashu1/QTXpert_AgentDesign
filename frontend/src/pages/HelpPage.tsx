import { Card, CardContent, Stack, Typography } from "@mui/material";

const FAQ = [
  {
    q: "What file types can I upload?",
    a: "PDF, DOCX, TXT, and Markdown for BRDs; JSON or CSV for Jira exports.",
  },
  {
    q: "How is my LLM provider selected?",
    a: "Set it in Settings \u2192 API Configuration. The active provider is used for every generation run unless overridden per-request.",
  },
  {
    q: "What export formats are supported?",
    a: "JSON, CSV, Excel, Markdown, and ready-to-import payloads for TestRail, Zephyr, Xray, and Azure DevOps Test Plans.",
  },
  {
    q: "How are automation candidates identified?",
    a: "Each generated test case is flagged by the agent based on stability, repeatability, and ROI of automating that scenario.",
  },
];

export default function HelpPage() {
  return (
    <Stack spacing={3}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>
        Help
      </Typography>
      <Stack spacing={2}>
        {FAQ.map((item) => (
          <Card key={item.q} sx={{ borderRadius: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {item.q}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {item.a}
              </Typography>
            </CardContent>
          </Card>
        ))}
      </Stack>
    </Stack>
  );
}
