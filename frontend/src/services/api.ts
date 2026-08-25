import { apiClient } from "@/services/apiClient";
import {
  GenerationRun,
  Project,
  Requirement,
  User,
  UserRole,
  TestCase,
  ExecutionRun,
  DashboardSummary,
  AICostSummary,
} from "@/types/domain";

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
    base_url: string;
    browser: "chromium" | "firefox" | "webkit";
    test_case_ids: string[];
  }) => apiClient.post<ExecutionRun>("/executions", payload),
  get: (runId: string) => apiClient.get<ExecutionRun>(`/executions/${runId}`),
  createDefect: (resultId: string, payload: { title: string; severity: string; description: string }) =>
    apiClient.post(`/execution-results/${resultId}/defects`, payload),
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
  getRun: (runId: string) => apiClient.get<GenerationRun>(`/history/${runId}`),
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

