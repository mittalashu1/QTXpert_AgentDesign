import { apiClient } from "@/services/apiClient";
import {
  GenerationRun,
  Project,
  Requirement,
  User,
} from "@/types/domain";

export const authApi = {
  login: (email: string, password: string) =>
    apiClient.post<{ access_token: string; refresh_token: string }>("/auth/login", {
      email,
      password,
    }),
  register: (email: string, full_name: string, password: string) =>
    apiClient.post<User>("/auth/register", { email, full_name, password }),
  me: () => apiClient.get<User>("/auth/me"),
  logout: () => apiClient.post("/auth/logout"),
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
  generate: (projectId: string, requirementIds: string[] = [], llmProviderOverride?: string) =>
    apiClient.post<GenerationRun>("/generate-testcases", {
      project_id: projectId,
      requirement_ids: requirementIds,
      llm_provider_override: llmProviderOverride,
    }),
  history: (projectId: string) =>
    apiClient.get<GenerationRun[]>("/history", { params: { project_id: projectId } }),
  getRun: (runId: string) => apiClient.get<GenerationRun>(`/history/${runId}`),
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
