import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { getStoredTokens, storeTokens, type AuthResponse, type User } from "../api/client";
import { fetchMe, logout } from "../api/auth";

interface AuthState {
  user: User | null;
  loading: boolean;
  signIn: (auth: AuthResponse) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getStoredTokens()) {
      setLoading(false);
      return;
    }
    fetchMe()
      .then(setUser)
      .catch(() => storeTokens(null))
      .finally(() => setLoading(false));
  }, []);

  const signIn = useCallback((auth: AuthResponse) => {
    storeTokens(auth.tokens);
    setUser(auth.user);
  }, []);

  const signOut = useCallback(() => {
    logout().catch(() => {
      // best-effort: cookie may already be gone
    });
    storeTokens(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
