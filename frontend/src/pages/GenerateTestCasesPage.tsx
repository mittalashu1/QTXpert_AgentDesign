"use client";

import { ChangeEvent, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Drawer,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

type CaseType = "Functional" | "Negative" | "Security" | "Accessibility";
type Priority = "High" | "Medium" | "Low";
type TestCase = {
  id: string;
  title: string;
  type: CaseType;
  priority: Priority;
  steps: string;
  expected: string;
};

const seedCases: TestCase[] = [
  { id: "TC-001", title: "Sign in with valid credentials", type: "Functional", priority: "High", steps: "1. Open the sign-in page\n2. Enter a registered email\n3. Enter the correct password\n4. Select Sign in", expected: "The user is authenticated and taken to their dashboard." },
  { id: "TC-002", title: "Reject an incorrect password", type: "Negative", priority: "High", steps: "1. Open the sign-in page\n2. Enter a registered email\n3. Enter an incorrect password\n4. Select Sign in", expected: "A clear error appears and the account remains secure." },
  { id: "TC-003", title: "Recover a forgotten password", type: "Functional", priority: "Medium", steps: "1. Select Forgot password\n2. Enter a registered email\n3. Submit the request", expected: "A password reset link is sent and confirmation is shown." },
  { id: "TC-004", title: "Prevent repeated brute-force attempts", type: "Security", priority: "High", steps: "1. Attempt sign-in with invalid credentials repeatedly\n2. Observe the response after the configured limit", expected: "Further attempts are throttled or temporarily blocked." },
  { id: "TC-005", title: "Complete sign-in using the keyboard", type: "Accessibility", priority: "Medium", steps: "1. Navigate all fields with Tab\n2. Enter credentials\n3. Submit using Enter", expected: "Focus order is logical and the form works without a pointer." },
];

const sources = [
  ["◈", "App or APK", "Analyze screens and flows"],
  ["J", "Jira", "Link stories or epics"],
  ["C", "Confluence", "Import requirements"],
  ["↗", "Website URL", "Explore a live product"],
  ["▤", "Documents", "PDF, DOCX, XLSX"],
  ["▶", "Video recording", "MP4, MOV, walkthrough"],
];

const journeys = ["Sign in", "Password reset", "Session security", "Profile setup", "Notifications"];

const buttonSx = { textTransform: "none", borderRadius: 2, fontWeight: 700 };
const teal = "#0a9b9d";

export default function GenerateTestCasesPage() {
  const [stage, setStage] = useState<"compose" | "analyze" | "results">("compose");
  const [prompt, setPrompt] = useState("Create comprehensive test cases for the authentication flow, including happy paths, edge cases and accessibility.");
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [sourceLink, setSourceLink] = useState("");
  const [files, setFiles] = useState<string[]>([]);
  const [focus, setFocus] = useState<string[]>(journeys.slice(0, 3));
  const [cases, setCases] = useState<TestCase[]>(seedCases);
  const [selected, setSelected] = useState(0);
  const [search, setSearch] = useState("");
  const [assistantOpen, setAssistantOpen] = useState(true);
  const [assistantPrompt, setAssistantPrompt] = useState("");
  const [message, setMessage] = useState("I can refine coverage, rewrite a case, or add scenarios while you review.");
  const [toast, setToast] = useState("");
  const [chatMode, setChatMode] = useState<"new" | "current">("new");
  const [exportOpen, setExportOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const current = cases[selected] ?? cases[0];
  const filteredCases = useMemo(() => cases.filter((item) => item.title.toLowerCase().includes(search.toLowerCase())), [cases, search]);

  const notify = (text: string) => {
    setToast(text);
    window.setTimeout(() => setToast(""), 2400);
  };

  const startNewChat = () => {
    setChatMode("new");
    setStage("compose");
    setPrompt("");
    setSelectedSource(null);
    setSourceLink("");
    setFiles([]);
    setFocus(journeys.slice(0, 3));
    setCases(seedCases);
    setSelected(0);
    notify("Started a new test-design chat");
  };

  const continueChat = () => {
    const saved = window.localStorage.getItem("qtxpert.test-suite");
    if (!saved) return notify("No saved suite yet — generate and save one first");
    try {
      const snapshot = JSON.parse(saved) as { cases?: TestCase[]; prompt?: string; files?: string[] };
      setCases(snapshot.cases?.length ? snapshot.cases : seedCases);
      setPrompt(snapshot.prompt ?? "");
      setFiles(snapshot.files ?? []);
      setChatMode("current");
      setStage("results");
      setSelected(0);
      notify("Continued your saved test-design chat");
    } catch {
      notify("The saved suite could not be restored");
    }
  };

  const saveSuite = () => {
    window.localStorage.setItem("qtxpert.test-suite", JSON.stringify({ cases, prompt, files, savedAt: new Date().toISOString() }));
    notify("Test suite saved — you can continue this chat later");
  };

  const downloadCases = (format: "csv" | "json") => {
    const rows = cases.map((item) => ({ ID: item.id, Title: item.title, Type: item.type, Priority: item.priority, Steps: item.steps, Expected: item.expected }));
    const body = format === "json" ? JSON.stringify(rows, null, 2) : `\ufeff${["ID", "Title", "Type", "Priority", "Steps", "Expected"].join(",")}\n${rows.map((row) => [row.ID, row.Title, row.Type, row.Priority, row.Steps, row.Expected].map((value) => `"${String(value).replaceAll('"', '""')}"`).join(",")).join("\n")}`;
    const blob = new Blob([body], { type: format === "json" ? "application/json" : "text/csv;charset=utf-8" });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `qtxpert-test-cases.${format}`;
    anchor.click();
    window.URL.revokeObjectURL(url);
    setExportOpen(false);
    notify(`Downloaded ${format.toUpperCase()} test cases`);
  };

  const updateCurrent = (field: keyof TestCase, value: string) => {
    setCases((items) => items.map((item, index) => index === selected ? { ...item, [field]: value } as TestCase : item));
  };

  const addEdgeCase = () => {
    const next: TestCase = { id: `TC-${String(cases.length + 1).padStart(3, "0")}`, title: "Lock the account after repeated failed attempts", type: "Security", priority: "High", steps: "1. Submit invalid credentials until the limit is reached\n2. Attempt another sign in\n3. Wait for the lockout period", expected: "The account is protected, the user sees a helpful message, and no sensitive details are exposed." };
    setCases((items) => [...items, next]);
    setSelected(cases.length);
    setMessage("Added a high-priority security case and selected it for review.");
    notify("New edge case added");
  };

  const applyAssistant = (action: "edge" | "mobile" | "expected") => {
    if (action === "edge") return addEdgeCase();
    if (action === "mobile") {
      updateCurrent("steps", `${current.steps}\n5. Repeat on a small-screen mobile viewport`);
      setMessage("Added a responsive/mobile step to the selected case.");
      return notify("Mobile coverage added");
    }
    updateCurrent("expected", `${current.expected} Include a clear, actionable message and preserve the user session state.`);
    setMessage("Tightened the expected result so it is easier to verify and debug.");
    notify("Expected result improved");
  };

  const askAssistant = () => {
    const request = assistantPrompt.trim();
    if (!request) return;
    setAssistantPrompt("");
    if (/edge|negative|security/i.test(request)) return applyAssistant("edge");
    if (/mobile|device|responsive/i.test(request)) return applyAssistant("mobile");
    applyAssistant("expected");
  };

  const handleFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const names = Array.from(event.target.files ?? []).map((file) => file.name);
    if (names.length) {
      setFiles((items) => [...items, ...names]);
      notify(`${names.length} source${names.length > 1 ? "s" : ""} ready to analyze`);
    }
  };

  const buildSuite = () => {
    if (!files.length && !prompt.trim() && !selectedSource) return notify("Add a source or describe what you want to test first");
    setStage("analyze");
  };

  if (stage === "analyze") {
    return (
      <Box sx={{ maxWidth: 980, mx: "auto", px: { xs: 2, md: 5 }, py: 6 }}>
        <Stack alignItems="center" spacing={1.2} sx={{ mb: 3 }}>
          <Box sx={{ width: 58, height: 58, borderRadius: "50%", display: "grid", placeItems: "center", bgcolor: teal, color: "white", fontSize: 26, boxShadow: `0 0 0 10px #dff7f5` }}>✦</Box>
          <Typography variant="overline" sx={{ color: teal, fontWeight: 800, letterSpacing: ".16em" }}>QTXPERT VISION AI</Typography>
          <Typography variant="h3" sx={{ fontWeight: 800, textAlign: "center", fontSize: { xs: 30, md: 38 } }}>Your app is mapped. Shape the coverage.</Typography>
          <Typography color="text.secondary" sx={{ maxWidth: 650, textAlign: "center" }}>We explored your sources and drafted journeys in plain English. Adjust the focus while test cases are assembled.</Typography>
        </Stack>
        <Paper sx={{ p: { xs: 2, md: 3 }, borderRadius: 3 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
            <Stack direction="row" spacing={1.5} alignItems="center"><Chip label="APK" size="small" sx={{ bgcolor: "#eee7ff", color: "#6e43c9", fontWeight: 800 }} /><Box><Typography fontWeight={800}>{files[0] ?? "Uploaded product"}</Typography><Typography variant="caption" color="text.secondary">18 screens · 7 user journeys detected</Typography></Box></Stack>
            <Chip label="✓ Analysis complete" size="small" sx={{ bgcolor: "#e9f8f1", color: "#078f73" }} />
          </Stack>
          <Box sx={{ height: 6, bgcolor: "#e7edef", borderRadius: 5, mb: 3 }}><Box sx={{ width: "100%", height: "100%", bgcolor: teal, borderRadius: 5 }} /></Box>
          <Stack direction={{ xs: "column", md: "row" }} spacing={3}>
            <Box flex={1}><Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>Detected journeys <Chip label="7" size="small" sx={{ ml: 1, height: 20, bgcolor: "#e6f7f5", color: teal }} /></Typography>{journeys.map((journey, index) => <Button key={journey} fullWidth onClick={() => setFocus((items) => items.includes(journey) ? items.filter((item) => item !== journey) : [...items, journey])} sx={{ ...buttonSx, justifyContent: "flex-start", mb: 1, px: 1.5, border: "1px solid", borderColor: focus.includes(journey) ? "#91d8d4" : "#e0e7ea", bgcolor: focus.includes(journey) ? "#f2fbfa" : "white", color: "#143d4d" }}><Box component="span" sx={{ width: 20, height: 20, mr: 1, borderRadius: 1, display: "grid", placeItems: "center", bgcolor: focus.includes(journey) ? teal : "#edf3f4", color: focus.includes(journey) ? "white" : "#789", fontSize: 11 }}>{index < 3 ? "✓" : "+"}</Box><Box component="span" sx={{ flex: 1, textAlign: "left" }}>{journey}</Box><Typography variant="caption" color="text.secondary">{index + 3} scenarios</Typography></Button>)}</Box>
            <Box flex={1} sx={{ bgcolor: "#f7fafb", p: 2, borderRadius: 2 }}><Typography variant="subtitle2" fontWeight={800}>Test plan preview</Typography><Stack direction="row" spacing={1.5} alignItems="center" sx={{ my: 1.5 }}><Typography variant="h3" sx={{ color: teal, fontWeight: 800 }}>24</Typography><Box><Typography fontWeight={800}>Cases planned</Typography><Typography variant="caption" color="text.secondary">Across {focus.length} selected journeys</Typography></Box></Stack><Divider /><Stack spacing={.7} sx={{ py: 1.5 }}>{[["Happy paths", 7], ["Negative & edge cases", 8], ["Security checks", 5], ["Accessibility", 4]].map(([label, count]) => <Stack direction="row" key={String(label)}><Typography variant="caption" color="text.secondary">● &nbsp;{label}</Typography><Typography variant="caption" fontWeight={800} sx={{ ml: "auto" }}>{count}</Typography></Stack>)}</Stack><TextField label="Tell QTXpert what else matters" multiline minRows={3} fullWidth value={prompt} onChange={(event) => setPrompt(event.target.value)} /></Box>
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }} spacing={2} sx={{ mt: 3, pt: 2, borderTop: "1px solid #e2e9eb" }}><Typography variant="caption" color="text.secondary">✦ You can edit every case after generation</Typography><Button variant="contained" onClick={() => setStage("results")} sx={{ ...buttonSx, bgcolor: teal }}>Build my test suite →</Button></Stack>
        </Paper>
      </Box>
    );
  }

  if (stage === "results") {
    return (
      <Box sx={{ px: { xs: 2, md: 4 }, py: 3, pr: { md: assistantOpen ? 45 : 4 } }}>
        <Stack direction={{ xs: "column", lg: "row" }} justifyContent="space-between" alignItems={{ xs: "stretch", lg: "end" }} spacing={2} sx={{ mb: 2 }}><Box><Button onClick={() => setStage("compose")} sx={{ ...buttonSx, color: "#658091", px: 0, mb: 1 }}>← Back to inputs</Button><Typography variant="h4" sx={{ fontWeight: 800 }}>Authentication test suite <Chip label="AI GENERATED" size="small" sx={{ ml: 1, bgcolor: "#e4f7f5", color: "#097d80", fontSize: 10 }} /></Typography><Typography variant="body2" color="text.secondary">Generated from <b>{files[0] ?? selectedSource ?? "your guidance"}</b> and your guidance</Typography></Box><Stack direction="row" spacing={1} flexWrap="wrap"><Button onClick={() => setAssistantOpen((value) => !value)} sx={{ ...buttonSx, border: "1px solid #d7e1e5" }}>✦ {assistantOpen ? "Hide" : "Open"} AI copilot</Button><Button onClick={() => setStage("analyze")} sx={{ ...buttonSx, border: "1px solid #d7e1e5" }}>↻ Regenerate</Button><Box sx={{ position: "relative" }}><Button onClick={() => setExportOpen((value) => !value)} sx={{ ...buttonSx, border: "1px solid #d7e1e5" }}>⇩ Export</Button>{exportOpen && <Paper sx={{ position: "absolute", right: 0, top: 44, zIndex: 8, p: .5, minWidth: 160 }}><Button fullWidth onClick={() => downloadCases("csv")} sx={{ ...buttonSx, justifyContent: "flex-start" }}>Excel-compatible CSV</Button><Button fullWidth onClick={() => downloadCases("json")} sx={{ ...buttonSx, justifyContent: "flex-start" }}>JSON</Button></Paper>}</Box><Button onClick={saveSuite} variant="contained" sx={{ ...buttonSx, bgcolor: teal }}>Save suite</Button><Button onClick={startNewChat} sx={{ ...buttonSx, border: "1px solid #d7e1e5" }}>＋ New chat</Button></Stack></Stack>
        <Paper sx={{ p: 2, mb: 2, borderRadius: 2 }}><Stack direction={{ xs: "column", md: "row" }} spacing={3}>{[["✓", "24", "Test cases"], ["◒", "92%", "Flow coverage"], ["!", "8", "High priority"], ["✦", "6", "Edge cases"]].map(([icon, value, label]) => <Stack direction="row" spacing={1} key={label} sx={{ minWidth: 125 }}><Chip label={icon} size="small" sx={{ bgcolor: "#e7f8f6", color: teal }} /><Box><Typography fontWeight={800}>{value}</Typography><Typography variant="caption" color="text.secondary">{label}</Typography></Box></Stack>)}<Box flex={1}><Stack direction="row" justifyContent="space-between"><Typography variant="caption" fontWeight={800}>Coverage looks strong</Typography><Typography variant="caption" color="text.secondary">2 suggestions to review</Typography></Stack><Box sx={{ mt: 1, height: 6, bgcolor: "#e7edef", borderRadius: 5 }}><Box sx={{ width: "92%", height: "100%", bgcolor: "#18bdb4", borderRadius: 5 }} /></Box></Box></Stack></Paper>
        <Stack direction={{ xs: "column", md: "row" }} sx={{ minHeight: 600, border: "1px solid #dce5e8", borderRadius: 3, overflow: "hidden", bgcolor: "white" }}><Box sx={{ width: { xs: "100%", md: 340 }, borderRight: { md: "1px solid #dce5e8" }, bgcolor: "#fafcfc", p: 1.5 }}><TextField fullWidth size="small" placeholder="Search test cases" value={search} onChange={(event) => setSearch(event.target.value)} sx={{ mb: 1.5, bgcolor: "white" }} />{filteredCases.map((item) => { const index = cases.findIndex((entry) => entry.id === item.id); return <Button key={item.id} fullWidth onClick={() => setSelected(index)} sx={{ ...buttonSx, justifyContent: "flex-start", textAlign: "left", mb: .5, p: 1.2, border: "1px solid", borderColor: index === selected ? "#a7dedd" : "transparent", bgcolor: index === selected ? "white" : "transparent", color: "#102238" }}><Box sx={{ flex: 1, minWidth: 0 }}><Typography variant="caption" color="text.secondary" display="block">{item.id} · {item.type}</Typography><Typography variant="body2" fontWeight={800} noWrap>{item.title}</Typography><Chip label={item.priority} size="small" sx={{ mt: .5, height: 20, fontSize: 10, color: item.priority === "High" ? "#d25555" : "#3a7e9a", bgcolor: item.priority === "High" ? "#ffeded" : "#e8f5fa" }} /></Box><Typography color="text.secondary">›</Typography></Button>})}<Button fullWidth onClick={() => { const next = { ...seedCases[0], id: `TC-${String(cases.length + 1).padStart(3, "0")}`, title: "Untitled test case" }; setCases((items) => [...items, next]); setSelected(cases.length); }} sx={{ ...buttonSx, mt: 1, border: "1px dashed #b9c9cf", color: teal }}>＋ Add test case</Button></Box>
          <Box sx={{ flex: 1, p: { xs: 2, md: 3 } }}><Stack direction="row" justifyContent="space-between" sx={{ mb: 2 }}><Stack direction="row" spacing={1}><Chip label={current.id} size="small" /><Chip label={`● ${current.priority}`} size="small" sx={{ bgcolor: current.priority === "High" ? "#ffeded" : "#fff4dc" }} /></Stack><Stack direction="row" spacing={1}><IconButton size="small" onClick={() => notify("Test case duplicated")}>▣</IconButton><IconButton size="small" onClick={() => notify("Test case menu opened")}>•••</IconButton></Stack></Stack><TextField fullWidth label="Test case title" value={current.title} onChange={(event) => updateCurrent("title", event.target.value)} sx={{ mb: 2 }} /><Stack direction={{ xs: "column", sm: "row" }} spacing={2}><TextField select fullWidth label="Type" value={current.type} onChange={(event) => updateCurrent("type", event.target.value)} sx={{ mb: 2 }}>{["Functional", "Negative", "Security", "Accessibility"].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField><TextField select fullWidth label="Priority" value={current.priority} onChange={(event) => updateCurrent("priority", event.target.value)} sx={{ mb: 2 }}>{["High", "Medium", "Low"].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}</TextField></Stack><TextField fullWidth multiline minRows={2} label="Preconditions" defaultValue={"• A registered user account exists\n• The user is signed out"} sx={{ mb: 2 }} /><TextField fullWidth multiline minRows={5} label="Test steps" value={current.steps} onChange={(event) => updateCurrent("steps", event.target.value)} sx={{ mb: 2 }} /><TextField fullWidth multiline minRows={3} label="Expected result" value={current.expected} onChange={(event) => updateCurrent("expected", event.target.value)} sx={{ mb: 2 }} /><Alert severity="info" action={<Button size="small" onClick={() => { updateCurrent("steps", `${current.steps}\n5. Refresh the page and verify the session`); notify("Suggestion added"); }}>＋ Add step</Button>}>AI suggestion: verify the session persists after a page refresh.</Alert><Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mt: 2, pt: 2, borderTop: "1px solid #e3e9ec" }}><Typography variant="caption" color="text.secondary">Changes save automatically</Typography><Stack direction="row" spacing={1}><Button disabled={selected === 0} onClick={() => setSelected((value) => value - 1)} sx={buttonSx}>← Previous</Button><Button disabled={selected === cases.length - 1} onClick={() => setSelected((value) => value + 1)} sx={buttonSx}>Next case →</Button></Stack></Stack></Box>
        </Stack>
        {assistantOpen && <Drawer anchor="right" open onClose={() => setAssistantOpen(false)} variant="persistent" PaperProps={{ sx: { width: { xs: "100%", sm: 330 }, top: { xs: 0, md: 70 }, height: { xs: "100%", md: "calc(100% - 70px)" }, p: 2 } }}><Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}><Box sx={{ width: 32, height: 32, display: "grid", placeItems: "center", borderRadius: 1.5, bgcolor: teal, color: "white" }}>✦</Box><Box flex={1}><Typography fontWeight={800}>Improve with AI</Typography><Typography variant="caption" color="text.secondary">Live suite copilot</Typography></Box><IconButton onClick={() => setAssistantOpen(false)}>×</IconButton></Stack><Box sx={{ bgcolor: "#f7fafb", p: 1.5, borderRadius: 2, mb: 2 }}><Typography variant="overline" color="text.secondary">Reviewing</Typography><Typography variant="body2" fontWeight={800}>{current.id} · {current.title}</Typography></Box><Box sx={{ bgcolor: "#edf8f6", border: "1px solid #c9ebe6", p: 1.5, borderRadius: 2, mb: 2 }}><Typography variant="body2">{message}</Typography></Box><Typography variant="overline" color="text.secondary" sx={{ mb: 1 }}>Quick improvements</Typography><Stack spacing={1}>{[["Add edge cases", "Find risks happy paths miss", "edge"], ["Cover mobile layouts", "Add responsive steps", "mobile"], ["Make it more verifiable", "Tighten expected results", "expected"]].map(([title, subtitle, action]) => <Button key={title} onClick={() => applyAssistant(action as "edge" | "mobile" | "expected")} sx={{ ...buttonSx, justifyContent: "flex-start", textAlign: "left", border: "1px solid #dbe6e8", p: 1.2, color: "#263f51" }}><Box sx={{ width: 22, height: 22, display: "grid", placeItems: "center", mr: 1, bgcolor: "#e4f7f5", color: teal, borderRadius: 1 }}>＋</Box><Box><Typography variant="caption" fontWeight={800} display="block">{title}</Typography><Typography variant="caption" color="text.secondary">{subtitle}</Typography></Box></Button>)}</Stack><Box sx={{ mt: "auto", display: "flex", gap: 1, alignItems: "end", border: "1px solid #cfdfe2", borderRadius: 2, p: 1 }}><TextField fullWidth multiline minRows={2} variant="standard" placeholder="Ask for a change…" value={assistantPrompt} onChange={(event) => setAssistantPrompt(event.target.value)} InputProps={{ disableUnderline: true }} /><Button onClick={askAssistant} variant="contained" sx={{ minWidth: 38, ...buttonSx, bgcolor: teal }}>↑</Button></Box><Typography variant="caption" color="text.secondary" textAlign="center" sx={{ mt: 1 }}>AI changes are suggestions until you apply them.</Typography></Drawer>}
        {toast && <Alert severity="success" sx={{ position: "fixed", right: 24, bottom: 24, zIndex: 20 }}>{toast}</Alert>}
      </Box>
    );
  }

  return (
      <Box sx={{ maxWidth: 1100, mx: "auto", px: { xs: 2, md: 5 }, py: 5 }}>
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }} sx={{ mb: 2 }}><Chip label={chatMode === "current" ? "Continuing saved chat" : "New test-design chat"} sx={{ alignSelf: "flex-start", bgcolor: "#e4f7f5", color: teal, fontWeight: 700 }} /><Stack direction="row" spacing={1}><Button onClick={continueChat} sx={{ ...buttonSx, border: "1px solid #d7e1e5" }}>↻ Continue current chat</Button><Button onClick={startNewChat} sx={{ ...buttonSx, bgcolor: teal, color: "white" }}>＋ New chat</Button></Stack></Stack><Stack alignItems="center" spacing={1}><Typography variant="overline" sx={{ color: teal, fontWeight: 800, letterSpacing: ".15em" }}>✦ AI TEST DESIGN</Typography><Typography variant="h2" sx={{ fontWeight: 850, letterSpacing: "-.04em", textAlign: "center", fontSize: { xs: 34, md: 50 } }}>Turn anything into <Box component="span" sx={{ color: teal }}>great test cases.</Box></Typography><Typography color="text.secondary" sx={{ maxWidth: 700, textAlign: "center", mb: 3 }}>Add your product, requirements, or ideas. QTXpert analyzes everything together and builds a complete, editable test suite.</Typography></Stack>
      <Paper sx={{ p: { xs: 2, md: 3 }, borderRadius: 3 }}><Stack direction="row" justifyContent="space-between" sx={{ mb: 2 }}><Box><Typography variant="h6" fontWeight={800}>What would you like to test?</Typography><Typography variant="body2" color="text.secondary">Add one or more sources — we’ll connect the context.</Typography></Box><Chip label="1 of 2" size="small" /></Stack><Stack direction="row" flexWrap="wrap" gap={1.2}>{sources.map(([icon, title, subtitle], index) => <Button key={title} onClick={() => { setSelectedSource(title); if (["Documents", "Video recording", "App or APK"].includes(title)) fileInputRef.current?.click(); }} sx={{ ...buttonSx, flex: "1 1 30%", minWidth: 200, justifyContent: "flex-start", textAlign: "left", border: "1px solid", borderColor: selectedSource === title || index === 0 ? "#a1dcda" : "#dce5e8", bgcolor: selectedSource === title ? "#f1fbfa" : "white", p: 1.3, color: "#102238" }}><Box sx={{ width: 34, height: 34, display: "grid", placeItems: "center", mr: 1, bgcolor: selectedSource === title ? teal : "#eef4f5", color: selectedSource === title ? "white" : teal, borderRadius: 1.5, fontWeight: 800 }}>{icon}</Box><Box flex={1}><Typography variant="body2" fontWeight={800}>{title}</Typography><Typography variant="caption" color="text.secondary">{subtitle}</Typography></Box><Typography color="text.secondary">{selectedSource === title ? "✓" : "＋"}</Typography></Button>)}</Stack><input ref={fileInputRef} hidden type="file" multiple onChange={handleFiles} /> <Box onClick={() => fileInputRef.current?.click()} sx={{ mt: 1.5, p: 2, border: "1.5px dashed #a9c5ca", borderRadius: 2, bgcolor: "#fbfdfd", cursor: "pointer" }}><Stack direction="row" spacing={1.5} alignItems="center"><Box sx={{ width: 40, height: 40, display: "grid", placeItems: "center", borderRadius: 1.5, bgcolor: "#e5f8f6", color: teal, fontSize: 22 }}>⇧</Box><Box flex={1}><Typography variant="body2" fontWeight={800}>Drop an app, APK, document, or video here</Typography><Typography variant="caption" color="text.secondary">or click to browse · Up to 500 MB per file</Typography></Box><Chip label="AUTO-DETECT" size="small" sx={{ bgcolor: "#e4f8f6", color: teal, fontSize: 9 }} /></Stack></Box>{files.map((file) => <Stack key={file} direction="row" spacing={1.2} alignItems="center" sx={{ mt: 1, p: 1.2, border: "1px solid #dce8e8", borderRadius: 2, bgcolor: "#f8fcfb" }}><Chip label={file.toLowerCase().endsWith(".apk") ? "APK" : "FILE"} size="small" sx={{ bgcolor: "#eee7ff", color: "#6e43c9", fontWeight: 800 }} /><Box flex={1}><Typography variant="body2" fontWeight={800}>{file}</Typography><Typography variant="caption" color="text.secondary">Ready to analyze</Typography></Box><Button size="small" onClick={() => setFiles((items) => items.filter((item) => item !== file))} sx={{ ...buttonSx, minWidth: 32, color: "#7b8c96" }}>×</Button></Stack>)}{selectedSource && !["Documents", "Video recording", "App or APK"].includes(selectedSource) && <TextField fullWidth label={`${selectedSource} link`} placeholder="Paste a URL or issue key" value={sourceLink} onChange={(event) => setSourceLink(event.target.value)} sx={{ mt: 1.5 }} />}<Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mt: 2.5, mb: .8 }}><Typography variant="body2" fontWeight={800}>Describe the flow in plain English <Typography component="span" variant="caption" color="text.secondary">Optional</Typography></Typography><Button onClick={() => setPrompt("Focus on critical user journeys, negative scenarios, security risks, accessibility, and cross-device behavior.")} sx={{ ...buttonSx, color: teal, fontSize: 12 }}>✦ Enhance prompt</Button></Stack><TextField fullWidth multiline minRows={4} value={prompt} onChange={(event) => setPrompt(event.target.value)} /><Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" spacing={2} sx={{ mt: 2.5, pt: 2, borderTop: "1px solid #e5ebee" }}><Stack direction="row" spacing={1} alignItems="center"><Typography variant="caption" color="text.secondary">Coverage</Typography>{["Quick", "Balanced", "Thorough"].map((value) => <Button key={value} onClick={() => notify(`${value} coverage selected`)} sx={{ ...buttonSx, px: 1, color: value === "Balanced" ? teal : "#66798a", bgcolor: value === "Balanced" ? "#f2f6f7" : "transparent" }}>{value}</Button>)}</Stack><Button variant="contained" onClick={buildSuite} sx={{ ...buttonSx, bgcolor: teal, px: 3 }}>✦ Analyze & generate →</Button></Stack></Paper><Stack direction="row" justifyContent="center" spacing={3} sx={{ mt: 2 }}><Typography variant="caption" color="text.secondary">✓ Sources stay private</Typography><Typography variant="caption" color="text.secondary">✓ Review before export</Typography><Typography variant="caption" color="text.secondary">✓ Edit everything</Typography></Stack>{toast && <Alert severity="success" sx={{ position: "fixed", right: 24, bottom: 24, zIndex: 20 }}>{toast}</Alert>}</Box>
  );
}
