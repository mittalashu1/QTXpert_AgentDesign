import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export const apiClient = axios.create({ baseURL: BASE_URL });

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem("qtxpert-access-token");
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let refreshInFlight: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  const refreshToken = localStorage.getItem("qtxpert-refresh-token");
  if (!refreshToken) throw new Error("No refresh token available");
  const response = await axios.post(`${BASE_URL}/auth/refresh`, {
    refresh_token: refreshToken,
  });
  localStorage.setItem("qtxpert-access-token", response.data.access_token);
  localStorage.setItem("qtxpert-refresh-token", response.data.refresh_token);
  return response.data.access_token;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true;
      try {
        refreshInFlight = refreshInFlight || refreshAccessToken();
        const newToken = await refreshInFlight;
        refreshInFlight = null;
        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${newToken}`;
        }
        return apiClient(originalRequest);
      } catch {
        refreshInFlight = null;
        localStorage.removeItem("qtxpert-access-token");
        localStorage.removeItem("qtxpert-refresh-token");
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);
