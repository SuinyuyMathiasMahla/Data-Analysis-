import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import type { Tokens, User } from "../types";
import { api, getRefreshToken, refreshSession, setSessionEndHandler, storeTokens } from "./api";

interface AuthState {
  user: User | null;
  /** true until the stored session has been checked on first load */
  loading: boolean;
  signIn: (email: string, password: string) => Promise<User>;
  signOut: () => Promise<void>;
  setUser: (user: User) => void;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setSessionEndHandler(() => setUser(null));
    refreshSession().then((tokens) => {
      if (cancelled) return;
      setUser(tokens ? tokens.user : null);
      setLoading(false);
    });
    return () => {
      cancelled = true;
      setSessionEndHandler(null);
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const tokens = await api.post<Tokens>("/auth/login", { email, password });
    storeTokens(tokens);
    setUser(tokens.user);
    return tokens.user;
  }, []);

  const signOut = useCallback(async () => {
    const refresh_token = getRefreshToken();
    try {
      if (refresh_token) await api.post("/auth/logout", { refresh_token });
    } catch {
      /* the local session is cleared either way */
    }
    storeTokens(null);
    setUser(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, loading, signIn, signOut, setUser, can: (permission) => !!user && user.permissions.includes(permission) }),
    [user, loading, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
