import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  Link,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import AddLinkOutlinedIcon from "@mui/icons-material/AddLinkOutlined";
import AdminPanelSettingsOutlinedIcon from "@mui/icons-material/AdminPanelSettingsOutlined";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import HubOutlinedIcon from "@mui/icons-material/HubOutlined";
import KeyOutlinedIcon from "@mui/icons-material/KeyOutlined";
import OpenInNewOutlinedIcon from "@mui/icons-material/OpenInNewOutlined";
import PeopleAltOutlinedIcon from "@mui/icons-material/PeopleAltOutlined";
import SecurityOutlinedIcon from "@mui/icons-material/SecurityOutlined";
import SettingsSuggestOutlinedIcon from "@mui/icons-material/SettingsSuggestOutlined";
import { useAuth } from "@/contexts/AuthContext";
import { useSelectedProject } from "@/hooks/useSelectedProject";
import { settingsApi } from "@/services/api";
import {
  IntegrationCatalogItem,
  IntegrationConnection,
  IntegrationConnectionTestResult,
  IntegrationNotificationMode,
  IntegrationOverview,
  IntegrationProvider,
  IntegrationScope,
  IntegrationUserPreferences,
} from "@/types/domain";
import { useNavigate } from "react-router-dom";

type SettingsTab = "overview" | "integrations" | "preferences" | "access";

interface IntegrationFormState {
  provider: IntegrationProvider;
  name: string;
  scope: IntegrationScope;
  projectId: string;
  baseUrl: string;
  externalOrg: string;
  externalProject: string;
  secretRef: string;
  scopes: string;
  notes: string;
  enabled: boolean;
}

const EMPTY_PREFERENCES: Omit<IntegrationUserPreferences, "id" | "user_id" | "created_at" | "updated_at"> = {
  default_provider: null,
  default_connection_id: null,
  notifications_enabled: true,
  notification_mode: "important",
  timezone: "Asia/Dubai",
};

function providerLabel(catalog: IntegrationCatalogItem[], provider: IntegrationProvider) {
  return catalog.find((item) => item.key === provider)?.label ?? provider;
}

function emptyForm(catalog: IntegrationCatalogItem[], provider: IntegrationProvider = "jira"): IntegrationFormState {
  return {
    provider,
    name: `${providerLabel(catalog, provider)} connection`,
    scope: "organization",
    projectId: "",
    baseUrl: "",
    externalOrg: "",
    externalProject: "",
    secretRef: "",
    scopes: "",
    notes: "",
    enabled: false,
  };
}

function errorMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return error instanceof Error ? error.message : "The settings request could not be completed.";
}

function statusLabel(status: IntegrationConnection["status"]) {
  return {
    not_configured: "Not configured",
    configured: "Configured",
    ready_for_test: "Ready for validation",
    needs_reauth: "Needs authentication",
    error: "Needs attention",
    disabled: "Disabled",
  }[status];
}

function statusColor(status: IntegrationConnection["status"]): "success" | "warning" | "error" | "info" | "default" {
  if (status === "configured") return "success";
  if (status === "needs_reauth" || status === "not_configured") return "warning";
  if (status === "error") return "error";
  if (status === "ready_for_test") return "info";
  return "default";
}

export default function SettingsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { selectedProject } = useSelectedProject();
  const queryClient = useQueryClient();
  const canManage = user?.role === "admin" || user?.role === "qa_lead";
  const [tab, setTab] = useState<SettingsTab>("overview");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<IntegrationConnection | null>(null);
  const [form, setForm] = useState<IntegrationFormState>(emptyForm([]));
  const [preferences, setPreferences] = useState(EMPTY_PREFERENCES);
  const [notice, setNotice] = useState<{ severity: "success" | "info" | "warning" | "error"; text: string } | null>(null);
  const [testResult, setTestResult] = useState<IntegrationConnectionTestResult | null>(null);

  const overviewQuery = useQuery<IntegrationOverview>({
    queryKey: ["settings-overview"],
    queryFn: () => settingsApi.integrationOverview().then((response) => response.data),
  });
  const catalogQuery = useQuery<IntegrationCatalogItem[]>({
    queryKey: ["integration-catalog"],
    queryFn: () => settingsApi.integrationCatalog().then((response) => response.data),
  });
  const catalog = useMemo(
    () => overviewQuery.data?.catalog ?? catalogQuery.data ?? [],
    [overviewQuery.data?.catalog, catalogQuery.data],
  );
  const connectionsQuery = useQuery<IntegrationConnection[]>({
    queryKey: ["integration-connections"],
    queryFn: () => settingsApi.listIntegrations().then((response) => response.data),
    enabled: canManage,
  });
  const preferencesQuery = useQuery<IntegrationUserPreferences | null>({
    queryKey: ["integration-preferences"],
    queryFn: () => settingsApi.getIntegrationPreferences().then((response) => response.data),
  });

  useEffect(() => {
    const saved = preferencesQuery.data;
    if (!saved) return;
    setPreferences({
      default_provider: saved.default_provider,
      default_connection_id: saved.default_connection_id,
      notifications_enabled: saved.notifications_enabled,
      notification_mode: saved.notification_mode,
      timezone: saved.timezone,
    });
  }, [preferencesQuery.data]);

  const createMutation = useMutation({
    mutationFn: (payload: Parameters<typeof settingsApi.createIntegration>[0]) => settingsApi.createIntegration(payload),
    onSuccess: () => {
      setFormOpen(false);
      setNotice({ severity: "success", text: "Integration metadata saved. Validate it before enabling a sync." });
      void queryClient.invalidateQueries({ queryKey: ["integration-connections"] });
      void queryClient.invalidateQueries({ queryKey: ["settings-overview"] });
    },
    onError: (error) => setNotice({ severity: "error", text: errorMessage(error) }),
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Parameters<typeof settingsApi.updateIntegration>[1] }) => settingsApi.updateIntegration(id, payload),
    onSuccess: () => {
      setFormOpen(false);
      setNotice({ severity: "success", text: "Integration settings updated." });
      void queryClient.invalidateQueries({ queryKey: ["integration-connections"] });
      void queryClient.invalidateQueries({ queryKey: ["settings-overview"] });
    },
    onError: (error) => setNotice({ severity: "error", text: errorMessage(error) }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => settingsApi.deleteIntegration(id),
    onSuccess: () => {
      setNotice({ severity: "success", text: "Integration connection removed." });
      void queryClient.invalidateQueries({ queryKey: ["integration-connections"] });
      void queryClient.invalidateQueries({ queryKey: ["settings-overview"] });
    },
    onError: (error) => setNotice({ severity: "error", text: errorMessage(error) }),
  });
  const testMutation = useMutation({
    mutationFn: (id: string) => settingsApi.testIntegration(id).then((response) => response.data),
    onSuccess: (result) => {
      setTestResult(result);
      setNotice({ severity: result.external_call_made ? "success" : "info", text: result.message });
      void queryClient.invalidateQueries({ queryKey: ["integration-connections"] });
      void queryClient.invalidateQueries({ queryKey: ["settings-overview"] });
    },
    onError: (error) => setNotice({ severity: "error", text: errorMessage(error) }),
  });
  const preferencesMutation = useMutation({
    mutationFn: () => settingsApi.updateIntegrationPreferences(preferences),
    onSuccess: () => {
      setNotice({ severity: "success", text: "Your integration preferences were saved." });
      void queryClient.invalidateQueries({ queryKey: ["integration-preferences"] });
      void queryClient.invalidateQueries({ queryKey: ["settings-overview"] });
    },
    onError: (error) => setNotice({ severity: "error", text: errorMessage(error) }),
  });

  const groupedCatalog = useMemo(() => {
    return catalog.reduce<Record<string, IntegrationCatalogItem[]>>((groups, item) => {
      (groups[item.category] ??= []).push(item);
      return groups;
    }, {});
  }, [catalog]);

  const openCreate = (provider: IntegrationProvider) => {
    setEditing(null);
    setTestResult(null);
    setForm(emptyForm(catalog, provider));
    setFormOpen(true);
  };

  const openEdit = (connection: IntegrationConnection) => {
    setEditing(connection);
    setTestResult(null);
    setForm({
      provider: connection.provider,
      name: connection.name,
      scope: connection.scope,
      projectId: connection.project_id ?? "",
      baseUrl: connection.base_url ?? "",
      externalOrg: connection.external_org ?? "",
      externalProject: connection.external_project ?? "",
      // The server never returns this field. A blank value preserves the
      // existing reference when editing; rotation is entered explicitly.
      secretRef: "",
      scopes: connection.scopes.join(", "),
      notes: typeof connection.metadata.notes === "string" ? connection.metadata.notes : "",
      enabled: connection.enabled,
    });
    setFormOpen(true);
  };

  const submitForm = () => {
    const projectId = form.scope === "project" ? form.projectId || selectedProject?.id || null : null;
    if (form.scope === "project" && !projectId) {
      setNotice({ severity: "warning", text: "Select the current project before saving a project-scoped connection." });
      return;
    }
    const common = {
      name: form.name.trim(),
      project_id: projectId,
      base_url: form.baseUrl.trim() || null,
      external_org: form.externalOrg.trim() || null,
      external_project: form.externalProject.trim() || null,
      scopes: form.scopes.split(",").map((scope) => scope.trim()).filter(Boolean),
      metadata: form.notes.trim() ? { notes: form.notes.trim() } : null,
      enabled: form.enabled,
    };
    if (editing) {
      const payload = form.secretRef.trim() ? { ...common, secret_ref: form.secretRef.trim() } : common;
      updateMutation.mutate({ id: editing.id, payload });
    } else {
      createMutation.mutate({
        provider: form.provider,
        scope: form.scope,
        ...common,
        secret_ref: form.secretRef.trim() || null,
      });
    }
  };

  const connections = connectionsQuery.data ?? [];
  const configuredCount = overviewQuery.data?.configured_connection_count ?? connections.filter((item) => item.status === "configured" || item.status === "ready_for_test").length;
  const busy = createMutation.isPending || updateMutation.isPending;

  return (
    <Stack spacing={3}>
      <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ md: "center" }} spacing={2}>
        <Box>
          <Typography variant="overline" color="primary.main" sx={{ letterSpacing: ".14em", fontWeight: 700 }}>WORKSPACE CONTROL</Typography>
          <Typography variant="h4" sx={{ fontWeight: 700 }}>Settings</Typography>
          <Typography color="text.secondary">Connect the systems that hold requirements, source changes, test cases, data, and evidence.</Typography>
        </Box>
        <Button variant="outlined" startIcon={<SettingsSuggestOutlinedIcon />} onClick={() => navigate("/settings/api-configuration")}>
          API configuration
        </Button>
      </Stack>

      {notice && <Alert severity={notice.severity} onClose={() => setNotice(null)}>{notice.text}</Alert>}
      {(overviewQuery.isError || catalogQuery.isError) && (
        <Alert severity="warning"><AlertTitle>Settings data is unavailable</AlertTitle>Retry after the database connection recovers. Existing connector secrets are not exposed by this page.</Alert>
      )}

      <Paper variant="outlined" sx={{ borderRadius: 3, overflow: "hidden" }}>
        <Tabs value={tab} onChange={(_, value: SettingsTab) => setTab(value)} variant="scrollable" allowScrollButtonsMobile>
          <Tab value="overview" label="Overview" />
          <Tab value="integrations" label="Integrations" />
          <Tab value="preferences" label="My preferences" />
          <Tab value="access" label="Access & roles" />
        </Tabs>
      </Paper>

      {tab === "overview" && (
        <OverviewPanel
          workspaceLabel={overviewQuery.data?.workspace_label ?? `${user?.full_name ?? "Your"} workspace`}
          role={overviewQuery.data?.role ?? user?.role ?? "viewer"}
          canManage={canManage}
          connectionCount={overviewQuery.data?.connection_count ?? connections.length}
          configuredCount={configuredCount}
          onIntegrations={() => setTab("integrations")}
        />
      )}

      {tab === "integrations" && (
        <IntegrationsPanel
          canManage={canManage}
          catalogGroups={groupedCatalog}
          catalog={catalog}
          connections={connections}
          selectedProjectName={selectedProject?.name ?? null}
          onCreate={openCreate}
          onEdit={openEdit}
          onDelete={(connection) => {
            if (window.confirm(`Remove “${connection.name}”? This removes only the QTXpert connection metadata.`)) deleteMutation.mutate(connection.id);
          }}
          onTest={(connection) => testMutation.mutate(connection.id)}
          testingId={testMutation.isPending ? testMutation.variables : null}
          testResult={testResult}
        />
      )}

      {tab === "preferences" && (
        <PreferencesPanel
          catalog={catalog}
          connections={connections}
          preferences={preferences}
          onChange={setPreferences}
          onSave={() => preferencesMutation.mutate()}
          busy={preferencesMutation.isPending}
          canManage={canManage}
        />
      )}

      {tab === "access" && <AccessPanel role={overviewQuery.data?.role ?? user?.role ?? "viewer"} canManage={canManage} />}

      <IntegrationDialog
        open={formOpen}
        editing={Boolean(editing)}
        form={form}
        catalog={catalog}
        selectedProjectName={selectedProject?.name ?? null}
        busy={busy}
        onChange={setForm}
        onClose={() => setFormOpen(false)}
        onSubmit={submitForm}
      />
    </Stack>
  );
}

function OverviewPanel({ workspaceLabel, role, canManage, connectionCount, configuredCount, onIntegrations }: { workspaceLabel: string; role: string; canManage: boolean; connectionCount: number; configuredCount: number; onIntegrations: () => void }) {
  return <Stack spacing={2.5}><Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(3, 1fr)" }, gap: 2 }}><MetricCard icon={<HubOutlinedIcon />} label="Workspace" value={workspaceLabel} detail="Account boundary" /><MetricCard icon={<AddLinkOutlinedIcon />} label="Connections" value={String(connectionCount)} detail={`${configuredCount} ready for validation`} /><MetricCard icon={<AdminPanelSettingsOutlinedIcon />} label="Your role" value={role.replaceAll("_", " ")} detail={canManage ? "Can manage connections" : "Personal settings only"} /></Box><Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1.2fr .8fr" }, gap: 2 }}><Card><CardContent><Stack spacing={2}><Stack direction="row" spacing={1.5} alignItems="center"><CheckCircleOutlineIcon color="primary" /><Typography variant="h6">A governed integration layer</Typography></Stack><Typography color="text.secondary">Use one connection record for each organization or project. QTXpert keeps requirements, source context, test cases, runtime data, and evidence linked without copying credentials into the application database.</Typography><Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap><Chip label="Context reads" variant="outlined" /><Chip label="Execution oracles" variant="outlined" /><Chip label="Approval-gated writes" variant="outlined" /></Stack><Button variant="contained" startIcon={<AddLinkOutlinedIcon />} onClick={onIntegrations} disabled={!canManage}>Review integrations</Button></Stack></CardContent></Card><Card><CardContent><Stack spacing={1.5}><Stack direction="row" spacing={1.5} alignItems="center"><SecurityOutlinedIcon color="primary" /><Typography variant="h6">Security boundary</Typography></Stack><Typography variant="body2" color="text.secondary">Only non-secret metadata and opaque secret-manager references are accepted. The local validation action makes no external request.</Typography><Typography variant="caption" color="text.secondary">Next: OAuth/PKCE, short-lived tokens, provider adapters, audit trails, and read/write approvals.</Typography></Stack></CardContent></Card></Box></Stack>;
}

function MetricCard({ icon, label, value, detail }: { icon: React.ReactNode; label: string; value: string; detail: string }) {
  return <Card><CardContent><Stack spacing={1}><Stack direction="row" justifyContent="space-between" alignItems="center"><Typography variant="caption" color="text.secondary">{label}</Typography><Box sx={{ color: "primary.main", display: "flex" }}>{icon}</Box></Stack><Typography variant="h6" sx={{ textTransform: "capitalize", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{value}</Typography><Typography variant="caption" color="text.secondary">{detail}</Typography></Stack></CardContent></Card>;
}

function IntegrationsPanel({ canManage, catalogGroups, catalog, connections, selectedProjectName, onCreate, onEdit, onDelete, onTest, testingId, testResult }: { canManage: boolean; catalogGroups: Record<string, IntegrationCatalogItem[]>; catalog: IntegrationCatalogItem[]; connections: IntegrationConnection[]; selectedProjectName: string | null; onCreate: (provider: IntegrationProvider) => void; onEdit: (connection: IntegrationConnection) => void; onDelete: (connection: IntegrationConnection) => void; onTest: (connection: IntegrationConnection) => void; testingId: string | null | undefined; testResult: IntegrationConnectionTestResult | null }) {
  return <Stack spacing={3}>{!canManage && <Alert severity="info"><AlertTitle>Personal access</AlertTitle>Only workspace administrators and QA leads can configure organization or project connections. You can still set personal defaults and notifications.</Alert>}<Box><Typography variant="h6">Integration catalogue</Typography><Typography color="text.secondary">Choose a system to define its boundary. Provider adapters are enabled only after credentials, scopes, and approvals are supplied.</Typography></Box>{Object.entries(catalogGroups).map(([category, items]) => <Box key={category}><Typography variant="overline" color="primary.main" sx={{ fontWeight: 700, letterSpacing: ".12em" }}>{category}</Typography><Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "repeat(2, 1fr)" }, gap: 2, mt: 1 }}>{items.map((item) => <Card key={item.key} variant="outlined"><CardContent><Stack spacing={1.5}><Stack direction="row" justifyContent="space-between" spacing={1} alignItems="flex-start"><Stack direction="row" spacing={1.25} alignItems="center"><HubOutlinedIcon color="primary" /><Typography variant="h6">{item.label}</Typography></Stack><Chip size="small" label={`${item.recommended_scope} scope`} variant="outlined" /></Stack><Typography variant="body2" color="text.secondary">{item.description}</Typography><Stack direction="row" flexWrap="wrap" useFlexGap gap={0.75}>{item.capabilities.map((capability) => <Chip key={capability} size="small" label={capability} />)}</Stack><Typography variant="caption" color="text.secondary">Auth: {item.auth_methods.join(" · ")}</Typography><Stack direction="row" spacing={1}><Button size="small" variant="contained" startIcon={<AddLinkOutlinedIcon />} disabled={!canManage} onClick={() => onCreate(item.key)}>Configure</Button>{item.docs_url && <Button size="small" component={Link} href={item.docs_url} target="_blank" rel="noreferrer" endIcon={<OpenInNewOutlinedIcon />}>Docs</Button>}</Stack></Stack></CardContent></Card>)}</Box></Box>)}<Divider /><Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1}><Box><Typography variant="h6">Saved connections</Typography><Typography color="text.secondary">{selectedProjectName ? `Current project: ${selectedProjectName}` : "Select a project in the top bar to prepare a project-scoped connection."}</Typography></Box><Chip icon={<KeyOutlinedIcon />} label="Secrets are never shown" variant="outlined" /></Stack>{testResult && <Alert severity="info"><AlertTitle>Local validation result</AlertTitle>{testResult.message}</Alert>}{!canManage ? null : connections.length === 0 ? <Paper variant="outlined" sx={{ p: 3, borderRadius: 2 }}><Typography fontWeight={600}>No connections yet</Typography><Typography color="text.secondary">Configure Jira, Confluence, source control, a test-case repository, or a read-only data source above.</Typography></Paper> : <Stack spacing={1.5}>{connections.map((connection) => <ConnectionCard key={connection.id} connection={connection} catalog={catalog} onEdit={onEdit} onDelete={onDelete} onTest={onTest} testing={testingId === connection.id} />)}</Stack>}</Stack>;
}

function ConnectionCard({ connection, catalog, onEdit, onDelete, onTest, testing }: { connection: IntegrationConnection; catalog: IntegrationCatalogItem[]; onEdit: (connection: IntegrationConnection) => void; onDelete: (connection: IntegrationConnection) => void; onTest: (connection: IntegrationConnection) => void; testing: boolean }) {
  return <Card variant="outlined"><CardContent><Stack spacing={1.5}><Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" spacing={1}><Box><Stack direction="row" spacing={1} alignItems="center"><Typography variant="h6">{connection.name}</Typography><Chip size="small" color={statusColor(connection.status)} label={statusLabel(connection.status)} /></Stack><Typography variant="body2" color="text.secondary">{providerLabel(catalog, connection.provider)} · {connection.scope === "project" ? `Project ${connection.project_id ?? "selected"}` : "Organization scope"}</Typography></Box><Stack direction="row" spacing={1}><Button size="small" startIcon={<CheckCircleOutlineIcon />} onClick={() => onTest(connection)} disabled={testing}>{testing ? "Validating…" : "Validate"}</Button><Button size="small" startIcon={<EditOutlinedIcon />} onClick={() => onEdit(connection)}>Edit</Button><Button size="small" color="error" startIcon={<DeleteOutlineIcon />} onClick={() => onDelete(connection)}>Remove</Button></Stack></Stack><Stack direction="row" flexWrap="wrap" useFlexGap gap={0.75}><Chip size="small" variant="outlined" label={connection.enabled ? "Enabled" : "Disabled"} /><Chip size="small" variant="outlined" label={connection.secret_configured ? "Secret reference present" : "Secret reference missing"} /><Chip size="small" variant="outlined" label={`${connection.scopes.length} scopes`} />{connection.external_org && <Chip size="small" variant="outlined" label={connection.external_org} />}{connection.external_project && <Chip size="small" variant="outlined" label={connection.external_project} />}</Stack>{connection.base_url && <Typography variant="caption" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>Endpoint: {connection.base_url}</Typography>}{connection.last_tested_at && <Typography variant="caption" color="text.secondary">Last local validation: {new Date(connection.last_tested_at).toLocaleString()}</Typography>}</Stack></CardContent></Card>;
}

function PreferencesPanel({ catalog, connections, preferences, onChange, onSave, busy, canManage }: { catalog: IntegrationCatalogItem[]; connections: IntegrationConnection[]; preferences: typeof EMPTY_PREFERENCES; onChange: (value: typeof EMPTY_PREFERENCES) => void; onSave: () => void; busy: boolean; canManage: boolean }) {
  return <Stack spacing={2.5}><Card><CardContent><Stack spacing={2}><Stack direction="row" spacing={1.5} alignItems="center"><PeopleAltOutlinedIcon color="primary" /><Box><Typography variant="h6">My preferences</Typography><Typography variant="body2" color="text.secondary">These choices affect your workspace experience, not organization credentials.</Typography></Box></Stack><Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}><TextField select label="Default integration" value={preferences.default_provider ?? ""} onChange={(event) => onChange({ ...preferences, default_provider: (event.target.value || null) as IntegrationProvider | null })}><MenuItem value="">No default</MenuItem>{catalog.map((item) => <MenuItem key={item.key} value={item.key}>{item.label}</MenuItem>)}</TextField><TextField select label="Default saved connection" value={preferences.default_connection_id ?? ""} onChange={(event) => onChange({ ...preferences, default_connection_id: event.target.value || null })} disabled={!canManage || connections.length === 0}><MenuItem value="">No default</MenuItem>{connections.map((connection) => <MenuItem key={connection.id} value={connection.id}>{connection.name}</MenuItem>)}</TextField><TextField select label="Notification level" value={preferences.notification_mode} onChange={(event) => onChange({ ...preferences, notification_mode: event.target.value as IntegrationNotificationMode })}><MenuItem value="all">All connector events</MenuItem><MenuItem value="important">Important events only</MenuItem><MenuItem value="none">No connector notifications</MenuItem></TextField><TextField label="Timezone" value={preferences.timezone} onChange={(event) => onChange({ ...preferences, timezone: event.target.value })} /></Box><FormControlLabel control={<Checkbox checked={preferences.notifications_enabled} onChange={(event) => onChange({ ...preferences, notifications_enabled: event.target.checked })} />} label="Allow integration notifications" /><Button variant="contained" onClick={onSave} disabled={busy}>{busy ? "Saving…" : "Save preferences"}</Button></Stack></CardContent></Card></Stack>;
}

function AccessPanel({ role, canManage }: { role: string; canManage: boolean }) {
  const roles = [["Admin", "Manage users, workspace connections, scopes, and approval gates."], ["QA lead", "Manage project connections and quality-system mappings."], ["QA engineer / automation engineer", "Use approved context and execution connections."], ["Business analyst", "Review imported context and traceability."], ["Viewer", "Read approved settings and evidence only."]];
  return <Stack spacing={2.5}><Alert severity="info"><AlertTitle>Current access boundary</AlertTitle>QTXpert currently treats the authenticated account as the workspace boundary. Project-scoped connections are limited to projects owned by the configuring account. Organization memberships and project-member enforcement are the next access-control milestone.</Alert><Card><CardContent><Stack spacing={2}><Stack direction="row" spacing={1.5} alignItems="center"><AdminPanelSettingsOutlinedIcon color="primary" /><Box><Typography variant="h6">Access & roles</Typography><Typography variant="body2" color="text.secondary">Your role: <strong>{role.replaceAll("_", " ")}</strong></Typography></Box></Stack>{roles.map(([name, description]) => <Box key={name}><Typography fontWeight={600}>{name}</Typography><Typography variant="body2" color="text.secondary">{description}</Typography></Box>)}{canManage && <Button variant="outlined" component={Link} href="/administration/users" startIcon={<PeopleAltOutlinedIcon />}>Manage users</Button>}</Stack></CardContent></Card></Stack>;
}

function IntegrationDialog({ open, editing, form, catalog, selectedProjectName, busy, onChange, onClose, onSubmit }: { open: boolean; editing: boolean; form: IntegrationFormState; catalog: IntegrationCatalogItem[]; selectedProjectName: string | null; busy: boolean; onChange: (value: IntegrationFormState) => void; onClose: () => void; onSubmit: () => void }) {
  const selected = catalog.find((item) => item.key === form.provider);
  return <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth><DialogTitle>{editing ? "Edit integration connection" : `Configure ${selected?.label ?? "integration"}`}</DialogTitle><DialogContent><Stack spacing={2.25} sx={{ pt: 1 }}><Alert severity="info"><AlertTitle>Secret-safe setup</AlertTitle>Enter metadata only. Use an opaque reference such as <code>vault://qtxpert/jira/prod</code> or <code>env://JIRA_TOKEN</code>; never paste a token, password, or bearer value.</Alert><Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}><TextField select label="Provider" value={form.provider} disabled={editing} onChange={(event) => onChange({ ...form, provider: event.target.value as IntegrationProvider })}>{catalog.map((item) => <MenuItem key={item.key} value={item.key}>{item.label}</MenuItem>)}</TextField><TextField label="Connection name" value={form.name} onChange={(event) => onChange({ ...form, name: event.target.value })} required /><TextField select label="Scope" value={form.scope} disabled={editing} helperText={form.scope === "organization" ? "Available to the workspace after access controls are enabled." : "Restricted to the selected project."} onChange={(event) => onChange({ ...form, scope: event.target.value as IntegrationScope, projectId: event.target.value === "project" ? form.projectId : "" })}><MenuItem value="organization">Organization</MenuItem><MenuItem value="project">Project</MenuItem></TextField><TextField label="Project" value={form.scope === "project" ? (selectedProjectName ?? "") : "Not applicable"} disabled helperText={form.scope === "project" ? "Uses the project selected in the top bar." : undefined} /><TextField label="Base URL / tenant URL" value={form.baseUrl} onChange={(event) => onChange({ ...form, baseUrl: event.target.value })} placeholder="https://jira.example.com" /><TextField label="Organization / workspace" value={form.externalOrg} onChange={(event) => onChange({ ...form, externalOrg: event.target.value })} /><TextField label="Project / repository / database" value={form.externalProject} onChange={(event) => onChange({ ...form, externalProject: event.target.value })} /><TextField label="Secret-manager reference" value={form.secretRef} onChange={(event) => onChange({ ...form, secretRef: event.target.value })} placeholder="vault://qtxpert/provider/connection" helperText={editing ? "Leave blank to preserve the existing reference." : "Required before a provider adapter can authenticate."} /></Box><TextField label="Permission scopes" value={form.scopes} onChange={(event) => onChange({ ...form, scopes: event.target.value })} placeholder="read:requirements, read:repositories" helperText="Comma-separated, least-privilege scopes; write scopes require a later approval." /><TextField label="Connection notes" value={form.notes} onChange={(event) => onChange({ ...form, notes: event.target.value })} multiline minRows={2} helperText="Non-secret notes only. Do not paste credentials or payloads." /><FormControlLabel control={<Checkbox checked={form.enabled} onChange={(event) => onChange({ ...form, enabled: event.target.checked })} />} label="Enable this connection for future approved adapter calls" /></Stack></DialogContent><DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" onClick={onSubmit} disabled={busy || !form.name.trim()}>{busy ? "Saving…" : editing ? "Save changes" : "Save connection"}</Button></DialogActions></Dialog>;
}
