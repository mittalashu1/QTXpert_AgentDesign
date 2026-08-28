import axios from "axios";
import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { authApi } from "@/services/api";
import { User } from "@/types/domain";

const ACCESS_TOKEN_KEY = "qtxpert-access-token";
const REFRESH_TOKEN_KEY = "qtxpert-refresh-token";
const AUTH_RETRY_DELAYS_MS = [500, 1000, 2000];

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  authUnavailable: boolean;
  retryAuth: () => void;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function getStatus(error: unknown): number | undefined {
  return axios.isAxiosError(error) ? error.response?.status : undefined;
}

function isTransientAuthError(error: unknown): boolean {
  const status = getStatus(error);
  return (
    status === undefined ||
    status === 408 ||
    status === 425 ||
    status === 429 ||
    status >= 500
  );
}

function clearTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

function wait(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms));
}

async function loadCurrentUserWithRetry(): Promise<User> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= AUTH_RETRY_DELAYS_MS.length; attempt += 1) {
    try {
      const response = await authApi.me();
      return response.data;
    } catch (error) {
      lastError = error;
      if (!isTransientAuthError(error) || attempt === AUTH_RETRY_DELAYS_MS.length) {
        throw error;
      }
      await wait(AUTH_RETRY_DELAYS_MS[attempt]);
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Authentication failed");
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [authUnavailable, setAuthUnavailable] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      const token = localStorage.getItem(ACCESS_TOKEN_KEY);
      if (!token) {
        if (!cancelled) {
          setUser(null);
          setAuthUnavailable(false);
          setIsLoading(false);
        }
        return;
      }

      setIsLoading(true);
      try {
        const currentUser = await loadCurrentUserWithRetry();
        if (!cancelled) {
          setUser(currentUser);
          setAuthUnavailable(false);
        }
      } catch (error) {
        if (cancelled) return;
        if (isTransientAuthError(error)) {
          // Preserve tokens across a restart, network blip, or temporary Neon
          // failure. ProtectedRoute offers a retry instead of forcing logout.
          setAuthUnavailable(true);
        } else {
          clearTokens();
          setUser(null);
          setAuthUnavailable(false);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [retryNonce]);

  const login = async (email: string, password: string) => {
    setAuthUnavailable(false);
    const tokenResponse = await authApi.login(email, password);
    localStorage.setItem(ACCESS_TOKEN_KEY, tokenResponse.data.access_token);
    localStorage.setItem(REFRESH_TOKEN_KEY, tokenResponse.data.refresh_token);
    try {
      const currentUser = await loadCurrentUserWithRetry();
      setUser(currentUser);
    } catch (error) {
      if (!isTransientAuthError(error)) clearTokens();
      throw error;
    }
  };

  const logout = () => {
    authApi.logout().catch(() => undefined);
    clearTokens();
    setAuthUnavailable(false);
    setUser(null);
  };

  const retryAuth = () => {
    setAuthUnavailable(false);
    setIsLoading(true);
    setRetryNonce((value) => value + 1);
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, authUnavailable, retryAuth, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
