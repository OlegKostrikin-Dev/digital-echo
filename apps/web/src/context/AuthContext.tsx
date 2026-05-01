import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Navigate, Outlet, useNavigate } from "react-router-dom";
import { AUTH_FETCH_TIMEOUT_MS } from "../api";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export type AuthUser = {
  email: string;
  role: "admin" | "guest";
};

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const r = await fetch(`${API_BASE}/api/auth/me`, {
      credentials: "include",
      signal: AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS),
    });
    if (!r.ok) {
      setUser(null);
      return;
    }
    const data = (await r.json()) as {
      authenticated?: boolean;
      email?: string;
      role?: string;
    };
    if (data.authenticated && data.email && (data.role === "admin" || data.role === "guest")) {
      setUser({ email: data.email, role: data.role });
    } else {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refresh()
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, [refresh]);

  const logout = useCallback(async () => {
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
      signal: AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS),
    });
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, refresh, logout }),
    [user, loading, refresh, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

export function RequireAuth() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center text-slate-500">
        Загрузка…
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/access" replace />;
  }
  return <Outlet />;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && (!user || user.role !== "admin")) {
      navigate("/admin/login", { replace: true });
    }
  }, [user, loading, navigate]);

  if (loading || !user || user.role !== "admin") {
    return (
      <div className="min-h-[40vh] flex items-center justify-center text-slate-500">
        Проверка доступа…
      </div>
    );
  }
  return <>{children}</>;
}
