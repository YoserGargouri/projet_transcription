import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api } from "@/api/client";
import type { Me } from "@/api/types";

interface AuthCtx {
  me: Me | null;
  ready: boolean;
  refresh: () => Promise<Me | null>;
  login: (email: string, password: string) => Promise<void>;
  register: (body: { name: string; email: string; password: string; business_name: string }) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const m = await api.get<Me>("/auth/me");
      setMe(m);
      return m;
    } catch {
      setMe(null);
      return null;
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    refresh();
    const onExpired = () => setMe(null);
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, [refresh]);

  const login = async (email: string, password: string) => {
    await api.post("/auth/login", { email, password });
    await refresh();
  };
  const register = async (body: { name: string; email: string; password: string; business_name: string }) => {
    await api.post("/auth/register", body);
    await refresh();
  };
  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setMe(null);
    }
  };

  return <Ctx.Provider value={{ me, ready, refresh, login, register, logout }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}

/** Protected routes: the server still checks every request; this only redirects early. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, ready } = useAuth();
  const loc = useLocation();
  if (!ready)
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", color: "var(--text-3)" }}>
        <span className="spinner" />
      </div>
    );
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  return <>{children}</>;
}
