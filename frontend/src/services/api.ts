import { apiClient } from "@/services/apiClient";
import {
  GenerationRun,
  GenerationRunSummary,
  Project,
  Requirement,
  User,
  UserRole,
  TestCase,
  ExecutionRun,
  ExecutionPlan,
  ExecutionSuiteType,
  DashboardSummary,
  AICostSummary,
  UploadedAsset,
  DocumentAnalysisRun,
  DocumentFinding,
  DocumentFindingStatus,
  DocumentProfile,
  ExecutionProvider,
  ExecutionTargetKind,
} from "@/types/domain";

const activeProjectId = () => localStorage.getItem("qtxpert-selected-project") || undefined;

export const authApi = {
  login: (email: string, password: string) =>
    apiClient.post<{ access_token: string; refresh_token: string }>("/auth/login", {
      email,
      password,
    }),
  me: () => apiClient.get<User>("/auth/me"),
  logout: () => apiClient.post("/auth/logout"),
  changePassword: (current_password: string, new_password: string) =>
    apiClient.put("/auth/me/password", { current_password, new_password }),
};

export const dashboardApi = {
  summary: (projectId: string) =>
    apiClient.get<DashboardSummary>("/dashboard", { params: { project_id: projectId } }),
  aiCosts: (days = 30) =>
    apiClient.get<AICostSummary>("/admin/ai-costs", { params: { days } }),
};

export const executionsApi = {
  list: (projectId: string) =>
    apiClient.get<ExecutionRun[]>("/executions", { params: { project_id: projectId } }),
  create: (payload: {
    project_id: string;
    name: string;
    base_url?: string;
    browser: "chromium" | "firefox" | "webkit";
    test_case_ids: string[];
    target_kind?: ExecutionTargetKind;
    provider?: ExecutionProvider;
    app_asset_id?: string;
    device_name?: string;
    platform_version?: string;
    appium_url?: string;
    appium_app?: string;
    no_reset?: boolean;
    auto_grant_permissions?: boolean;
  }) => apiClient.post<ExecutionRun>("/executions", payload),
  get: (runId: string) => apiClient.get<ExecutionRun>(`/executions/${runId}`),
  createDefect: (resultId: string, payload: { title: string; severity: string; description: string }) =>
    apiClient.post(`/execution-results/${resultId}/defects`, payload),
};

export const executionPlansApi = {
  list: (projectId: string) =>
    apiClient.get<ExecutionPlan[]>("/execution-plans", { params: { project_id: projectId } }),
  get: (planId: string) => apiClient.get<ExecutionPlan>(`/execution-plans/${planId}`),
  import: (payload: {
    project_id: string;
    generation_run_id: string;
    name?: string;
    suite_type: ExecutionSuiteType;
  }) => apiClient.post<ExecutionPlan>("/execution-plans/import", payload),
  updateCases: (
    planId: string,
    cases: Array<{ id: string; selected: boolean; execution_mode: "automated" | "manual" }>,
  ) => apiClient.patch<ExecutionPlan>(`/execution-plans/${planId}/cases`, { cases }),
  preflight: (planId: string, payload: {
    target_kind: ExecutionTargetKind;
    provider: ExecutionProvider;
    base_url?: string;
    app_asset_id?: string;
    device_name?: string;
    platform_version?: string;
    appium_url?: string;
    appium_app?: string;
    no_reset?: boolean;
    auto_grant_permissions?: boolean;
  }) =>
    apiClient.post<ExecutionPlan>(`/execution-plans/${planId}/preflight`, payload),
  execute: (planId: string, payload: {
    target_kind: ExecutionTargetKind;
    provider: ExecutionProvider;
    base_url?: string;
    app_asset_id?: string;
    device_name?: string;
    platform_version?: string;
    appium_url?: string;
    appium_app?: string;
    no_reset?: boolean;
    auto_grant_permissions?: boolean;
    name?: string;
    browser?: "chromium";
  }) =>
    apiClient.post<ExecutionRun>(`/execution-plans/${planId}/execute`, payload),
  rerun: (planId: string, sourceExecutionId: string, name?: string) =>
    apiClient.post<ExecutionRun>(`/execution-plans/${planId}/rerun`, {
      source_execution_id: sourceExecutionId,
      name,
    }),
};

export const usersApi = {
  list: () => apiClient.get<User[]>("/auth/users"),
  create: (payload: { email: string; full_name: string; password: string; role: UserRole }) =>
    apiClient.post<User>("/auth/users", payload),
  update: (id: string, payload: Partial<Pick<User, "full_name" | "role" | "is_active">>) =>
    apiClient.patch<User>(`/auth/users/${id}`, payload),
  resetPassword: (id: string, new_password: string) =>
    apiClient.put(`/auth/users/${id}/password`, { new_password }),
};

export const projectsApi = {
  list: () => apiClient.get<Project[]>("/projects"),
  create: (name: string, description?: string) =>
    apiClient.post<Project>("/projects", { name, description }),
  update: (id: string, name: string, description?: string | null) =>
    apiClient.patch<Project>(`/projects/${id}`, { name, description: description ?? null }),
};

export const uploadsApi = {
  list: (params?: { category?: string; extension?: string; project_id?: string }) => {
    const projectId = params?.project_id || activeProjectId();
    return apiClient.get<UploadedAsset[]>("/uploads", {
      params: { ...params, ...(projectId ? { project_id: projectId } : {}) },
    });
  },
  upload: (file: File, options?: { projectId?: string; sourceModule?: string; category?: string }) => {
    const form = new FormData();
    const projectId = options?.projectId || activeProjectId();
    form.append("file", file);
    if (projectId) form.append("project_id", projectId);
    if (options?.sourceModule) form.append("source_module", options.sourceModule);
    if (options?.category) form.append("category", options.category);
    return apiClient.post<UploadedAsset>("/uploads", form, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 300000,
    });
  },
  download: (id: string) => apiClient.get(`/uploads/${id}/content`, { responseType: "blob" }),
  remove: (id: string) => apiClient.delete(`/uploads/${id}`),
};

export const documentIntelligenceApi = {
  latest: (projectId: string) =>
    apiClient.get<DocumentAnalysisRun | null>("/document-intelligence/runs/latest", {
      params: { project_id: projectId },
    }),
  getRun: (runId: string) =>
    apiClient.get<DocumentAnalysisRun>(`/document-intelligence/runs/${runId}`),
  analyze: (payload: {
    project_id: string;
    asset_ids: string[];
    profile: DocumentProfile;
    additional_context?: string;
  }) => apiClient.post<DocumentAnalysisRun>("/document-intelligence/analyze", payload),
  reviewFinding: (
    findingId: string,
    payload: {
      status: DocumentFindingStatus;
      resolution_note?: string | null;
      suggested_refinement?: string | null;
    }
  ) => apiClient.patch<DocumentFinding>(`/document-intelligence/findings/${findingId}`, payload),
  publish: (runId: string) =>
    apiClient.post<{ run_id: string; requirement_id: string; title: string; message: string }>(
      `/document-intelligence/runs/${runId}/publish`
    ),
};

export const requirementsApi = {
  listForProject: (projectId: string) =>
    apiClient.get<Requirement[]>("/requirements", { params: { project_id: projectId } }),
  upload: (projectId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return apiClient.post<Requirement>("/upload", formData, {
      params: { project_id: projectId },
      headers: { "Content-Type": "multipart/form-data" },
      // APK/IPA sources can be hundreds of megabytes and are streamed by the
      // backend. Allow enough time for the upload on a normal connection.
      timeout: 300_000,
    });
  },
  submitDirectPrompt: (projectId: string, title: string, content: string) =>
    apiClient.post<Requirement>("/requirements/direct-prompt", {
      project_id: projectId,
      title,
      content,
    }),
};

export const testCasesApi = {
  generate: (
    projectId: string,
    requirementIds: string[] = [],
    llmProviderOverride?: string,
    generationProfile: "smoke" | "feature" | "regression" | "deep_regression" = "feature",
    testSetTitle?: string,
  ) =>
    apiClient.post<GenerationRun>("/generate-testcases", {
      project_id: projectId,
      requirement_ids: requirementIds,
      llm_provider_override: llmProviderOverride,
      generation_profile: generationProfile,
      test_set_title: testSetTitle,
    }),
  history: (projectId: string) =>
    apiClient.get<GenerationRun[]>("/history", { params: { project_id: projectId } }),
  historySummaries: (projectId: string, limit = 200, offset = 0) =>
    apiClient.get<GenerationRunSummary[]>("/history-summaries", {
      params: { project_id: projectId, limit, offset },
    }),
  getRun: (runId: string) => apiClient.get<GenerationRun>(`/history/${runId}`),
  updateRunTitle: (runId: string, title: string) =>
    apiClient.patch<GenerationRun>(`/history/${runId}/title`, { title }),
  deleteRun: (runId: string) =>
    apiClient.delete<void>(`/history/${runId}`),
  updateRun: (runId: string, testCases: TestCase[]) =>
    apiClient.patch<GenerationRun>(`/history/${runId}`, {
      test_cases: testCases.map((testCase) => ({
        id: testCase.id,
        scenario: testCase.scenario,
        objective: testCase.objective,
        preconditions: testCase.preconditions,
        steps: testCase.steps,
        expected_result: testCase.expected_result,
      })),
    }),
  export: (generationRunId: string, format: string) =>
    apiClient.post(
      "/export",
      { generation_run_id: generationRunId, format },
      { responseType: "blob" }
    ),
};

export const settingsApi = {
  listConfigurations: () => apiClient.get("/settings"),
  createConfiguration: (payload: {
    name: string;
    llm_provider: string;
    llm_model: string;
    is_active: boolean;
  }) => apiClient.post("/settings", payload),
  testProvider: (provider: string) =>
    apiClient.post<{ provider: string; healthy: boolean; detail: string }>(
      "/settings/test-provider",
      { provider }
    ),
};

