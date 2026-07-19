import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { authApi } from "@/services/api";
import { User } from "@/types/domain";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("qtxpert-access-token");
    if (!token) {
      setIsLoading(false);
      return;
    }
    authApi
      .me()
      .then((res) => setUser(res.data))
      .catch(() => {
        localStorage.removeItem("qtxpert-access-token");
        localStorage.removeItem("qtxpert-refresh-token");
      })
      .finally(() => setIsLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const tokenResponse = await authApi.login(email, password);
    localStorage.setItem("qtxpert-access-token", tokenResponse.data.access_token);
    localStorage.setItem("qtxpert-refresh-token", tokenResponse.data.refresh_token);
    const me = await authApi.me();
    setUser(me.data);
  };

  const logout = () => {
    authApi.logout().catch(() => undefined);
    localStorage.removeItem("qtxpert-access-token");
    localStorage.removeItem("qtxpert-refresh-token");
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
