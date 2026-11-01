"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import type { SystemStatus, User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  status: SystemStatus | null;
  refresh: () => Promise<void>;
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  has: (feature: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await api<User>("/auth/me"));
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    Promise.all([
      refresh(),
      api<SystemStatus>("/system/status").then(setStatus).catch(() => setStatus(null)),
    ]).finally(() => setLoading(false));
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api<{ user: User }>("/auth/login", { method: "POST", body: { email, password } });
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    setUser(null);
  }, []);

  const has = useCallback((feature: string) => Boolean(user?.entitlements?.features?.[feature]), [user]);

  return (
    <AuthContext.Provider value={{ user, loading, status, refresh, login, logout, has }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
